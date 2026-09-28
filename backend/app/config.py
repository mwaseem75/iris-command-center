"""App settings, read from environment variables or a local .env file."""

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

    # --- Optional: also save execution traces to ^CommandCenterTrace in
    # iris_namespace, so they survive a restart. The in-memory store is
    # still what the API reads from. ---
    persist_traces_to_iris: bool = False
    iris_namespace: str = "USER"
    # Docker publishes the container's 1972 on the host as 1973, and the
    # backend connects from the host by default.
    iris_superserver_port: int = 1973

    # --- Optional: also save Custom Issue Rules to ^CommandCenterIssueRule in
    # iris_namespace, so they survive a restart. Without it they're kept in
    # memory only. ---
    persist_issue_rules_to_iris: bool = False

    # --- Optional: build and search CommandCenter.Knowledge (IRIS vector
    # search) in iris_namespace. ---
    enable_knowledge_search: bool = False

    # --- Optional: run the Demo Activity rehearsal once after the first
    # successful startup. ---
    auto_run_demo_activity: bool = False


@lru_cache
def get_settings() -> Settings:
    """Settings are read once per process."""
    return Settings()
