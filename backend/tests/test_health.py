from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.db.session import check_database_connection
from app.main import create_app


def test_health_reports_paper_mode(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "trading_mode": "paper"}


def create_readiness_client(*, database_ready: bool) -> tuple[FastAPI, TestClient]:
    """Create an app whose database readiness result is deterministic."""
    application = create_app()

    def override_database_readiness() -> bool:
        return database_ready

    application.dependency_overrides[check_database_connection] = override_database_readiness
    return application, TestClient(application)


def test_readiness_succeeds_when_database_is_accessible() -> None:
    _, test_client = create_readiness_client(database_ready=True)

    with test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_readiness_fails_safely_when_database_is_unavailable() -> None:
    _, test_client = create_readiness_client(database_ready=False)

    with test_client:
        response = test_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"detail": "database unavailable"}
