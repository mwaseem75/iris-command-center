// Thin fetch layer for the Command Center backend's /api/iris/* routes.
// This module ONLY talks to our own backend, never to IRIS directly — the
// backend holds the IRIS session/JWT; the browser never sees it.
//
// Response shapes here match backend/app/models/iris.py exactly (verified
// against the actual backend, not guessed) — every endpoint wraps its
// payload in { status, console, result }. See docs/api-capability-matrix.md
// for how those shapes were originally verified against IRIS itself.

// Matches the backend's default app_port (see backend/app/config.py).
// Adjust this if the backend is run on a different host/port.
const API_BASE_URL = "http://localhost:8000";

class ApiError extends Error {
  constructor(message, { status = null, path = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

// The header's connection pill (index.html's #connection-status) is shell
// chrome shared by every view, but only Dashboard used to keep it updated —
// so it went stale (frozen at Dashboard's last state) the moment the
// operator navigated anywhere else. Every view already funnels its IRIS
// reads through this one fetchIris() function, so updating the header pill
// here — the single real choke point — keeps it honest for whichever view
// is actually active, without any per-view module needing to know about it.
// A richer, view-specific label (e.g. Dashboard's own "Connected as X")
// set right after its own batch of requests settles simply overwrites this
// generic one, since that happens strictly after these per-request updates.
function setHeaderConnectionStatus(state, label) {
  const dot = document.getElementById("connection-status");
  const labelEl = document.getElementById("connection-status-label");
  if (!dot || !labelEl) return;
  dot.dataset.state = state;
  labelEl.textContent = label;
}

/**
 * Fetch and parse a GET /api/iris/* endpoint. Never logs or includes
 * headers, credentials, or response bodies from failed requests — only a
 * short, safe status summary reaches the caller.
 */
async function fetchIris(path) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
    });
  } catch {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError("Could not reach the Command Center backend.", { path });
  }

  if (!response.ok) {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError(`Backend returned HTTP ${response.status} for ${path}.`, {
      status: response.status,
      path,
    });
  }

  setHeaderConnectionStatus("connected", "Connected to backend");
  return response.json();
}

/**
 * POST /api/iris/journal/purge-archived — the app's ONLY mutating request,
 * and the sole reason this file has a second fetch helper at all. It never
 * duplicates the backend's authorization/confirmation logic: this function
 * only forwards exactly what the caller decided (PurgeArchived + an
 * explicit, user-driven `confirmed` flag) to the existing, already-tested
 * route (backend/app/routes/journal.py), which alone decides whether
 * anything is authorized to happen. There is no "force"/"bypass" field
 * here — nothing this function accepts can skip that route's own checks.
 */
async function postJournalPurgeArchived(purgeArchived, confirmed) {
  const path = "/api/iris/journal/purge-archived";
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ PurgeArchived: purgeArchived, confirmed }),
    });
  } catch {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError("Could not reach the Command Center backend.", { path });
  }

  if (!response.ok) {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError(`Backend returned HTTP ${response.status} for ${path}.`, {
      status: response.status,
      path,
    });
  }

  setHeaderConnectionStatus("connected", "Connected to backend");
  return response.json();
}

/**
 * POST /api/iris/namespaces — this project's second mutating request,
 * alongside postJournalPurgeArchived above (namespace.create, backend/app/
 * routes/namespaces.py). Same discipline: forwards exactly what the
 * caller decided (the five request fields plus an explicit, user-driven
 * `confirmed` flag) to the existing, already-tested route, which alone
 * decides whether anything is authorized to happen. No "force"/"bypass"
 * field here either.
 *
 * `dryRun` forwards the route's own `dry_run` field (already supported by
 * NamespaceCreateOperationRequest/NamespaceCreateHandler.dry_run() — never
 * calls put()/post_async_task(), so it can never mutate IRIS) — used by
 * the "New Namespace" wizard's Review step to get a real, server-
 * validated preview before the operator's explicit confirmation triggers
 * an actual (dryRun=false) execution.
 */
