"""Pydantic models for IRIS SysAdmin REST API responses.

These model the response shapes as actually VERIFIED against a real running
IRIS 2026.2 instance (see docs/api-capability-matrix.md), not as guessed from
mainspec_v2.json alone. Where the spec and the observed response disagree,
the model follows the observed response, and the discrepancy is noted below.

Several of the Step 3 endpoints (fs-access-purposes, the OAuth2 client/server
list endpoints, wallet collections) were only ever observed returning an
EMPTY result on this instance — no populated entry was ever seen, so no
entry shape is modeled for them; `result` is typed permissively
(`list[Any]`) rather than inventing fields. Likewise, GET
/v2/security/oauth2/server was only ever observed returning its documented
404 "not configured" case, never a real success body, so its `result` is
typed as a permissive `dict[str, Any]` rather than a guessed schema.

Known, deliberate divergence from mainspec_v2.json's schemas:
  - The spec's `LoginResponse`/`Info` schemas describe some fields as flat
    (no wrapper) or unwrapped; the actually observed response for every
    endpoint wired up so far (/info, /v2/namespaces, /v2/databases,
    /v2/processes) wraps its payload in {"status": ..., "console": ...,
    "result": ...}. That wrapper is modeled here as `IRISEnvelope`.
  - The spec's `BaseResponse` schema (used elsewhere in the spec) declares
    `status.Errors` (capitalized) as an array of strings. Every response
    observed for these four endpoints had an EMPTY errors array, so the
    element type was never actually confirmed for them — `errors` is
    modeled permissively (`list[Any]`) rather than assuming either shape.
    The lowercase key `errors` (not `Errors`) is what was actually observed.
  - `console` was always an empty array in every observed response for
    these endpoints; also modeled permissively for the same reason.
  - `Info.privileges` is modeled as a dict of privilege name -> {"use": bool}
    rather than fixed named fields, because the exact set of keys present
    depends on which privileges the authenticated account holds (only
    observed for `_SYSTEM`, which holds nearly all of them) — see
    docs/api-capability-matrix.md's note that `ConfigStore` was absent
    from the response even though the spec's schema lists it.
"""

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

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


# --- POST /v2/database-dir/info (async-task-backed; see
#     app/iris_client/client.py's post_async_task/wait_for_async_task) —
#     "View a variety of non-configurable info, such as block size and
#     available free space" per mainspec_v2.json's own summary, which
#     documents no result schema at all. All 19 fields below were directly
#     observed, populated, in a real response from icc-iris-dev (database
#     USER) — nothing here is guessed from the spec alone. Unlike
#     DatabaseEntry above, there is no Name/Directory/Status field — the
#     caller already knows the Directory it queried (it's the request's own
#     `dir` parameter), and this endpoint reports storage facts, not
#     identity/mount-summary ones.


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


# --- POST /v2/database-dir/integrity-check (async-task-backed; see
#     app/iris_client/client.py's post_async_task/wait_for_async_task) —
#     "Run an integrity check on a local database" per mainspec_v2.json's
#     own summary. UNLIKE DatabaseInfoResult above, this operation has
#     deliberately NEVER been executed against a real IRIS instance (an
#     integrity check is a real, resource-intensive scan of live data, not
#     a quick metadata read — executing one was explicitly out of scope
#     for this implementation pass). mainspec_v2.json documents no result
#     schema for it either. `Result` below is therefore typed as `Any`
#     rather than guessed — the same permissive-typing discipline this
#     module's own docstring already establishes for endpoints whose
#     populated shape has never been observed (see fs-access-purposes/
#     OAuth2/wallet-collections above). Every OTHER field below (State,
#     TaskName, Console, FailureReason, TimeQueued/TimeStarted/
#     TimeFinished) is NOT guessed — it is IRIS's own generic async-task
#     envelope, already independently confirmed live, populated, more than
#     once (POST /v2/security/audit/records, POST /v2/database-dir/info —
#     see AuditRecordEntry and DatabaseInfoResult above); only the
#     `Result` payload's own internal shape is specific to this one
#     endpoint and unconfirmed.


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


