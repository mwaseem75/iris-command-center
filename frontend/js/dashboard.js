// Dashboard view: the main landing screen. Fetches read-only IRIS data via
// IrisApi and renders it — System Health (IRIS version + resource counts,
// the original Step 1 content), Recent Activity (the backend's own
// in-memory execution traces, the same data Observability shows in full),
// and Explore (static quicklink cards that navigate to other already-built
// views via nav.js's navigateTo() — no data fetch of their own). Rendering
// is kept separate from fetching (api.js) so each can change independently.
//
// No new backend endpoint or IRIS call was added for this: Recent Activity
// reuses IrisApi.getExecutionTraces() (already used by observability.js),
// and Explore reuses navigation only.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  connectionStatus: document.getElementById("connection-status"),
  connectionStatusLabel: document.getElementById("connection-status-label"),
  loadingState: document.getElementById("loading-state"),
  errorBanner: document.getElementById("error-banner"),
  errorBannerText: document.getElementById("error-banner-text"),
  statGrid: document.getElementById("stat-grid"),
  lastUpdated: document.getElementById("last-updated"),
  refreshButton: document.getElementById("refresh-button"),
  activityEmpty: document.getElementById("dashboard-activity-empty"),
  activityTableWrapper: document.getElementById("dashboard-activity-table-wrapper"),
  activityTableBody: document.getElementById("dashboard-activity-table-body"),
  viewObservabilityButton: document.getElementById("dashboard-view-observability-button"),
  quicklinks: document.getElementById("dashboard-quicklinks"),
};

// How many of the most recent execution traces to show — this is a
// landing-page glance, not the full list (Observability already shows
// every trace). The backend already returns traces newest-first (see
// backend/app/observability/store.py's record_trace), so this is a plain
// slice, never a re-sort.
const RECENT_ACTIVITY_LIMIT = 5;

const STAT_CARDS = {
  namespaces: { valueEl: "stat-namespaces", cardSelector: '[data-card="namespaces"]' },
  databases: { valueEl: "stat-databases", cardSelector: '[data-card="databases"]' },
  processes: { valueEl: "stat-processes", cardSelector: '[data-card="processes"]' },
  webApps: { valueEl: "stat-web-apps", cardSelector: '[data-card="web-apps"]' },
  tasks: { valueEl: "stat-tasks", cardSelector: '[data-card="tasks"]' },
};

function setConnectionStatus(state, label) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
}

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  dom.statGrid.style.opacity = isLoading ? "0.5" : "1";
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

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatDuration(ms) {
  if (typeof ms !== "number") return PLACEHOLDER;
  if (ms < 1000) return `${ms.toFixed(2)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatTimestamp(iso) {
  if (typeof iso !== "string" || !iso) return PLACEHOLDER;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

// Same badge convention already used by observability.js's own execution
// traces table — duplicated here (not imported) so this view stays
// self-contained, the same convention every other view file already
// follows (see e.g. investigation.js/capabilities.js's own small helpers).
const STATUS_BADGE_CLASS = {
  success: "status-badge--ok",
  ok: "status-badge--ok",
  dry_run: "status-badge--neutral",
  skipped: "status-badge--neutral",
  not_applicable: "status-badge--neutral",
  confirmation_required: "status-badge--warning",
  required_not_received: "status-badge--warning",
};

function statusBadgeClass(status) {
  if (typeof status !== "string") return "status-badge--neutral";
  return STATUS_BADGE_CLASS[status] || "status-badge--error";
}

function makeStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${statusBadgeClass(status)}`;
  badge.textContent = textOrPlaceholder(status).replace(/_/g, " ");
  return badge;
}

function makeCell(content) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  if (content instanceof Node) {
    cell.append(content);
  } else {
    cell.textContent = content;
    cell.title = content;
  }
  return cell;
}

/** Renders up to RECENT_ACTIVITY_LIMIT execution traces. `result` is a
 * fulfilled/rejected Promise.allSettled entry — a failure here shows the
 * same empty state as "no traces yet" rather than a scary error, since
 * this is a landing-page glance and Observability already surfaces real
 * failures in full. */
function renderRecentActivity(result) {
  dom.activityTableBody.replaceChildren();

  const traces =
    result.status === "fulfilled" && Array.isArray(result.value.traces)
      ? result.value.traces
      : [];

  if (traces.length === 0) {
    dom.activityTableWrapper.hidden = true;
    dom.activityEmpty.hidden = false;
    return;
  }

  dom.activityEmpty.hidden = true;
  dom.activityTableWrapper.hidden = false;

  for (const trace of traces.slice(0, RECENT_ACTIVITY_LIMIT)) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(trace.operation_name)),
      makeCell(makeStatusBadge(trace.status)),
      makeCell(formatDuration(trace.duration_ms)),
      makeCell(formatTimestamp(trace.start_time)),
    );
    dom.activityTableBody.append(row);
  }
}

