"""Pydantic models for IRIS Admin REST API responses.

These follow what IRIS 2026.2 actually returns, which doesn't always match
mainspec_v2.json. Where they differ we go with the real response:
- Every response is wrapped in {"status", "console", "result"}
  (IRISEnvelope), even where the spec shows a flat body.
- The key is `status.errors` (lowercase), not `Errors`. We've only seen it
  empty, so it and `console` are list[Any].
- `Info.privileges` is a dict of name -> {"use": bool}, since which keys
  show up depends on the account's privileges.

Endpoints we've only ever seen return an empty list get list[Any] rather
than made-up fields. The OAuth2 models are the exception: those IRIS
classes hold secrets, so they use all-optional allowlist models.
"""

from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import BaseModel, BeforeValidator, Field

ResultT = TypeVar("ResultT")


class IRISStatus(BaseModel):
    errors: list[Any] = Field(default_factory=list)
    summary: str = ""


class IRISEnvelope(BaseModel, Generic[ResultT]):
    status: IRISStatus
    console: list[Any] = Field(default_factory=list)
    result: ResultT


# --- GET /info ---


class AdminPrivilegeFlag(BaseModel):
    use: bool


class InfoNamespaceRef(BaseModel):
    name: str


class InfoResult(BaseModel):
    apiVersion: int
    username: str
    serverVersion: str
    systemMode: str
    product: str
    namespaces: list[InfoNamespaceRef]
    privileges: dict[str, AdminPrivilegeFlag]


# --- GET /v2/namespaces ---


class NamespaceEntry(BaseModel):
    Name: str
    Globals: str
    Routines: str
    SysGlobals: str
    SysRoutines: str
    Library: str
    TempGlobals: str


# --- GET /v2/databases ---


class DatabaseEntry(BaseModel):
    Name: str
    Directory: str
    Server: str
    ClusterMountMode: bool
    MountRequired: bool
    MountAtStartup: bool
    StreamLocation: str
    Status: str


# --- POST /v2/database-dir/info (async task) ---
# Storage facts for one database; the spec has no result schema, so these
# fields come from a real response. No Name/Directory: the caller already
# knows the directory it asked about.


class DatabaseInfoResult(BaseModel):
    Size: int
    ExpansionSize: int
    MaxSize: int
    ReadOnlyReason: str
    EncryptionKeyID: str
    BlockSize: int
    Blocks: int
    AvailableSpace: float
    DiskFree: str
    EndFree: int
    LastExpansionTime: str
    MirrorSetName: str
    MirrorDBName: str
    SFN: int
    Mirrored: bool
    Encrypted: bool
    Full: bool
    Mounted: bool
    MirrorFailoverDB: bool


# --- POST /v2/database-dir/integrity-check (async task) ---
# We haven't run one against a real instance (it scans live data) and the
# spec has no result schema, so `Result` is Any. The other fields are the
# standard async-task envelope we've seen from audit records and
# database-dir/info.


class DatabaseIntegrityCheckResult(BaseModel):
    State: str
    TaskName: str
    Console: list[Any]
    FailureReason: str
    Result: Any
    TimeQueued: str
    TimeStarted: str
    TimeFinished: str


# --- GET /v2/processes ---


class ProcessEntry(BaseModel):
    Job: int
    Pid: int
    Username: str
    Device: str
    Nspace: str
    Routine: str
    Commands: int
    Globals: int
    State: str
    ClientName: str
    EXEname: str
    IPAddress: str
    CanBeExamined: bool
    CanBeSuspended: bool
    CanBeTerminated: bool
    CanReceiveBroadcast: bool
    PrvGblBlkCnt: int
    OSUserName: str
    CPUTime: int
    ParentPid: int
    ElapsedTime: str


# --- GET /v2/web-apps ---


class WebAppEntry(BaseModel):
    Name: str
    Namespace: str
    NamespaceDefault: bool
    Enabled: bool
    Type: str
    Resource: str
    AuthenticationMethods: list[str]
    IsSystemApp: bool
    DispatchClass: str


