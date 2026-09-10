from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.sports import _build_nfl_provider, get_sports_data_provider
from app.core.config import Settings, SportsDataProviderName
from tests.test_sports_api import FakeSportsRepository, sports_client


def test_nfl_provider_selection_is_explicit_and_cached() -> None:
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://test:test@localhost/test"),
        balldontlie_api_key=SecretStr("test-key"),
        _env_file=None,
    )
    _build_nfl_provider.cache_clear()
    first = get_sports_data_provider(settings, SportsDataProviderName.BALLDONTLIE_NFL)
    second = get_sports_data_provider(settings, SportsDataProviderName.BALLDONTLIE_NFL)
    assert first is second
    assert first.name == "balldontlie_nfl"
    assert get_sports_data_provider(settings).name == "balldontlie"
    assert settings.trading_mode.value == "paper"
    _build_nfl_provider.cache_clear()


def test_nfl_missing_credentials_fail_closed(client: TestClient) -> None:
    response = client.post("/teams/ingest?provider=balldontlie_nfl")
    assert response.status_code == 503
    assert response.json() == {"detail": "sports-data provider credentials are not configured"}


def test_nfl_reads_accept_league_and_provider_filters() -> None:
    repository = FakeSportsRepository()
    _, test_client = sports_client(repository=repository)
    with test_client:
        teams = test_client.get("/teams?league=nfl&provider=balldontlie_nfl")
        events = test_client.get("/events?league=nfl&provider=balldontlie_nfl")
    assert teams.status_code == events.status_code == 200
    assert teams.json() == events.json() == []
    assert repository.event_arguments is not None
    assert repository.event_arguments["league"] == "nfl"
    assert repository.event_arguments["provider_name"] == "balldontlie_nfl"
