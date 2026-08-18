from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.evaluation import (
    get_evaluation_repository,
    get_forecast_evaluation_service,
    get_trading_performance_service,
)
from app.domain.forecast_evaluation import (
    ForecastCalibrationBin,
    ForecastCalibrationReport,
    ModelEvaluationSummary,
    PairedModelComparison,
)
from app.domain.forecasts import ForecastPurpose
from app.domain.trading_evaluation import (
    SnapshotDrawdown,
    TradingPerformanceEvaluation,
)
from app.main import create_app
from app.models.evaluation import ForecastEvaluationRecord
from app.models.forecasts import ModelVersionRecord
from app.services.evaluation.service import (
    ForecastEvaluationRunResult,
    ForecastModelPerformance,
    ForecastPerformanceResult,
)

EVALUATION_ID = UUID("a3000000-0000-0000-0000-000000000001")
FORECAST_ID = UUID("a3000000-0000-0000-0000-000000000002")
EVENT_ID = UUID("a3000000-0000-0000-0000-000000000003")
MODEL_A_ID = UUID("a3000000-0000-0000-0000-000000000004")
MODEL_B_ID = UUID("a3000000-0000-0000-0000-000000000005")
HOME_TEAM_ID = UUID("a3000000-0000-0000-0000-000000000006")
AWAY_TEAM_ID = UUID("a3000000-0000-0000-0000-000000000007")
PORTFOLIO_ID = UUID("a3000000-0000-0000-0000-000000000008")
SNAPSHOT_ID = UUID("a3000000-0000-0000-0000-000000000009")
UNKNOWN_ID = UUID("a3000000-0000-0000-0000-000000000099")
FORECAST_AT = datetime(2026, 8, 17, 12, tzinfo=UTC)
TIP_AT = datetime(2026, 8, 17, 23, tzinfo=UTC)
EVALUATED_AT = datetime(2026, 8, 18, 12, tzinfo=UTC)
POLICY_VERSION = "1.0.0+cfg.evaluation"
POLICY_FINGERPRINT = "a" * 64


def model_record() -> ModelVersionRecord:
    return ModelVersionRecord(
        id=MODEL_A_ID,
        model_name="nba_elo",
        model_version="1.0.0+cfg.aaaaaaaaaaaa",
        algorithm="elo",
        configuration={"k_factor": "20"},
        configuration_fingerprint="b" * 64,
        formula="p_home=standard_elo_logistic",
        description="API fixture",
        created_at=FORECAST_AT,
    )


def evaluation_record() -> ForecastEvaluationRecord:
    record = ForecastEvaluationRecord(
        id=EVALUATION_ID,
        base_forecast_id=FORECAST_ID,
        sports_event_id=EVENT_ID,
        model_version_id=MODEL_A_ID,
        home_team_id=HOME_TEAM_ID,
        away_team_id=AWAY_TEAM_ID,
        purpose="operational",
        event_date=date(2026, 8, 17),
        result_scheduled_start_time=TIP_AT,
        forecast_as_of=FORECAST_AT,
        forecast_generated_at=FORECAST_AT,
        result_source_last_seen_at=EVALUATED_AT,
        home_win_probability=Decimal("0.640000"),
        predicted_home_win=True,
        home_won=True,
        result_home_score=110,
        result_away_score=101,
        brier_score=Decimal("0.129600000000"),
        correct=True,
        policy_name="binary_home_brier",
        policy_version=POLICY_VERSION,
        policy_fingerprint=POLICY_FINGERPRINT,
        outcome_fingerprint="c" * 64,
        input_fingerprint="d" * 64,
        audit_snapshot={"result_provider": "fixture"},
        evaluated_at=EVALUATED_AT,
    )
    record.model_version = model_record()
    return record


def run_result() -> ForecastEvaluationRunResult:
    return ForecastEvaluationRunResult(
        purpose=ForecastPurpose.OPERATIONAL,
        start_date=date(2026, 8, 17),
        end_date=date(2026, 8, 18),
        examined=3,
        eligible=2,
        persisted=1,
        replayed=1,
        skip_counts={"not_final": 1},
        evaluator_name="binary_home_brier",
        evaluator_version=POLICY_VERSION,
        evaluator_fingerprint=POLICY_FINGERPRINT,
    )