# --- GET /v2/web-app?name=<Name> ---
# Mirrors Security.Applications. Two differences from the spec: `Type` is
# missing from the real response (so only WebAppEntry has a Type), and
# `WSGIType` is a string, not an integer.


class WebAppMatchRole(BaseModel):
    MatchRole: str
    TargetRoles: list[str]


class WebAppDetail(BaseModel):
    AutheEnabled: int
    AutoCompile: bool
    ChangePasswordPage: str
    CookiePath: str
    CorsAllowlist: list[str]
    CorsCredentialsAllowed: bool
    CorsHeadersList: list[str]
    CSPZENEnabled: bool
    CSRFToken: bool
    DeepSeeEnabled: bool
    Description: str
    DispatchClass: str
    Enabled: bool
    ErrorPage: str
    EventClass: str
    GroupById: str
    iKnowEnabled: bool
    InbndWebServicesEnabled: bool
    IsNameSpaceDefault: bool
    JWTAuthEnabled: bool
    JWTAccessTokenTimeout: int
    JWTRefreshTokenTimeout: int
    LockCSPName: bool
    LoginPage: str
    MatchRoles: list[WebAppMatchRole]
    NameSpace: str
    Package: str
    Path: str
    PermittedClasses: str
    Recurse: bool
    RedirectEmptyPath: bool
    Resource: str
    ServeFiles: str
    ServeFilesTimeout: int
    SuperClass: str
    Timeout: int
    TraceEnabled: bool
    TwoFactorEnabled: bool
    UseCookies: str
    SessionScope: str
    UserCookieScope: str
    WSGIAppLocation: str
    WSGIAppName: str
    WSGICallable: str
    WSGIDebug: bool
    WSGIType: str


# --- GET /v2/web-sessions ---
# Timeout is a "YYYY-MM-DD HH:MM:SS" string, SesProcessId is "" when no
# process is serving the session, LicenseId is "<user>@<address>".
#
# `ID` is left out on purpose: it's the CSP session id (what
# DELETE /v2/web-session?id= takes), so it must not leave the backend.
# Pydantic drops unmodelled fields, so it can't end up in a response.


class WebSessionEntry(BaseModel):
    Username: str
    Preserve: int
    Application: str
    Timeout: str
    LicenseId: str
    SesProcessId: str
    AllowEndSession: bool


# --- GET /api/mgmnt/v1/{namespace}/spec{webApplication} ---
# Swagger 2.0 generated from a REST app's dispatch class. Every operation
# has operationId and x-ISC_ServiceMethod; summary, description and
# parameters are optional. Parameters can be a $ref to the top-level
# `parameters` (resolved in the route). The generated `responses` are
# always the same two placeholders, so we skip them.
# RestEndpoint/RestRouteMap are a flattened copy of that document.


class RestEndpointParameter(BaseModel):
    name: str | None = None
    location: str | None = None  # Swagger's `in`
    required: bool | None = None
    type: str | None = None
    description: str | None = None
    pattern: str | None = None
    bodySchema: dict[str, Any] | None = None  # Swagger's `schema` (body parameters)
    ref: str | None = None  # unresolvable "$ref", kept as-is


class RestEndpoint(BaseModel):
    method: str
    path: str
    operationId: str | None = None
    serviceMethod: str | None = None  # Swagger's x-ISC_ServiceMethod
    summary: str | None = None
    description: str | None = None
    parameters: list[RestEndpointParameter]


class RestRouteMap(BaseModel):
    name: str
    namespace: str
    dispatchClass: str
    enabled: bool | None = None
    basePath: str | None = None
    swagger: str | None = None
    endpoints: list[RestEndpoint]


# --- GET /v2/ext-lang-servers ---


class ExternalLanguageServerEntry(BaseModel):
    Name: str
    Port: int
    Type: str


# --- GET /v2/tasks ---


class TaskEntry(BaseModel):
    Name: str
    Type: str
    Namespace: str
    Description: str
    Id: int
    Suspended: bool
    LastFinished: str
    NextScheduled: str