/** result is a fulfilled/rejected entry from Promise.allSettled. `extract`
 * pulls the count (or value) out of a successful envelope. Renders a plain
 * unavailable state on failure rather than propagating the error into the
 * DOM — one failed card never blocks the others from rendering. */
function renderCountCard(key, result, extract) {
  const { valueEl, cardSelector } = STAT_CARDS[key];
  const valueNode = document.getElementById(valueEl);
  const cardNode = dom.statGrid.querySelector(cardSelector);

  if (result.status === "fulfilled") {
    valueNode.textContent = String(extract(result.value));
    valueNode.classList.remove("stat-card__value--unavailable");
    cardNode.classList.remove("stat-card--error");
  } else {
    valueNode.textContent = "Unavailable";
    valueNode.classList.add("stat-card__value--unavailable");
    cardNode.classList.add("stat-card--error");
  }
}

function renderInfoCard(result) {
  const versionNode = document.getElementById("stat-version");
  const versionMetaNode = document.getElementById("stat-version-meta");

  if (result.status === "fulfilled") {
    const info = result.value.result;
    // Response shape verified against the backend's InfoResult model —
    // apiVersion, serverVersion, product are the fields it actually returns.
    versionNode.textContent = info.serverVersion || "Unknown";
    versionMetaNode.textContent = `${info.product || "iris"} • API v${info.apiVersion ?? "?"}`;
    versionNode.classList.remove("stat-card__value--unavailable");
    setConnectionStatus("connected", `Connected as ${info.username || "unknown user"}`);
  } else {
    versionNode.textContent = "Unavailable";
    versionNode.classList.add("stat-card__value--unavailable");
    versionMetaNode.textContent = "";
    setConnectionStatus("error", "Could not reach IRIS");
  }
}

function describeFailures(results) {
  const failures = Object.entries(results).filter(([, r]) => r.status === "rejected");
  if (failures.length === 0) return null;

  // Deliberately generic/non-alarming: never surface raw error objects,
  // status codes tied to auth, or anything resembling a header/token.
  if (failures.length === Object.keys(results).length) {
    return "Could not load dashboard data right now. The Command Center backend may be unreachable.";
  }
  return `Some dashboard data could not be loaded (${failures.length} of ${Object.keys(results).length} sections). The rest is shown below.`;
}

/**
 * Fetches all dashboard data and renders it. Uses Promise.allSettled so one
 * failing endpoint never prevents the others from displaying — required by
 * this step's "handle partial API failures gracefully".
 */
export async function loadDashboard() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionStatus("checking", "Checking connection…");

  const [info, namespaces, databases, processes, webApps, tasks, executionTraces] =
    await Promise.allSettled([
      IrisApi.getInfo(),
      IrisApi.getNamespaces(),
      IrisApi.getDatabases(),
      IrisApi.getProcesses(),
      IrisApi.getWebApps(),
      IrisApi.getTasks(),
      IrisApi.getExecutionTraces(),
    ]);

  renderInfoCard(info);
  renderCountCard("namespaces", namespaces, (body) => body.result.length);
  renderCountCard("databases", databases, (body) => body.result.length);
  renderCountCard("processes", processes, (body) => body.result.length);
  renderCountCard("webApps", webApps, (body) => body.result.length);
  renderCountCard("tasks", tasks, (body) => body.result.length);
  renderRecentActivity(executionTraces);

  const results = { info, namespaces, databases, processes, webApps, tasks, executionTraces };
  setErrorBanner(describeFailures(results));

  dom.lastUpdated.textContent = `Last updated ${new Date().toLocaleTimeString()}`;
  setLoading(false);
}

export function initDashboardControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadDashboard();
  });

  dom.viewObservabilityButton.addEventListener("click", () => {
    navigateTo("observability");
  });

  // Each quicklink card just navigates — none fetches or renders anything
  // of its own; the target view's own normal view-opened load (see app.js)
  // does that, exactly as if the operator had clicked its sidebar item.
  dom.quicklinks.querySelectorAll("[data-quicklink]").forEach((button) => {
    button.addEventListener("click", () => {
      navigateTo(button.dataset.quicklink);
    });
  });
}

// Re-exported only so a future test/module can construct a matching error
// type without importing api.js directly.
export { ApiError };