async function postNamespaceCreate(fields, confirmed, dryRun = false) {
  const path = "/api/iris/namespaces";
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ...fields, confirmed, dry_run: dryRun }),
    });
  } catch {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError("Could not reach the Command Center backend.", { path });
  }

  if (!response.ok) {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError(`Backend returned HTTP ${response.status} for ${path}.`, {
      status: response.status,
      path,
    });
  }

  setHeaderConnectionStatus("connected", "Connected to backend");
  return response.json();
}

/**
 * POST /api/iris/databases — this project's third mutating request,
 * alongside postJournalPurgeArchived and postNamespaceCreate above
 * (database.create, backend/app/routes/databases.py). Same discipline:
 * forwards exactly what the caller decided (the request's own fields plus
 * an explicit, user-driven `confirmed` flag) to the existing,
 * already-tested route, which alone decides whether anything is
 * authorized to happen. No "force"/"bypass" field here either.
 *
 * `dryRun` forwards the route's own `dry_run` field (already supported by
 * DatabaseCreateOperationRequest/DatabaseCreateHandler.dry_run() — never
 * calls post(), so it can never mutate IRIS) — used by the "New Database"
 * wizard's Review step to get a real, server-validated preview before the
 * operator's explicit confirmation triggers an actual (dryRun=false)
 * execution. Note: DatabaseCreateHandler's dry-run branch, like
 * NamespaceCreateHandler's, is only reached once `confirmed: true` is
 * also sent — see namespaces.js's module docstring for why (the
 * executor's confirmation gate runs before the dry_run branch); the
 * dry-run call itself still never mutates IRIS regardless.
 */
async function postDatabaseCreate(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/databases", fields, confirmed, dryRun);
}

/**
 * database.mount (POST /api/iris/databases/mount,
 * backend/app/routes/databases.py) — same request/response discipline as
 * postDatabaseCreate: forwards the operator's fields plus explicit
 * `confirmed`/`dry_run` flags; the backend alone authorizes. Dry-run
 * (DatabaseMountHandler.dry_run()) only reads IRIS's database info and
 * never sends the mount request.
 */
async function postDatabaseMount(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/databases/mount", fields, confirmed, dryRun);
}

/**
 * POST /api/iris/web-apps/set-enabled — web_app.set_enabled
 * (backend/app/routes/web_apps.py). Same body convention and helper as the
 * database operations: only the caller's fields plus an explicit
 * `confirmed` flag and `dry_run`; the backend alone authorizes (Manage,
 * plus IRIS's own Secure), hard-denies protected apps, executes, and
 * verifies. No force/bypass field exists.
 */
async function postWebAppSetEnabled(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/web-apps/set-enabled", fields, confirmed, dryRun);
}

async function postDatabaseOperation(path, fields, confirmed, dryRun) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ ...fields, confirmed, dry_run: dryRun }),
    });
  } catch {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError("Could not reach the Command Center backend.", { path });
  }

  if (!response.ok) {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError(`Backend returned HTTP ${response.status} for ${path}.`, {
      status: response.status,
      path,
    });
  }

  setHeaderConnectionStatus("connected", "Connected to backend");
  return response.json();
}