# --- GET /v2/task/info?id=<Id> ---
# `Status` is a string; "-1" means running, -2..-5 are errors described
# in `Error`. Use this `Suspended`, not the list's: the list said false
# for two tasks that were actually suspended. ---


class TaskInfo(BaseModel):
    Type: str
    Status: str
    Error: str
    LastSchedule: str
    LastStarted: str
    LastFinished: str
    NextScheduled: str
    Suspended: bool


# --- GET /api/iris/tasks/overview (our own) ---
# GET /v2/tasks merged with each task's /v2/task/info. The list's
# `Suspended` is dropped (see TaskInfo). `Info` and `State` are None if
# the info call failed. `NextScheduled` is kept as the raw string: a
# datetime, "" for on-demand tasks, or text like "Runs After #1:00". ---


class TaskOverviewEntry(BaseModel):
    Id: int
    Name: str
    Type: str
    Namespace: str
    Description: str
    LastFinished: str
    NextScheduled: str
    Info: TaskInfo | None
    State: Literal["Running", "Not Running", "Suspended"] | None


# --- GET /v2/task?id=<Id> ---
# Some types differ from the spec: TimePeriodEvery/TimePeriodDay come back
# as ints or "", ExpiresDays/Hours/Minutes as "". Those (and
# DailyIncrement) are `int | str` and passed through.
#
# `Settings` depends on the task class and can contain credentials
# (Diagnostic Report has SMTPPass). routes/iris.py redacts those before
# returning: values become None and the paths go in `RedactedSettings`
# (our field, not IRIS's). ---


class TaskDetail(BaseModel):
    Name: str
    Description: str
    TaskClass: str
    NameSpace: str
    RunAsUser: str
    Priority: str
    IsBatch: bool
    MirrorStatus: str
    RescheduleOnStart: bool
    SuspendOnError: bool
    SuspendTerminated: bool
    TimePeriod: str
    TimePeriodEvery: int | str
    TimePeriodDay: int | str
    DailyFrequency: str
    DailyFrequencyTime: str
    DailyIncrement: int | str
    DailyStartTime: str
    DailyEndTime: str
    StartDate: str
    EndDate: str
    RunAfterGUID: str
    Expires: bool
    ExpiresDays: int | str
    ExpiresHours: int | str
    ExpiresMinutes: int | str
    OpenOutputFile: bool
    OutputDirectory: str
    OutputFilename: str
    OutputFileIsBinary: bool
    EmailOutput: bool
    EmailOnCompletion: list[str]
    EmailOnError: list[str]
    EmailOnExpiration: list[str]
    Settings: dict[str, Any]
    RedactedSettings: list[str] = Field(default_factory=list)


# --- GET /v2/task/manager ---
# {"Status": "Running"}; can also be "Not running" or "Suspended". ---


class TaskManagerStatus(BaseModel):
    Status: str


# --- Security: Identity & Access ---
# GET /v2/security/users|user|roles|role|role/owners|resources|resource.
# Routes are in routes/security_access.py. ---


class SecurityUserEntry(BaseModel):
    Name: str
    FullName: str
    Enabled: bool
    Type: str
    Namespace: str
    Routine: str


# GET /v2/security/user also returns EmailAddress, PhoneNumber,
# PhoneProvider and Comment. Those aren't modelled, so they get dropped;
# the route lists which ones IRIS sent in `WithheldFields`. Anything new
# IRIS adds is dropped the same way. There's no password or hash field.
# `AutheEnabled` is the two-factor bitmask (2**20 SMS, 2**21 TOTP).


class SecurityUserDetail(BaseModel):
    FullName: str
    Enabled: bool
    Roles: list[str]
    EscalationRoles: list[str]
    NameSpace: str
    Routine: str
    AutheEnabled: int
    ChangePassword: bool
    PasswordNeverExpires: bool
    AccountNeverExpires: bool
    ExpirationDate: str
    HOTPKeyDisplay: bool
    WithheldFields: list[str] = Field(default_factory=list)


