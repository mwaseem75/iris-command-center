// Small fetch wrapper for the backend's /api/iris/* routes.
//
// The browser only ever talks to our backend, never to IRIS; the backend
// holds the IRIS session. Most endpoints wrap their data in
// { status, console, result }.

// The backend's default port (see backend/app/config.py). Change it if
// you run the backend somewhere else.
const API_BASE_URL = "http://localhost:8000";

class ApiError extends Error {
  constructor(message, { status = null, path = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.path = path;
  }
}

// Update the header's connection pill on every request. All pages go
// through fetchIris(), so this keeps it right whichever page is open.
// Pages that set a more specific label (e.g. Dashboard's "Connected as X")
// do so after their requests finish, so theirs wins.
function setHeaderConnectionStatus(state, label) {
  const dot = document.getElementById("connection-status");
  const labelEl = document.getElementById("connection-status-label");
  if (!dot || !labelEl) return;
  dot.dataset.state = state;
  labelEl.textContent = label;
}

/**
 * GET an /api/iris/* endpoint and parse it. On failure only a short, safe
 * status message reaches the caller (no headers or response bodies).
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
 * POST /api/iris/journal/purge-archived. Sends PurgeArchived and the
 * user's `confirmed` flag; the backend decides whether it's allowed. There's
 * no force/bypass option. `resolutionIssueType` (optional) only labels the
 * trace as an Issue Resolver resolution; the backend checks it. `dryRun`
 * (optional) asks for the handler's dry run, which only reads the current
 * value and never sends the PUT.
 */
async function postJournalPurgeArchived(purgeArchived, confirmed, resolutionIssueType = null, dryRun = false) {
  const path = "/api/iris/journal/purge-archived";
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        PurgeArchived: purgeArchived,
        confirmed,
        ...(resolutionIssueType ? { resolution_issue_type: resolutionIssueType } : {}),
        ...(dryRun ? { dry_run: true } : {}),
      }),
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
 * POST /api/iris/namespaces (namespace.create). Sends the request fields
 * and `confirmed`; the backend decides whether it's allowed.
 *
 * `dryRun` maps to the route's `dry_run`, used by the wizard's Review step
 * for a preview (nothing is created).
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
 * POST /api/iris/databases (database.create). Sends the request fields and
 * `confirmed`; the backend decides whether it's allowed.
 *
 * `dryRun` maps to the route's `dry_run`, used by the wizard's Review step.
 * Like namespaces, the dry run also needs `confirmed: true` because the
 * executor checks confirmation first. It still never creates anything.
 */
async function postDatabaseCreate(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/databases", fields, confirmed, dryRun);
}

/**
 * database.mount (POST /api/iris/databases/mount). Sends the fields plus `confirmed` and `dry_run`;
 * the backend does the authorization, checks, execution and verification.
 * The dry run only reads the database info.
 */
async function postDatabaseMount(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/databases/mount", fields, confirmed, dryRun);
}

/**
 * database.dismount (POST /api/iris/databases/dismount). Sends {Directory} plus `confirmed` and `dry_run`;
 * the backend does the authorization, checks, execution and verification.
 */
async function postDatabaseDismount(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/databases/dismount", fields, confirmed, dryRun);
}

/**
 * web_app.set_enabled (POST /api/iris/web-apps/set-enabled). Sends {Name, Enabled} plus `confirmed` and `dry_run`;
 * the backend does the authorization, checks, execution and verification.
 */
async function postWebAppSetEnabled(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/web-apps/set-enabled", fields, confirmed, dryRun);
}

/**
 * web_app.update_description (POST /api/iris/web-apps/update-description). Sends {Name, Description} plus `confirmed` and `dry_run`;
 * the backend does the authorization, checks, execution and verification.
 */
async function postWebAppUpdateDescription(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/web-apps/update-description", fields, confirmed, dryRun);
}

