"""Configuration/settings layer. All values come from environment variables
(or a local .env file, never committed) — nothing here is hard-coded."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- IRIS connection ---
    iris_base_url: str
    iris_username: str
    iris_password: SecretStr

    # --- IRIS request behavior ---
    iris_request_timeout_seconds: float = 10.0

    # --- Command Center application server ---
    app_host: str = "0.0.0.0"
    app_port: int = 8000


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — environment is read once per process."""
    return Settings()