class SecurityRoleEntry(BaseModel):
    Name: str
    Description: str
    CreatedBy: str
    EscalationOnly: bool


class RoleResourceGrant(BaseModel):
    Name: str
    Permissions: str


class SecurityRoleDetail(BaseModel):
    Description: str
    GrantedRoles: list[str]
    EscalationOnly: bool
    Resources: list[RoleResourceGrant]


# `AdminOption` is "0" on User/Role rows and `false` on
# "User (escalation)" rows. Passed through as-is.


class RoleOwnerEntry(BaseModel):
    Name: str
    Type: str
    AdminOption: bool | str


# GET /api/iris/security/roles/access-map (our own): the role list merged
# with each role's detail. `Listed` is False for roles that exist but
# aren't in GET /v2/security/roles (e.g. %SQLTuneTable). `Detail` is None
# if the detail call failed.


class RoleAccessEntry(BaseModel):
    Name: str
    Listed: bool
    Detail: SecurityRoleDetail | None


class SecurityResourceEntry(BaseModel):
    Name: str
    Description: str
    PublicPermission: str
    ResourceType: str
    AllowDelete: bool


class SecurityResourceDetail(BaseModel):
    Description: str
    PublicPermission: str


# --- Security: Authentication ---

# GET /v2/security/services. `Enabled` is really a boolean (the spec says
# string) and there's no `EnabledBoolean`. An empty AllowedConnections
# means no restrictions. AuthenticationMethods leaves out AutheSystem
# (bit 10), though the detail's AutheEnabled includes it.


class SecurityServiceEntry(BaseModel):
    Name: str
    Enabled: bool
    Public: str
    AuthenticationMethods: list[str]
    AllowedConnections: list[str]
    Description: str
    HttpOnlyCookies: bool
    TwoFactorEnabled: bool


# GET /v2/security/service?name=. AutheEnabled is a bitmask
# (bit 0 AutheK5CCache ... bit 25 MutualTLS).


class SecurityServiceDetail(BaseModel):
    AutheEnabled: int
    ClientSystems: list[str]
    Description: str
    Enabled: bool


# GET /v2/security/web-auth. SMTPUsername and TwoFactorFrom aren't
# modelled (the route lists them in `WithheldFields`); IRIS doesn't
# return the SMTP password. New fields are dropped too.


class WebAuthSettings(BaseModel):
    AutheUnauthenticated: bool
    AutheOS: bool
    AutheOSDelegated: bool
    AutheOSLDAP: bool
    AutheCache: bool
    AutheDelegated: bool
    AutheAlwaysTryDelegated: bool
    AutheKB: bool
    AutheLDAP: bool
    AutheLDAPCache: bool
    AutheOAuth2: bool
    AutheLoginToken: bool
    AutheTwoFactorSMS: bool
    AutheTwoFactorPW: bool
    LoginCookieTimeout: int
    TwoFactorTimeout: int
    SMTPServer: str
    JWTIssuer: str
    JWTSigAlg: str
    WithheldFields: list[str] = Field(default_factory=list)


# GET /v2/security/superserver?port=&bindAddress=.
# SSLSupportLevel: 0 = None, 1 = Accept, 2 = Require.


class SuperserverDetail(BaseModel):
    Description: str
    Enabled: bool
    SystemDefault: bool
    SSLConfig: str
    SSLSupportLevel: int
    EnableCacheDirect: bool
    EnableClients: bool
    EnableCSP: bool
    EnableDataCheck: bool
    EnableECP: bool
    EnableMirror: bool
    EnableNodeJS: bool
    EnableShadows: bool
    EnableSharding: bool
    EnableSNMP: bool
    EnableWebLink: bool


# GET /api/iris/security/superservers (our own): the list merged with each
# detail. `Detail` is None if that call failed.


class SuperserverEntry(BaseModel):
    Port: int
    BindAddress: str
    Enabled: bool
    SystemDefault: bool
    Detail: SuperserverDetail | None


