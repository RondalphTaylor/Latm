from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nfl_pilot import NflPilotScenarioRecord
from app.models.portfolio import PortfolioRecord

_PROFILES = {
    "conservative": (Decimal("0.01"), Decimal("0.05")),
    "baseline": (Decimal("0.02"), Decimal("0.10")),
    "assertive": (Decimal("0.05"), Decimal("0.20")),
}


class NflPilotScenarioService:
    """Register immutable scenario settings without authorizing any entry."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self, portfolio_id: UUID, profile: str
    ) -> tuple[NflPilotScenarioRecord, bool]:
        caps = _PROFILES.get(profile)
        if caps is None:
            raise ValueError("invalid NFL pilot profile")
        portfolio = await self._session.get(PortfolioRecord, portfolio_id)
        if portfolio is None:
            raise LookupError("paper portfolio not found")
        if portfolio.execution_mode != "paper" or not portfolio.is_active:
            raise ValueError("NFL pilot requires an active paper portfolio")
        scenario_key = f"nfl-pilot-2026:{portfolio.idempotency_key}:{profile}"
        policy = {
            "version": "nfl-paper-pilot-scenarios-v1",
            "profile": profile,
            "per_entry_exposure": str(caps[0]),
            "aggregate_exposure": str(caps[1]),
            "minimum_adjusted_edge": "0.03",
            "execution_mode": "paper",
            "live_trading_enabled": False,
        }
        fingerprint = hashlib.sha256(
            json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        try:
            existing = await self._session.scalar(
                select(NflPilotScenarioRecord).where(
                    NflPilotScenarioRecord.portfolio_id == portfolio.id
                )
            )
            if existing is not None:
                if existing.profile != profile or existing.policy_fingerprint != fingerprint:
                    raise ValueError(
                        "portfolio already belongs to another frozen NFL pilot scenario"
                    )
                await self._session.commit()
                return existing, False
            now = datetime.now(UTC)
            values = {
                "id": uuid4(),
                "scenario_key": scenario_key,
                "portfolio_id": portfolio.id,
                "profile": profile,
                "execution_mode": "paper",
                "starting_bankroll": portfolio.starting_bankroll,
                "per_entry_exposure": caps[0],
                "aggregate_exposure": caps[1],
                "minimum_adjusted_edge": Decimal("0.03"),
                "live_trading_enabled": False,
                "policy_version": policy["version"],
                "policy_fingerprint": fingerprint,
                "created_at": now,
                "audit": {
                    "portfolio": {
                        "id": str(portfolio.id),
                        "idempotency_key": portfolio.idempotency_key,
                        "starting_bankroll": str(portfolio.starting_bankroll),
                    },
                    "policy": policy,
                },
            }
            inserted = await self._session.scalar(
                insert(NflPilotScenarioRecord)
                .values(values)
                .on_conflict_do_nothing(index_elements=[NflPilotScenarioRecord.portfolio_id])
                .returning(NflPilotScenarioRecord.id)
            )
            record = await self._session.scalar(
                select(NflPilotScenarioRecord).where(
                    NflPilotScenarioRecord.portfolio_id == portfolio.id
                )
            )
            if record is None:
                raise RuntimeError("NFL pilot scenario could not be read back")
            await self._session.commit()
            return record, inserted is not None
        except Exception:
            await self._session.rollback()
            raise