/**
 * user.set_enabled (POST /api/iris/security/users/set-enabled). Sends {Name, Enabled} plus `confirmed` and `dry_run`;
 * the backend does the authorization, checks, execution and verification.
 */
async function postUserSetEnabled(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/security/users/set-enabled", fields, confirmed, dryRun);
}

/**
 * task.run_now (POST /api/iris/tasks/run-now). Sends {Id} plus `confirmed` and `dry_run`;
 * the backend does the authorization, checks, execution and verification.
 * No scheduling option.
 */
async function postTaskRunNow(fields, confirmed, dryRun = false) {
  return postDatabaseOperation("/api/iris/tasks/run-now", fields, confirmed, dryRun);
}

/**
 * POST /api/iris/demo/rehearsal (Demo Activity). The body is just
 * { confirmed, scenario }; the backend runs each operation through the
 * normal framework and restores everything. Returns
 * { status, confirmed, detail, steps }. 409 means one is already running.
 */
/**
 * Custom Issue Rules: POST /api/iris/issue-rules (create) and
 * /api/iris/issue-rules/delete. A 4xx is thrown as an ApiError whose message
 * is the backend's explanation (a validation message, a missing privilege, a
 * duplicate name...), so the form can show it. Only field messages are used,
 * never the values sent.
 */
async function postIssueRule(path, body) {
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
    });
  } catch {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError("Could not reach the Command Center backend.", { path });
  }
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && data.detail;
    const message = typeof detail === "string"
      ? detail
      : Array.isArray(detail)
        ? detail.map((item) => item && item.msg).filter(Boolean).join(" ")
        : "";
    throw new ApiError(message || `Backend returned HTTP ${response.status} for ${path}.`, {
      status: response.status,
      path,
    });
  }
  setHeaderConnectionStatus("connected", "Connected to backend");
  return data;
}

