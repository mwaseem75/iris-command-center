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
import { countBy, renderDonut, renderStackedBar, topCategories } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  connectionStatus: document.getElementById("connection-status"),
  connectionStatusLabel: document.getElementById("connection-status-label"),
  headerVersion: document.getElementById("header-version-meta"),
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
  databasesViz: document.getElementById("stat-databases-viz"),
  processesViz: document.getElementById("stat-processes-viz"),
  webAppsViz: document.getElementById("stat-web-apps-viz"),
  tasksViz: document.getElementById("stat-tasks-viz"),
  operationsViz: document.getElementById("dashboard-operations-viz"),
  operationsEmpty: document.getElementById("dashboard-operations-empty"),
  operationsSummary: document.getElementById("dashboard-operations-summary"),
  tracesViz: document.getElementById("dashboard-traces-viz"),
  tracesEmpty: document.getElementById("dashboard-traces-empty"),
  tracesSummary: document.getElementById("dashboard-traces-summary"),
  capabilitiesViz: document.getElementById("dashboard-capabilities-viz"),
  capabilitiesEmpty: document.getElementById("dashboard-capabilities-empty"),
  capabilitiesSummary: document.getElementById("dashboard-capabilities-summary"),
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

/** Micro-bars beneath a stat card's big number — each is a REAL category
 * breakdown computed from the SAME already-fetched response array that
 * card's own count already came from (no extra network call this adds).
 * Renders nothing (leaves the slot empty) on failure or an empty list,
 * rather than drawing a placeholder shape for data that doesn't exist. */
function renderDatabasesViz(result) {
  if (result.status !== "fulfilled" || !Array.isArray(result.value.result)) return;
  const entries = topCategories(countBy(result.value.result, (db) => db.Status || "Unknown"), 5);
  renderStackedBar(dom.databasesViz, entries, { compact: true });
}

function renderProcessesViz(result) {
  if (result.status !== "fulfilled" || !Array.isArray(result.value.result)) return;
  const entries = topCategories(countBy(result.value.result, (p) => p.State || "Unknown"), 5);
  renderStackedBar(dom.processesViz, entries, { compact: true });
}

function renderWebAppsViz(result) {
  if (result.status !== "fulfilled" || !Array.isArray(result.value.result)) return;
  const entries = countBy(result.value.result, (app) => (app.Enabled ? "Enabled" : "Disabled"));
  renderStackedBar(dom.webAppsViz, entries, { compact: true });
}

/** Run State split from GET /api/iris/tasks/overview's backend-derived
 * `State` — the same grouping (and "Unknown" for a task whose info could
 * not be read) the Tasks view uses, so the two always agree. Never the task
 * list's own Suspended flag, which was observed reporting false for
 * suspended tasks. */
function renderTasksViz(result) {
  if (result.status !== "fulfilled" || !Array.isArray(result.value.result)) return;
  const entries = countBy(result.value.result, (task) => task.State || "Unknown");
  renderStackedBar(dom.tasksViz, entries, { compact: true });
}

/** The three "Insights" cards — each a donut over data an existing view
 * already exposes in full (Operations, Observability, API Explorer),
 * reused here rather than duplicated: Operations' own risk_level, the
 * execution trace store's own status, and the capability matrix's own
 * verification_status. Two of these three (`operations`, `capabilities`)
 * are new network calls added to loadDashboard()'s Promise.allSettled —
 * both already-existing, already-used-elsewhere GET routes; the third
 * (`executionTraces`) reuses the exact same fetch Recent Activity below
 * already makes. */
function renderOperationsInsight(result) {
  if (result.status !== "fulfilled" || !Array.isArray(result.value.operations)) {
    dom.operationsEmpty.hidden = false;
    dom.operationsSummary.textContent = "";
    return;
  }
  const operations = result.value.operations;
  if (operations.length === 0) {
    dom.operationsEmpty.hidden = false;
    dom.operationsSummary.textContent = "";
    return;
  }
  dom.operationsEmpty.hidden = true;
  const entries = countBy(operations, (op) => op.risk_level || "unknown");
  renderDonut(dom.operationsViz, entries, { size: 62, centerValue: operations.length, centerLabel: "ops" });
  const mutatingCount = operations.filter((op) => op.kind === "mutating").length;
  dom.operationsSummary.textContent =
    `${operations.length} operation${operations.length === 1 ? "" : "s"} registered · ${mutatingCount} mutating`;
}

