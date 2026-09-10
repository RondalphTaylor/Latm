from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import TypeAdapter
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.domain.nfl_shadow import NflShadowTarget
from app.models.markets import PredictionMarketRecord
from app.models.matching import MarketEventMatchRecord
from app.models.nfl_forecasting import NflPayoutForecastRecord
from app.models.sports import SportsEventRecord
from app.services.matching.service import MarketEventMatchingService
from app.services.nfl_forecasting.engine import build_nfl_payout_forecast_candidate
from app.services.nfl_research.baseline import NflResearchGame
from app.services.nfl_research.shadow import build_shadow_prediction
from app.services.nfl_research.shadow_repository import NflShadowForecastRepository

_SEED_GAMES = TypeAdapter(list[NflResearchGame])


class NflPayoutForecastRepository:
    """Atomically persist blocked paper candidates with replay-safe request identity."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _now(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise ValueError("database clock unavailable")
        return value

    async def _find_key(self, key: str) -> NflPayoutForecastRecord | None:
        rows = await self._session.scalars(
            select(NflPayoutForecastRecord)
            .where(NflPayoutForecastRecord.idempotency_key == key)
            .execution_options(populate_existing=True)
        )
        return rows.one_or_none()

    async def run(
        self, match_id: UUID, idempotency_key: str
    ) -> tuple[NflPayoutForecastRecord, bool]:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", idempotency_key) is None:
            raise ValueError("invalid idempotency key")
        try:
            # Global key serialization precedes market/event locks even across different matches.
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "nfl-payout-candidate:" + idempotency_key},
            )
            existing = await self._find_key(idempotency_key)
            if existing is not None:
                if existing.match_id != match_id:
                    raise ValueError("idempotency key belongs to another match")
                await self._session.commit()
                return existing, False
            # Internal method deliberately does not commit: candidate failure rolls back new shadow.
            shadow, _ = await NflShadowForecastRepository(self._session)._run(match_id)
            event = await self._session.get(SportsEventRecord, shadow.sports_event_id)
            market = await self._session.get(PredictionMarketRecord, shadow.market_id)
            if event is None or market is None:
                raise LookupError("locked NFL source no longer exists")
            if market.close_time is None:
                raise ValueError("NFL paper candidate requires an explicit market close time")
            now = await self._now()
            match = await self._session.get(MarketEventMatchRecord, match_id)
            if match is None:
                raise LookupError("locked NFL match no longer exists")
            seed = shadow.audit.get("seed")
            if not isinstance(seed, dict):
                raise ValueError("shadow historical seed audit is missing")
            games = _SEED_GAMES.validate_python(seed.get("games"))
            target = NflShadowTarget.model_validate(
                {
                    "event_id": event.id,
                    "provider_event_id": event.provider_event_id,
                    "season": event.season,
                    "week": event.raw_data.get("week"),
                    "scheduled_start": event.scheduled_start_time,
                    "home_team_id": event.home_team_id,
                    "away_team_id": event.away_team_id,
                    "source_last_seen": event.last_seen_at,
                }
            )
            prediction = build_shadow_prediction(games, target, now)
            candidate = build_nfl_payout_forecast_candidate(
                prediction=prediction,
                match_id=match_id,
                market_id=market.id,
                yes_team_id=shadow.yes_team_id,
                source_shadow_snapshot_id=shadow.id,
                market_close_time=market.close_time,
                market_last_seen_at=market.last_seen_at,
            )
            finished = await self._now()
            if finished < now or finished >= candidate.valid_until:
                raise ValueError("NFL candidate expired or clock changed while building")
            values = candidate.model_dump(exclude={"block_reasons"})
            values.update(
                id=uuid4(),
                idempotency_key=idempotency_key,
                scheduled_start_time=event.scheduled_start_time,
                market_close_time=market.close_time,
                event_source_last_seen_at=event.last_seen_at,
                market_source_last_seen_at=market.last_seen_at,
                audit={
                    "candidate": candidate.model_dump(mode="json"),
                    "prediction": prediction.model_dump(mode="json"),
                    "current_event_source": event.raw_data,
                    "current_market_source": market.raw_data,
                    "current_market": MarketEventMatchingService._market_input(market).model_dump(
                        mode="json"
                    ),
                    "current_match_evidence": match.evidence,
                    "current_match_input_fingerprint": match.input_fingerprint,
                    "seed_games": [game.model_dump(mode="json") for game in games],
                    "market_close_time": market.close_time.isoformat(),
                    "market_last_seen_at": market.last_seen_at.isoformat(),
                    "insert_checked_at": finished.isoformat(),
                    "source_shadow_snapshot_id": str(shadow.id),
                },
            )
            inserted_id = await self._session.scalar(
                insert(NflPayoutForecastRecord)
                .values(values)
                .on_conflict_do_nothing(index_elements=[NflPayoutForecastRecord.idempotency_key])
                .returning(NflPayoutForecastRecord.id)
            )
            record = await self._find_key(idempotency_key)
            if record is None:
                raise ValueError("NFL candidate insert could not be read back")
            if record.match_id != match_id:
                raise ValueError("idempotency key belongs to another match")
            await self._session.commit()
            return record, inserted_id is not None
        except Exception:
            await self._session.rollback()
            raise

    async def get_forecast(self, forecast_id: UUID) -> NflPayoutForecastRecord | None:
        rows = await self._session.scalars(
            select(NflPayoutForecastRecord)
            .where(NflPayoutForecastRecord.id == forecast_id)
            .execution_options(populate_existing=True)
        )
        return rows.one_or_none()

    async def list_forecasts(self, *, limit: int, offset: int) -> list[NflPayoutForecastRecord]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid NFL candidate pagination")
        rows = await self._session.scalars(
            select(NflPayoutForecastRecord)
            .options(defer(NflPayoutForecastRecord.audit))
            .order_by(
                NflPayoutForecastRecord.generated_at.desc(), NflPayoutForecastRecord.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all())
