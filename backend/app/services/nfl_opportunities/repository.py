from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.domain.markets import MarketPrice
from app.domain.nfl_forecasting import NflPayoutForecastCandidate
from app.models.markets import MarketPriceRecord
from app.models.nfl_forecasting import NflPayoutForecastRecord
from app.models.nfl_opportunities import NflPaperOpportunityRecord
from app.services.nfl_opportunities.engine import build_nfl_paper_opportunity_comparison
from app.services.nfl_research.shadow_repository import NflShadowForecastRepository


class NflPaperOpportunityRepository:
    """Persist two-sided, blocked NFL ask comparisons without touching trade state."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _now(self) -> datetime:
        value = await self._session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime):
            raise ValueError("database clock unavailable")
        return value

    async def _find_key(self, key: str) -> NflPaperOpportunityRecord | None:
        rows = await self._session.scalars(
            select(NflPaperOpportunityRecord)
            .where(NflPaperOpportunityRecord.idempotency_key == key)
            .execution_options(populate_existing=True)
        )
        return rows.one_or_none()

    @staticmethod
    def _candidate(record: NflPayoutForecastRecord) -> NflPayoutForecastCandidate:
        try:
            candidate = NflPayoutForecastCandidate.model_validate(record.audit.get("candidate"))
        except (TypeError, ValueError) as exc:
            raise ValueError("NFL forecast candidate audit is invalid") from exc
        if (
            candidate.match_id != record.match_id
            or candidate.market_id != record.market_id
            or candidate.event_id != record.event_id
            or candidate.source_shadow_snapshot_id != record.source_shadow_snapshot_id
            or candidate.home_team_id != record.home_team_id
            or candidate.away_team_id != record.away_team_id
            or candidate.yes_team_id != record.yes_team_id
            or candidate.model_version != record.model_version
            or candidate.seed_fingerprint != record.seed_fingerprint
            or candidate.generated_at != record.generated_at
            or candidate.valid_until != record.valid_until
            or candidate.expected_home_payout != record.expected_home_payout
            or candidate.expected_away_payout != record.expected_away_payout
            or candidate.expected_yes_payout != record.expected_yes_payout
            or candidate.expected_no_payout != record.expected_no_payout
            or candidate.input_fingerprint != record.input_fingerprint
            or record.purpose != "paper_candidate"
            or record.metric_kind != "expected_payout"
            or record.execution_mode != "paper"
            or record.promotion_state != "blocked"
            or record.operational_eligible
            or record.trading_enabled
        ):
            raise ValueError("NFL forecast candidate lineage is inconsistent")
        return candidate

    async def run(
        self, forecast_id: UUID, idempotency_key: str
    ) -> tuple[NflPaperOpportunityRecord, bool]:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}", idempotency_key) is None:
            raise ValueError("invalid idempotency key")
        try:
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "nfl-paper-opportunity:" + idempotency_key},
            )
            existing = await self._find_key(idempotency_key)
            if existing is not None:
                if existing.forecast_id != forecast_id:
                    raise ValueError("idempotency key belongs to another forecast")
                await self._session.commit()
                return existing, False

            forecast = await self._session.get(NflPayoutForecastRecord, forecast_id)
            if forecast is None:
                raise LookupError("NFL paper forecast candidate not found")
            latest = await self._session.scalar(
                select(NflPayoutForecastRecord)
                .where(
                    NflPayoutForecastRecord.market_id == forecast.market_id,
                    NflPayoutForecastRecord.model_version == forecast.model_version,
                    NflPayoutForecastRecord.seed_fingerprint == forecast.seed_fingerprint,
                )
                .order_by(
                    NflPayoutForecastRecord.generated_at.desc(), NflPayoutForecastRecord.id.desc()
                )
                .limit(1)
            )
            if latest is None or latest.id != forecast_id:
                raise ValueError("NFL forecast candidate is superseded")
            candidate = self._candidate(forecast)
            start = await self._now()
            if not candidate.generated_at <= start < candidate.valid_until:
                raise ValueError("NFL paper forecast candidate is expired or future-dated")

            # Reuse the locked current-source validation. It may replay a shadow row,
            # but an altered source must not silently reuse this candidate's lineage.
            shadow, _ = await NflShadowForecastRepository(self._session)._run(forecast.match_id)
            if shadow.id != forecast.source_shadow_snapshot_id:
                raise ValueError("NFL candidate source shadow is no longer current")

            price = await self._session.scalar(
                select(MarketPriceRecord)
                .where(MarketPriceRecord.market_id == forecast.market_id)
                .order_by(MarketPriceRecord.retrieved_at.desc(), MarketPriceRecord.id.desc())
                .limit(1)
                .execution_options(populate_existing=True)
            )
            price_input = (
                MarketPrice(
                    yes_bid=price.yes_bid,
                    yes_ask=price.yes_ask,
                    no_bid=price.no_bid,
                    no_ask=price.no_ask,
                    last_price=price.last_price,
                    volume=price.volume,
                    volume_24h=price.volume_24h,
                    open_interest=price.open_interest,
                    liquidity=price.liquidity,
                    retrieved_at=price.retrieved_at,
                )
                if price is not None
                else None
            )
            comparison = build_nfl_paper_opportunity_comparison(
                forecast=candidate,
                forecast_id=forecast.id,
                latest_market_price_id=price.id if price is not None else None,
                market_price=price_input,
                evaluated_at=start,
            )
            finished = await self._now()
            if finished < start or finished >= candidate.valid_until:
                raise ValueError("NFL candidate expired or clock changed while comparing")
            if comparison.valid_until is not None and finished >= comparison.valid_until:
                raise ValueError("NFL quote expired while comparing")

            values = comparison.model_dump()
            values.update(
                id=uuid4(),
                idempotency_key=idempotency_key,
                audit={
                    "comparison": comparison.model_dump(mode="json"),
                    "forecast_candidate": candidate.model_dump(mode="json"),
                    "forecast_input_fingerprint": forecast.input_fingerprint,
                    "source_shadow_snapshot_id": str(forecast.source_shadow_snapshot_id),
                    "price": price_input.model_dump(mode="json") if price_input else None,
                    "price_id": str(price.id) if price is not None else None,
                    "source_checked_at": finished.isoformat(),
                    "cost_model": "none_pre_cost_direct_ask_comparison",
                },
            )
            inserted = await self._session.scalar(
                insert(NflPaperOpportunityRecord)
                .values(values)
                .on_conflict_do_nothing(index_elements=[NflPaperOpportunityRecord.idempotency_key])
                .returning(NflPaperOpportunityRecord.id)
            )
            record = await self._find_key(idempotency_key)
            if record is None:
                raise ValueError("NFL paper opportunity insert could not be read back")
            if record.forecast_id != forecast_id:
                raise ValueError("idempotency key belongs to another forecast")
            await self._session.commit()
            return record, inserted is not None
        except Exception:
            await self._session.rollback()
            raise

    async def get_opportunity(self, opportunity_id: UUID) -> NflPaperOpportunityRecord | None:
        return await self._session.get(NflPaperOpportunityRecord, opportunity_id)

    async def list_opportunities(
        self, *, limit: int, offset: int
    ) -> list[NflPaperOpportunityRecord]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("invalid NFL paper opportunity pagination")
        rows = await self._session.scalars(
            select(NflPaperOpportunityRecord)
            .options(defer(NflPaperOpportunityRecord.audit))
            .order_by(
                NflPaperOpportunityRecord.evaluated_at.desc(), NflPaperOpportunityRecord.id.desc()
            )
            .limit(limit)
            .offset(offset)
        )
        return list(rows.all())
