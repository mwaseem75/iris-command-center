// Security view: fetches the three existing read-only OAuth2 endpoints
// ONLY (GET /api/iris/security/oauth2/server,
// GET /api/iris/security/oauth2/client/server-definitions,
// GET /api/iris/security/oauth2/server/clients) and renders them. No other
// endpoint is called from this module, and no mutating HTTP method is used
// anywhere in it.
//
// The backend's own models (backend/app/models/iris.py) type these results
// as dict[str, Any] / list[Any] because no populated response shape has
// ever been observed against a real IRIS instance (see
// docs/api-capability-matrix.md) — this view renders whatever fields IRIS
// actually returns, discovered at runtime, rather than inventing a fixed
// shape.
//
// The backend's GET /security/oauth2/server route treats IRIS's documented
// 404 "OAuth 2.0 server is not configured" response as a normal, successful
// read (HTTP 200, with the real status/result body IRIS sent) — this view
// renders that as an informational "not configured" state, not an error.

import { IrisApi } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("security-loading-state"),
  errorBanner: document.getElementById("security-error-banner"),
  errorBannerText: document.getElementById("security-error-banner-text"),
  refreshButton: document.getElementById("security-refresh-button"),
  connectionStatus: document.getElementById("security-connection-status"),
  connectionStatusLabel: document.getElementById("security-connection-status-label"),
  connectionDetail: document.getElementById("security-connection-detail"),
  oauthServerList: document.getElementById("security-oauth2-server-list"),
  oauthServerEmpty: document.getElementById("security-oauth2-server-empty"),
  oauthServerStatusLine: document.getElementById("security-oauth2-server-status-line"),
  clientDefsWrapper: document.getElementById("security-client-defs-table-wrapper"),
  clientDefsThead: document.getElementById("security-client-defs-thead"),
  clientDefsBody: document.getElementById("security-client-defs-table-body"),
  clientDefsEmpty: document.getElementById("security-client-defs-empty"),
  serverClientsWrapper: document.getElementById("security-server-clients-table-wrapper"),
  serverClientsThead: document.getElementById("security-server-clients-thead"),
  serverClientsBody: document.getElementById("security-server-clients-table-body"),
  serverClientsEmpty: document.getElementById("security-server-clients-empty"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in the other views.
  dom.refreshButton.disabled = isLoading;
  dom.refreshButton.classList.toggle("btn--spinning", isLoading);
}

function setErrorBanner(message) {
  if (!message) {
    dom.errorBanner.hidden = true;
    return;
  }
  dom.errorBannerText.textContent = message;
  dom.errorBanner.hidden = false;
}

function setConnectionState(state, label, detail) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
  dom.connectionDetail.textContent = detail || "";
}

function formatValue(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

// Cells/rows are always built via document.createElement + .textContent —
// never innerHTML — so a config value containing HTML-special characters
// can never be interpreted as markup.
function makeCell(text) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

// A single, unambiguous status badge (reusing the same component every
// other view uses) for whether this instance is configured as an OAuth2
// Authorization Server at all — the one real, binary fact this card's
// data actually supports; purely a visual addition to the existing
// object-shaped rendering below it.
function setOauthServerStatusBadge(configured) {
  dom.oauthServerStatusLine.replaceChildren();
  if (configured === null) return;
  const badge = document.createElement("span");
  badge.className = `status-badge ${configured ? "status-badge--ok" : "status-badge--neutral"}`;
  badge.textContent = configured ? "Configured" : "Not configured";
  dom.oauthServerStatusLine.append(badge);
}

function renderOauthServer(settled) {
  dom.oauthServerList.replaceChildren();

  if (settled.status !== "fulfilled") {
    dom.oauthServerEmpty.textContent = "Could not load OAuth 2.0 server configuration.";
    dom.oauthServerEmpty.hidden = false;
    setOauthServerStatusBadge(null);
    return;
  }

  const response = settled.value;
  const data =
    response && response.result && typeof response.result === "object" ? response.result : {};
  const errors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];
  const entries = Object.entries(data);

  if (entries.length === 0) {
    // IRIS's documented 404 for "not configured" arrives here as a normal
    // successful envelope with an empty result and a descriptive error
    // entry (see backend/app/routes/iris.py) — shown as information, not
    // as the page's error banner.
    const message =
      errors.length > 0 && errors[0] && errors[0].error
        ? errors[0].error
        : "OAuth 2.0 server is not configured on this instance.";
    dom.oauthServerEmpty.textContent = message;
    dom.oauthServerEmpty.hidden = false;
    setOauthServerStatusBadge(false);
    return;
  }

  dom.oauthServerEmpty.hidden = true;
  setOauthServerStatusBadge(true);
  entries.sort(([a], [b]) => a.localeCompare(b));
  for (const [key, value] of entries) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = key;

    const dd = document.createElement("dd");
    dd.className = "info-list__value info-list__value--mono";
    dd.textContent = formatValue(value);

    row.append(dt, dd);
    dom.oauthServerList.append(row);
  }
}

