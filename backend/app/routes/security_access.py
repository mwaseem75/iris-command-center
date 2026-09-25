"""Read-only Security routes, all %Admin_Secure:U:
  - Identity & Access: users, roles, role owners and resources (IRIS's GET
    /v2/security/users|user|roles|role|role/owners|resources|resource).
  - Authentication Posture: services, system-wide web authentication,
    superservers and application class-access (GET /v2/security/services|
    service|web-auth|superservers|superserver, /v2/web-app/pct-accesses).
  - X.509 credentials: credential and certificate METADATA only (GET
    /v2/security/x509-credentials|x509-credential|x509-credential/
    certificate). Key material and key passwords are never modelled.
  - OAuth 2.0: authorization server, registered clients, server
    definitions, client configurations, resource servers and mappings
    (GET /v2/security/oauth2/*), through explicit allowlist models.
  - Wallet: collections and their secrets' NAMES AND TYPES only (GET
    /v2/wallet/collections|collection|secrets, %Admin_Wallet:U). No route
    here requests a secret value — IRIS has no GET for one — and the
    models are allowlists, so no value-bearing field can pass through.

Nothing here changes IRIS state — only GETs are sent, and no route is gated
by the authorization/confirmation/execution framework, the same as every
read route in app/routes/iris.py.

Personal data: GET /v2/security/user's EmailAddress, PhoneNumber,
PhoneProvider and free-text Comment are withheld (see app/models/iris.py's SecurityUserDetail).
web-auth's SMTPUsername and TwoFactorFrom are withheld the same way. IRIS returns no
password, hash or secret from any of these endpoints.
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
    ClassAccessEntry,
    OAuth2ClientConfigDetail,
    OAuth2ClientConfigEntry,
    OAuth2Overview,
    OAuth2ResourceMappingEntry,
    OAuth2ResourceServerDetail,
    OAuth2ResourceServerEntry,
    OAuth2ServerClientDetail,
    OAuth2ServerClientEntry,
    OAuth2ServerConfigView,
    OAuth2ServerDefinitionDetail,
    OAuth2ServerDefinitionEntry,
    OAuth2ServerDefinitionOverview,
    RoleAccessEntry,
    RoleOwnerEntry,
    SecurityResourceDetail,
    SecurityServiceDetail,
    SecurityServiceEntry,
    SecurityResourceEntry,
    SecurityRoleDetail,
    SecurityRoleEntry,
    SecurityUserDetail,
    SecurityUserEntry,
    SuperserverDetail,
    SuperserverEntry,
    WalletCollectionDetail,
    WalletCollectionEntry,
    WalletCollectionOverview,
    WalletSecretEntry,
    WebAuthSettings,
    X509CertificateInfo,
    X509CredentialDetail,
    X509CredentialEntry,
    X509CredentialOverview,
)
from app.routes.iris import _IRIS_CLIENT_ERRORS, _as_http_exception

router = APIRouter(prefix="/api/iris/security", tags=["iris-security"])

# User-detail fields IRIS returns that never leave this backend.
_WITHHELD_USER_FIELDS = ("EmailAddress", "PhoneNumber", "PhoneProvider", "Comment")

# web-auth fields that never leave this backend: a mail-server credential
# identifier and the two-factor sender email address. IRIS returns no SMTP
# password at all.
_WITHHELD_WEB_AUTH_FIELDS = ("SMTPUsername", "TwoFactorFrom")

# Roles that exist but that GET /v2/security/roles was observed not to list
# on IRIS 2026.2 (icc-iris-dev: 38 roles in Security.Roles, 37 listed;
# %SQLTuneTable missing even with maxRows=5000). Each is included in the
# access map only if its own detail call confirms it exists here.
_KNOWN_UNLISTED_ROLES = ("%SQLTuneTable",)

# At most this many role-detail calls are in flight for one access-map
# request (38 roles on icc-iris-dev).
_ROLE_DETAIL_CONCURRENCY = 8
_SUPERSERVER_DETAIL_CONCURRENCY = 4
_WALLET_SECRETS_CONCURRENCY = 4
_X509_CERTIFICATE_CONCURRENCY = 4


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


# --- Authentication Posture ---


@router.get("/services", response_model=IRISEnvelope[list[SecurityServiceEntry]])
async def get_services(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[SecurityServiceEntry]]:
    raw = await _get(client, "/v2/security/services", None, "IRIS reports no services")
    return IRISEnvelope[list[SecurityServiceEntry]].model_validate(raw)


@router.get("/services/detail", response_model=IRISEnvelope[SecurityServiceDetail])
async def get_service_detail(
    name: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[SecurityServiceDetail]:
    raw = await _get(client, "/v2/security/service", {"name": name}, "IRIS reports no service with this name")
    return IRISEnvelope[SecurityServiceDetail].model_validate(raw)


@router.get("/web-auth", response_model=IRISEnvelope[WebAuthSettings])
async def get_web_auth(client: IRISClient = Depends(get_iris_client)) -> IRISEnvelope[WebAuthSettings]:
    """System-wide authentication settings. SMTPUsername and TwoFactorFrom
    are dropped before the response is built; their names (only those IRIS
    sent) are listed in `WithheldFields`, their values never are."""
    raw = await _get(client, "/v2/security/web-auth", None, "IRIS reports no web authentication settings")
    result = raw.get("result") if isinstance(raw, dict) else None
    if isinstance(result, dict):
        withheld = [field for field in _WITHHELD_WEB_AUTH_FIELDS if field in result]
        result = {k: v for k, v in result.items() if k not in _WITHHELD_WEB_AUTH_FIELDS}
        result["WithheldFields"] = withheld
        raw = {**raw, "result": result}
    return IRISEnvelope[WebAuthSettings].model_validate(raw)


@router.get("/superservers", response_model=IRISEnvelope[list[SuperserverEntry]])
async def get_superservers(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[SuperserverEntry]]:
    """Every superserver from the list, each merged with its own detail
    (keyed by the list's real Port + BindAddress). A failed detail call
    gives Detail=None and a warning in status.errors, never a guess."""
    raw = await _get(client, "/v2/security/superservers", None, "IRIS reports no superservers")
    listing = IRISEnvelope[list[dict[str, Any]]].model_validate(raw)
    semaphore = asyncio.Semaphore(_SUPERSERVER_DETAIL_CONCURRENCY)

    async def read_detail(entry: dict[str, Any]) -> SuperserverDetail | None:
        async with semaphore:
            try:
                body = await client.get(
                    "/v2/security/superserver",
                    params={"port": entry.get("Port"), "bindAddress": entry.get("BindAddress")},
                )
                return SuperserverDetail.model_validate(body.get("result") if isinstance(body, dict) else None)
            except (*_IRIS_CLIENT_ERRORS, ValidationError):
                return None

    details = await asyncio.gather(*(read_detail(entry) for entry in listing.result))

    errors = list(listing.status.errors)
    entries: list[SuperserverEntry] = []
    for entry, detail in zip(listing.result, details):
        server = SuperserverEntry.model_validate({**entry, "Detail": detail})
        if detail is None:
            errors.append(
                {"error": f"Superserver detail unavailable for {server.BindAddress}:{server.Port}", "port": server.Port}
            )
        entries.append(server)
    missing = sum(1 for detail in details if detail is None)
    summary = listing.status.summary
    if missing and not summary:
        summary = f"Superserver detail unavailable for {missing} superserver{'' if missing == 1 else 's'}"
    return IRISEnvelope[list[SuperserverEntry]](
        status={"errors": errors, "summary": summary}, console=listing.console, result=entries
    )


@router.get("/class-access", response_model=IRISEnvelope[list[ClassAccessEntry]])
async def get_class_access(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[ClassAccessEntry]]:
    """Application class-access (IRIS's "percent class access") entries:
    which % classes each web application may use."""
    raw = await _get(client, "/v2/web-app/pct-accesses", None, "IRIS reports no class-access entries")
    return IRISEnvelope[list[ClassAccessEntry]].model_validate(raw)


# --- Wallet (metadata only) ---


@router.get("/wallet/overview", response_model=IRISEnvelope[list[WalletCollectionOverview]])
async def get_wallet_overview(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[WalletCollectionOverview]]:
    """Every wallet collection with its secrets' names and types. A failed
    secret-list call gives Secrets=None plus a warning in status.errors
    (naming only the collection), never a guess. Only GETs are sent."""
    raw = await _get(client, "/v2/wallet/collections", None, "IRIS reports no wallet collections")
    listing = IRISEnvelope[list[WalletCollectionEntry]].model_validate(raw)
    semaphore = asyncio.Semaphore(_WALLET_SECRETS_CONCURRENCY)

    async def read_secrets(name: str) -> list[WalletSecretEntry] | None:
        async with semaphore:
            try:
                body = await client.get("/v2/wallet/secrets", params={"collection": name})
                result = body.get("result") if isinstance(body, dict) else None
                if not isinstance(result, list):
                    return None
                return [WalletSecretEntry.model_validate(entry) for entry in result]
            except (*_IRIS_CLIENT_ERRORS, ValidationError):
                return None

    secrets = await asyncio.gather(*(read_secrets(entry.Name) for entry in listing.result))

    errors = list(listing.status.errors)
    entries: list[WalletCollectionOverview] = []
    for entry, collection_secrets in zip(listing.result, secrets):
        if collection_secrets is None:
            errors.append({"error": f"Secret list unavailable for {entry.Name}", "collection": entry.Name})
        entries.append(WalletCollectionOverview(**entry.model_dump(), Secrets=collection_secrets))
    missing = sum(1 for collection_secrets in secrets if collection_secrets is None)
    summary = listing.status.summary
    if missing and not summary:
        summary = f"Secret list unavailable for {missing} collection{'' if missing == 1 else 's'}"
    return IRISEnvelope[list[WalletCollectionOverview]](
        status={"errors": errors, "summary": summary}, console=listing.console, result=entries
    )


@router.get("/wallet/collections/detail", response_model=IRISEnvelope[WalletCollectionDetail])
async def get_wallet_collection_detail(
    name: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[WalletCollectionDetail]:
    """One collection's edit/use resources. IRIS answers 404 for an unknown
    name (observed live: ERROR #5809)."""
    raw = await _get(
        client, "/v2/wallet/collection", {"name": name}, "IRIS reports no wallet collection with this name"
    )
    return IRISEnvelope[WalletCollectionDetail].model_validate(raw)


@router.get("/wallet/secrets", response_model=IRISEnvelope[list[WalletSecretEntry]])
async def get_wallet_secrets(
    collection: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[list[WalletSecretEntry]]:
    """Names and types of the secrets in one collection — never values.
    `collection` is IRIS's own required parameter name."""
    raw = await _get(
        client,
        "/v2/wallet/secrets",
        {"collection": collection},
        "IRIS reports no wallet collection with this name",
    )
    return IRISEnvelope[list[WalletSecretEntry]].model_validate(raw)


# --- X.509 credentials (metadata only) ---


@router.get("/x509/overview", response_model=IRISEnvelope[list[X509CredentialOverview]])
async def get_x509_overview(
    client: IRISClient = Depends(get_iris_client),
) -> IRISEnvelope[list[X509CredentialOverview]]:
    """Every X.509 credential with its certificate's metadata (subject,
    issuer, serial, validity). A failed certificate call gives
    Certificate=None plus a warning in status.errors (naming only the
    alias), never a guess. Only GETs are sent."""
    raw = await _get(client, "/v2/security/x509-credentials", None, "IRIS reports no X.509 credentials")
    listing = IRISEnvelope[list[X509CredentialEntry]].model_validate(raw)
    semaphore = asyncio.Semaphore(_X509_CERTIFICATE_CONCURRENCY)

    async def read_certificate(alias: str) -> X509CertificateInfo | None:
        async with semaphore:
            try:
                body = await client.get("/v2/security/x509-credential/certificate", params={"alias": alias})
                return X509CertificateInfo.model_validate(body.get("result") if isinstance(body, dict) else None)
            except (*_IRIS_CLIENT_ERRORS, ValidationError):
                return None

    certificates = await asyncio.gather(*(read_certificate(entry.Alias) for entry in listing.result))

    errors = list(listing.status.errors)
    entries: list[X509CredentialOverview] = []
    for entry, certificate in zip(listing.result, certificates):
        if certificate is None:
            errors.append({"error": f"Certificate unavailable for {entry.Alias}", "alias": entry.Alias})
        entries.append(X509CredentialOverview(**entry.model_dump(), Certificate=certificate))
    missing = sum(1 for certificate in certificates if certificate is None)
    summary = listing.status.summary
    if missing and not summary:
        summary = f"Certificate unavailable for {missing} credential{'' if missing == 1 else 's'}"
    return IRISEnvelope[list[X509CredentialOverview]](
        status={"errors": errors, "summary": summary}, console=listing.console, result=entries
    )


@router.get("/x509/credentials/detail", response_model=IRISEnvelope[X509CredentialDetail])
async def get_x509_credential_detail(
    alias: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[X509CredentialDetail]:
    """One credential's owners, peer names and CA file. IRIS answers 404 for
    an unknown alias (observed live: ERROR #914)."""
    raw = await _get(
        client, "/v2/security/x509-credential", {"alias": alias}, "IRIS reports no X.509 credential with this alias"
    )
    return IRISEnvelope[X509CredentialDetail].model_validate(raw)


@router.get("/x509/credentials/certificate", response_model=IRISEnvelope[X509CertificateInfo])
async def get_x509_certificate(
    alias: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[X509CertificateInfo]:
    """The certificate's metadata for one credential — never key material."""
    raw = await _get(
        client,
        "/v2/security/x509-credential/certificate",
        {"alias": alias},
        "IRIS reports no X.509 credential with this alias",
    )
    return IRISEnvelope[X509CertificateInfo].model_validate(raw)


# --- OAuth 2.0 (allowlisted metadata only) ---

# The two services IRIS accepts for resource-server mappings (the spec:
# 'Valid values are "%Service_WebGateway" and "%Service_Bindings"').
_OAUTH_MAPPING_SERVICES = ("%Service_WebGateway", "%Service_Bindings")
_OAUTH_CONCURRENCY = 4


@router.get("/oauth/overview", response_model=IRISEnvelope[OAuth2Overview])
async def get_oauth_overview(client: IRISClient = Depends(get_iris_client)) -> IRISEnvelope[OAuth2Overview]:
    """Every OAuth 2.0 area in one response: authorization server
    configuration, registered clients, server definitions (each with its
    client configurations), resource servers and resource-server mappings.

    Only GETs are sent, and every part is built from an allowlist model. The
    documented 404 "not configured" answer for the authorization server is
    ServerConfigured=False, not an error. Any other failed part is None plus
    a warning in status.errors (naming only the area), never a guess.
    """
    errors: list[dict[str, Any]] = []
    semaphore = asyncio.Semaphore(_OAUTH_CONCURRENCY)

    async def read(path: str, params: dict[str, Any] | None = None) -> Any:
        async with semaphore:
            body = await (client.get(path, params=params) if params else client.get(path))
            return body.get("result") if isinstance(body, dict) else None

    async def read_list(path: str, model: type, area: str, params: dict[str, Any] | None = None) -> list | None:
        try:
            result = await read(path, params)
            if not isinstance(result, list):
                raise ValueError("not a list")
            return [model.model_validate(item) for item in result if isinstance(item, dict)]
        except (*_IRIS_CLIENT_ERRORS, ValidationError, ValueError):
            errors.append({"error": f"OAuth 2.0 {area} unavailable", "area": area})
            return None

    async def read_server() -> tuple[bool | None, OAuth2ServerConfigView | None]:
        try:
            result = await read("/v2/security/oauth2/server")
            return True, OAuth2ServerConfigView.model_validate(result if isinstance(result, dict) else {})
        except IRISResponseError as exc:
            if exc.status_code == 404:
                return False, None
            errors.append({"error": "OAuth 2.0 authorization server unavailable", "area": "authorization server"})
            return None, None
        except (*_IRIS_CLIENT_ERRORS, ValidationError):
            errors.append({"error": "OAuth 2.0 authorization server unavailable", "area": "authorization server"})
            return None, None

    async def read_mappings() -> list[OAuth2ResourceMappingEntry] | None:
        parts = await asyncio.gather(
            *(
                read_list(
                    "/v2/security/oauth2/resource-server/mappings",
                    OAuth2ResourceMappingEntry,
                    f"resource mappings for {service}",
                    {"service": service},
                )
                for service in _OAUTH_MAPPING_SERVICES
            )
        )
        return None if any(part is None for part in parts) else [m for part in parts for m in part]

    (configured, server), server_clients, definitions, resource_servers, mappings = await asyncio.gather(
        read_server(),
        read_list("/v2/security/oauth2/server/clients", OAuth2ServerClientEntry, "registered clients"),
        read_list("/v2/security/oauth2/client/server-definitions", OAuth2ServerDefinitionEntry, "server definitions"),
        read_list("/v2/security/oauth2/resource-servers", OAuth2ResourceServerEntry, "resource servers"),
        read_mappings(),
    )

    definition_overviews: list[OAuth2ServerDefinitionOverview] | None = None
    if definitions is not None:
        configurations = await asyncio.gather(
            *(
                read_list(
                    "/v2/security/oauth2/client/client-configurations",
                    OAuth2ClientConfigEntry,
                    f"client configurations for server definition {definition.ID}",
                    {"serverId": definition.ID},
                )
                if definition.ID
                else asyncio.sleep(0, result=None)
                for definition in definitions
            )
        )
        definition_overviews = [
            OAuth2ServerDefinitionOverview(**definition.model_dump(), ClientConfigurations=configs)
            for definition, configs in zip(definitions, configurations)
        ]

    overview = OAuth2Overview(
        ServerConfigured=configured,
        Server=server,
        ServerClients=server_clients,
        ServerDefinitions=definition_overviews,
        ResourceServers=resource_servers,
        ResourceMappings=mappings,
    )
    summary = f"{len(errors)} OAuth 2.0 area{'' if len(errors) == 1 else 's'} unavailable" if errors else ""
    return IRISEnvelope[OAuth2Overview](status={"errors": errors, "summary": summary}, console=[], result=overview)


@router.get("/oauth/server-clients/detail", response_model=IRISEnvelope[OAuth2ServerClientDetail])
async def get_oauth_server_client_detail(
    clientId: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[OAuth2ServerClientDetail]:
    """A client registered with this authorization server. `clientId` is the
    IRIS parameter name. No client secret is modelled."""
    raw = await _get(
        client, "/v2/security/oauth2/server/client", {"clientId": clientId}, "IRIS reports no OAuth 2.0 client with this id"
    )
    return IRISEnvelope[OAuth2ServerClientDetail].model_validate(raw)


@router.get("/oauth/server-definitions/detail", response_model=IRISEnvelope[OAuth2ServerDefinitionDetail])
async def get_oauth_server_definition_detail(
    serverId: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[OAuth2ServerDefinitionDetail]:
    raw = await _get(
        client,
        "/v2/security/oauth2/client/server-definition",
        {"serverId": serverId},
        "IRIS reports no OAuth 2.0 server definition with this id",
    )
    return IRISEnvelope[OAuth2ServerDefinitionDetail].model_validate(raw)


@router.get("/oauth/client-configurations/detail", response_model=IRISEnvelope[OAuth2ClientConfigDetail])
async def get_oauth_client_configuration_detail(
    applicationName: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[OAuth2ClientConfigDetail]:
    """A client configuration. No ClientSecret / ClientPassword is modelled."""
    raw = await _get(
        client,
        "/v2/security/oauth2/client/client-configuration",
        {"applicationName": applicationName},
        "IRIS reports no OAuth 2.0 client configuration with this name",
    )
    return IRISEnvelope[OAuth2ClientConfigDetail].model_validate(raw)


@router.get("/oauth/resource-servers/detail", response_model=IRISEnvelope[OAuth2ResourceServerDetail])
async def get_oauth_resource_server_detail(
    name: str, client: IRISClient = Depends(get_iris_client)
) -> IRISEnvelope[OAuth2ResourceServerDetail]:
    raw = await _get(
        client,
        "/v2/security/oauth2/resource-server",
        {"name": name},
        "IRIS reports no OAuth 2.0 resource server with this name",
    )
    return IRISEnvelope[OAuth2ResourceServerDetail].model_validate(raw)
