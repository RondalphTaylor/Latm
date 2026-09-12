from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.markets import MarketPriceRecord, MarketResolutionRecord
from app.models.nfl_pilot import (
    NflPilotEntryRecord,
    NflPilotPositionEventRecord,
    NflPilotPositionRecord,
)


def _floor_cent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


class NflPilotLifecycleService:
    """Mark and settle NFL pilot fills without touching NBA execution state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _now(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise ValueError("database clock unavailable")
        return value

    async def _position(self, entry_id: UUID, now: datetime) -> NflPilotPositionRecord:
        position = await self._session.scalar(
            select(NflPilotPositionRecord).where(NflPilotPositionRecord.entry_id == entry_id)
        )
        if position is not None:
            return position
        entry = await self._session.get(NflPilotEntryRecord, entry_id)
        if entry is None:
            raise LookupError("NFL pilot entry not found")
        position = NflPilotPositionRecord(
            id=uuid4(),
            entry_id=entry.id,
            scenario_id=entry.scenario_id,
            market_id=entry.market_id,
            direction=entry.direction,
            quantity=entry.quantity,
            total_cost_basis=entry.total_cost,
            status="open",
            mark_price=None,
            market_value=Decimal("0.00"),
            unrealized_pnl=-entry.total_cost,
            realized_pnl=Decimal("0.00"),
            settled_at=None,
            official_resolution_id=None,
            execution_mode="paper",
            live_trading_enabled=False,
            created_at=now,
            updated_at=now,
            audit={"entry_id": str(entry.id), "created_from": "nfl_pilot_entry"},
        )
        self._session.add(position)
        await self._session.flush()
        return position

    @staticmethod
    def _check_key(idempotency_key: str) -> None:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", idempotency_key) is None:
            raise ValueError("invalid idempotency key")

    async def mark(
        self, entry_id: UUID, idempotency_key: str
    ) -> tuple[NflPilotPositionEventRecord, bool]:
        self._check_key(idempotency_key)
        try:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"nfl-pilot-lifecycle:{entry_id}"},
            )
            existing = await self._session.scalar(
                select(NflPilotPositionEventRecord).where(
                    NflPilotPositionEventRecord.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                await self._session.commit()
                return existing, False
            now = await self._now()
            position = await self._position(entry_id, now)
            if position.status != "open":
                raise ValueError("NFL pilot position is not open")
            price = await self._session.scalar(
                select(MarketPriceRecord)
                .where(MarketPriceRecord.market_id == position.market_id)
                .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
                .limit(1)
            )
            if price is None or price.retrieved_at < now - timedelta(minutes=15):
                raise ValueError("NFL pilot mark requires a fresh market quote")
            bid = price.yes_bid if position.direction == "yes" else price.no_bid
            ask = price.yes_ask if position.direction == "yes" else price.no_ask
            mark_price = bid if bid is not None and bid > 0 else ask
            if mark_price is None or not Decimal("0") < mark_price < Decimal("1"):
                raise ValueError("NFL pilot quote has no usable directional mark")
            market_value = _floor_cent(mark_price * position.quantity)
            unrealized = market_value - position.total_cost_basis
            event = NflPilotPositionEventRecord(
                id=uuid4(),
                idempotency_key=idempotency_key,
                position_id=position.id,
                market_price_id=price.id,
                official_resolution_id=None,
                event_type="mark",
                mark_price=mark_price,
                market_value=market_value,
                unrealized_pnl=unrealized,
                realized_pnl=position.realized_pnl,
                recorded_at=now,
                execution_mode="paper",
                live_trading_enabled=False,
                audit={
                    "mark_basis": "directional_bid" if bid else "directional_ask_fallback",
                    "entry_id": str(entry_id),
                },
            )
            self._session.add(event)
            position.mark_price = mark_price
            position.market_value = market_value
            position.unrealized_pnl = unrealized
            position.updated_at = now
            await self._session.commit()
            return event, True
        except Exception:
            await self._session.rollback()
            raise

    async def settle(
        self, entry_id: UUID, idempotency_key: str
    ) -> tuple[NflPilotPositionEventRecord, bool]:
        self._check_key(idempotency_key)
        try:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"nfl-pilot-lifecycle:{entry_id}"},
            )
            existing = await self._session.scalar(
                select(NflPilotPositionEventRecord).where(
                    NflPilotPositionEventRecord.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                await self._session.commit()
                return existing, False
            now = await self._now()
            position = await self._position(entry_id, now)
            if position.status != "open":
                raise ValueError("NFL pilot position is not open")
            resolution = await self._session.scalar(
                select(MarketResolutionRecord)
                .where(MarketResolutionRecord.market_id == position.market_id)
                .order_by(
                    MarketResolutionRecord.settled_at.desc(), MarketResolutionRecord.id.desc()
                )
                .limit(1)
            )
            if resolution is None:
                raise ValueError("NFL pilot settlement requires an official market resolution")
            payout = resolution.yes_payout if position.direction == "yes" else resolution.no_payout
            proceeds = _floor_cent(payout * position.quantity)
            realized = proceeds - position.total_cost_basis
            event = NflPilotPositionEventRecord(
                id=uuid4(),
                idempotency_key=idempotency_key,
                position_id=position.id,
                market_price_id=None,
                official_resolution_id=resolution.id,
                event_type="settlement",
                mark_price=None,
                market_value=Decimal("0.00"),
                unrealized_pnl=Decimal("0.00"),
                realized_pnl=realized,
                recorded_at=now,
                execution_mode="paper",
                live_trading_enabled=False,
                audit={
                    "entry_id": str(entry_id),
                    "resolution_type": resolution.resolution_type,
                    "held_payout": str(payout),
                    "gross_proceeds": str(proceeds),
                },
            )
            self._session.add(event)
            position.status = "settled"
            position.market_value = Decimal("0.00")
            position.unrealized_pnl = Decimal("0.00")
            position.realized_pnl = realized
            position.settled_at = resolution.settled_at
            position.official_resolution_id = resolution.id
            position.updated_at = now
            await self._session.commit()
            return event, True
        except Exception:
            await self._session.rollback()
            raise