# --- GET /v2/web-app?name=<Name> — "View details of a web application"
#     per mainspec_v2.json. The spec says these fields mirror the class
#     Security.Applications. All 46 fields below were directly observed,
#     with these exact types, in real responses for all 22 web apps on
#     icc-iris-dev. Two discrepancies from the spec were observed and are
#     modelled as observed, not as documented:
#       - the spec lists `Type` (integer bitmap), but the live response
#         omits it entirely, so it is NOT a field here (the list endpoint's
#         string `Type` on WebAppEntry is the only Type we have);
#       - the spec documents `WSGIType` as an integer, but it is returned
#         as a string (e.g. "WSGI").


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


# --- GET /v2/web-sessions — "View a list of web sessions" per
#     mainspec_v2.json (field types only; the spec gives no descriptions).
#     Observed live on icc-iris-dev with the same types: Timeout is a
#     "YYYY-MM-DD HH:MM:SS" timestamp string, SesProcessId a string (""
#     when no process is currently serving the session), and LicenseId
#     "<username>@<client address>".
#
#     The IRIS `ID` field is deliberately NOT modelled: it is the CSP
#     session identifier — the value DELETE /v2/web-session?id= takes to
#     end a session — so it must never leave this backend. Pydantic drops
#     unmodelled fields during validation, so `ID` can't reach a response.


class WebSessionEntry(BaseModel):
    Username: str
    Preserve: int
    Application: str
    Timeout: str
    LicenseId: str
    SesProcessId: str
    AllowEndSession: bool


# --- GET /api/mgmnt/v1/{namespace}/spec{webApplication} — IRIS's API
#     Management API (not part of mainspec_v2.json) generates a Swagger 2.0
#     document from a REST web app's dispatch-class route map. Observed
#     against all 9 REST apps on icc-iris-dev: every operation has
#     operationId + x-ISC_ServiceMethod (the dispatch-class method that
#     implements the route); summary/description/parameters are optional;
#     parameters are {name, in, required, type?, description?, pattern?,
#     schema?} or a {"$ref": "#/parameters/<name>"} to the spec's own
#     top-level `parameters` (resolved by the route — an unresolvable $ref
#     is kept as `ref` rather than guessed). The generated `responses` are
#     always the same two placeholders ("(Expected Result)"/"(Unexpected
#     Error)"), so they carry no information and are not modelled.
#     RestEndpoint/RestRouteMap are this backend's flattened view of that
#     document — every value is copied from it, nothing is derived except
#     the upper-casing of the HTTP method key.


class RestEndpointParameter(BaseModel):
    name: str | None = None
    location: str | None = None  # Swagger's `in`
    required: bool | None = None
    type: str | None = None
    description: str | None = None
    pattern: str | None = None
    bodySchema: dict[str, Any] | None = None  # Swagger's `schema` (body parameters)
    ref: str | None = None  # an unresolvable "$ref", kept verbatim


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


# --- GET /v2/task/info?id=<Id> — mainspec_v2.json's TaskExtraInfo. All 8
#     fields observed live, with these types, for every task on
#     icc-iris-dev. `Status` is a string ("1"); the spec documents "-1" as
#     "the job is currently running" and -2..-5 as error codes whose text is
#     in `Error`. `Suspended` here is the reliable flag: the list endpoint
#     reported `false` for two tasks whose %SYS.Task.Suspended was 2, while
#     this endpoint (and /v2/task/upcoming) reported `true`. ---


class TaskInfo(BaseModel):
    Type: str
    Status: str
    Error: str
    LastSchedule: str
    LastStarted: str
    LastFinished: str
    NextScheduled: str
    Suspended: bool


# --- GET /api/iris/tasks/overview — this backend's own merge of
#     GET /v2/tasks with GET /v2/task/info for each task. The list's own
#     `Suspended` is deliberately NOT carried over (see TaskInfo above).
#     `Info` is None, and `State` with it, when that task's info call
#     failed; `State` is derived from Info only (see routes/iris.py's
#     _task_state). `NextScheduled` is the list's raw string — observed as
#     a "YYYY-MM-DD HH:MM:SS" datetime, "" (on-demand tasks) or free text
#     such as "Runs After #1:00" — and is never parsed here. ---


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