// Column names are discovered at runtime from the entries IRIS actually
// returns (see module header) — never a hardcoded/invented list.
function renderOauthList(settled, { wrapper, thead, body, empty, notLoadedMessage, emptyMessage }) {
  body.replaceChildren();
  thead.replaceChildren();

  if (settled.status !== "fulfilled") {
    wrapper.hidden = true;
    empty.textContent = notLoadedMessage;
    empty.hidden = false;
    return;
  }

  const items =
    settled.value && Array.isArray(settled.value.result) ? settled.value.result : [];

  if (items.length === 0) {
    wrapper.hidden = true;
    empty.textContent = emptyMessage;
    empty.hidden = false;
    return;
  }

  empty.hidden = true;
  wrapper.hidden = false;

  const columns = Object.keys(items[0]);
  const headRow = document.createElement("tr");
  for (const column of columns) {
    const th = document.createElement("th");
    th.setAttribute("scope", "col");
    th.textContent = column;
    headRow.append(th);
  }
  thead.append(headRow);

  for (const item of items) {
    const row = document.createElement("tr");
    for (const column of columns) {
      row.append(makeCell(formatValue(item[column])));
    }
    body.append(row);
  }
}

function describeFailures(results) {
  const entries = Object.values(results);
  const failures = entries.filter((r) => r.status === "rejected");
  if (failures.length === 0) return null;
  if (failures.length === entries.length) {
    return "Could not load security data right now. The Command Center backend may be unreachable.";
  }
  return `Some security data could not be loaded (${failures.length} of ${entries.length} sections). The rest is shown below.`;
}

/**
 * Fetches all three OAuth2 endpoints and renders them. These are the ONLY
 * network calls this module makes — no mutating request exists anywhere in
 * this file. Uses Promise.allSettled so one failing endpoint never blocks
 * the others from rendering, the same pattern used in dashboard.js.
 */
export async function loadSecurity() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  const [oauthServer, clientDefs, serverClients] = await Promise.allSettled([
    IrisApi.getOauth2Server(),
    IrisApi.getOauth2ClientServerDefinitions(),
    IrisApi.getOauth2ServerClients(),
  ]);

  renderOauthServer(oauthServer);
  renderOauthList(clientDefs, {
    wrapper: dom.clientDefsWrapper,
    thead: dom.clientDefsThead,
    body: dom.clientDefsBody,
    empty: dom.clientDefsEmpty,
    notLoadedMessage: "Could not load client server definitions.",
    emptyMessage: "No client server definitions reported.",
  });
  renderOauthList(serverClients, {
    wrapper: dom.serverClientsWrapper,
    thead: dom.serverClientsThead,
    body: dom.serverClientsBody,
    empty: dom.serverClientsEmpty,
    notLoadedMessage: "Could not load registered clients.",
    emptyMessage: "No registered clients reported.",
  });

  const results = { oauthServer, clientDefs, serverClients };
  setErrorBanner(describeFailures(results));

  const settledList = Object.values(results);
  const allFailed = settledList.every((r) => r.status === "rejected");
  const anyFailed = settledList.some((r) => r.status === "rejected");
  if (allFailed) {
    setConnectionState("error", "Could not reach IRIS", "");
  } else if (anyFailed) {
    setConnectionState("degraded", "Connected (with warnings)", "");
  } else {
    setConnectionState("connected", "Connected", "");
  }

  setLoading(false);
}

export function initSecurityControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadSecurity();
  });
}
