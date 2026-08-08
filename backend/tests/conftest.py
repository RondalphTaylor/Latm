from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, TradingMode, get_settings
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide an isolated FastAPI test client with deterministic settings."""
    application = create_app()

    def override_settings() -> Settings:
        return Settings(
            database_url="postgresql+asyncpg://test:test@localhost:5432/test",
            trading_mode=TradingMode.PAPER,
            _env_file=None,
        )

    application.dependency_overrides[get_settings] = override_settings
    with TestClient(application) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    """Prevent settings state from leaking between tests."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
