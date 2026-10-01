"""Live compatibility check of an IRIS instance.

Uses an IRISClient built for that instance (its URL, user, namespace and
password), never the Primary's shared client, and returns an InstanceCheck.
It doesn't change any instance definition; recording the result is up to the
caller.

1. Reachability: unauthenticated GET /api/admin/info. 401 means the System
   Administration API is there; 404 means it isn't (incompatible); no answer
   means unreachable. No credentials are sent. Without the API (IRIS releases
   before 2026.2), GET /api/atelier/ (Basic auth), which older releases also
   have, tells apart wrong credentials and gives the version to report.
2-3. Log in (/api/admin/login) and GET /api/admin/info.
4. Require product "iris" and apiVersion 2. The version string alone decides
   nothing: older or other servers fail at steps 1-4.
5. Every required endpoint must answer. They are the verified, parameterless
   GETs of the API capability matrix that Command Center uses. An endpoint
   counts as present on 2xx, or on a 4xx with IRIS's JSON error body (e.g.
   404 "OAuth 2.0 server is not configured"); a non-JSON 404/405 means the
   route doesn't exist, and 403 means this user can't use it.
6. The Management API (/api/mgmnt/) is recorded but optional.

Messages are fixed text: no exception text, response body or credential is
ever put in the result.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import httpx
from pydantic import SecretStr, ValidationError

from app.capabilities import CAPABILITY_REGISTRY
from app.config import Settings
from app.instances.credentials import CredentialStoreError, WalletCredentialStore, resolve_password
from app.instances.models import InstanceCheck, InstanceCheckStatus, InstanceDefinition
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import (
    IRISAuthError,
    IRISConnectionError,
    IRISResponseError,
    IRISTimeoutError,
)
from app.models.iris import InfoResult, IRISEnvelope

_ADMIN_PREFIX = "/api/admin"
EXPECTED_PRODUCT = "iris"
EXPECTED_API_VERSION = 2
# The release whose System Administration API the checks below were verified on.
MINIMUM_IRIS_VERSION = "2026.2"

# The verified, parameterless Admin API reads Command Center uses.
REQUIRED_ENDPOINTS: tuple[str, ...] = tuple(
    entry.endpoint.removeprefix(_ADMIN_PREFIX)
    for entry in CAPABILITY_REGISTRY
    if entry.verification_status == "Verified"
    and entry.method == "GET"
    and entry.endpoint.startswith(f"{_ADMIN_PREFIX}/v2/")
    and entry.command_center_path is not None
)


def _failed(
    status: InstanceCheckStatus, failure: str, detail: str, **values: object
) -> InstanceCheck:
    return InstanceCheck(
        checked_at=datetime.now(timezone.utc), status=status, failure=failure, detail=detail, **values
    )


async def check_instance(
    instance: InstanceDefinition, settings: Settings, store: WalletCredentialStore
) -> InstanceCheck:
    """Check a registered instance with its stored credential."""
    try:
        password = await asyncio.to_thread(resolve_password, instance, settings, store)
    except CredentialStoreError:
        return _failed(
            InstanceCheckStatus.AUTH_FAILED,
            "credential_unavailable",
            "The instance's stored credential could not be read.",
        )
    return await check_connection(
        base_url=instance.base_url,
        username=instance.username,
        password=password,
        namespace=instance.namespace,
        settings=settings,
    )


async def check_connection(
    *, base_url: str, username: str, password: SecretStr, namespace: str, settings: Settings
) -> InstanceCheck:
    """Check a connection definition (also usable before it is saved)."""
    instance_settings = settings.model_copy(
        update={
            "iris_base_url": base_url.rstrip("/"),
            "iris_username": username,
            "iris_password": password,
            "iris_namespace": namespace,
        }
    )
    try:
        reachable = await _probe(instance_settings)
    except httpx.HTTPError:
        return _failed(InstanceCheckStatus.UNREACHABLE, "unreachable", "The instance could not be reached.")
    if not reachable:
        return await _without_admin_api(instance_settings)

    client = IRISClient(instance_settings)
    try:
        return await _check(client)
    except Exception:  # noqa: BLE001 - never let an error's text reach the result
        return _failed(InstanceCheckStatus.INCOMPATIBLE, "check_failed", "The compatibility check could not complete.")
    finally:
        await client.aclose()


async def _probe(settings: Settings) -> bool:
    """False if the Admin API isn't there (404). Raises httpx errors if unreachable."""
    async with httpx.AsyncClient() as http:
        response = await http.get(
            f"{settings.iris_base_url}{_ADMIN_PREFIX}/info", timeout=settings.iris_request_timeout_seconds
        )
    return response.status_code != 404