# --- GET /v2/task?id=<Id> — mainspec_v2.json's Task schema. Every field
#     was present, with no extras, for all 7 tasks read on icc-iris-dev.
#     Where the observed type differs from the spec it is modelled as
#     observed: TimePeriodEvery/TimePeriodDay came back as integers or ""
#     (spec: string), ExpiresDays/Hours/Minutes as "" (spec: integer), so
#     these — and DailyIncrement, the same kind of "" -or-count field — are
#     `int | str` and passed through unchanged.
#
#     `Settings` is TaskClass-specific and can hold credentials (Diagnostic
#     Report's includes SMTPPass). routes/iris.py redacts sensitive keys
#     before this model is returned: their values become None and their
#     key paths are listed in `RedactedSettings`, which is this backend's
#     own field, not IRIS's. ---


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


# --- GET /v2/task/manager — observed live as {"Status": "Running"}; the
#     spec's enum is "Running" / "Not running" / "Suspended". ---


class TaskManagerStatus(BaseModel):
    Status: str


# --- Security: Identity & Access (GET /v2/security/users|user|roles|role|
#     role/owners|resources|resource). Every field below was observed live
#     on icc-iris-dev, with these types, for all 9 users, all 38 roles and
#     the resources read; see routes/security_access.py for the routes. ---


class SecurityUserEntry(BaseModel):
    Name: str
    FullName: str
    Enabled: bool
    Type: str
    Namespace: str
    Routine: str


# GET /v2/security/user also returns EmailAddress, PhoneNumber,
# PhoneProvider and a free-text Comment. They may hold personal data and are
# deliberately NOT modelled,
# so validation drops them and no response ever carries them; the route
# lists which of them IRIS sent in `WithheldFields` (this backend's own
# field). The model is an allowlist: any field IRIS adds later is dropped
# the same way. No password or hash field exists in IRIS's response.
# `AutheEnabled` is the spec's two-factor bitmask (2**20 SMS, 2**21 TOTP).


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


# `AdminOption` is documented as boolean but observed as the string "0" on
# "User" and "Role" rows and as `false` on "User (escalation)" rows — both
# are passed through unchanged.


class RoleOwnerEntry(BaseModel):
    Name: str
    Type: str
    AdminOption: bool | str


# GET /api/iris/security/roles/access-map — this backend's merge of the
# role list with each role's GET /v2/security/role detail. `Listed` is False
# for a role that exists (its detail returned 200) but that GET
# /v2/security/roles does not list — observed for %SQLTuneTable. `Detail`
# is None when that role's detail call failed.


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


# --- Security: Authentication Posture. All shapes observed live on
#     icc-iris-dev (15 services, 1 superserver, 10 class-access entries). ---

# GET /v2/security/services. The spec types `Enabled` as a string and lists
# an `EnabledBoolean`; live, `Enabled` is a boolean and `EnabledBoolean` is
# absent, so the model follows the live response. AllowedConnections empty
# means "no restrictions" (spec). AuthenticationMethods omits AutheSystem
# (bit 10), which the detail's AutheEnabled bitmask does include.


class SecurityServiceEntry(BaseModel):
    Name: str
    Enabled: bool
    Public: str
    AuthenticationMethods: list[str]
    AllowedConnections: list[str]
    Description: str
    HttpOnlyCookies: bool
    TwoFactorEnabled: bool


# GET /v2/security/service?name= — AutheEnabled is the spec-documented
# bitmask (Bit 0 AutheK5CCache … Bit 25 MutualTLS).


class SecurityServiceDetail(BaseModel):
    AutheEnabled: int
    ClientSystems: list[str]
    Description: str
    Enabled: bool


# GET /v2/security/web-auth — system-wide authentication settings. The
# response's SMTPUsername (a mail-server credential identifier) and
# TwoFactorFrom (the two-factor sender email address) are deliberately NOT
# modelled (the route lists them in `WithheldFields`, this backend's own
# field); no SMTP password is ever returned by IRIS. The model
# is an allowlist, so any field IRIS adds later is dropped too.


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


