"""Shared test fixtures.

Provides harmless placeholder IRIS connection settings for every test, so
the FastAPI app's lifespan (which constructs Settings()) never fails due to
missing required environment variables, regardless of test order. These are
not real credentials and are never used to contact a real IRIS instance in
this test suite — IRIS interaction is mocked/overridden per test.
"""

import pytest


@pytest.fixture(autouse=True)
def iris_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRIS_BASE_URL", "http://iris.invalid.test:52773")
    monkeypatch.setenv("IRIS_USERNAME", "test-user")
    monkeypatch.setenv("IRIS_PASSWORD", "test-password-not-real")