def calibration_report() -> ForecastCalibrationReport:
    return ForecastCalibrationReport(
        model_version_id=MODEL_A_ID,
        model_name="nba_elo",
        model_version="1.0.0+cfg.aaaaaaaaaaaa",
        purpose=ForecastPurpose.OPERATIONAL,
        sample_size=1,
        bin_count=2,
        mean_brier_score=Decimal("0.129600000000"),
        expected_calibration_error=Decimal("0.360000000000"),
        maximum_calibration_error=Decimal("0.360000000000"),
        bins=(
            ForecastCalibrationBin(
                index=0,
                lower_bound=Decimal("0"),
                upper_bound=Decimal("0.5"),
                upper_bound_inclusive=False,
                sample_size=0,
                home_wins=0,
                mean_prediction=None,
                observed_frequency=None,
                signed_calibration_gap=None,
                absolute_calibration_gap=None,
                mean_brier_score=None,
            ),
            ForecastCalibrationBin(
                index=1,
                lower_bound=Decimal("0.5"),
                upper_bound=Decimal("1"),
                upper_bound_inclusive=True,
                sample_size=1,
                home_wins=1,
                mean_prediction=Decimal("0.640000000000"),
                observed_frequency=Decimal("1.000000000000"),
                signed_calibration_gap=Decimal("-0.360000000000"),
                absolute_calibration_gap=Decimal("0.360000000000"),
                mean_brier_score=Decimal("0.129600000000"),
            ),
        ),
        policy_version=POLICY_VERSION,
        policy_fingerprint=POLICY_FINGERPRINT,
    )


def populated_performance_result() -> ForecastPerformanceResult:
    summary = ModelEvaluationSummary(
        model_version_id=MODEL_A_ID,
        model_name="nba_elo",
        model_version="1.0.0+cfg.aaaaaaaaaaaa",
        purpose=ForecastPurpose.OPERATIONAL,
        sample_size=1,
        home_wins=1,
        decisive_prediction_count=1,
        correct_prediction_count=1,
        mean_brier_score=Decimal("0.129600000000"),
        prediction_accuracy=Decimal("1.000000000000"),
        expected_calibration_error=Decimal("0.360000000000"),
        maximum_calibration_error=Decimal("0.360000000000"),
        policy_version=POLICY_VERSION,
        policy_fingerprint=POLICY_FINGERPRINT,
    )
    return ForecastPerformanceResult(
        purpose=ForecastPurpose.OPERATIONAL,
        evaluation_count=1,
        unique_event_count=1,
        model_count=1,
        models=(
            ForecastModelPerformance(
                summary=summary,
                calibration=calibration_report(),
            ),
        ),
        evaluator_name="binary_home_brier",
        evaluator_version=POLICY_VERSION,
        evaluator_fingerprint=POLICY_FINGERPRINT,
        warnings=(),
    )


def empty_performance_result() -> ForecastPerformanceResult:
    return ForecastPerformanceResult(
        purpose=ForecastPurpose.HISTORICAL_REPLAY,
        evaluation_count=0,
        unique_event_count=0,
        model_count=0,
        models=(),
        evaluator_name="binary_home_brier",
        evaluator_version=POLICY_VERSION,
        evaluator_fingerprint=POLICY_FINGERPRINT,
        warnings=("historical replay warning",),
    )


def paired_comparison() -> PairedModelComparison:
    return PairedModelComparison(
        model_a_version_id=MODEL_A_ID,
        model_b_version_id=MODEL_B_ID,
        purpose=ForecastPurpose.OPERATIONAL,
        model_a_sample_size=1,
        model_b_sample_size=1,
        paired_sample_size=1,
        model_a_unpaired_count=0,
        model_b_unpaired_count=0,
        outcome_mismatch_count=0,
        model_a_mean_brier=Decimal("0.129600000000"),
        model_b_mean_brier=Decimal("0.160000000000"),
        mean_brier_delta_a_minus_b=Decimal("-0.030400000000"),
        model_a_lower_brier_count=1,
        model_b_lower_brier_count=0,
        equal_brier_count=0,
        paired_event_ids=(EVENT_ID,),
        policy_version=POLICY_VERSION,
        policy_fingerprint=POLICY_FINGERPRINT,
    )


