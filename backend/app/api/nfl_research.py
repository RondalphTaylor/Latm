from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.nfl_research.baseline import NflResearchReport, evaluate_games
from app.services.nfl_research.repository import (
    NflIgnoredResearchEvent,
    NflResearchRepository,
    NflResearchSourceSnapshot,
)

router = APIRouter(tags=["nfl-research"])


class NflResearchBaselineResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["blocked", "research_preview"]
    research_only: Literal[True] = True
    operational_forecast_published: Literal[False] = False
    trading_eligible: Literal[False] = False
    observation_basis: Literal["retrospective_latest_results"] = "retrospective_latest_results"
    selected_count: int
    source_fingerprint: str
    source_snapshots: tuple[NflResearchSourceSnapshot, ...]
    ignored_rows: tuple[NflIgnoredResearchEvent, ...]
    ignored_reason_counts: dict[str, int]
    blockers: tuple[str, ...]
    evaluation_error: str | None = None
    report: NflResearchReport | None


def get_nfl_research_repository(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> NflResearchRepository:
    return NflResearchRepository(session)


@router.get("/nfl-research-baseline", response_model=NflResearchBaselineResponse)
async def get_nfl_research_baseline(
    repository: Annotated[NflResearchRepository, Depends(get_nfl_research_repository)],
) -> NflResearchBaselineResponse:
    """Preview an experimental baseline from local results; never publish a forecast."""
    selection = await repository.select_games()
    blockers = list(selection.blockers)
    report: NflResearchReport | None = None
    evaluation_error: str | None = None
    if not blockers:
        try:
            report = evaluate_games(list(selection.games))
        except ValueError as exc:
            blockers.append("historical_evaluation_invalid")
            evaluation_error = str(exc)
    return NflResearchBaselineResponse(
        status="blocked" if blockers else "research_preview",
        selected_count=len(selection.games),
        source_fingerprint=selection.source_fingerprint,
        source_snapshots=selection.sources,
        ignored_rows=selection.ignored,
        ignored_reason_counts=selection.ignored_reason_counts,
        blockers=tuple(blockers),
        evaluation_error=evaluation_error,
        report=report,
    )
