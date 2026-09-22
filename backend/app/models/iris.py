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
