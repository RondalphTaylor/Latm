from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.matching import (
    CandidateScore,
    MarketEventMatchDecision,
    MarketEventMatchStatus,
    MarketMatchInput,
    MatchingPolicy,
    SportsEventMatchInput,
    TeamMatchInput,
    TeamSignal,
)
from app.domain.sports import SportsLeague
from app.services.matching.aliases import (
    extract_team_signals,
    has_non_nba_sport_signal,
    normalize_match_text,
)
from app.services.matching.mlb_aliases import (
    extract_mlb_team_signals,
    has_non_mlb_sport_signal,
)
from app.services.matching.nfl_aliases import (
    extract_nfl_team_signals,
    has_non_nfl_sport_signal,
    resolve_nfl_team_designator,
)
from app.services.matching.nfl_contracts import (
    NFL_CONTRACT_POLICY_VERSION,
    evaluate_nfl_contract,
    nfl_team_codes,
)

MATCHER_VERSION = "deterministic-team-time-v2"
_CONFIDENCE_QUANTUM = Decimal("0.0001")
_TEAM_WEIGHT = Decimal("0.70")
_TEMPORAL_WEIGHT = Decimal("0.30")


def _quantize(value: Decimal) -> Decimal:
    return min(Decimal("1"), max(Decimal("0"), value)).quantize(
        _CONFIDENCE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _market_text(market: MarketMatchInput) -> tuple[str, str]:
    fields = (
        market.title,
        market.subtitle,
        market.rules_primary,
        market.rules_secondary,
        *market.outcome_labels,
    )
    original_text = " ".join(value for value in fields if value)
    return original_text, normalize_match_text(original_text)


def _reference_time(market: MarketMatchInput) -> tuple[datetime | None, str]:
    if market.occurrence_time is not None:
        return market.occurrence_time, "occurrence_time"
    if market.close_time is not None:
        return market.close_time, "close_time"
    return None, "none"


def _temporal_score(delta_seconds: int, *, source: str) -> Decimal:
    if delta_seconds <= 3 * 60 * 60:
        score = Decimal("1.00")
    elif delta_seconds <= 12 * 60 * 60:
        score = Decimal("0.85")
    elif delta_seconds <= 24 * 60 * 60:
        score = Decimal("0.60")
    else:
        score = Decimal("0.30")
    if source == "close_time":
        score *= Decimal("0.65")
    return _quantize(score)


def _candidate_score(
    event: SportsEventMatchInput,
    *,
    team_score: Decimal,
    reference_time: datetime | None,
    reference_source: str,
    policy: MatchingPolicy,
    nfl_date: date | None = None,
) -> CandidateScore:
    if reference_time is None:
        temporal_score = Decimal("0")
        delta_seconds = None
        within_window = False
        method = "team_pair_only"
    else:
        delta_seconds = int(abs((event.scheduled_start_time - reference_time).total_seconds()))
        within_window = delta_seconds <= policy.time_window_hours * 60 * 60
        temporal_score = (
            _temporal_score(delta_seconds, source=reference_source)
            if within_window
            else Decimal("0")
        )
        method = (
            "exact_team_pair_and_time"
            if reference_source == "occurrence_time" and delta_seconds <= 3 * 60 * 60
            else "team_pair_and_time"
        )
    confidence = _quantize(_TEAM_WEIGHT * team_score + _TEMPORAL_WEIGHT * temporal_score)
    if nfl_date is not None:
        date_matches = (
            event.scheduled_start_time.astimezone(ZoneInfo("America/New_York")).date() == nfl_date
        )
        if reference_time is None:
            # Exact contract calendar date is evidence, not a fabricated kickoff time.
            temporal_score = Decimal("0.95") if date_matches else Decimal("0")
            within_window = date_matches
            method = "nfl_team_pair_contract_date"
        else:
            within_window = within_window and date_matches
            if not within_window:
                temporal_score = Decimal("0")
        confidence = _quantize(_TEAM_WEIGHT * team_score + _TEMPORAL_WEIGHT * temporal_score)
    return CandidateScore(
        event_id=event.id,
        scheduled_start_time=event.scheduled_start_time,
        home_team_id=event.home_team_id,
        away_team_id=event.away_team_id,
        team_score=team_score,
        temporal_score=temporal_score,
        confidence=confidence,
        time_delta_seconds=delta_seconds,
        within_time_window=within_window,
        method=method,
    )


def _fingerprint(
    *,
    market: MarketMatchInput,
    policy: MatchingPolicy,
    signals: tuple[TeamSignal, ...],
    relevant_events: tuple[SportsEventMatchInput, ...],
) -> str:
    payload = {
        "market": {
            "id": str(market.id),
            "league": market.league.value,
            "title": market.title,
            "subtitle": market.subtitle,
            "rules_primary": market.rules_primary,
            "rules_secondary": market.rules_secondary,
            "category": market.category,
            "market_type": market.market_type,
            "outcome_labels": market.outcome_labels,
            "occurrence_time": market.occurrence_time.isoformat()
            if market.occurrence_time is not None
            else None,
            "close_time": market.close_time.isoformat() if market.close_time is not None else None,
        },
        "policy": policy.model_dump(mode="json"),
        "signals": [signal.model_dump(mode="json") for signal in signals],
        "events": [
            {
                "id": str(event.id),
                "event_date": event.event_date.isoformat(),
                "scheduled_start_time": event.scheduled_start_time.isoformat(),
                "home_team_id": str(event.home_team_id),
                "away_team_id": str(event.away_team_id),
            }
            for event in sorted(relevant_events, key=lambda item: str(item.id))
        ],
    }
    if market.league is SportsLeague.NFL:
        payload["nfl_contract"] = {
            "version": NFL_CONTRACT_POLICY_VERSION,
            "provider": market.provider_name,
            "market": market.provider_market_id,
            "event": market.provider_event_id,
            "series": market.series_ticker,
        }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class MarketEventMatcher:
    """Deterministically match one classified sports market to one game."""

    def __init__(self, policy: MatchingPolicy) -> None:
        self._policy = policy

    def match(
        self,
        market: MarketMatchInput,
        *,
        teams: tuple[TeamMatchInput, ...],
        events: tuple[SportsEventMatchInput, ...],
        evaluated_at: datetime | None = None,
    ) -> MarketEventMatchDecision:
        """Return a conservative match decision with inspectible evidence."""
        evaluation_time = evaluated_at or datetime.now(UTC)
        original_text, text = _market_text(market)
        if market.league is SportsLeague.NFL:
            signals = extract_nfl_team_signals(text, teams, original_text=original_text)
            incompatible_sport_signal = has_non_nfl_sport_signal(text)
        elif market.league is SportsLeague.MLB:
            signals = extract_mlb_team_signals(text, teams, original_text=original_text)
            incompatible_sport_signal = has_non_mlb_sport_signal(text)
        else:
            signals = extract_team_signals(text, teams, original_text=original_text)
            incompatible_sport_signal = has_non_nba_sport_signal(text)
        signal_by_team = {signal.team_id: signal for signal in signals}
        signal_ids = set(signal_by_team)
        team_pairs = {frozenset((left, right)) for left, right in combinations(signal_ids, 2)}
        relevant_events = tuple(
            event
            for event in events
            if frozenset((event.home_team_id, event.away_team_id)) in team_pairs
        )
        fingerprint = _fingerprint(
            market=market,
            policy=self._policy,
            signals=signals,
            relevant_events=relevant_events,
        )
        reference_time, reference_source = _reference_time(market)
        nfl_contract = evaluate_nfl_contract(market) if market.league is SportsLeague.NFL else None
        if nfl_contract is not None and market.occurrence_time is None:
            reference_time, reference_source = None, "contract_date"
        base_evidence = {
            "normalized_text": text,
            "market_last_seen_at": market.last_seen_at.isoformat(),
            "reference_time_source": reference_source,
            "reference_time": reference_time.isoformat() if reference_time is not None else None,
            "league": market.league.value,
            "incompatible_sport_signal": incompatible_sport_signal,
        }

        if nfl_contract is not None:
            base_evidence.update(
                {
                    "contract_policy_version": NFL_CONTRACT_POLICY_VERSION,
                    "contract_eligible_for_research": nfl_contract.eligible,
                    "contract_reason": nfl_contract.reason,
                    "contract_date": nfl_contract.game_date.isoformat()
                    if nfl_contract.game_date
                    else None,
                    "tie_yes_payout": "0.50" if nfl_contract.eligible else None,
                    "postponement_window_hours": "48" if nfl_contract.eligible else None,
                    "rules_primary": market.rules_primary,
                    "rules_secondary": market.rules_secondary,
                    "exceptional_settlement": "official_exchange_fair_price_required",
                    "execution_supported": False,
                }
            )
            selected: tuple[TeamSignal, ...] = ()
            if nfl_contract.selected_team:
                selected_text = f"{nfl_contract.selected_team} Pro Football"
                selected = extract_nfl_team_signals(
                    normalize_match_text(selected_text), teams, original_text=selected_text
                )
            nfl_reason = nfl_contract.reason if not nfl_contract.eligible else None
            if nfl_reason is None:
                designators = re.split(r" (?:vs\.?|at) ", nfl_contract.matchup or "")
                resolved_pair = {resolve_nfl_team_designator(value, teams) for value in designators}
                if len(designators) != 2 or None in resolved_pair or resolved_pair != signal_ids:
                    nfl_reason = "unrecognized_matchup_designators"
                if resolve_nfl_team_designator(nfl_contract.selected_team or "", teams) is None:
                    nfl_reason = "unrecognized_yes_designator"
            if nfl_reason is None and (len(selected) != 1 or selected[0].team_id not in signal_ids):
                nfl_reason = "unresolved_yes_team"
            if nfl_reason is None:
                selected_team = next(team for team in teams if team.id == selected[0].team_id)
                suffix = (market.provider_market_id or "").rsplit("-", 1)[-1]
                if suffix not in nfl_team_codes(selected_team.abbreviation):
                    nfl_reason = "conflicting_yes_team_identifier"
                pair_text = f"{nfl_contract.matchup} Pro Football"
                pair = extract_nfl_team_signals(
                    normalize_match_text(pair_text), teams, original_text=pair_text
                )
                if len(pair) != 2 or {signal.team_id for signal in pair} != signal_ids:
                    nfl_reason = "conflicting_matchup_teams"
                else:
                    pair_teams = [team for team in teams if team.id in signal_ids]
                    first_codes = nfl_team_codes(pair_teams[0].abbreviation)
                    second_codes = nfl_team_codes(pair_teams[1].abbreviation)
                    ticker_pair = (market.provider_event_id or "").split("-")[-1][7:]
                    if ticker_pair not in {
                        code for a in first_codes for b in second_codes for code in (a + b, b + a)
                    }:
                        nfl_reason = "conflicting_matchup_identifiers"
                for label in market.outcome_labels:
                    if label.casefold() in {"yes", "no"}:
                        continue
                    label_text = f"{label} Pro Football"
                    label_signals = extract_nfl_team_signals(
                        normalize_match_text(label_text), teams, original_text=label_text
                    )
                    if len(label_signals) != 1 or label_signals[0].team_id != selected[0].team_id:
                        nfl_reason = "conflicting_outcome_labels"
            if nfl_reason is not None:
                reason = nfl_reason
                base_evidence["contract_eligible_for_research"] = False
                base_evidence["contract_reason"] = reason
                return self._decision(
                    market=market,
                    status=MarketEventMatchStatus.UNMATCHED,
                    confidence=Decimal("0"),
                    method="nfl_contract_ineligible",
                    reason=reason,
                    fingerprint=fingerprint,
                    signals=signals,
                    candidates=(),
                    evidence=base_evidence,
                    evaluated_at=evaluation_time,
                )
            base_evidence["yes_team_id"] = str(selected[0].team_id)

        if incompatible_sport_signal:
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.UNMATCHED,
                confidence=Decimal("0"),
                method="incompatible_sport_signal",
                reason="market text contains an explicit incompatible sport signal",
                fingerprint=fingerprint,
                signals=signals,
                candidates=(),
                evidence=base_evidence,
                evaluated_at=evaluation_time,
            )
        if len(signals) < 2:
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.UNMATCHED,
                confidence=Decimal("0"),
                method="insufficient_team_evidence",
                reason=f"market text did not identify two {market.league.value.upper()} teams",
                fingerprint=fingerprint,
                signals=signals,
                candidates=(),
                evidence=base_evidence,
                evaluated_at=evaluation_time,
            )

        candidates = tuple(
            sorted(
                (
                    _candidate_score(
                        event,
                        team_score=_quantize(
                            (
                                signal_by_team[event.home_team_id].quality
                                + signal_by_team[event.away_team_id].quality
                            )
                            / Decimal("2")
                        ),
                        reference_time=reference_time,
                        reference_source=reference_source,
                        policy=self._policy,
                        nfl_date=nfl_contract.game_date if nfl_contract else None,
                    )
                    for event in relevant_events
                ),
                key=lambda candidate: (-candidate.confidence, str(candidate.event_id)),
            )
        )

        if len(signals) > 2:
            confidence = candidates[0].confidence if candidates else Decimal("0")
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.UNMATCHED,
                confidence=confidence,
                method="non_single_game_market",
                reason=f"market text identified more than two {market.league.value.upper()} teams",
                fingerprint=fingerprint,
                signals=signals,
                candidates=candidates,
                evidence=base_evidence,
                evaluated_at=evaluation_time,
            )
        if not candidates:
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.UNMATCHED,
                confidence=Decimal("0"),
                method="no_team_pair_event",
                reason=(
                    "no persisted event contains the identified "
                    f"{market.league.value.upper()} team pair"
                ),
                fingerprint=fingerprint,
                signals=signals,
                candidates=(),
                evidence=base_evidence,
                evaluated_at=evaluation_time,
            )

        if reference_time is None and nfl_contract is None:
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.AMBIGUOUS,
                confidence=candidates[0].confidence,
                method="team_pair_only",
                reason="team-pair candidates exist but the market has no usable event time",
                fingerprint=fingerprint,
                signals=signals,
                candidates=candidates,
                evidence=base_evidence,
                evaluated_at=evaluation_time,
            )

        viable = tuple(candidate for candidate in candidates if candidate.within_time_window)
        if not viable:
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.UNMATCHED,
                confidence=candidates[0].confidence,
                method="date_mismatch",
                reason="identified team-pair events fall outside the configured time window",
                fingerprint=fingerprint,
                signals=signals,
                candidates=candidates,
                evidence=base_evidence,
                evaluated_at=evaluation_time,
            )

        best = viable[0]
        runner_up = viable[1] if len(viable) > 1 else None
        margin = best.confidence - runner_up.confidence if runner_up is not None else Decimal("1")
        evidence = {
            **base_evidence,
            "runner_up_margin": str(margin),
        }
        if best.confidence < self._policy.min_confidence:
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.AMBIGUOUS,
                confidence=best.confidence,
                method=best.method,
                reason="best candidate is below the configured confidence threshold",
                fingerprint=fingerprint,
                signals=signals,
                candidates=candidates,
                evidence=evidence,
                evaluated_at=evaluation_time,
            )
        if runner_up is not None and margin < self._policy.ambiguity_margin:
            return self._decision(
                market=market,
                status=MarketEventMatchStatus.AMBIGUOUS,
                confidence=best.confidence,
                method=best.method,
                reason="best candidate is not sufficiently separated from the runner-up",
                fingerprint=fingerprint,
                signals=signals,
                candidates=candidates,
                evidence=evidence,
                evaluated_at=evaluation_time,
            )
        return self._decision(
            market=market,
            status=MarketEventMatchStatus.MATCHED,
            confidence=best.confidence,
            method=best.method,
            reason="unique candidate met the configured confidence and margin thresholds",
            fingerprint=fingerprint,
            signals=signals,
            candidates=candidates,
            evidence=evidence,
            evaluated_at=evaluation_time,
            sports_event_id=best.event_id,
        )

    def _decision(
        self,
        *,
        market: MarketMatchInput,
        status: MarketEventMatchStatus,
        confidence: Decimal,
        method: str,
        reason: str,
        fingerprint: str,
        signals: tuple[TeamSignal, ...],
        candidates: tuple[CandidateScore, ...],
        evidence: dict[str, str | bool | None],
        evaluated_at: datetime,
        sports_event_id: UUID | None = None,
    ) -> MarketEventMatchDecision:
        eligible = status is MarketEventMatchStatus.MATCHED and market.league is SportsLeague.NBA
        return MarketEventMatchDecision(
            market_id=market.id,
            league=market.league,
            sports_event_id=sports_event_id,
            status=status,
            confidence=_quantize(confidence),
            method=method,
            reason=reason,
            matcher_version=self._policy.matcher_version,
            min_confidence=self._policy.min_confidence,
            ambiguity_margin=self._policy.ambiguity_margin,
            time_window_hours=self._policy.time_window_hours,
            automatic_trading_eligible=eligible,
            input_fingerprint=fingerprint,
            team_signals=signals,
            candidate_scores=candidates,
            evidence=evidence,
            evaluated_at=evaluated_at,
        )
