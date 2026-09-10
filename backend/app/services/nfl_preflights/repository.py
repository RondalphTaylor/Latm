from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.nfl_paper_preflight import (
    NflPaperPreflightInput,
    NflPaperPreflightPolicy,
    evaluate_nfl_paper_preflight,
    preflight_policy_fingerprint,
)
from app.models.markets import MarketPriceRecord
from app.models.nfl_forecasting import NflPayoutForecastRecord
from app.models.nfl_opportunities import NflPaperOpportunityRecord
from app.models.nfl_preflights import NflPaperPreflightRecord
from app.services.nfl_research.shadow_repository import NflShadowForecastRepository


class NflPaperPreflightRepository:
    """Persist cost calculations only after current NFL source revalidation."""

    def __init__(self, session: AsyncSession, policy: NflPaperPreflightPolicy) -> None:
        self._session = session
        self._policy = policy
        self._policy_fingerprint = preflight_policy_fingerprint(policy)

    async def _now(self) -> datetime:
        now = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(now, datetime):
            raise ValueError("database clock unavailable")
        return now

    async def run(
        self, opportunity_id: UUID, direction: str, capital_cap: Decimal, idempotency_key: str
    ) -> tuple[NflPaperPreflightRecord, bool]:
        if direction not in {"yes", "no"} or capital_cap <= 0:
            raise ValueError("invalid NFL preflight request")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", idempotency_key) is None:
            raise ValueError("invalid idempotency key")
        try:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "nfl-paper-preflight:" + idempotency_key},
            )
            existing = await self._session.scalar(
                select(NflPaperPreflightRecord).where(
                    NflPaperPreflightRecord.idempotency_key == idempotency_key
                )
            )
            if existing is not None:
                if existing.opportunity_id != opportunity_id:
                    raise ValueError("idempotency key belongs to another opportunity")
                await self._session.commit()
                return existing, False
            opportunity = await self._session.get(NflPaperOpportunityRecord, opportunity_id)
            if opportunity is None:
                raise LookupError("NFL paper opportunity not found")
            now = await self._now()
            if (
                opportunity.valid_until is None
                or not opportunity.evaluated_at <= now < opportunity.valid_until
            ):
                raise ValueError("NFL paper opportunity is expired or unavailable")
            forecast = await self._session.get(NflPayoutForecastRecord, opportunity.forecast_id)
            if forecast is None:
                raise ValueError("NFL paper opportunity forecast is unavailable")
            shadow, _ = await NflShadowForecastRepository(self._session)._run(forecast.match_id)
            if shadow.id != forecast.source_shadow_snapshot_id:
                raise ValueError("NFL paper opportunity source is no longer current")
            latest_price = await self._session.scalar(
                select(MarketPriceRecord)
                .where(MarketPriceRecord.market_id == opportunity.market_id)
                .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
                .limit(1)
            )
            if latest_price is None or latest_price.id != opportunity.price_id:
                raise ValueError("NFL paper opportunity quote is no longer current")
            expected_payout = (
                opportunity.yes_expected_payout
                if direction == "yes"
                else opportunity.no_expected_payout
            )
            direct_ask = (
                opportunity.yes_direct_ask if direction == "yes" else opportunity.no_direct_ask
            )
            raw_edge = opportunity.yes_raw_edge if direction == "yes" else opportunity.no_raw_edge
            if direct_ask is None or raw_edge is None:
                raise ValueError("NFL paper opportunity side is not directly comparable")
            result = evaluate_nfl_paper_preflight(
                NflPaperPreflightInput(
                    expected_payout=expected_payout,
                    direct_ask=direct_ask,
                    raw_edge=raw_edge,
                    capital_cap=capital_cap,
                ),
                self._policy,
            )
            values = result.model_dump()
            values.update(
                id=uuid4(),
                idempotency_key=idempotency_key,
                opportunity_id=opportunity.id,
                market_id=opportunity.market_id,
                direction=direction,
                reviewed_at=now,
                valid_until=opportunity.valid_until,
                capital_cap=capital_cap,
                expected_payout=expected_payout,
                direct_ask=direct_ask,
                raw_edge=raw_edge,
                execution_mode="paper",
                promotion_state="blocked",
                policy_version=self._policy.code_version,
                policy_fingerprint=self._policy_fingerprint,
                audit={
                    "opportunity_id": str(opportunity.id),
                    "forecast_id": str(opportunity.forecast_id),
                    "price_id": str(opportunity.price_id),
                    "source_shadow_snapshot_id": str(shadow.id),
                    "preflight": result.model_dump(mode="json"),
                    "policy": self._policy.model_dump(mode="json"),
                },
            )
            inserted = await self._session.scalar(
                insert(NflPaperPreflightRecord)
                .values(values)
                .on_conflict_do_nothing(index_elements=[NflPaperPreflightRecord.idempotency_key])
                .returning(NflPaperPreflightRecord.id)
            )
            record = await self._session.scalar(
                select(NflPaperPreflightRecord).where(
                    NflPaperPreflightRecord.idempotency_key == idempotency_key
                )
            )
            if record is None:
                raise ValueError("NFL preflight insert could not be read back")
            await self._session.commit()
            return record, inserted is not None
        except Exception:
            await self._session.rollback()
            raise
