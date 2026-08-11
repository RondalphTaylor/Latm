from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from uuid import UUID

from app.domain.forecasts import (
    BaseForecast,
    EloConfiguration,
    ForecastTargetInput,
    HistoricalGameInput,
)

ELO_FORMULA = (
    "p_home=1/(1+10^(-(home_rating+home_court_advantage-away_rating)/logistic_scale)); "
    "delta=k_factor*(actual_home_win-p_home); home+=delta; away-=delta"
)
_PROBABILITY_QUANTUM = Decimal("0.000001")
_RATING_QUANTUM = Decimal("0.0001")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def configuration_fingerprint(configuration: EloConfiguration) -> str:
    """Hash every formula and parameter that defines effective model behavior."""
    return _canonical_hash(
        {
            "configuration": configuration.model_dump(mode="json"),
            "formula": ELO_FORMULA,
            "probability_precision": str(_PROBABILITY_QUANTUM),
            "rating_precision": str(_RATING_QUANTUM),
        }
    )


def effective_model_version(configuration: EloConfiguration) -> str:
    """Make parameter changes unambiguous in the persisted model identity."""
    fingerprint = configuration_fingerprint(configuration)
    return f"{configuration.code_version}+cfg.{fingerprint[:12]}"


def source_event_fingerprint(
    *,
    event_id: UUID,
    scheduled_start_time: datetime,
    home_team_id: UUID,
    away_team_id: UUID,
    event_status: str,
) -> str:
    """Hash forecast-relevant event semantics, excluding observation time."""
    return _canonical_hash(
        {
            "event_id": str(event_id),
            "scheduled_start_time": scheduled_start_time.isoformat(),
            "home_team_id": str(home_team_id),
            "away_team_id": str(away_team_id),
            "event_status": event_status,
        }
    )