function renderTracesInsight(result) {
  if (result.status !== "fulfilled" || !Array.isArray(result.value.traces)) {
    dom.tracesEmpty.hidden = false;
    dom.tracesSummary.textContent = "";
    return;
  }
  const traces = result.value.traces;
  if (traces.length === 0) {
    dom.tracesEmpty.hidden = false;
    dom.tracesSummary.textContent = "";
    return;
  }
  dom.tracesEmpty.hidden = true;
  const entries = countBy(traces, (t) => textOrPlaceholder(t.status).replace(/_/g, " "));
  renderDonut(dom.tracesViz, entries, { size: 62, centerValue: traces.length, centerLabel: "traces" });
  dom.tracesSummary.textContent =
    `${traces.length} trace${traces.length === 1 ? "" : "s"} recorded this session`;
}

function renderCapabilitiesInsight(result) {
  if (result.status !== "fulfilled" || !Array.isArray(result.value.capabilities)) {
    dom.capabilitiesEmpty.hidden = false;
    dom.capabilitiesSummary.textContent = "";
    return;
  }
  const capabilities = result.value.capabilities;
  if (capabilities.length === 0) {
    dom.capabilitiesEmpty.hidden = false;
    dom.capabilitiesSummary.textContent = "";
    return;
  }
  dom.capabilitiesEmpty.hidden = true;
  const entries = countBy(capabilities, (c) => c.verification_status || "Unknown");
  renderDonut(dom.capabilitiesViz, entries, { size: 62, centerValue: capabilities.length, centerLabel: "tracked" });
  const availableCount = capabilities.filter((c) => c.available).length;
  dom.capabilitiesSummary.textContent =
    `${capabilities.length} capabilities tracked · ${availableCount} available in this Command Center`;
}

/** IRIS version/build now renders as compact secondary text in the global
 * header (moved out of the Dashboard's old "IRIS Version" KPI card — see
 * `.header-status__version` in styles.css) rather than its own large stat
 * card. Same `GET /api/iris/info` fields as before (serverVersion,
 * product, apiVersion); nothing new is fetched or invented. */
function renderInfoCard(result) {
  if (result.status === "fulfilled") {
    const info = result.value.result;
    dom.headerVersion.textContent =
      `${info.serverVersion || "Unknown"} · ${info.product || "iris"} · API v${info.apiVersion ?? "?"}`;
    setConnectionStatus("connected", `Connected as ${info.username || "unknown user"}`);
  } else {
    dom.headerVersion.textContent = "";
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

  const [info, namespaces, databases, processes, webApps, tasks, executionTraces, operations, capabilities] =
    await Promise.allSettled([
      IrisApi.getInfo(),
      IrisApi.getNamespaces(),
      IrisApi.getDatabases(),
      IrisApi.getProcesses(),
      IrisApi.getWebApps(),
      IrisApi.getTaskOverview(),
      IrisApi.getExecutionTraces(),
      IrisApi.getOperations(),
      IrisApi.getCapabilities(),
    ]);

  renderInfoCard(info);
  renderCountCard("namespaces", namespaces, (body) => body.result.length);
  renderCountCard("databases", databases, (body) => body.result.length);
  renderCountCard("processes", processes, (body) => body.result.length);
  renderCountCard("webApps", webApps, (body) => body.result.length);
  renderCountCard("tasks", tasks, (body) => body.result.length);
  renderDatabasesViz(databases);
  renderProcessesViz(processes);
  renderWebAppsViz(webApps);
  renderTasksViz(tasks);
  renderRecentActivity(executionTraces);
  renderOperationsInsight(operations);
  renderTracesInsight(executionTraces);
  renderCapabilitiesInsight(capabilities);

  const results = {
    info,
    namespaces,
    databases,
    processes,
    webApps,
    tasks,
    executionTraces,
    operations,
    capabilities,
  };
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

  // The five KPI cards (Namespaces/Databases/Processes/Web Applications/
  // Tasks) double as navigation shortcuts to their existing views — same
  // navigateTo() as the quicklink cards above, no separate/duplicate
  // navigation mechanism and no new fetch. Each card's own `data-card`
  // value already matches its target view's `data-view` exactly (e.g.
  // "web-apps"), so no separate lookup table is needed. Keyboard-
  // activatable since these are <article role="button" tabindex="0">
  // elements, not real <button>s — Enter/Space are wired manually to
  // match native button activation.
  dom.statGrid.querySelectorAll(".stat-card--interactive[data-card]").forEach((card) => {
    card.addEventListener("click", () => {
      navigateTo(card.dataset.card);
    });
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      navigateTo(card.dataset.card);
    });
  });
}

// Re-exported only so a future test/module can construct a matching error
// type without importing api.js directly.
export { ApiError };
