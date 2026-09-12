from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.markets import MarketPriceRecord
from app.models.nfl_forecasting import NflPayoutForecastRecord
from app.models.nfl_pilot import (
    NflPilotEntryRecord,
    NflPilotPositionRecord,
    NflPilotScenarioRecord,
)
from app.models.nfl_preflights import NflPaperPreflightRecord
from app.services.nfl_research.shadow_repository import NflShadowForecastRepository


class NflPilotEntryService:
    """Fill an isolated paper entry from a still-current cost-qualified preflight."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _now(self) -> datetime:
        now = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(now, datetime):
            raise ValueError("database clock unavailable")
        return now

    async def run(
        self, scenario_id: UUID, preflight_id: UUID, idempotency_key: str
    ) -> tuple[NflPilotEntryRecord, bool]:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", idempotency_key) is None:
            raise ValueError("invalid idempotency key")
        try:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"nfl-pilot-entry:{scenario_id}"},
            )
            existing = await self._session.scalar(
                select(NflPilotEntryRecord).where(
                    NflPilotEntryRecord.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                if existing.scenario_id != scenario_id or existing.preflight_id != preflight_id:
                    raise ValueError("idempotency key belongs to another NFL pilot entry")
                await self._session.commit()
                return existing, False
            scenario = await self._session.get(NflPilotScenarioRecord, scenario_id)
            preflight = await self._session.get(NflPaperPreflightRecord, preflight_id)
            if scenario is None:
                raise LookupError("NFL pilot scenario not found")
            if preflight is None:
                raise LookupError("NFL paper preflight not found")
            now = await self._now()
            if scenario.execution_mode != "paper" or scenario.live_trading_enabled:
                raise ValueError("NFL pilot scenario is not paper-only")
            if (
                preflight.execution_mode != "paper"
                or preflight.sizing_status != "cost_qualified"
                or preflight.adjusted_edge is None
                or preflight.quantity <= 0
                or not preflight.reviewed_at <= now < preflight.valid_until
            ):
                raise ValueError("NFL pilot requires a fresh cost-qualified preflight")
            if preflight.adjusted_edge < scenario.minimum_adjusted_edge:
                raise ValueError("NFL pilot preflight does not meet scenario edge minimum")
            forecast_id = preflight.audit.get("forecast_id")
            price_id = preflight.audit.get("price_id")
            if not isinstance(forecast_id, str) or not isinstance(price_id, str):
                raise ValueError("NFL pilot preflight audit is incomplete")
            forecast = await self._session.get(NflPayoutForecastRecord, UUID(forecast_id))
            if forecast is None:
                raise ValueError("NFL pilot forecast source is unavailable")
            shadow, _ = await NflShadowForecastRepository(self._session)._run(forecast.match_id)
            if shadow.id != forecast.source_shadow_snapshot_id:
                raise ValueError("NFL pilot source is no longer current")
            latest_price = await self._session.scalar(
                select(MarketPriceRecord)
                .where(MarketPriceRecord.market_id == preflight.market_id)
                .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
                .limit(1)
            )
            if latest_price is None or str(latest_price.id) != price_id:
                raise ValueError("NFL pilot quote is no longer current")
            committed = await self._session.scalar(
                select(func.coalesce(func.sum(NflPilotEntryRecord.total_cost), Decimal("0.00")))
                .outerjoin(
                    NflPilotPositionRecord,
                    NflPilotPositionRecord.entry_id == NflPilotEntryRecord.id,
                )
                .where(
                    NflPilotEntryRecord.scenario_id == scenario.id,
                    or_(
                        NflPilotPositionRecord.id.is_(None),
                        NflPilotPositionRecord.status == "open",
                    ),
                )
            )
            committed_cost = Decimal(str(committed))
            entry_cap = (scenario.starting_bankroll * scenario.per_entry_exposure).quantize(
                Decimal("0.01")
            )
            aggregate_cap = (scenario.starting_bankroll * scenario.aggregate_exposure).quantize(
                Decimal("0.01")
            )
            aggregate_remaining = aggregate_cap - committed_cost
            if preflight.total_cost > entry_cap:
                raise ValueError("NFL pilot preflight exceeds per-entry exposure cap")
            if preflight.total_cost > aggregate_remaining:
                raise ValueError("NFL pilot preflight exceeds aggregate exposure cap")
            values = {
                "id": uuid4(),
                "idempotency_key": idempotency_key,
                "scenario_id": scenario.id,
                "portfolio_id": scenario.portfolio_id,
                "preflight_id": preflight.id,
                "opportunity_id": preflight.opportunity_id,
                "market_id": preflight.market_id,
                "direction": preflight.direction,
                "entered_at": now,
                "status": "filled",
                "quantity": preflight.quantity,
                "gross_cost": preflight.gross_cost,
                "estimated_fee": preflight.estimated_fee,
                "total_cost": preflight.total_cost,
                "adjusted_edge": preflight.adjusted_edge,
                "minimum_adjusted_edge": scenario.minimum_adjusted_edge,
                "entry_cap": entry_cap,
                "aggregate_cap": aggregate_cap,
                "execution_mode": "paper",
                "live_trading_enabled": False,
                "policy_version": "nfl-paper-pilot-entry-v1",
                "policy_fingerprint": scenario.policy_fingerprint,
                "audit": {
                    "authorization": "user-approved historical-qualified paper pilot",
                    "scenario_policy_version": scenario.policy_version,
                    "preflight_id": str(preflight.id),
                    "forecast_id": forecast_id,
                    "price_id": price_id,
                    "source_shadow_snapshot_id": str(shadow.id),
                    "committed_before": str(committed_cost),
                    "aggregate_remaining_before": str(aggregate_remaining),
                },
            }
            inserted = await self._session.scalar(
                insert(NflPilotEntryRecord)
                .values(values)
                .on_conflict_do_nothing(index_elements=[NflPilotEntryRecord.idempotency_key])
                .returning(NflPilotEntryRecord.id)
            )
            record = await self._session.scalar(
                select(NflPilotEntryRecord).where(
                    NflPilotEntryRecord.idempotency_key == idempotency_key
                )
            )
            if record is None:
                raise RuntimeError("NFL pilot entry could not be read back")
            await self._session.commit()
            return record, inserted is not None
        except Exception:
            await self._session.rollback()
            raise
