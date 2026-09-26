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

    # --- Optional IRIS-side execution trace persistence (see
    # app/observability/iris_trace_writer.py). Off by default: the
    # in-memory trace store (app/observability/store.py) is the only trace
    # storage until this is explicitly enabled. When enabled, traces are
    # additionally, best-effort written to ^CommandCenterTrace in the given
    # namespace via IRIS's Native API — this never replaces or changes the
    # in-memory store or any existing read route. ---
    persist_traces_to_iris: bool = False
    iris_namespace: str = "USER"
    # Default matches icc-iris-dev's host-mapped superserver port (the
    # container's own internal port is the standard 1972, but Docker
    # publishes it to the host as 1973 — see `docker ps`'s PORTS column,
    # `0.0.0.0:1973->1972/tcp`). This backend always connects from the
    # host, so 1973 is the correct default for this project's dev setup.
    iris_superserver_port: int = 1973

    # --- Optional IRIS Vector Search knowledge base (see
    # app/knowledge/store.py). Off by default. When enabled, startup
    # creates the CommandCenter.Knowledge table in iris_namespace if it is
    # missing and reindexes the in-code corpus into it (over the same
    # Native API connection settings as above); GET
    # /api/iris/knowledge/search then answers from IRIS. ---
    enable_knowledge_search: bool = False


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance — environment is read once per process."""
    return Settings()
