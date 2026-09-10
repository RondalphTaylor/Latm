from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer, noload, selectinload

from app.core.config import get_settings
from app.domain.matching import MatchingPolicy
from app.domain.nfl_shadow import NflShadowTarget
from app.models.markets import PredictionMarketRecord
from app.models.matching import MarketEventMatchRecord
from app.models.nfl_shadow import NflShadowForecastRecord
from app.models.sports import SportsEventRecord, TeamRecord
from app.providers.sports.nfl import NflGamePayload
from app.services.matching.matcher import MATCHER_VERSION, MarketEventMatcher
from app.services.matching.nfl_contracts import NFL_CONTRACT_POLICY_VERSION
from app.services.matching.service import MarketEventMatchingService
from app.services.nfl_research.repository import NflResearchRepository
from app.services.nfl_research.shadow import build_shadow_prediction


def _fresh(observed: datetime, now: datetime) -> bool:
    return now - timedelta(hours=24) <= observed <= now


class NflShadowForecastRepository:
    """Append a frozen research snapshot after locked, current pregame revalidation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _now(self) -> datetime:
        result = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(result, datetime):
            raise ValueError("database clock unavailable")
        return result

    async def _latest_match(self, market_id: UUID) -> MarketEventMatchRecord | None:
        result = await self._session.scalars(
            select(MarketEventMatchRecord)
            .where(MarketEventMatchRecord.market_id == market_id)
            .order_by(MarketEventMatchRecord.evaluated_at.desc(), MarketEventMatchRecord.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
        )
        return result.one_or_none()

    async def run(self, match_id: UUID) -> tuple[NflShadowForecastRecord, bool]:
        try:
            result = await self._run(match_id)
            await self._session.commit()
            return result
        except Exception:
            await self._session.rollback()
            raise

    async def _run(self, match_id: UUID) -> tuple[NflShadowForecastRecord, bool]:
        requested = await self._session.get(MarketEventMatchRecord, match_id)
        if requested is None:
            raise LookupError("NFL match not found")
        market = await self._session.scalar(
            select(PredictionMarketRecord)
            .where(PredictionMarketRecord.id == requested.market_id)
            .options(
                selectinload(PredictionMarketRecord.outcomes),
                noload(PredictionMarketRecord.prices),
                noload(PredictionMarketRecord.resolutions),
            )
            .with_for_update(of=PredictionMarketRecord)
            .execution_options(populate_existing=True)
        )
        if market is None:
            raise LookupError("NFL market not found")
        match = await self._latest_match(market.id)
        if (
            match is None
            or match.id != match_id
            or match.league != "nfl"
            or match.status != "matched"
            or match.sports_event_id is None
            or match.automatic_trading_eligible
            or match.evidence.get("contract_eligible_for_research") is not True
            or match.evidence.get("contract_policy_version") != NFL_CONTRACT_POLICY_VERSION
            or match.matcher_version != MATCHER_VERSION
        ):
            raise ValueError("latest match is not an eligible current-policy NFL research match")
        event = await self._session.scalar(
            select(SportsEventRecord)
            .where(SportsEventRecord.id == match.sports_event_id)
            .with_for_update(of=SportsEventRecord)
            .execution_options(populate_existing=True)
        )
        if event is None:
            raise LookupError("NFL event not found")
        now = await self._now()
        if (
            event.provider_name != "balldontlie_nfl"
            or event.league != "nfl"
            or event.season != 2026
            or event.postseason
            or event.postponed
            or event.status != "scheduled"
            or event.home_score is not None
            or event.away_score is not None
            or event.scheduled_start_time <= now
            or market.sports_league != "nfl"
            or market.sports_market_type != "single_game_winner"
            or not market.sports_classification_fingerprint
            or market.status not in {"open", "active"}
            or (market.close_time is not None and market.close_time <= now)
            or not _fresh(event.last_seen_at, now)
            or not _fresh(market.last_seen_at, now)
            or match.evaluated_at > now
        ):
            raise ValueError(
                "current NFL event or market fails pregame, freshness, or lifecycle gates"
            )
        payload = NflGamePayload.model_validate(event.raw_data)
        if (
            str(payload.id) != event.provider_event_id
            or payload.season != 2026
            or payload.postseason
            or payload.status_state.strip().casefold() != "scheduled"
            or payload.date != event.scheduled_start_time
            or str(payload.home_team.id) != event.home_team.provider_team_id
            or str(payload.visitor_team.id) != event.away_team.provider_team_id
            or event.home_team.provider_name != "balldontlie_nfl"
            or event.away_team.provider_name != "balldontlie_nfl"
            or event.home_team.league != "nfl"
            or event.away_team.league != "nfl"
            or type(event.raw_data.get("week")) is not int
            or event.raw_data.get("preseason", False) is not False
            or event.raw_data.get("season_type", 2) not in (2, "2")
            or payload.home_team_score not in (None, 0)
            or payload.visitor_team_score not in (None, 0)
        ):
            raise ValueError("NFL target source metadata conflicts with its normalized event")
        settings = get_settings()
        policy = MatchingPolicy(
            matcher_version=MATCHER_VERSION,
            min_confidence=settings.matching_min_confidence,
            ambiguity_margin=settings.matching_ambiguity_margin,
            time_window_hours=settings.matching_time_window_hours,
        )
        teams = list(
            (
                await self._session.scalars(
                    select(TeamRecord).where(
                        TeamRecord.league == "nfl", TeamRecord.provider_name == "balldontlie_nfl"
                    )
                )
            ).all()
        )
        previous_candidate_ids = [UUID(str(row["event_id"])) for row in match.candidate_scores]
        candidates = list(
            (
                await self._session.scalars(
                    select(SportsEventRecord)
                    .where(
                        SportsEventRecord.league == "nfl",
                        SportsEventRecord.provider_name == "balldontlie_nfl",
                        or_(
                            SportsEventRecord.id.in_(previous_candidate_ids),
                            SportsEventRecord.event_date.between(
                                event.event_date - timedelta(days=7),
                                event.event_date + timedelta(days=7),
                            ),
                        ),
                    )
                    .execution_options(populate_existing=True)
                )
            )
            .unique()
            .all()
        )
        current = MarketEventMatcher(policy).match(
            MarketEventMatchingService._market_input(market),
            teams=tuple(MarketEventMatchingService._team_input(team) for team in teams),
            events=tuple(
                MarketEventMatchingService._event_input(candidate) for candidate in candidates
            ),
            evaluated_at=now,
        )
        if (
            current.status != "matched"
            or current.sports_event_id != event.id
            or current.input_fingerprint != match.input_fingerprint
            or current.evidence.get("yes_team_id") != match.evidence.get("yes_team_id")
            or current.evidence.get("contract_eligible_for_research") is not True
        ):
            raise ValueError("stored NFL match is stale or ambiguous; rerun matching")
        yes_team_id = UUID(str(current.evidence["yes_team_id"]))
        if yes_team_id not in (event.home_team_id, event.away_team_id):
            raise ValueError("NFL YES team does not belong to the current event")
        target = NflShadowTarget(
            event_id=event.id,
            provider_event_id=event.provider_event_id,
            season=2026,
            week=payload.week,
            scheduled_start=event.scheduled_start_time,
            home_team_id=event.home_team_id,
            away_team_id=event.away_team_id,
            source_last_seen=event.last_seen_at,
        )
        seed = await NflResearchRepository(self._session).select_games()
        if seed.blockers:
            raise ValueError("NFL shadow historical seed blocked: " + ", ".join(seed.blockers))
        prediction = build_shadow_prediction(list(seed.games), target, now)
        generated = await self._now()
        if (
            generated < now
            or generated >= event.scheduled_start_time
            or (market.close_time is not None and market.close_time <= generated)
            or not _fresh(market.last_seen_at, generated)
            or not _fresh(event.last_seen_at, generated)
        ):
            raise ValueError(
                "NFL kickoff or freshness boundary crossed while building shadow snapshot"
            )
        latest = await self._latest_match(market.id)
        if latest is None or latest.id != match_id:
            raise ValueError("NFL match changed while building shadow snapshot")
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "model": prediction.config_version,
                    "seed": prediction.seed_fingerprint,
                    "target": prediction.target_fingerprint,
                    "market_id": str(market.id),
                    "match_input": match.input_fingerprint,
                    "contract_policy": NFL_CONTRACT_POLICY_VERSION,
                    "yes_team_id": str(yes_team_id),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        yes_payout = (
            prediction.expected_home_payout
            if yes_team_id == event.home_team_id
            else prediction.expected_away_payout
        )
        audit = {
            "prediction": prediction.model_dump(mode="json"),
            "seed": {
                "games": [game.model_dump(mode="json") for game in seed.games],
                "source_fingerprint": seed.source_fingerprint,
            },
            "target_source": event.raw_data,
            "market_source": MarketEventMatchingService._market_input(market).model_dump(
                mode="json"
            ),
            "classification_fingerprint": market.sports_classification_fingerprint,
            "match_evidence": match.evidence,
            "revalidated_match": current.model_dump(mode="json"),
            "match_id": str(match.id),
            "match_evaluated_at": match.evaluated_at.isoformat(),
        }
        inserted_id = await self._session.scalar(
            insert(NflShadowForecastRecord)
            .values(
                id=uuid4(),
                match_id=match.id,
                market_id=market.id,
                sports_event_id=event.id,
                yes_team_id=yes_team_id,
                model_version=prediction.config_version,
                seed_fingerprint=prediction.seed_fingerprint,
                input_fingerprint=fingerprint,
                generated_at=generated,
                scheduled_start_time=event.scheduled_start_time,
                target_source_last_seen_at=event.last_seen_at,
                expected_home_payout=prediction.expected_home_payout,
                expected_away_payout=prediction.expected_away_payout,
                expected_yes_payout=yes_payout,
                expected_no_payout=Decimal("1") - yes_payout,
                research_only=True,
                trading_enabled=False,
                audit=audit,
            )
            .on_conflict_do_nothing(index_elements=[NflShadowForecastRecord.input_fingerprint])
            .returning(NflShadowForecastRecord.id)
        )
        record = await self._session.scalar(
            select(NflShadowForecastRecord).where(
                NflShadowForecastRecord.input_fingerprint == fingerprint
            )
        )
        if record is None:
            raise ValueError("NFL shadow snapshot persistence failed")
        return record, inserted_id is not None

    async def get_snapshot(self, snapshot_id: UUID) -> NflShadowForecastRecord | None:
        return await self._session.get(NflShadowForecastRecord, snapshot_id)

    async def list_snapshots(self, *, limit: int, offset: int) -> list[NflShadowForecastRecord]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("NFL shadow pagination is outside its bounds")
        return list(
            (
                await self._session.scalars(
                    select(NflShadowForecastRecord)
                    .options(defer(NflShadowForecastRecord.audit))
                    .order_by(
                        NflShadowForecastRecord.generated_at.desc(),
                        NflShadowForecastRecord.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