async def _without_admin_api(settings: Settings) -> InstanceCheck:
    """The server answers but has no /api/admin: report its version if the
    Atelier API gives it, or a login failure if the credentials are wrong."""
    version = None
    try:
        async with httpx.AsyncClient() as http:
            response = await http.get(
                f"{settings.iris_base_url}/api/atelier/",
                auth=(settings.iris_username, settings.iris_password.get_secret_value()),
                timeout=settings.iris_request_timeout_seconds,
            )
        if response.status_code == 401:
            return _failed(InstanceCheckStatus.AUTH_FAILED, "auth_failed", "Authentication with the instance failed.")
        if response.status_code == 200:
            version = response.json()["result"]["content"]["version"]
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        pass  # the version is only for the message
    return _failed(
        InstanceCheckStatus.INCOMPATIBLE,
        "admin_api_unavailable",
        "The IRIS System Administration API (/api/admin) is not available on this server. "
        f"Requires IRIS {MINIMUM_IRIS_VERSION} or later.",
        server_version=version if isinstance(version, str) else None,
    )


async def _check(client: IRISClient) -> InstanceCheck:
    try:
        raw = await client.get("/info")
    except IRISAuthError:
        return _failed(InstanceCheckStatus.AUTH_FAILED, "auth_failed", "Authentication with the instance failed.")
    except (IRISConnectionError, IRISTimeoutError):
        return _failed(InstanceCheckStatus.UNREACHABLE, "unreachable", "The instance could not be reached.")
    except IRISResponseError:
        return _failed(
            InstanceCheckStatus.INCOMPATIBLE, "info_unavailable", "The instance did not return its identity (/info)."
        )

    try:
        info = IRISEnvelope[InfoResult].model_validate(raw).result
    except ValidationError:
        return _failed(
            InstanceCheckStatus.INCOMPATIBLE, "unexpected_identity", "The instance's identity (/info) was not recognized."
        )
    identity = {
        "product": info.product,
        "server_version": info.serverVersion,
        "api_version": info.apiVersion,
        "username": info.username,
    }
    if info.product.lower() != EXPECTED_PRODUCT:
        return _failed(
            InstanceCheckStatus.INCOMPATIBLE, "unexpected_identity", "The server is not an InterSystems IRIS instance.",
            **identity,
        )
    if info.apiVersion != EXPECTED_API_VERSION:
        return _failed(
            InstanceCheckStatus.INCOMPATIBLE, "unsupported_api_version",
            f"The instance's API version is not supported (Command Center requires version {EXPECTED_API_VERSION}).",
            **identity,
        )

    ok: list[str] = []
    missing: list[str] = []
    for path in REQUIRED_ENDPOINTS:
        (ok if await _endpoint_present(client, path) else missing).append(path)
    mgmnt = await _mgmnt_available(client)
    if missing:
        return _failed(
            InstanceCheckStatus.INCOMPATIBLE, "endpoints_missing",
            f"{len(missing)} required System Administration API endpoint(s) are missing or not permitted.",
            endpoints_ok=ok, endpoints_missing=missing, mgmnt_api_available=mgmnt, **identity,
        )
    return InstanceCheck(
        checked_at=datetime.now(timezone.utc),
        status=InstanceCheckStatus.COMPATIBLE,
        endpoints_ok=ok,
        mgmnt_api_available=mgmnt,
        **identity,
    )


async def _endpoint_present(client: IRISClient, path: str) -> bool:
    try:
        await client.get(path)
    except IRISResponseError as exc:
        return 400 <= exc.status_code < 500 and exc.status_code != 403 and exc.body is not None
    except (IRISConnectionError, IRISTimeoutError, IRISAuthError, ValueError):
        return False
    return True


async def _mgmnt_available(client: IRISClient) -> bool:
    try:
        await client.get_mgmnt("/")
    except Exception:  # noqa: BLE001 - optional: any failure just means unavailable
        return False
    return True