def trading_performance() -> TradingPerformanceEvaluation:
    return TradingPerformanceEvaluation(
        portfolio_id=PORTFOLIO_ID,
        as_of_snapshot_id=SNAPSHOT_ID,
        as_of_sequence=0,
        as_of=EVALUATED_AT,
        calculated_at=EVALUATED_AT,
        starting_bankroll=Decimal("1000.00"),
        net_total_pnl=Decimal("0.00"),
        realized_pnl=Decimal("0.00"),
        unrealized_pnl=Decimal("0.00"),
        return_on_starting_bankroll=Decimal("0.0000000000"),
        realized_return_on_starting_bankroll=Decimal("0.0000000000"),
        unrealized_return_on_starting_bankroll=Decimal("0.0000000000"),
        profitable=False,
        position_count=0,
        open_position_count=0,
        completed_position_count=0,
        winning_position_count=0,
        losing_position_count=0,
        breakeven_position_count=0,
        win_rate=None,
        average_raw_entry_edge=None,
        average_adjusted_entry_edge=None,
        average_terminal_return=None,
        aggregate_return_on_cost=None,
        completed_cost_basis=Decimal("0.00"),
        maximum_drawdown=SnapshotDrawdown(
            amount=Decimal("0.00"),
            fraction=Decimal("0.0000000000"),
            peak_snapshot_id=SNAPSHOT_ID,
            trough_snapshot_id=SNAPSHOT_ID,
            peak_value=Decimal("1000.00"),
            trough_value=Decimal("1000.00"),
            peak_at=EVALUATED_AT,
            trough_at=EVALUATED_AT,
        ),
        entry_lineage_groups=(),
        evaluation_policy_name="paper_trading_performance",
        evaluation_policy_version=POLICY_VERSION,
        evaluation_policy_fingerprint="e" * 64,
        input_fingerprint="f" * 64,
        warnings=("maximum drawdown is snapshot-sampled",),
    )


class FakeEvaluationRepository:
    def __init__(self, record: ForecastEvaluationRecord | None = None) -> None:
        self.record = record
        self.list_arguments: dict[str, object] | None = None

    async def list_forecast_evaluations(
        self,
        **kwargs: object,
    ) -> list[ForecastEvaluationRecord]:
        self.list_arguments = kwargs
        return [self.record] if self.record is not None else []

    async def get_forecast_evaluation(
        self,
        evaluation_id: UUID,
    ) -> ForecastEvaluationRecord | None:
        if self.record is not None and evaluation_id == self.record.id:
            return self.record
        return None


class FakeForecastEvaluationService:
    def __init__(
        self,
        *,
        performance_results: list[ForecastPerformanceResult] | None = None,
    ) -> None:
        self.performance_results = performance_results or []
        self.run_arguments: dict[str, object] | None = None
        self.performance_arguments: list[dict[str, object]] = []
        self.compare_arguments: dict[str, object] | None = None

    async def run(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date,
        end_date: date,
        event_id: UUID | None,
        model_version_id: UUID | None,
        limit: int,
        offset: int,
    ) -> ForecastEvaluationRunResult:
        self.run_arguments = {
            "purpose": purpose,
            "start_date": start_date,
            "end_date": end_date,
            "event_id": event_id,
            "model_version_id": model_version_id,
            "limit": limit,
            "offset": offset,
        }
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        return run_result()

    async def performance(
        self,
        *,
        purpose: ForecastPurpose,
        start_date: date | None,
        end_date: date | None,
        model_version_ids: tuple[UUID, ...] | None,
    ) -> ForecastPerformanceResult:
        self.performance_arguments.append(
            {
                "purpose": purpose,
                "start_date": start_date,
                "end_date": end_date,
                "model_version_ids": model_version_ids,
            }
        )
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if model_version_ids is not None and UNKNOWN_ID in model_version_ids:
            raise LookupError(f"model version not found: {UNKNOWN_ID}")
        if not self.performance_results:
            raise AssertionError("fake forecast evaluation service has no performance result")
        return self.performance_results.pop(0)

    async def compare(
        self,
        *,
        purpose: ForecastPurpose,
        model_a_version_id: UUID,
        model_b_version_id: UUID,
        start_date: date | None,
        end_date: date | None,
    ) -> PairedModelComparison:
        self.compare_arguments = {
            "purpose": purpose,
            "model_a_version_id": model_a_version_id,
            "model_b_version_id": model_b_version_id,
            "start_date": start_date,
            "end_date": end_date,
        }
        if model_a_version_id == model_b_version_id:
            raise ValueError("paired comparison requires distinct model versions")
        if start_date is not None and end_date is not None and start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        if UNKNOWN_ID in {model_a_version_id, model_b_version_id}:
            raise LookupError(f"model version not found: {UNKNOWN_ID}")
        return paired_comparison()


