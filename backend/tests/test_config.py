import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_load_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRIS_BASE_URL", "https://iris.test.local:52773")
    monkeypatch.setenv("IRIS_USERNAME", "_SYSTEM")
    monkeypatch.setenv("IRIS_PASSWORD", "not-a-real-password")

    settings = Settings()

    assert settings.iris_base_url == "https://iris.test.local:52773"
    assert settings.iris_username == "_SYSTEM"
    assert settings.iris_password.get_secret_value() == "not-a-real-password"


def test_settings_apply_sensible_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRIS_BASE_URL", "https://iris.test.local:52773")
    monkeypatch.setenv("IRIS_USERNAME", "_SYSTEM")
    monkeypatch.setenv("IRIS_PASSWORD", "not-a-real-password")

    settings = Settings()

    assert settings.app_host == "0.0.0.0"
    assert settings.app_port == 8000
    assert settings.iris_request_timeout_seconds == 10.0


def test_settings_missing_required_values_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IRIS_BASE_URL", raising=False)
    monkeypatch.delenv("IRIS_USERNAME", raising=False)
    monkeypatch.delenv("IRIS_PASSWORD", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_password_never_appears_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRIS_BASE_URL", "https://iris.test.local:52773")
    monkeypatch.setenv("IRIS_USERNAME", "_SYSTEM")
    monkeypatch.setenv("IRIS_PASSWORD", "super-secret-value")

    settings = Settings()

    assert "super-secret-value" not in repr(settings)
    assert "super-secret-value" not in str(settings)
