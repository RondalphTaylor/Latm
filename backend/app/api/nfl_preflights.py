from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, TradingMode, get_settings
from app.db.session import get_session
from app.domain.nfl_paper_preflight import NflPaperPreflightPolicy
from app.schemas.nfl_preflights import NflPaperPreflightResponse, NflPaperPreflightRunResponse
from app.services.nfl_preflights.repository import NflPaperPreflightRepository

router = APIRouter(tags=["nfl-paper-preflights"])


@router.post("/nfl-paper-preflights/run", response_model=NflPaperPreflightRunResponse)
async def run_nfl_paper_preflight(
    opportunity_id: UUID,
    direction: Annotated[str, Query(pattern="^(yes|no)$")],
    capital_cap: Annotated[Decimal, Query(gt=0)],
    idempotency_key: Annotated[str, Query(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,99}$")],
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> NflPaperPreflightRunResponse:
    """Persist an execution-blocked, cost-aware NFL paper review."""
    if settings.trading_mode is not TradingMode.PAPER:
        raise HTTPException(status_code=409, detail="NFL paper preflights require paper mode")
    policy = NflPaperPreflightPolicy(
        slippage_bps=settings.paper_slippage_bps,
        fee_bps=settings.paper_fee_bps,
        minimum_adjusted_edge=Decimal("0.03"),
    )
    try:
        record, created = await NflPaperPreflightRepository(session, policy).run(
            opportunity_id, direction, capital_cap, idempotency_key
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return NflPaperPreflightRunResponse(
        created=created, preflight=NflPaperPreflightResponse.model_validate(record)
    )