class FakeTradingPerformanceService:
    def __init__(
        self,
        *,
        result: TradingPerformanceEvaluation | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.portfolio_ids: list[UUID] = []

    async def evaluate(self, portfolio_id: UUID) -> TradingPerformanceEvaluation:
        self.portfolio_ids.append(portfolio_id)
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("fake trading performance service has no result")
        return self.result


def api_client(
    *,
    repository: FakeEvaluationRepository | None = None,
    forecast_service: FakeForecastEvaluationService | None = None,
    trading_service: FakeTradingPerformanceService | None = None,
) -> tuple[FastAPI, TestClient]:
    application = create_app()
    repository = repository or FakeEvaluationRepository()
    forecast_service = forecast_service or FakeForecastEvaluationService()
    trading_service = trading_service or FakeTradingPerformanceService(result=trading_performance())
    application.dependency_overrides[get_evaluation_repository] = lambda: repository
    application.dependency_overrides[get_forecast_evaluation_service] = lambda: forecast_service
    application.dependency_overrides[get_trading_performance_service] = lambda: trading_service
    return application, TestClient(application)


def test_forecast_evaluation_run_success_and_service_validation() -> None:
    service = FakeForecastEvaluationService()
    _, client = api_client(forecast_service=service)

    with client:
        success = client.post(
            "/forecast-evaluations/run?purpose=operational&start_date=2026-08-17"
            f"&end_date=2026-08-18&event_id={EVENT_ID}&model_version_id={MODEL_A_ID}"
            "&limit=25&offset=2"
        )
        invalid = client.post(
            "/forecast-evaluations/run?purpose=operational&start_date=2026-08-18"
            "&end_date=2026-08-17"
        )

    assert success.status_code == 200
    assert success.json() == {
        "purpose": "operational",
        "start_date": "2026-08-17",
        "end_date": "2026-08-18",
        "examined": 3,
        "eligible": 2,
        "persisted": 1,
        "replayed": 1,
        "skip_counts": {"not_final": 1},
        "evaluator_name": "binary_home_brier",
        "evaluator_version": POLICY_VERSION,
        "evaluator_fingerprint": POLICY_FINGERPRINT,
    }
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "start_date must not be after end_date"}
    assert service.run_arguments == {
        "purpose": ForecastPurpose.OPERATIONAL,
        "start_date": date(2026, 8, 18),
        "end_date": date(2026, 8, 17),
        "event_id": None,
        "model_version_id": None,
        "limit": 250,
        "offset": 0,
    }


def test_evaluation_list_detail_404_and_filter_forwarding() -> None:
    repository = FakeEvaluationRepository(evaluation_record())
    _, client = api_client(repository=repository)

    with client:
        listed = client.get(
            f"/forecast-evaluations?forecast_id={FORECAST_ID}&sports_event_id={EVENT_ID}"
            "&purpose=operational&model_name=nba_elo"
            "&model_version=1.0.0%2Bcfg.aaaaaaaaaaaa"
            "&start_date=2026-08-17&end_date=2026-08-18"
            "&evaluator_version=1.0.0%2Bcfg.evaluation"
            "&limit=25&offset=2"
        )
        detail = client.get(f"/forecast-evaluations/{EVALUATION_ID}")
        missing = client.get(f"/forecast-evaluations/{UNKNOWN_ID}")

    assert listed.status_code == detail.status_code == 200
    assert listed.json()[0] == detail.json()
    assert detail.json()["base_forecast_id"] == str(FORECAST_ID)
    assert detail.json()["observed_home_win"] is True
    assert detail.json()["brier_score"] == "0.129600000000"
    assert detail.json()["model"]["model_name"] == "nba_elo"
    assert detail.json()["source_snapshot"] == {"result_provider": "fixture"}
    assert missing.status_code == 404
    assert missing.json() == {"detail": "forecast evaluation not found"}
    assert repository.list_arguments == {
        "forecast_id": FORECAST_ID,
        "sports_event_id": EVENT_ID,
        "purpose": ForecastPurpose.OPERATIONAL,
        "model_name": "nba_elo",
        "model_version": "1.0.0+cfg.aaaaaaaaaaaa",
        "start_date": date(2026, 8, 17),
        "end_date": date(2026, 8, 18),
        "evaluator_version": POLICY_VERSION,
        "limit": 25,
        "offset": 2,
    }


