from __future__ import annotations

from typing import Protocol

from app.domain.forecasts import BaseForecast, ForecastTargetInput, HistoricalGameInput


class ForecastModel(Protocol):
    """Common deterministic event-forecast boundary."""

    def forecast_many(
        self,
        targets: tuple[ForecastTargetInput, ...],
        history: tuple[HistoricalGameInput, ...],
    ) -> tuple[BaseForecast, ...]: ...