export const IrisApi = {
  getInfo: () => fetchIris("/api/iris/info"),
  getNamespaces: () => fetchIris("/api/iris/namespaces"),
  getDatabases: () => fetchIris("/api/iris/databases"),
  // Read-only — backed by IRIS's own async-task POST /v2/database-dir/info
  // (the backend waits for that task to finish; see
  // backend/app/routes/iris.py's get_database_info), the same pattern
  // getAuditRecords() already uses. `directory` is the database's real
  // Directory field, sent verbatim as the `dir` query parameter.
  getDatabaseInfo: (directory) =>
    fetchIris(`/api/iris/databases/info?dir=${encodeURIComponent(directory)}`),
  // Read-only — backed by IRIS's own async-task POST /v2/database-dir/
  // integrity-check (see backend/app/routes/iris.py's
  // get_database_integrity_check), the same async-task pattern
  // getDatabaseInfo()/getAuditRecords() already use. `directory` is the
  // database's real Directory field, sent verbatim as the `dir` query
  // parameter. Unlike getDatabaseInfo(), the response is NOT an
  // IRISEnvelope — it's IRIS's own raw async-task envelope (State,
  // TaskName, Console, FailureReason, Result, Time*), since this
  // operation's actual outcome/Result shape has never been observed
  // against a real IRIS instance (see that route's own docstring) and
  // this project never invents a shape to unwrap it into.
  checkDatabaseIntegrity: (directory) =>
    fetchIris(`/api/iris/databases/integrity-check?dir=${encodeURIComponent(directory)}`),
  getProcesses: () => fetchIris("/api/iris/processes"),
  getWebApps: () => fetchIris("/api/iris/web-apps"),
  // Read-only — full configuration of one web app via GET /v2/web-app
  // (see backend/app/routes/iris.py's get_web_app_detail). `name` is the
  // app's real Name (e.g. "/api/admin"), sent verbatim as the `name` query
  // parameter — a query parameter because names contain slashes.
  getWebAppDetail: (name) =>
    fetchIris(`/api/iris/web-apps/detail?name=${encodeURIComponent(name)}`),
  // Read-only — the REST route map IRIS generates for a REST web app, via
  // IRIS's API Management API (see backend/app/routes/iris.py's
  // get_web_app_rest_endpoints). HTTP 404 means IRIS has no route map for
  // this app (not a REST app, or IRIS could not generate one).
  getWebAppRestEndpoints: (name) =>
    fetchIris(`/api/iris/web-apps/rest-endpoints?name=${encodeURIComponent(name)}`),
  // Read-only — active web sessions (GET /v2/web-sessions). The backend
  // strips each session's IRIS ID before responding, so it never reaches
  // the browser (see backend/app/routes/iris.py's get_web_sessions).
  getWebSessions: () => fetchIris("/api/iris/web-sessions"),
  getTasks: () => fetchIris("/api/iris/tasks"),
  // Read-only — every task merged with its GET /v2/task/info and a derived
  // State (see backend/app/routes/iris.py's get_tasks_overview). The list's
  // own Suspended flag is not included; it was observed to be wrong.
  getTaskOverview: () => fetchIris("/api/iris/tasks/overview"),
  // Read-only — one task's full configuration; the backend redacts
  // sensitive Settings values before responding.
  getTaskDetail: (id) => fetchIris(`/api/iris/tasks/detail?id=${encodeURIComponent(id)}`),
  getTaskManager: () => fetchIris("/api/iris/tasks/manager"),
  // Read-only Identity & Access (backend/app/routes/security_access.py).
  // User detail arrives with personal fields already withheld by the
  // backend; no endpoint here returns a password, hash or secret.
  getSecurityUsers: () => fetchIris("/api/iris/security/users"),
  getSecurityUserDetail: (name) =>
    fetchIris(`/api/iris/security/users/detail?name=${encodeURIComponent(name)}`),
  getSecurityRoles: () => fetchIris("/api/iris/security/roles"),
  getSecurityRoleDetail: (name) =>
    fetchIris(`/api/iris/security/roles/detail?name=${encodeURIComponent(name)}`),
  getSecurityRoleOwners: (name) =>
    fetchIris(`/api/iris/security/roles/owners?name=${encodeURIComponent(name)}`),
  getSecurityRoleAccessMap: () => fetchIris("/api/iris/security/roles/access-map"),
  getSecurityResources: () => fetchIris("/api/iris/security/resources"),
  getSecurityResourceDetail: (name) =>
    fetchIris(`/api/iris/security/resources/detail?name=${encodeURIComponent(name)}`),
  // Read-only Authentication Posture (same backend module). web-auth
  // arrives with SMTPUsername already withheld by the backend.
  getSecurityServices: () => fetchIris("/api/iris/security/services"),
  getSecurityServiceDetail: (name) =>
    fetchIris(`/api/iris/security/services/detail?name=${encodeURIComponent(name)}`),
  getSecurityWebAuth: () => fetchIris("/api/iris/security/web-auth"),
  getSecuritySuperservers: () => fetchIris("/api/iris/security/superservers"),
  getSecurityClassAccess: () => fetchIris("/api/iris/security/class-access"),
  // Read-only Wallet METADATA (same backend module): collections with their
  // secrets' names and types. No endpoint returns a secret value.
  getSecurityWalletOverview: () => fetchIris("/api/iris/security/wallet/overview"),
  getSecurityWalletCollectionDetail: (name) =>
    fetchIris(`/api/iris/security/wallet/collections/detail?name=${encodeURIComponent(name)}`),
  getSecurityWalletSecrets: (collection) =>
    fetchIris(`/api/iris/security/wallet/secrets?collection=${encodeURIComponent(collection)}`),
  getOauth2Server: () => fetchIris("/api/iris/security/oauth2/server"),
  getOauth2ClientServerDefinitions: () =>
    fetchIris("/api/iris/security/oauth2/client/server-definitions"),
  getOauth2ServerClients: () => fetchIris("/api/iris/security/oauth2/server/clients"),
  getExtLangServers: () => fetchIris("/api/iris/ext-lang-servers"),
  getFsAccessPurposes: () => fetchIris("/api/iris/fs-access-purposes"),
  getWalletCollections: () => fetchIris("/api/iris/wallet/collections"),
  getAuditEnabled: () => fetchIris("/api/iris/security/audit/enabled"),
  // `filters` is a plain object of the backend's own documented, optional
  // query parameters (beginDateTime, endDateTime, eventTypes, usernames,
  // ascending, jsonSearch, ...) — see backend/app/routes/iris.py's
  // get_audit_records. Empty/undefined values are omitted entirely rather
  // than sent as empty strings, so an unfilled filter behaves exactly like
  // never having been supplied (IRIS's own "list everything" default).
  getAuditRecords: (filters = {}) => {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== "") {
        params.set(key, value);
      }
    }
    const queryString = params.toString();
    return fetchIris(`/api/iris/security/audit/records${queryString ? `?${queryString}` : ""}`);
  },
  getJournalSettings: () => fetchIris("/api/iris/journal/settings"),
  getOperations: () => fetchIris("/api/iris/operations"),
  // Unlike every other IrisApi method, the response here is the Command
  // Center's own { reply, intent } shape (backend/app/models/schemas.py's
  // AssistantQueryResponse) — not an IRISEnvelope — because this endpoint
  // never returns raw IRIS data, only a natural-language summary of it.
  queryAssistant: (message) =>
    fetchIris(`/api/iris/assistant/query?message=${encodeURIComponent(message)}`),
  // The response is a plain OperationResult (backend/app/execution/models.py)
  // — not an IRISEnvelope — the same structured shape
  // POST /api/iris/journal/purge-archived has always returned.
  executeJournalPurgeArchived: (purgeArchived, confirmed) =>
    postJournalPurgeArchived(purgeArchived, confirmed),
  // The response is a plain OperationResult, the same structured shape as
  // executeJournalPurgeArchived above — POST /api/iris/namespaces
  // (backend/app/routes/namespaces.py) has always returned it. Pass
  // dryRun=true for a real, non-mutating server-validated preview.
  createNamespace: (fields, confirmed, dryRun = false) =>
    postNamespaceCreate(fields, confirmed, dryRun),
  // The response is a plain OperationResult, the same structured shape as
  // createNamespace above — POST /api/iris/databases
  // (backend/app/routes/databases.py) has always returned it. Pass
  // dryRun=true for a real, non-mutating server-validated preview.
  createDatabase: (fields, confirmed, dryRun = false) =>
    postDatabaseCreate(fields, confirmed, dryRun),
  // Same OperationResult shape — POST /api/iris/databases/mount. Pass
  // dryRun=true for a real, non-mutating server-validated preview.
  mountDatabase: (fields, confirmed, dryRun = false) =>
    postDatabaseMount(fields, confirmed, dryRun),
  setWebAppEnabled: (fields, confirmed, dryRun = false) =>
    postWebAppSetEnabled(fields, confirmed, dryRun),
  // Read-only — this endpoint makes no IRIS call itself; it only reads the
  // backend's in-memory execution trace store (backend/app/observability/).
  getExecutionTraces: () => fetchIris("/api/iris/observability/traces"),
  // Read-only — this endpoint makes no IRIS call itself either; it serves
  // the backend's own project-maintained capability registry
  // (backend/app/capabilities.py), with `available` computed against this
  // backend's own currently-registered routes.
  getCapabilities: () => fetchIris("/api/iris/capabilities"),
};

export { ApiError, API_BASE_URL };