async function postDemoRehearsal(confirmed, scenario = "standard") {
  const path = "/api/iris/demo/rehearsal";
  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ confirmed: confirmed === true, scenario }),
    });
  } catch {
    setHeaderConnectionStatus("error", "Could not reach the Command Center backend");
    throw new ApiError("Could not reach the Command Center backend.", { path });
  }

  if (!response.ok) {
    throw new ApiError(`Backend returned HTTP ${response.status} for ${path}.`, {
      status: response.status,
      path,
    });
  }

  setHeaderConnectionStatus("connected", "Connected to backend");
  return response.json();
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
  getHealthReport: () => fetchIris("/api/iris/health"),
  getNamespaces: () => fetchIris("/api/iris/namespaces"),
  getDatabases: () => fetchIris("/api/iris/databases"),
  // Storage info for one database (IRIS runs it as an async task; the
  // backend waits for it). `directory` is sent as the `dir` parameter.
  getDatabaseInfo: (directory) =>
    fetchIris(`/api/iris/databases/info?dir=${encodeURIComponent(directory)}`),
  // Integrity check for one database (also an async task). Unlike
  // getDatabaseInfo(), this returns IRIS's raw task envelope (State,
  // TaskName, Console, FailureReason, Result, Time*), since we've never seen
  // a real Result to unwrap.
  checkDatabaseIntegrity: (directory) =>
    fetchIris(`/api/iris/databases/integrity-check?dir=${encodeURIComponent(directory)}`),
  getProcesses: () => fetchIris("/api/iris/processes"),
  getWebApps: () => fetchIris("/api/iris/web-apps"),
  // Full config of one web app. `name` (e.g. "/api/admin") is a query
  // parameter because names contain slashes.
  getWebAppDetail: (name) =>
    fetchIris(`/api/iris/web-apps/detail?name=${encodeURIComponent(name)}`),
  // REST route map for a REST web app (from IRIS's /api/mgmnt). 404 means
  // there isn't one (not a REST app, or IRIS couldn't build it).
  getWebAppRestEndpoints: (name) =>
    fetchIris(`/api/iris/web-apps/rest-endpoints?name=${encodeURIComponent(name)}`),
  // Active web sessions. The backend removes the session IDs.
  getWebSessions: () => fetchIris("/api/iris/web-sessions"),
  getTasks: () => fetchIris("/api/iris/tasks"),
  // IRIS system dashboard: performance, health, alerts, licensing.
  getMonitorDashboard: () => fetchIris("/api/iris/monitor/dashboard"),
  // Size of every local database in one call.
  getDatabaseStorage: () => fetchIris("/api/iris/databases/storage"),
  // Every task with its /v2/task/info and a derived State. The list's
  // Suspended flag is left out because it's unreliable.
  getTaskOverview: () => fetchIris("/api/iris/tasks/overview"),
  // One task's full config, with sensitive Settings redacted by the backend.
  getTaskDetail: (id) => fetchIris(`/api/iris/tasks/detail?id=${encodeURIComponent(id)}`),
  getTaskManager: () => fetchIris("/api/iris/tasks/manager"),
  // Identity & Access. The backend removes personal fields from user details;
  // nothing here returns a password, hash or secret.
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
  // Authentication. web-auth comes without SMTPUsername.
  getSecurityServices: () => fetchIris("/api/iris/security/services"),
  getSecurityServiceDetail: (name) =>
    fetchIris(`/api/iris/security/services/detail?name=${encodeURIComponent(name)}`),
  getSecurityWebAuth: () => fetchIris("/api/iris/security/web-auth"),
  getSecuritySuperservers: () => fetchIris("/api/iris/security/superservers"),
  getSecurityClassAccess: () => fetchIris("/api/iris/security/class-access"),
  // Wallet metadata: collections and their secrets' names and types, no values.
  getSecurityWalletOverview: () => fetchIris("/api/iris/security/wallet/overview"),
  getSecurityWalletCollectionDetail: (name) =>
    fetchIris(`/api/iris/security/wallet/collections/detail?name=${encodeURIComponent(name)}`),
  getSecurityWalletSecrets: (collection) =>
    fetchIris(`/api/iris/security/wallet/secrets?collection=${encodeURIComponent(collection)}`),
  // X.509 credential and certificate metadata, no keys or key passwords.
  getSecurityX509Overview: () => fetchIris("/api/iris/security/x509/overview"),
  getSecurityX509CredentialDetail: (alias) =>
    fetchIris(`/api/iris/security/x509/credentials/detail?alias=${encodeURIComponent(alias)}`),
  getSecurityX509Certificate: (alias) =>
    fetchIris(`/api/iris/security/x509/credentials/certificate?alias=${encodeURIComponent(alias)}`),
  // OAuth 2.0: one overview plus details, with safe fields only (no secrets
  // or tokens).
  getSecurityOAuthOverview: () => fetchIris("/api/iris/security/oauth/overview"),
  getSecurityOAuthServerClient: (clientId) =>
    fetchIris(`/api/iris/security/oauth/server-clients/detail?clientId=${encodeURIComponent(clientId)}`),
  getSecurityOAuthServerDefinition: (serverId) =>
    fetchIris(`/api/iris/security/oauth/server-definitions/detail?serverId=${encodeURIComponent(serverId)}`),
  getSecurityOAuthClientConfiguration: (applicationName) =>
    fetchIris(
      `/api/iris/security/oauth/client-configurations/detail?applicationName=${encodeURIComponent(applicationName)}`,
    ),
  getSecurityOAuthResourceServer: (name) =>
    fetchIris(`/api/iris/security/oauth/resource-servers/detail?name=${encodeURIComponent(name)}`),
  getExtLangServers: () => fetchIris("/api/iris/ext-lang-servers"),
  getFsAccessPurposes: () => fetchIris("/api/iris/fs-access-purposes"),
  getWalletCollections: () => fetchIris("/api/iris/wallet/collections"),
  getAuditEnabled: () => fetchIris("/api/iris/security/audit/enabled"),
  // `filters` holds the optional query parameters (beginDateTime,
  // endDateTime, eventTypes, usernames, ascending, jsonSearch, ...). Empty
  // values are left out, so IRIS returns everything by default.
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
  // Our own PythonDiagnostics shape (not an IRISEnvelope): host values from
  // Embedded Python inside IRIS. Missing values are null and listed in
  // `unavailable`.
  getPythonDiagnostics: () => fetchIris("/api/iris/python/diagnostics"),
  // The newest entries of IRIS's messages.log (read-only, no parameters).
  getMessagesLog: () => fetchIris("/api/iris/messages-log"),
  // { issues: [...] } from our own issue check.
  getIssues: () => fetchIris("/api/iris/issues"),
  // { query, results: [{ source, title, body, score }] }: stored documents
  // ranked by IRIS Vector Search. 503 when ENABLE_KNOWLEDGE_SEARCH is off.
  searchKnowledge: (query) => fetchIris(`/api/iris/knowledge/search?q=${encodeURIComponent(query)}`),
  // Returns our own { reply, intent } shape, not an IRISEnvelope.
  queryAssistant: (message) =>
    fetchIris(`/api/iris/assistant/query?message=${encodeURIComponent(message)}`),
  // Returns an OperationResult (backend/app/execution/models.py).
  executeJournalPurgeArchived: (purgeArchived, confirmed, resolutionIssueType = null, dryRun = false) =>
    postJournalPurgeArchived(purgeArchived, confirmed, resolutionIssueType, dryRun),
  // Returns an OperationResult. Pass dryRun=true for a preview.
  createNamespace: (fields, confirmed, dryRun = false) =>
    postNamespaceCreate(fields, confirmed, dryRun),
  // Returns an OperationResult. Pass dryRun=true for a preview.
  createDatabase: (fields, confirmed, dryRun = false) =>
    postDatabaseCreate(fields, confirmed, dryRun),
  // Same, for POST /api/iris/databases/mount.
  mountDatabase: (fields, confirmed, dryRun = false) =>
    postDatabaseMount(fields, confirmed, dryRun),
  dismountDatabase: (fields, confirmed, dryRun = false) =>
    postDatabaseDismount(fields, confirmed, dryRun),
  setWebAppEnabled: (fields, confirmed, dryRun = false) =>
    postWebAppSetEnabled(fields, confirmed, dryRun),
  updateWebAppDescription: (fields, confirmed, dryRun = false) =>
    postWebAppUpdateDescription(fields, confirmed, dryRun),
  setUserEnabled: (fields, confirmed, dryRun = false) =>
    postUserSetEnabled(fields, confirmed, dryRun),
  runTaskNow: (fields, confirmed, dryRun = false) => postTaskRunNow(fields, confirmed, dryRun),
  // Demo Activity rehearsal, only called from demo-activity.js's Confirm
  // button. scenario: "standard" (default) or "issue_resolution" (IPM).
  runDemoRehearsal: (confirmed, scenario = "standard") => postDemoRehearsal(confirmed, scenario),
  // Our own execution traces (no IRIS call).
  getExecutionTraces: () => fetchIris("/api/iris/observability/traces"),
  // Custom Issue Rules (detection-only). Deleting is only called from the
  // Issue Resolver's inline "Confirm delete" button, so it sends confirmed=true.
  getIssueRules: () => fetchIris("/api/iris/issue-rules"),
  createIssueRule: (rule) => postIssueRule("/api/iris/issue-rules", rule),
  deleteIssueRule: (name) => postIssueRule("/api/iris/issue-rules/delete", { name, confirmed: true }),
  // Our own capability registry (no IRIS call); `available` says whether
  // the route exists.
  getCapabilities: () => fetchIris("/api/iris/capabilities"),
};

export { ApiError, API_BASE_URL };
