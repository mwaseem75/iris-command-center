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
    throw new ApiError("Could not reach the Command Center backend.", { path });
  }

  if (!response.ok) {
    throw new ApiError(`Backend returned HTTP ${response.status} for ${path}.`, {
      status: response.status,
      path,
    });
  }

  return response.json();
}

export const IrisApi = {
  getInfo: () => fetchIris("/api/iris/info"),
  getNamespaces: () => fetchIris("/api/iris/namespaces"),
  getDatabases: () => fetchIris("/api/iris/databases"),
  getProcesses: () => fetchIris("/api/iris/processes"),
  getWebApps: () => fetchIris("/api/iris/web-apps"),
  getTasks: () => fetchIris("/api/iris/tasks"),
  getOauth2Server: () => fetchIris("/api/iris/security/oauth2/server"),
  getOauth2ClientServerDefinitions: () =>
    fetchIris("/api/iris/security/oauth2/client/server-definitions"),
  getOauth2ServerClients: () => fetchIris("/api/iris/security/oauth2/server/clients"),
  getJournalSettings: () => fetchIris("/api/iris/journal/settings"),
  getOperations: () => fetchIris("/api/iris/operations"),
  // Unlike every other IrisApi method, the response here is the Command
  // Center's own { reply, intent } shape (backend/app/models/schemas.py's
  // AssistantQueryResponse) — not an IRISEnvelope — because this endpoint
  // never returns raw IRIS data, only a natural-language summary of it.
  queryAssistant: (message) =>
    fetchIris(`/api/iris/assistant/query?message=${encodeURIComponent(message)}`),
};

export { ApiError, API_BASE_URL };