def test_forecast_performance_exposes_empty_and_per_model_shapes() -> None:
    service = FakeForecastEvaluationService(
        performance_results=[empty_performance_result(), populated_performance_result()]
    )
    _, client = api_client(forecast_service=service)

    with client:
        empty = client.get("/forecast-performance?purpose=historical_replay")
        populated = client.get(
            "/forecast-performance?purpose=operational&start_date=2026-08-17"
            f"&end_date=2026-08-18&model_version_id={MODEL_A_ID}"
            f"&model_version_id={MODEL_B_ID}"
        )

    assert empty.status_code == populated.status_code == 200
    assert empty.json()["evaluation_count"] == 0
    assert empty.json()["unique_event_count"] == 0
    assert empty.json()["model_count"] == 0
    assert empty.json()["models"] == []
    assert empty.json()["warnings"] == ["historical replay warning"]
    payload = populated.json()
    assert payload["evaluation_count"] == 1
    assert payload["unique_event_count"] == 1
    assert payload["model_count"] == 1
    assert payload["models"][0]["summary"]["mean_brier_score"] == "0.129600000000"
    assert payload["models"][0]["calibration"]["bin_count"] == 2
    assert payload["models"][0]["calibration"]["bins"][0]["mean_prediction"] is None
    assert service.performance_arguments[1]["model_version_ids"] == (
        MODEL_A_ID,
        MODEL_B_ID,
    )


def test_paired_comparison_shape_and_distinct_model_validation() -> None:
    service = FakeForecastEvaluationService()
    _, client = api_client(forecast_service=service)
    valid_path = (
        "/forecast-performance/compare?purpose=operational"
        f"&model_a_version_id={MODEL_A_ID}&model_b_version_id={MODEL_B_ID}"
        "&start_date=2026-08-17&end_date=2026-08-18"
    )
    invalid_path = (
        "/forecast-performance/compare?purpose=operational"
        f"&model_a_version_id={MODEL_A_ID}&model_b_version_id={MODEL_A_ID}"
    )

    with client:
        valid = client.get(valid_path)
        invalid = client.get(invalid_path)

    assert valid.status_code == 200
    assert valid.json()["comparison"]["paired_sample_size"] == 1
    assert valid.json()["comparison"]["paired_event_ids"] == [str(EVENT_ID)]
    assert valid.json()["comparison"]["mean_brier_delta_a_minus_b"] == "-0.030400000000"
    assert valid.json()["warnings"] == []
    assert invalid.status_code == 422
    assert invalid.json() == {"detail": "paired comparison requires distinct model versions"}


def test_unknown_requested_model_ids_return_404() -> None:
    service = FakeForecastEvaluationService()
    _, client = api_client(forecast_service=service)

    with client:
        performance = client.get(
            f"/forecast-performance?purpose=operational&model_version_id={UNKNOWN_ID}"
        )
        comparison = client.get(
            "/forecast-performance/compare?purpose=operational"
            f"&model_a_version_id={MODEL_A_ID}&model_b_version_id={UNKNOWN_ID}"
        )

    expected = {"detail": f"model version not found: {UNKNOWN_ID}"}
    assert performance.status_code == comparison.status_code == 404
    assert performance.json() == comparison.json() == expected


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (LookupError("portfolio not found"), 404),
        (RuntimeError("portfolio ledger is inconsistent"), 409),
    ],
)
def test_portfolio_performance_maps_missing_and_conflicting_ledgers(
    error: Exception,
    expected_status: int,
) -> None:
    service = FakeTradingPerformanceService(error=error)
    _, client = api_client(trading_service=service)

    with client:
        response = client.get(f"/portfolios/{PORTFOLIO_ID}/performance")

    assert response.status_code == expected_status
    assert response.json() == {"detail": str(error)}
    assert service.portfolio_ids == [PORTFOLIO_ID]


