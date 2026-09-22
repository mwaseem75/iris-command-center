"""Read-only Identity & Access routes: users, roles, role owners and
resources (IRIS's GET /v2/security/users|user|roles|role|role/owners|
resources|resource, all %Admin_Secure:U).

Nothing here changes IRIS state — only GETs are sent, and no route is gated
by the authorization/confirmation/execution framework, the same as every
read route in app/routes/iris.py.

Personal data: GET /v2/security/user's EmailAddress, PhoneNumber,
PhoneProvider and free-text Comment are withheld (see app/models/iris.py's SecurityUserDetail).
IRIS returns no password, hash or secret from any of these endpoints.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError

from app.dependencies import get_iris_client
from app.iris_client.client import IRISClient
from app.iris_client.exceptions import IRISResponseError
from app.models.iris import (
    IRISEnvelope,
    RoleAccessEntry,
    RoleOwnerEntry,
    SecurityResourceDetail,
    SecurityResourceEntry,
    SecurityRoleDetail,
    SecurityRoleEntry,
    SecurityUserDetail,
    SecurityUserEntry,
)
from app.routes.iris import _IRIS_CLIENT_ERRORS, _as_http_exception

router = APIRouter(prefix="/api/iris/security", tags=["iris-security"])

# User-detail fields IRIS returns that never leave this backend.
_WITHHELD_USER_FIELDS = ("EmailAddress", "PhoneNumber", "PhoneProvider", "Comment")

# Roles that exist but that GET /v2/security/roles was observed not to list
# on IRIS 2026.2 (icc-iris-dev: 38 roles in Security.Roles, 37 listed;
# %SQLTuneTable missing even with maxRows=5000). Each is included in the
# access map only if its own detail call confirms it exists here.
_KNOWN_UNLISTED_ROLES = ("%SQLTuneTable",)

# At most this many role-detail calls are in flight for one access-map
# request (38 roles on icc-iris-dev).
_ROLE_DETAIL_CONCURRENCY = 8


async def _get(client: IRISClient, path: str, params: dict[str, Any] | None, not_found: str) -> Any:
    """GET an IRIS path, mapping IRIS's documented 404 (unknown name) to a
    404 with a safe, fixed message; every other failure is the shared
    generic mapping."""
    try:
        return await client.get(path, params=params) if params else await client.get(path)
    except IRISResponseError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=404, detail=not_found) from exc
        raise _as_http_exception(exc) from exc
    except _IRIS_CLIENT_ERRORS as exc:
        raise _as_http_exception(exc) from exc


@router.get("/users", response_model=IRISEnvelope[list[SecurityUserEntry]])
async def get_users(client: IRISClient = Depends(get_iris_client)) -> IRISEnvelope[list[SecurityUserEntry]]:
    raw = await _get(client, "/v2/security/users", None, "IRIS reports no users")
    return IRISEnvelope[list[SecurityUserEntry]].model_validate(raw)


@router.get("/users/detail", response_model=IRISEnvelope[SecurityUserDetail])
async def get_user_detail(
    name: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[SecurityUserDetail]:
    """One user's account, roles and password-policy flags. Personal fields
    are dropped before the response is built; their names (only those IRIS
    actually sent) are listed in `WithheldFields`. Values never are."""
    raw = await _get(client, "/v2/security/user", {"name": name}, "IRIS reports no user with this name")
    result = raw.get("result") if isinstance(raw, dict) else None
    if isinstance(result, dict):
        withheld = [field for field in _WITHHELD_USER_FIELDS if field in result]
        result = {k: v for k, v in result.items() if k not in _WITHHELD_USER_FIELDS}
        result["WithheldFields"] = withheld
        raw = {**raw, "result": result}
    return IRISEnvelope[SecurityUserDetail].model_validate(raw)


@router.get("/roles", response_model=IRISEnvelope[list[SecurityRoleEntry]])
async def get_roles(client: IRISClient = Depends(get_iris_client)) -> IRISEnvelope[list[SecurityRoleEntry]]:
    """IRIS's role list exactly as returned — including its omission of
    %SQLTuneTable, which is never added here (see /roles/access-map)."""
    raw = await _get(client, "/v2/security/roles", None, "IRIS reports no roles")
    return IRISEnvelope[list[SecurityRoleEntry]].model_validate(raw)


@router.get("/roles/detail", response_model=IRISEnvelope[SecurityRoleDetail])
async def get_role_detail(
    name: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[SecurityRoleDetail]:
    raw = await _get(client, "/v2/security/role", {"name": name}, "IRIS reports no role with this name")
    return IRISEnvelope[SecurityRoleDetail].model_validate(raw)


@router.get("/roles/owners", response_model=IRISEnvelope[list[RoleOwnerEntry]])
async def get_role_owners(
    name: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[list[RoleOwnerEntry]]:
    """Users and roles holding a role, including "User (escalation)" rows,
    exactly as IRIS reports them."""
    raw = await _get(
        client, "/v2/security/role/owners", {"name": name}, "IRIS reports no role with this name"
    )
    return IRISEnvelope[list[RoleOwnerEntry]].model_validate(raw)


@router.get("/roles/access-map", response_model=IRISEnvelope[list[RoleAccessEntry]])
async def get_role_access_map(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[RoleAccessEntry]]:
    """Every role's granted roles and resource permissions in one response —
    the data behind resource → role lookups and privileged-access views.

    Starts from IRIS's role list (Listed=True), then adds roles that exist
    but are not listed (Listed=False): names in _KNOWN_UNLISTED_ROLES and
    any role named in another role's GrantedRoles, each only if its own
    detail call returns it. A missing one (404) is simply not added. A
    failed detail call for a listed role gives Detail=None plus a warning
    in status.errors, never a guess.
    """
    raw = await _get(client, "/v2/security/roles", None, "IRIS reports no roles")
    listing = IRISEnvelope[list[SecurityRoleEntry]].model_validate(raw)
    listed = [role.Name for role in listing.result]
    semaphore = asyncio.Semaphore(_ROLE_DETAIL_CONCURRENCY)

    async def read_detail(name: str) -> SecurityRoleDetail | None | bool:
        """The detail, None on failure, or False if IRIS says it doesn't exist."""
        async with semaphore:
            try:
                body = await client.get("/v2/security/role", params={"name": name})
                return SecurityRoleDetail.model_validate(body.get("result") if isinstance(body, dict) else None)
            except IRISResponseError as exc:
                return False if exc.status_code == 404 else None
            except (*_IRIS_CLIENT_ERRORS, ValidationError):
                return None

    details: dict[str, SecurityRoleDetail | None | bool] = dict(
        zip(listed, await asyncio.gather(*(read_detail(name) for name in listed)))
    )

    referenced = {
        granted
        for detail in details.values()
        if isinstance(detail, SecurityRoleDetail)
        for granted in detail.GrantedRoles
    }
    candidates = sorted((set(_KNOWN_UNLISTED_ROLES) | referenced) - set(listed))
    unlisted = dict(zip(candidates, await asyncio.gather(*(read_detail(name) for name in candidates))))

    errors = list(listing.status.errors)
    entries: list[RoleAccessEntry] = []
    for name, detail in details.items():
        if not isinstance(detail, SecurityRoleDetail):
            errors.append({"error": f"Role detail unavailable for {name}", "role": name})
            detail = None
        entries.append(RoleAccessEntry(Name=name, Listed=True, Detail=detail))
    for name, detail in unlisted.items():
        # Only roles IRIS itself confirms exist are added; nothing else is.
        if isinstance(detail, SecurityRoleDetail):
            entries.append(RoleAccessEntry(Name=name, Listed=False, Detail=detail))

    missing = sum(1 for entry in entries if entry.Detail is None)
    summary = listing.status.summary
    if missing and not summary:
        summary = f"Role detail unavailable for {missing} role{'' if missing == 1 else 's'}"
    return IRISEnvelope[list[RoleAccessEntry]](
        status={"errors": errors, "summary": summary}, console=listing.console, result=entries
    )


@router.get("/resources", response_model=IRISEnvelope[list[SecurityResourceEntry]])
async def get_resources(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[SecurityResourceEntry]]:
    raw = await _get(client, "/v2/security/resources", None, "IRIS reports no resources")
    return IRISEnvelope[list[SecurityResourceEntry]].model_validate(raw)


@router.get("/resources/detail", response_model=IRISEnvelope[SecurityResourceDetail])
async def get_resource_detail(
    name: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[SecurityResourceDetail]:
    raw = await _get(
        client, "/v2/security/resource", {"name": name}, "IRIS reports no resource with this name"
    )
    return IRISEnvelope[SecurityResourceDetail].model_validate(raw)
