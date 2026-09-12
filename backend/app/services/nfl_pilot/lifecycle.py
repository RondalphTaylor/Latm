from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_DOWN, Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.markets import MarketPriceRecord, MarketResolutionRecord
from app.models.nfl_forecasting import NflPayoutForecastRecord
from app.models.nfl_pilot import (
    NflPilotAlertRecord,
    NflPilotEntryRecord,
    NflPilotMonitoringDecisionRecord,
    NflPilotPositionEventRecord,
    NflPilotPositionRecord,
    NflPilotQuoteCheckRecord,
    NflPilotScenarioRecord,
)


def _floor_cent(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _official_resolution(
    resolutions: Sequence[MarketResolutionRecord],
) -> MarketResolutionRecord:
    if not resolutions:
        raise ValueError("NFL pilot settlement requires an official market resolution")
    if len({(item.yes_payout, item.no_payout) for item in resolutions}) != 1:
        raise ValueError("NFL pilot settlement has conflicting official resolutions")
    resolution = resolutions[0]
    if resolution.source != "official_provider" or resolution.settled_at > resolution.retrieved_at:
        raise ValueError("NFL pilot settlement resolution is not an official final fact")
    return resolution


@dataclass(frozen=True)
class QuoteAssessment:
    """Provider-neutral directional quote quality used before a pilot mark."""

    quote_status: str
    reason: str | None
    directional_bid: Decimal | None
    directional_ask: Decimal | None
    spread: Decimal | None
    quote_age_seconds: int


@dataclass(frozen=True)
class PilotRecommendation:
    recommendation: str
    reason: str
    requires_attention: bool
    remaining_edge: Decimal | None


def _quote_assessment(price: MarketPriceRecord, direction: str, now: datetime) -> QuoteAssessment:
    bid = price.yes_bid if direction == "yes" else price.no_bid
    ask = price.yes_ask if direction == "yes" else price.no_ask
    age_seconds = max(0, int((now - price.retrieved_at).total_seconds()))
    valid_bid = bid is not None and Decimal("0") < bid < Decimal("1")
    valid_ask = ask is not None and Decimal("0") < ask < Decimal("1")
    spread = ask - bid if bid is not None and ask is not None and valid_bid and valid_ask else None
    if age_seconds > 15 * 60:
        return QuoteAssessment(
            "stale", "quote_age_exceeds_15_minutes", bid, ask, spread, age_seconds
        )
    if not valid_bid or not valid_ask:
        return QuoteAssessment(
            "unusable", "directional_bid_or_ask_missing", bid, ask, spread, age_seconds
        )
    if spread is not None and spread < Decimal("0"):
        return QuoteAssessment(
            "unusable", "directional_quote_crossed", bid, ask, spread, age_seconds
        )
    return QuoteAssessment("fresh", None, bid, ask, spread, age_seconds)


def _recommendation(
    quote_status: str,
    forecast: NflPayoutForecastRecord | None,
    direction: str,
    bid: Decimal | None,
    now: datetime,
) -> PilotRecommendation:
    """Recommend a paper action without mutating any position or portfolio state."""
    if quote_status != "fresh":
        return PilotRecommendation("hold", f"quote_{quote_status}", True, None)
    if forecast is None:
        return PilotRecommendation("hold", "forecast_missing", True, None)
    if not forecast.generated_at <= now < forecast.valid_until:
        return PilotRecommendation("hold", "forecast_stale", True, None)
    if bid is None:
        return PilotRecommendation("hold", "directional_bid_missing", True, None)
    expected = forecast.expected_yes_payout if direction == "yes" else forecast.expected_no_payout
    edge = (expected - bid).quantize(Decimal("0.000001"))
    if edge <= 0:
        return PilotRecommendation("close", "remaining_edge_nonpositive", True, edge)
    if edge < Decimal("0.03"):
        return PilotRecommendation("reduce", "remaining_edge_below_3_percent", True, edge)
    return PilotRecommendation("hold", "minimum_hold_edge_met", False, edge)


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
                if existing.event_type != "mark" or existing.audit.get("entry_id") != str(entry_id):
                    raise ValueError(
                        "idempotency key belongs to another NFL pilot lifecycle action"
                    )
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
            prior_mark = await self._session.scalar(
                select(NflPilotPositionEventRecord).where(
                    NflPilotPositionEventRecord.position_id == position.id,
                    NflPilotPositionEventRecord.market_price_id == price.id,
                )
            )
            if prior_mark is not None:
                await self._session.commit()
                return prior_mark, False
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
                if existing.event_type != "settlement" or existing.audit.get("entry_id") != str(
                    entry_id
                ):
                    raise ValueError(
                        "idempotency key belongs to another NFL pilot lifecycle action"
                    )
                await self._session.commit()
                return existing, False
            now = await self._now()
            position = await self._position(entry_id, now)
            if position.status != "open":
                raise ValueError("NFL pilot position is not open")
            resolutions = list(
                await self._session.scalars(
                    select(MarketResolutionRecord)
                    .where(MarketResolutionRecord.market_id == position.market_id)
                    .order_by(
                        MarketResolutionRecord.settled_at.desc(), MarketResolutionRecord.id.desc()
                    )
                )
            )
            resolution = _official_resolution(resolutions)
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

    async def summary(self, scenario_id: UUID) -> dict[str, Decimal | int]:
        """Return reconciled pilot-only balances without touching the generic portfolio."""
        rows = list(
            await self._session.scalars(
                select(NflPilotPositionRecord).where(
                    NflPilotPositionRecord.scenario_id == scenario_id
                )
            )
        )
        if not rows:
            entry_count = await self._session.scalar(
                select(func.count())
                .select_from(NflPilotEntryRecord)
                .where(NflPilotEntryRecord.scenario_id == scenario_id)
            )
            if not entry_count:
                raise LookupError("NFL pilot scenario has no entries")
        open_cost = sum(
            (row.total_cost_basis for row in rows if row.status == "open"), Decimal("0.00")
        )
        realized = sum(
            (row.realized_pnl for row in rows if row.status == "settled"), Decimal("0.00")
        )
        scenario = await self._session.get(NflPilotScenarioRecord, scenario_id)
        if scenario is None:
            raise LookupError("NFL pilot scenario not found")
        current_bankroll = scenario.starting_bankroll + realized
        return {
            "open_positions": sum(row.status == "open" for row in rows),
            "settled_positions": sum(row.status == "settled" for row in rows),
            "committed_capital": open_cost,
            "realized_pnl": realized,
            "current_bankroll": current_bankroll,
            "available_bankroll": current_bankroll - open_cost,
        }

    async def _record_quote_check(
        self,
        position: NflPilotPositionRecord,
        price: MarketPriceRecord,
        assessment: QuoteAssessment,
        now: datetime,
    ) -> bool:
        """Persist one immutable quality result per position and provider snapshot."""
        existing = await self._session.scalar(
            select(NflPilotQuoteCheckRecord).where(
                NflPilotQuoteCheckRecord.position_id == position.id,
                NflPilotQuoteCheckRecord.market_price_id == price.id,
            )
        )
        if existing is not None:
            return False
        self._session.add(
            NflPilotQuoteCheckRecord(
                id=uuid4(),
                position_id=position.id,
                market_price_id=price.id,
                quote_status=assessment.quote_status,
                reason=assessment.reason,
                directional_bid=assessment.directional_bid,
                directional_ask=assessment.directional_ask,
                spread=assessment.spread,
                liquidity=price.liquidity,
                quote_retrieved_at=price.retrieved_at,
                quote_age_seconds=assessment.quote_age_seconds,
                checked_at=now,
                execution_mode="paper",
                live_trading_enabled=False,
                audit={"direction": position.direction, "market_id": str(position.market_id)},
            )
        )
        await self._session.commit()
        return True

    async def _record_decision(
        self,
        position: NflPilotPositionRecord,
        recommendation: PilotRecommendation,
        price: MarketPriceRecord | None,
        forecast: NflPayoutForecastRecord | None,
        now: datetime,
    ) -> tuple[NflPilotMonitoringDecisionRecord, bool]:
        source = f"{position.id}:{price.id if price else 'missing'}:{forecast.id if forecast else 'missing'}"
        key = "nfl-pilot-decision:" + hashlib.sha256(source.encode()).hexdigest()
        existing = await self._session.scalar(
            select(NflPilotMonitoringDecisionRecord).where(
                NflPilotMonitoringDecisionRecord.idempotency_key == key
            )
        )
        if existing is not None:
            return existing, False
        record = NflPilotMonitoringDecisionRecord(
            id=uuid4(),
            idempotency_key=key,
            position_id=position.id,
            recommendation=recommendation.recommendation,
            reason=recommendation.reason,
            requires_attention=recommendation.requires_attention,
            remaining_edge=recommendation.remaining_edge,
            evaluated_at=now,
            execution_mode="paper",
            live_trading_enabled=False,
            audit={
                "market_price_id": str(price.id) if price else None,
                "forecast_id": str(forecast.id) if forecast else None,
            },
        )
        self._session.add(record)
        await self._session.commit()
        return record, True

    async def _record_alert(self, decision: NflPilotMonitoringDecisionRecord) -> bool:
        if not decision.requires_attention:
            return False
        existing = await self._session.scalar(
            select(NflPilotAlertRecord).where(NflPilotAlertRecord.decision_id == decision.id)
        )
        if existing is not None:
            return False
        self._session.add(
            NflPilotAlertRecord(
                id=uuid4(),
                decision_id=decision.id,
                severity="attention",
                message=f"NFL pilot {decision.recommendation}: {decision.reason}",
                created_at=decision.evaluated_at,
                execution_mode="paper",
                live_trading_enabled=False,
                audit={"position_id": str(decision.position_id)},
            )
        )
        await self._session.commit()
        return True

    async def decisions(
        self, scenario_id: UUID, attention_only: bool, limit: int, offset: int
    ) -> list[NflPilotMonitoringDecisionRecord]:
        statement = (
            select(NflPilotMonitoringDecisionRecord)
            .join(NflPilotPositionRecord)
            .where(NflPilotPositionRecord.scenario_id == scenario_id)
        )
        if attention_only:
            statement = statement.where(NflPilotMonitoringDecisionRecord.requires_attention)
        return list(
            await self._session.scalars(
                statement.order_by(NflPilotMonitoringDecisionRecord.evaluated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )

    async def attention(self, limit: int) -> list[NflPilotMonitoringDecisionRecord]:
        return list(
            await self._session.scalars(
                select(NflPilotMonitoringDecisionRecord)
                .where(NflPilotMonitoringDecisionRecord.requires_attention)
                .order_by(NflPilotMonitoringDecisionRecord.evaluated_at.desc())
                .limit(limit)
            )
        )

    async def alerts(self, limit: int) -> list[NflPilotAlertRecord]:
        return list(
            await self._session.scalars(
                select(NflPilotAlertRecord)
                .order_by(NflPilotAlertRecord.created_at.desc())
                .limit(limit)
            )
        )

    async def monitor(
        self, scenario_id: UUID
    ) -> tuple[int, int, int, int, int, int, int, int, int, int, int, int]:
        """Audit every available open-position quote before making a bounded mark."""
        positions = list(
            await self._session.scalars(
                select(NflPilotPositionRecord).where(
                    NflPilotPositionRecord.scenario_id == scenario_id,
                    NflPilotPositionRecord.status == "open",
                )
            )
        )
        marks_created = 0
        quote_checks_created = 0
        fresh = 0
        stale = 0
        unusable = 0
        missing = 0
        skipped = 0
        holds = reduces = closes = attention_required = 0
        for position in positions:
            price = await self._session.scalar(
                select(MarketPriceRecord)
                .where(MarketPriceRecord.market_id == position.market_id)
                .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
                .limit(1)
            )
            if price is None:
                missing += 1
                skipped += 1
                holds += 1
                attention_required += 1
                decision, _ = await self._record_decision(
                    position,
                    PilotRecommendation("hold", "quote_missing", True, None),
                    None,
                    None,
                    await self._now(),
                )
                await self._record_alert(decision)
                continue
            now = await self._now()
            assessment = _quote_assessment(price, position.direction, now)
            forecast = await self._session.scalar(
                select(NflPayoutForecastRecord)
                .where(NflPayoutForecastRecord.market_id == position.market_id)
                .order_by(
                    NflPayoutForecastRecord.generated_at.desc(), NflPayoutForecastRecord.id.desc()
                )
                .limit(1)
            )
            recommendation = _recommendation(
                assessment.quote_status,
                forecast,
                position.direction,
                assessment.directional_bid,
                now,
            )
            holds += int(recommendation.recommendation == "hold")
            reduces += int(recommendation.recommendation == "reduce")
            closes += int(recommendation.recommendation == "close")
            attention_required += int(recommendation.requires_attention)
            decision, _ = await self._record_decision(
                position, recommendation, price, forecast, now
            )
            await self._record_alert(decision)
            quote_checks_created += int(
                await self._record_quote_check(position, price, assessment, now)
            )
            if assessment.quote_status == "stale":
                stale += 1
                skipped += 1
                continue
            if assessment.quote_status == "unusable":
                unusable += 1
                skipped += 1
                continue
            fresh += 1
            try:
                _, was_created = await self.mark(
                    position.entry_id, f"nfl-pilot-monitor:{position.id}:{price.id}"
                )
            except ValueError:
                skipped += 1
                continue
            marks_created += int(was_created)
        return (
            len(positions),
            quote_checks_created,
            fresh,
            stale,
            unusable,
            missing,
            marks_created,
            skipped,
            holds,
            reduces,
            closes,
            attention_required,
        )
