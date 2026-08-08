from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.forecasts import get_forecast_repository, get_forecast_service
from app.core.config import Settings, get_settings
from app.domain.forecasts import ForecastPurpose
from app.main import create_app
from app.models.forecasts import BaseForecastRecord, ModelVersionRecord
from app.services.forecasting.service import ForecastRunResult

FORECAST_ID = UUID("84fb71c4-8791-48c0-a3d2-71939d321dc7")
MODEL_ID = UUID("45b19b5b-69b9-44d8-b937-07b00db838f9")
EVENT_ID = UUID("6e30fc37-1947-43f4-88bf-9588d3216497")
HOME_ID = UUID("ca069c07-4ff4-4de5-bf30-a92f65466bcc")
AWAY_ID = UUID("94f25d41-1315-4a86-b373-c47c88c171b3")
TIP_TIME = datetime(2026, 8, 2, 23, tzinfo=UTC)


def model_record() -> ModelVersionRecord:
    return ModelVersionRecord(
        id=MODEL_ID,
        model_name="nba_elo",
        model_version="1.0.0+cfg.abcdef123456",
        algorithm="elo",
        configuration={
            "initial_rating": "1500",
            "k_factor": "20",
            "logistic_scale": "400",
            "home_court_advantage": "100",
        },
        configuration_fingerprint="a" * 64,
        formula="p_home=standard_elo_logistic",
        description="fixture",
        created_at=TIP_TIME,
    )


def forecast_record() -> BaseForecastRecord:
    record = BaseForecastRecord(
        id=FORECAST_ID,
        sports_event_id=EVENT_ID,
        model_version_id=MODEL_ID,
        purpose="operational",
        home_team_id=HOME_ID,
        away_team_id=AWAY_ID,
        home_win_probability=Decimal("0.640065"),
        away_win_probability=Decimal("0.359935"),
        home_team_rating=Decimal("1500.0000"),
        away_team_rating=Decimal("1500.0000"),
        adjusted_rating_difference=Decimal("100.0000"),
        training_data_fingerprint="b" * 64,
        input_fingerprint="c" * 64,
        input_features={"home_cold_start": True},
        training_games_seen=0,
        training_games_processed=0,
        skipped_tied_games=0,
        skipped_incomplete_games=0,
        home_prior_games=0,
        away_prior_games=0,
        latest_training_event_time=None,
        forecast_as_of=TIP_TIME,
        source_event_last_seen_at=TIP_TIME,
        generated_at=TIP_TIME,
    )
    record.model_version = model_record()
    return record


class FakeForecastRepository:
    def __init__(self, record: BaseForecastRecord | None = None) -> None:
        self.record = record
        self.list_arguments: dict[str, object] | None = None

    async def list_forecasts(self, **kwargs: object) -> list[BaseForecastRecord]:
        self.list_arguments = kwargs
        return [self.record] if self.record is not None else []

    async def get_forecast(self, forecast_id: UUID) -> BaseForecastRecord | None:
        if self.record is not None and self.record.id == forecast_id:
            return self.record
        return None

    async def list_model_versions(self) -> list[ModelVersionRecord]:
        return [self.record.model_version] if self.record is not None else []


class FakeForecastService:
    async def run(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date,
        end_date: date,
        event_id: UUID | None,
        limit: int,
        offset: int,
    ) -> ForecastRunResult:
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        return ForecastRunResult(
            model_name="nba_elo",
            model_version="1.0.0+cfg.abcdef123456",
            purpose=purpose,
            start_date=start_date,
            end_date=end_date,
            examined=1,
            generated=1,
            persisted=1,
            training_games_seen=10,
            training_games_processed=9,
            skipped_tied_games=1,
            skipped_incomplete_games=0,
        )


def forecast_client(
    repository: FakeForecastRepository,
    *,
    service: FakeForecastService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    application.dependency_overrides[get_settings] = lambda: Settings(
        database_url="postgresql+asyncpg://test:test@localhost/test",
        _env_file=None,
    )
    application.dependency_overrides[get_forecast_repository] = lambda: repository
    if service is not None:
        application.dependency_overrides[get_forecast_service] = lambda: service
    return application, TestClient(application)


def test_run_forecasts_returns_model_and_replay_audit_counts() -> None:
    _, client = forecast_client(FakeForecastRepository(), service=FakeForecastService())

    with client:
        response = client.post(
            "/forecasts/run?purpose=historical_replay&start_date=2026-08-01"
            f"&end_date=2026-08-02&event_id={EVENT_ID}&limit=25&offset=2"
        )

    assert response.status_code == 200
    assert response.json()["purpose"] == "historical_replay"
    assert response.json()["persisted"] == 1
    assert response.json()["training_games_processed"] == 9


def test_list_detail_event_history_and_model_registry_expose_audit_data() -> None:
    repository = FakeForecastRepository(forecast_record())
    _, client = forecast_client(repository)

    with client:
        list_response = client.get(
            f"/forecasts?latest_only=true&purpose=operational&sports_event_id={EVENT_ID}"
            "&model_name=nba_elo&model_version=1.0.0%2Bcfg.abcdef123456&limit=25&offset=2"
        )
        detail_response = client.get(f"/forecasts/{FORECAST_ID}")
        event_response = client.get(f"/events/{EVENT_ID}/forecasts?latest_only=false")
        models_response = client.get("/forecasts/model-versions")

    assert list_response.status_code == 200
    assert list_response.json()[0]["home_win_probability"] == "0.640065"
    assert list_response.json()[0]["model"]["model_name"] == "nba_elo"
    assert list_response.json()[0]["input_features"]["home_cold_start"] is True
    assert detail_response.status_code == 200
    assert event_response.status_code == 200
    assert models_response.status_code == 200
    assert models_response.json()[0]["configuration_fingerprint"] == "a" * 64
    assert repository.list_arguments == {
        "latest_only": False,
        "purpose": None,
        "sports_event_id": EVENT_ID,
        "model_name": None,
        "model_version": None,
        "limit": 100,
        "offset": 0,
    }


def test_unknown_forecast_returns_404_and_invalid_range_returns_422() -> None:
    _, client = forecast_client(FakeForecastRepository(), service=FakeForecastService())

    with client:
        missing = client.get(f"/forecasts/{FORECAST_ID}")
        invalid = client.post(
            "/forecasts/run?purpose=operational&start_date=2026-08-02&end_date=2026-08-01"
        )

    assert missing.status_code == 404
    assert missing.json() == {"detail": "forecast not found"}
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "start_date must not be after end_date"}