# GET /v2/web-app/pct-accesses: which % classes each web app (or
# "all-applications") may use.


# --- Security: Wallet (%Admin_Wallet:U) ---
# Our instance has no wallet collections, so these follow the spec.
# Permission fields are optional so a missing one shows "not reported";
# Name is required.
#
# Metadata only. IRIS has no GET that returns a secret value
# (/v2/wallet/secret is PUT/DELETE only), and any extra field like
# `Secret` would be dropped anyway. ---


class WalletCollectionEntry(BaseModel):
    Name: str
    EditResource: str | None = None
    UseResource: str | None = None


class WalletCollectionDetail(BaseModel):
    EditResource: str | None = None
    UseResource: str | None = None


class WalletSecretEntry(BaseModel):
    Name: str
    Type: str | None = None


# GET /api/iris/security/wallet/overview (our own): each collection with
# its secrets' names and types. `Secrets` is None if that list failed.


class WalletCollectionOverview(BaseModel):
    Name: str
    EditResource: str | None = None
    UseResource: str | None = None
    Secrets: list[WalletSecretEntry] | None


# --- Security: X.509 credentials (%Admin_Secure:U, keyed by `alias`) ---
# Our instance has none (an unknown alias is 404 ERROR #914), so these
# follow the spec, with everything except Alias optional.
#
# Certificate metadata only. `HasPrivateKey` is just a boolean; key
# material, passwords, file paths and PEM contents only appear in the
# POST body and aren't modelled. ---


class X509CredentialEntry(BaseModel):
    Alias: str
    HasPrivateKey: bool | None = None
    OwnerList: list[str] | None = None
    PeerNames: list[str] | None = None
    CAFile: str | None = None


class X509CredentialDetail(BaseModel):
    OwnerList: list[str] | None = None
    PeerNames: list[str] | None = None
    CAFile: str | None = None


class X509CertificateInfo(BaseModel):
    HasPrivateKey: bool | None = None
    SerialNumber: str | None = None
    IssuerDN: str | None = None
    SubjectDN: str | None = None
    ValidityNotBefore: str | None = None
    ValidityNotAfter: str | None = None


# GET /api/iris/security/x509/overview (our own): each credential with its
# certificate metadata. `Certificate` is None if that call failed.


class X509CredentialOverview(X509CredentialEntry):
    Certificate: X509CertificateInfo | None


# --- Security: OAuth 2.0 (GET /v2/security/oauth2/*) ---
# Nothing is configured on our instance (the server gives 404 ERROR #8864,
# lists are empty), so these follow the spec.
#
# These are allowlists: IRIS's OAuth2 classes also hold client secrets,
# registration tokens, key passwords and so on, and only the fields below
# can get through. Every field is optional and uses the _Safe* types, so a
# missing or oddly typed value becomes None, and a nested object can't
# sneak through a string or list field. `*Credentials` fields are X.509
# aliases, not keys. ---


def _only_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _only_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _only_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _only_str_list(value: Any) -> list[str] | None:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else None