# GET /v2/security/superserver?port=&bindAddress= (the list's own key
# fields). SSLSupportLevel: 0 = None, 1 = Accept, 2 = Require (spec).


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


# GET /api/iris/security/superservers — GET /v2/security/superservers merged
# with each entry's detail; `Detail` is None when that detail call failed.


class SuperserverEntry(BaseModel):
    Port: int
    BindAddress: str
    Enabled: bool
    SystemDefault: bool
    Detail: SuperserverDetail | None


# GET /v2/web-app/pct-accesses — which % classes each web application (or
# "all-applications") may use.


# --- Security: Wallet (GET /v2/wallet/collections|collection|secrets, all
#     %Admin_Wallet:U). icc-iris-dev has NO wallet collections (live list is
#     [], SQL %Wallet.Collection has 0 rows), so no populated response has
#     been observed: these shapes follow mainspec_v2.json (WalletCollection,
#     WalletCollectionList, WalletSecretList). The permission fields are
#     optional so a populated response missing one shows "not reported"
#     instead of failing; Name is required.
#
#     These models are strict allowlists of METADATA ONLY. IRIS has no GET
#     that returns a secret's value (GET /v2/wallet/secrets is documented as
#     "names and types of secrets"; /v2/wallet/secret is PUT/DELETE only and
#     its schema is writeOnly). Any other field IRIS might send — e.g. a
#     `Secret` or `WalletSecretConfig` — is dropped by validation and can
#     never reach a response. ---


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


# GET /api/iris/security/wallet/overview — every collection merged with its
# secrets' names and types. `Secrets` is None when that collection's secret
# list could not be read.


class WalletCollectionOverview(BaseModel):
    Name: str
    EditResource: str | None = None
    UseResource: str | None = None
    Secrets: list[WalletSecretEntry] | None


# --- Security: X.509 credentials (GET /v2/security/x509-credentials |
#     x509-credential | x509-credential/certificate, all %Admin_Secure:U,
#     keyed by IRIS's own `alias` query parameter). icc-iris-dev has NO X.509
#     credentials (live list is [], SQL %SYS.X509Credentials has 0 rows;
#     unknown alias → 404 ERROR #914), so no populated response has been
#     observed: these shapes follow mainspec_v2.json (X509CredentialsList,
#     X509Credential, X509CredentialCertificate), with every field except
#     Alias optional so a populated response missing one shows "not
#     reported" instead of failing.
#
#     Strict allowlists of certificate METADATA. `HasPrivateKey` is only a
#     boolean (the spec: "Returns if a private key is present"). Private key
#     material, PrivateKeyPassword, PrivateKeyFile/CertificateFile and PEM
#     contents are write-body-only in the spec (POST x509-credential) and are
#     not modelled — any such field IRIS might send is dropped. ---


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


# GET /api/iris/security/x509/overview — every credential merged with its
# certificate's metadata; `Certificate` is None when that call failed.


class X509CredentialOverview(X509CredentialEntry):
    Certificate: X509CertificateInfo | None


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


# --- POST /v2/security/audit/records (async-task-backed; see
#     app/iris_client/client.py's post_async_task/wait_for_async_task and
#     docs/api-capability-matrix.md). All 24 fields below were directly
#     observed, populated, in real audit records returned by icc-iris-dev —
#     nothing here is guessed from the spec alone. ---


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


# --- Endpoints whose result entry shape has never been observed populated:
#     GET /v2/fs-access-purposes, GET /v2/security/oauth2/client/server-definitions,
#     GET /v2/security/oauth2/server/clients, GET /v2/wallet/collections.
#     `result` is `list[Any]` for these — see module docstring. No dedicated
#     entry model is defined, since defining one would mean inventing fields
#     that have never actually been observed. ---

# --- GET /v2/security/oauth2/server: only ever observed returning its
#     documented 404 "not configured" case — no success body has ever been
#     observed, so `result` is `dict[str, Any]` rather than a guessed schema.
#     See module docstring. ---