def test_portfolio_performance_returns_read_only_paper_metrics() -> None:
    service = FakeTradingPerformanceService(result=trading_performance())
    _, client = api_client(trading_service=service)

    with client:
        response = client.get(f"/portfolios/{PORTFOLIO_ID}/performance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio_id"] == str(PORTFOLIO_ID)
    assert payload["net_total_pnl"] == "0.00"
    assert payload["maximum_drawdown"]["amount"] == "0.00"
    assert payload["entry_lineage_groups"] == []
    assert "trading_mode" not in payload
    assert "order" not in payload


@pytest.mark.parametrize(
    "path",
    [
        "/forecast-evaluations/run?purpose=live&start_date=2026-08-17&end_date=2026-08-18",
        "/forecast-evaluations?purpose=live",
        "/forecast-performance?purpose=live",
        (
            "/forecast-performance/compare?purpose=live"
            f"&model_a_version_id={MODEL_A_ID}&model_b_version_id={MODEL_B_ID}"
        ),
        "/forecast-evaluations/run?purpose=operational&start_date=2026-08-17"
        "&end_date=2026-08-18&limit=0",
        "/forecast-evaluations/run?purpose=operational&start_date=2026-08-17"
        "&end_date=2026-08-18&limit=501",
        "/forecast-evaluations/run?purpose=operational&start_date=2026-08-17"
        "&end_date=2026-08-18&offset=-1",
        "/forecast-evaluations?limit=0",
        "/forecast-evaluations?limit=501",
        "/forecast-evaluations?offset=-1",
        "/forecast-evaluations?start_date=2026-08-18&end_date=2026-08-17",
        "/forecast-performance?purpose=operational&start_date=2026-08-18&end_date=2026-08-17",
        (
            "/forecast-performance/compare?purpose=operational"
            f"&model_a_version_id={MODEL_A_ID}&model_b_version_id={MODEL_B_ID}"
            "&start_date=2026-08-18&end_date=2026-08-17"
        ),
    ],
)
def test_invalid_purpose_dates_and_pagination_are_rejected(path: str) -> None:
    service = FakeForecastEvaluationService()
    _, client = api_client(forecast_service=service)

    with client:
        method = "POST" if path.startswith("/forecast-evaluations/run") else "GET"
        response = client.request(method, path)

    assert response.status_code == 422


def test_evaluation_openapi_exposes_no_live_or_order_controls() -> None:
    service = FakeForecastEvaluationService()
    application, client = api_client(forecast_service=service)
    schema = application.openapi()
    operations = (
        schema["paths"]["/forecast-evaluations/run"]["post"],
        schema["paths"]["/forecast-evaluations"]["get"],
        schema["paths"]["/forecast-evaluations/{evaluation_id}"]["get"],
        schema["paths"]["/forecast-performance"]["get"],
        schema["paths"]["/forecast-performance/compare"]["get"],
        schema["paths"]["/portfolios/{portfolio_id}/performance"]["get"],
    )

    for operation in operations:
        assert "requestBody" not in operation
        parameter_names = {parameter["name"] for parameter in operation.get("parameters", [])}
        assert parameter_names.isdisjoint(
            {"trading_mode", "execution_mode", "live", "order_type", "provider_order_id"}
        )

    with client:
        response = client.post(
            "/forecast-evaluations/run?purpose=operational&start_date=2026-08-17"
            "&end_date=2026-08-18&trading_mode=live&order_type=market"
        )

    assert response.status_code == 200
    assert service.run_arguments is not None
    assert set(service.run_arguments) == {
        "purpose",
        "start_date",
        "end_date",
        "event_id",
        "model_version_id",
        "limit",
        "offset",
    }