def _only_dict(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _only_dict_list(value: Any) -> list[dict[str, Any]] | None:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else None


_SafeStr = Annotated[str | None, BeforeValidator(_only_str)]
_SafeBool = Annotated[bool | None, BeforeValidator(_only_bool)]
_SafeInt = Annotated[int | None, BeforeValidator(_only_int)]
_SafeStrList = Annotated[list[str] | None, BeforeValidator(_only_str_list)]


class OAuth2ServerMetadataView(BaseModel):
    """Public discovery endpoints and capabilities (part of OAuth2ServerMetadata)."""

    issuer: _SafeStr = None
    authorization_endpoint: _SafeStr = None
    token_endpoint: _SafeStr = None
    userinfo_endpoint: _SafeStr = None
    revocation_endpoint: _SafeStr = None
    introspection_endpoint: _SafeStr = None
    jwks_uri: _SafeStr = None
    registration_endpoint: _SafeStr = None
    end_session_endpoint: _SafeStr = None
    scopes_supported: _SafeStrList = None
    response_types_supported: _SafeStrList = None
    grant_types_supported: _SafeStrList = None
    code_challenge_methods_supported: _SafeStrList = None
    token_endpoint_auth_methods_supported: _SafeStrList = None
    id_token_signing_alg_values_supported: _SafeStrList = None


class OAuth2ClientMetadataView(BaseModel):
    """Client registration metadata (part of OAuth2ClientMetadata). `contacts`
    (email addresses) is left out.
    """

    client_name: _SafeStr = None
    application_type: _SafeStr = None
    redirect_uris: _SafeStrList = None
    response_types: _SafeStrList = None
    grant_types: _SafeStrList = None
    token_endpoint_auth_method: _SafeStr = None
    id_token_signed_response_alg: _SafeStr = None
    client_uri: _SafeStr = None
    logo_uri: _SafeStr = None
    policy_uri: _SafeStr = None
    tos_uri: _SafeStr = None
    default_max_age: _SafeInt = None


class OAuth2Scope(BaseModel):
    Scope: _SafeStr = None
    Description: _SafeStr = None


class OAuth2ServerConfigView(BaseModel):
    """GET /v2/security/oauth2/server (%Admin_OAuth2_Server:U)."""

    IssuerEndpoint: _SafeStr = None
    Description: _SafeStr = None
    AccessTokenInterval: _SafeInt = None
    AuthorizationCodeInterval: _SafeInt = None
    RefreshTokenInterval: _SafeInt = None
    SessionInterval: _SafeInt = None
    ClientSecretInterval: _SafeInt = None
    SupportedScopes: Annotated[list[OAuth2Scope] | None, BeforeValidator(_only_dict_list)] = None
    DefaultScope: _SafeStr = None
    AllowUnsupportedScope: _SafeBool = None
    ReturnRefreshToken: _SafeStr = None
    SupportSession: _SafeBool = None
    AudRequired: _SafeBool = None
    AllowPublicClientRefresh: _SafeBool = None
    ForcePKCEForPublicClients: _SafeBool = None
    ForcePKCEForConfidentialClients: _SafeBool = None
    CustomizationRoles: _SafeStrList = None
    CustomizationNamespace: _SafeStr = None
    AuthenticateClass: _SafeStr = None
    SessionClass: _SafeStr = None
    ValidateUserClass: _SafeStr = None
    GenerateTokenClass: _SafeStr = None
    RevokeTokenClass: _SafeStr = None
    ServerCredentials: _SafeStr = None
    SigningAlgorithm: _SafeStr = None
    EncryptionAlgorithm: _SafeStr = None
    KeyAlgorithm: _SafeStr = None
    SSLConfiguration: _SafeStr = None
    Metadata: Annotated[OAuth2ServerMetadataView | None, BeforeValidator(_only_dict)] = None


class OAuth2ServerClientEntry(BaseModel):
    """GET /v2/security/oauth2/server/clients (%Admin_OAuth2_Registration:U).
    ClientId is public, not a secret.
    """

    Name: _SafeStr = None
    ClientId: _SafeStr = None
    ClientType: _SafeStr = None
    Description: _SafeStr = None
    RedirectURL: _SafeStrList = None


class OAuth2ServerClientDetail(BaseModel):
    """GET /v2/security/oauth2/server/client?clientId= (no ClientSecret)."""

    Name: _SafeStr = None
    RedirectURL: _SafeStrList = None
    LaunchURL: _SafeStr = None
    DefaultScope: _SafeStr = None
    Description: _SafeStr = None
    ClientType: _SafeStr = None
    ClientCredentials: _SafeStr = None
    Metadata: Annotated[OAuth2ClientMetadataView | None, BeforeValidator(_only_dict)] = None


class OAuth2ClientConfigEntry(BaseModel):
    """GET /v2/security/oauth2/client/client-configurations?serverId=."""

    ApplicationName: _SafeStr = None
    ClientType: _SafeStr = None
    DefaultScope: _SafeStr = None


class OAuth2ServerDefinitionEntry(BaseModel):
    """GET /v2/security/oauth2/client/server-definitions (%Admin_OAuth2_Client:U)."""

    ID: _SafeStr = None
    IssuerEndpoint: _SafeStr = None
    ClientCount: _SafeInt = None
    ResourceCount: _SafeInt = None


class OAuth2ServerDefinitionDetail(BaseModel):
    """GET /v2/security/oauth2/client/server-definition?serverId= (without the
    write-only InitialAccessToken).
    """

    IssuerEndpoint: _SafeStr = None
    SSLConfiguration: _SafeStr = None
    ServerCredentials: _SafeStr = None
    Metadata: Annotated[OAuth2ServerMetadataView | None, BeforeValidator(_only_dict)] = None


class OAuth2ClientConfigDetail(BaseModel):
    """GET /v2/security/oauth2/client/client-configuration?applicationName=
    (no ClientSecret / ClientPassword)."""

    OAuth2ServerDefinition: _SafeStr = None
    Enabled: _SafeBool = None
    Description: _SafeStr = None
    ClientType: _SafeStr = None
    SSLConfiguration: _SafeStr = None
    RedirectionEndpoint: _SafeStr = None
    DefaultScope: _SafeStr = None
    JWTAudience: _SafeStr = None
    ClientCredentials: _SafeStr = None
    Metadata: Annotated[OAuth2ClientMetadataView | None, BeforeValidator(_only_dict)] = None


class OAuth2ResourceServerEntry(BaseModel):
    """GET /v2/security/oauth2/resource-servers (%Admin_Secure:U)."""

    Name: _SafeStr = None
    ServerDefinition: _SafeStr = None


class OAuth2ResourceServerDetail(BaseModel):
    """GET /v2/security/oauth2/resource-server?name= (no client secret; the
    undocumented `Authenticator` object is skipped).
    """

    Enabled: _SafeBool = None
    Description: _SafeStr = None
    IssuerEndpoint: _SafeStr = None
    ScopeRequiredToConnect: _SafeStr = None
    Audiences: _SafeStrList = None
    AccessTokenIsJWT: _SafeBool = None
    AlwaysCallIntrospection: _SafeBool = None
    ClientId: _SafeStr = None
    IntrospectionAuthMethod: _SafeStr = None
    UseOIDC: _SafeBool = None


class OAuth2ResourceMappingEntry(BaseModel):
    """GET /v2/security/oauth2/resource-server/mappings?service=."""

    Service: _SafeStr = None
    Key: _SafeStr = None
    Resource: _SafeStr = None


# GET /api/iris/security/oauth/overview (our own). Each part is None if
# its call failed (with a warning). `ServerConfigured` is False on IRIS's
# "not configured" 404 and None on any other failure.


class OAuth2ServerDefinitionOverview(OAuth2ServerDefinitionEntry):
    ClientConfigurations: list[OAuth2ClientConfigEntry] | None


class OAuth2Overview(BaseModel):
    ServerConfigured: bool | None
    Server: OAuth2ServerConfigView | None
    ServerClients: list[OAuth2ServerClientEntry] | None
    ServerDefinitions: list[OAuth2ServerDefinitionOverview] | None
    ResourceServers: list[OAuth2ResourceServerEntry] | None
    ResourceMappings: list[OAuth2ResourceMappingEntry] | None


# --- GET /v2/monitor/dashboard/main (%Admin_Operate:U) ---
# Feeds the Dashboard's health, resources, alerts and license panels.
# LicenseUse/LicenseUseHigh are percentages or "" with no license limit.
# SystemMonitor false means the values aren't being updated. Performance
# counters other than GlobalRefsPerSecond/CacheEfficiency are totals since
# startup. BusyProcesses' Process can be "" or a PID. ---


class DashboardPerformance(BaseModel):
    GlobalRefsPerSecond: int
    GlobalRefs: int
    GlobalSetKill: int
    RoutineRefs: int
    LogicalRequests: int
    DiskReads: int
    DiskWrites: int
    CacheEfficiency: float


class DashboardECP(BaseModel):
    ECPClients: str
    ECPClientTraffic: int
    ECPServers: str
    ECPServerTraffic: int
    ShadowConnections: str
    Shadows: str


class DashboardStatus(BaseModel):
    UpTime: str
    LastBackup: str
    SystemMonitor: bool


def _blank_or_non_numeric_to_none(value: Any) -> Any:
    """Just after IRIS starts, a busy process can report Commands as "".
    Blank or non-numeric strings become None; everything else is validated
    as usual.
    """
    if isinstance(value, str) and not value.strip().lstrip("+-").isdigit():
        return None
    return value


class DashboardBusyProcess(BaseModel):
    Process: int | str
    Commands: Annotated[int | None, BeforeValidator(_blank_or_non_numeric_to_none)]


class DashboardSystemUsage(BaseModel):
    DatabaseSpace: str
    DatabaseJournal: str
    JournalSpace: str
    JournalEntries: int
    LockTable: str
    WriteDaemon: str
    Processes: int
    CSPSessions: int
    BusyProcesses: list[DashboardBusyProcess]


class DashboardAlerts(BaseModel):
    SeriousAlerts: int
    ApplicationErrors: int


class DashboardLicensing(BaseModel):
    LicenseLimit: int
    LicenseUse: int | str
    LicenseUseHigh: int | str


class DashboardUpcomingTask(BaseModel):
    Task: str
    Time: str
    Status: str


class MonitorDashboard(BaseModel):
    Performance: DashboardPerformance
    ECP: DashboardECP
    Status: DashboardStatus
    SystemUsage: DashboardSystemUsage
    Alerts: DashboardAlerts
    Licensing: DashboardLicensing
    UpcomingTasks: list[DashboardUpcomingTask]


# --- GET /v2/database-dirs ---
# Sizes of all local databases in one call (Dashboard storage panel), so
# we don't need a database-dir/info task per database. Size is MB,
# MaxSize is "Unlimited" or a number. Encryption fields are skipped. ---


class DatabaseStorageEntry(BaseModel):
    Directory: str
    Size: int
    MaxSize: int | str
    Status: str
    Mirrored: bool
    Encrypted: bool


class ClassAccessEntry(BaseModel):
    Name: str
    AllowType: str
    Class: str
    AllowAccess: bool
    System: bool


# --- GET /v2/journal/settings ---


class JournalSettings(BaseModel):
    AlternateDirectory: str
    ArchiveName: str
    BackupsBeforePurge: int
    CurrentDirectory: str
    DaysBeforePurge: int
    FileSizeLimit: int
    FreezeOnError: bool
    JournalFilePrefix: str
    JournalcspSession: bool
    PurgeArchived: bool
    CompressFiles: bool
    wijdir: str
    targwijsz: int


# --- GET /v2/security/audit/enabled ---


class AuditEnabledResult(BaseModel):
    Enabled: bool


# --- POST /v2/security/audit/records (async task) ---


class AuditRecordEntry(BaseModel):
    SystemID: str
    AuditIndex: int
    TimeStamp: str
    EventSource: str
    EventType: str
    Event: str
    Pid: int
    SessionID: str
    Username: str
    Description: str
    UTCTimeStamp: str
    JobNumber: int
    Authentication: str
    ClientExecutableName: str
    ClientIPAddress: str
    EventData: str
    Namespace: str
    Roles: str
    RoutineSpec: str
    UserInfo: str
    JobId: int
    Status: str
    OSUsername: str
    StartupClientIPAddress: str


# --- Endpoints we've only seen return empty lists ---
# GET /v2/fs-access-purposes, oauth2/client/server-definitions,
# oauth2/server/clients, /v2/wallet/collections. `result` is list[Any]
# until we see real entries.

# --- GET /v2/security/oauth2/server ---
# We've only seen its "not configured" 404, so `result` is
# dict[str, Any].
