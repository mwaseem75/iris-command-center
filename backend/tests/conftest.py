"""Shared test fixtures.

Provides harmless placeholder IRIS connection settings for every test, so
the FastAPI app's lifespan (which constructs Settings()) never fails due to
missing required environment variables, regardless of test order. These are
not real credentials and are never used to contact a real IRIS instance in
this test suite — IRIS interaction is mocked/overridden per test.

Also provides the shared `mock_iris_client`/`client` fixtures used by every
IRIS route test, so each test file doesn't redefine them.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from app.dependencies import get_iris_client
from app.main import app


@pytest.fixture(autouse=True)
def iris_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRIS_BASE_URL", "http://iris.invalid.test:52773")
    monkeypatch.setenv("IRIS_USERNAME", "test-user")
    monkeypatch.setenv("IRIS_PASSWORD", "test-password-not-real")


@pytest.fixture
def mock_iris_client() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def client(mock_iris_client: AsyncMock) -> TestClient:
    app.dependency_overrides[get_iris_client] = lambda: mock_iris_client
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
