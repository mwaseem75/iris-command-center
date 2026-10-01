"""Instance definitions and the result of an instance's compatibility check.

A definition never holds a password: the Primary's comes from the
environment, and a user-defined instance's will be a reference to its stored
credential (`credential_ref`).
"""

from datetime import datetime
from enum import Enum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

PRIMARY_INSTANCE_ID = "primary"

# Hosts of IRIS instances that Docker Compose manages: docker-compose.yml's
# iris-2 service (its data volume and password), registered here at
# http://iris-2:52773. Like the Primary, such an instance can't be edited or
# deleted here; Check and activate/deactivate still work.
DOCKER_MANAGED_HOSTS = frozenset({"iris-2"})


def is_docker_managed(instance: "InstanceDefinition") -> bool:
    return not instance.primary and urlsplit(instance.base_url).hostname in DOCKER_MANAGED_HOSTS


def normalize_base_url(value: str) -> str:
    """An instance URL: http(s) with a host, no credentials, query or fragment."""
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("must be an http:// or https:// URL with a host")
    if parts.username or parts.password:
        raise ValueError("must not contain credentials")
    if parts.query or parts.fragment:
        raise ValueError("must not contain a query or fragment")
    return value.strip().rstrip("/")


class InstanceCheckStatus(str, Enum):
    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"
    UNREACHABLE = "unreachable"
    AUTH_FAILED = "auth_failed"


class InstanceCheck(BaseModel):
    """The outcome of the last live check of an instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    checked_at: datetime
    status: InstanceCheckStatus
    product: str | None = None
    server_version: str | None = None
    api_version: int | None = None
    username: str | None = None
    endpoints_ok: list[str] = []
    endpoints_missing: list[str] = []
    mgmnt_api_available: bool | None = None
    failure: str | None = None
    detail: str | None = None


class InstanceDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")
    name: str = Field(min_length=1, max_length=80)
    base_url: str = Field(min_length=1, max_length=255)
    username: str = Field(min_length=1, max_length=160)
    namespace: str = Field(default="USER", pattern=r"^%?[A-Za-z][A-Za-z0-9_-]{0,63}$")
    active: bool = True
    primary: bool = False
    credential_ref: str | None = Field(default=None, max_length=128)
    created_at: datetime
    updated_at: datetime
    last_check: InstanceCheck | None = None

    @field_validator("name", "username")
    @classmethod
    def _plain_text(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(ch) < 32 for ch in value):
            raise ValueError("must be non-empty plain text")
        return value

    @field_validator("base_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        return normalize_base_url(value)


class InstanceView(BaseModel):
    """What the API returns for an instance: no password and no Wallet reference."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    base_url: str
    username: str
    namespace: str
    active: bool
    primary: bool
    has_credential: bool
    docker_managed: bool = False  # see DOCKER_MANAGED_HOSTS
    created_at: datetime
    updated_at: datetime
    last_check: InstanceCheck | None = None

    @classmethod
    def of(cls, instance: InstanceDefinition) -> "InstanceView":
        return cls(
            **instance.model_dump(exclude={"credential_ref"}),
            has_credential=instance.primary or instance.credential_ref is not None,
            docker_managed=is_docker_managed(instance),
        )