class EloForecastModel:
    """Leakage-free deterministic NBA Elo V1 implementation."""

    def __init__(
        self,
        configuration: EloConfiguration | None = None,
        *,
        generated_at: datetime | None = None,
    ) -> None:
        self.configuration = configuration or EloConfiguration()
        self.configuration_fingerprint = configuration_fingerprint(self.configuration)
        self.model_version = effective_model_version(self.configuration)
        self._generated_at = generated_at or datetime.now(UTC)

    def _expected_home_probability_raw(
        self,
        home_rating: Decimal,
        away_rating: Decimal,
    ) -> Decimal:
        with localcontext() as context:
            context.prec = 40
            adjusted_difference = (
                home_rating + self.configuration.home_court_advantage - away_rating
            )
            exponent = -adjusted_difference / self.configuration.logistic_scale
            return Decimal("1") / (Decimal("1") + Decimal("10") ** exponent)

    def home_win_probability(
        self,
        home_rating: Decimal,
        away_rating: Decimal,
    ) -> Decimal:
        """Return the stored-precision home win probability."""
        return self._expected_home_probability_raw(home_rating, away_rating).quantize(
            _PROBABILITY_QUANTUM,
            rounding=ROUND_HALF_UP,
        )

    def update_ratings(
        self,
        home_rating: Decimal,
        away_rating: Decimal,
        *,
        home_won: bool,
    ) -> tuple[Decimal, Decimal]:
        """Apply one zero-sum standard Elo result update."""
        expected_home = self._expected_home_probability_raw(home_rating, away_rating)
        actual_home = Decimal("1") if home_won else Decimal("0")
        delta = self.configuration.k_factor * (actual_home - expected_home)
        new_home = (home_rating + delta).quantize(_RATING_QUANTUM, rounding=ROUND_HALF_UP)
        new_away = (away_rating - delta).quantize(_RATING_QUANTUM, rounding=ROUND_HALF_UP)
        return new_home, new_away

    def forecast_many(
        self,
        targets: tuple[ForecastTargetInput, ...],
        history: tuple[HistoricalGameInput, ...],
    ) -> tuple[BaseForecast, ...]:
        """Replay final games strictly before each target's explicit cutoff."""
        ratings: dict[UUID, Decimal] = {}
        games_by_team: dict[UUID, int] = {}
        ordered_history = sorted(
            history,
            key=lambda game: (game.scheduled_start_time, str(game.event_id)),
        )
        ordered_targets = sorted(
            targets,
            key=lambda target: (
                target.history_cutoff,
                target.scheduled_start_time,
                str(target.event_id),
            ),
        )
        history_index = 0
        training_hasher = hashlib.sha256()
        games_seen = 0
        games_processed = 0
        skipped_ties = 0
        skipped_incomplete = 0
        latest_training_event_time: datetime | None = None
        forecasts: list[BaseForecast] = []

        for target in ordered_targets:
            while (
                history_index < len(ordered_history)
                and ordered_history[history_index].scheduled_start_time < target.history_cutoff
            ):
                game = ordered_history[history_index]
                history_index += 1
                games_seen += 1
                disposition = "processed"
                if game.home_score is None or game.away_score is None:
                    skipped_incomplete += 1
                    disposition = "skipped_incomplete"
                elif game.home_score == game.away_score:
                    skipped_ties += 1
                    disposition = "skipped_tie"
                else:
                    home_rating = ratings.get(
                        game.home_team_id,
                        self.configuration.initial_rating,
                    )
                    away_rating = ratings.get(
                        game.away_team_id,
                        self.configuration.initial_rating,
                    )
                    new_home, new_away = self.update_ratings(
                        home_rating,
                        away_rating,
                        home_won=game.home_score > game.away_score,
                    )
                    ratings[game.home_team_id] = new_home
                    ratings[game.away_team_id] = new_away
                    games_by_team[game.home_team_id] = games_by_team.get(game.home_team_id, 0) + 1
                    games_by_team[game.away_team_id] = games_by_team.get(game.away_team_id, 0) + 1
                    games_processed += 1
                    latest_training_event_time = game.scheduled_start_time

                semantic_game = {
                    "event_id": str(game.event_id),
                    "scheduled_start_time": game.scheduled_start_time.isoformat(),
                    "home_team_id": str(game.home_team_id),
                    "away_team_id": str(game.away_team_id),
                    "home_score": game.home_score,
                    "away_score": game.away_score,
                    "disposition": disposition,
                }
                training_hasher.update(
                    json.dumps(
                        semantic_game,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                    + b"\n"
                )

            home_rating = ratings.get(
                target.home_team_id,
                self.configuration.initial_rating,
            )
            away_rating = ratings.get(
                target.away_team_id,
                self.configuration.initial_rating,
            )
            home_probability = self.home_win_probability(home_rating, away_rating)
            away_probability = Decimal("1.000000") - home_probability
            training_fingerprint = training_hasher.hexdigest()
            event_fingerprint = source_event_fingerprint(
                event_id=target.event_id,
                scheduled_start_time=target.scheduled_start_time,
                home_team_id=target.home_team_id,
                away_team_id=target.away_team_id,
                event_status=target.event_status,
            )
            input_fingerprint = _canonical_hash(
                {
                    "target": {
                        "event_id": str(target.event_id),
                        "scheduled_start_time": target.scheduled_start_time.isoformat(),
                        "home_team_id": str(target.home_team_id),
                        "away_team_id": str(target.away_team_id),
                        "event_status": target.event_status,
                        "purpose": target.purpose.value,
                    },
                    "source_event_fingerprint": event_fingerprint,
                    "configuration_fingerprint": self.configuration_fingerprint,
                    "training_data_fingerprint": training_fingerprint,
                    "home_team_rating": str(home_rating),
                    "away_team_rating": str(away_rating),
                    "home_prior_games": games_by_team.get(target.home_team_id, 0),
                    "away_prior_games": games_by_team.get(target.away_team_id, 0),
                }
            )
            forecasts.append(
                BaseForecast(
                    sports_event_id=target.event_id,
                    home_team_id=target.home_team_id,
                    away_team_id=target.away_team_id,
                    home_win_probability=home_probability,
                    away_win_probability=away_probability,
                    home_team_rating=home_rating,
                    away_team_rating=away_rating,
                    adjusted_rating_difference=home_rating
                    + self.configuration.home_court_advantage
                    - away_rating,
                    model_name=self.configuration.model_name,
                    model_version=self.model_version,
                    configuration_fingerprint=self.configuration_fingerprint,
                    source_event_fingerprint=event_fingerprint,
                    training_data_fingerprint=training_fingerprint,
                    input_fingerprint=input_fingerprint,
                    purpose=target.purpose,
                    training_games_seen=games_seen,
                    training_games_processed=games_processed,
                    skipped_tied_games=skipped_ties,
                    skipped_incomplete_games=skipped_incomplete,
                    home_prior_games=games_by_team.get(target.home_team_id, 0),
                    away_prior_games=games_by_team.get(target.away_team_id, 0),
                    latest_training_event_time=latest_training_event_time,
                    forecast_as_of=target.history_cutoff,
                    source_event_last_seen_at=target.source_last_seen_at,
                    generated_at=self._generated_at,
                )
            )
        return tuple(forecasts)
