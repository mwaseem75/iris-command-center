// Dashboard view: the main landing screen — a live view of the connected
// IRIS instance built only from real, read-only data:
//   - KPI row: counts from the existing list routes, plus Uptime and License
//     Use from IRIS's own System Dashboard.
//   - System Health, Recent Alerts and the Resources trends: GET
//     /api/iris/monitor/dashboard (IRIS's GET /v2/monitor/dashboard/main).
//   - Database Storage: GET /api/iris/databases/storage (/v2/database-dirs),
//     named via the existing database list.
//   - Process Distribution: the existing GET /api/iris/processes.
//   - Recent Operations: the backend's own execution traces plus the
//     operations registry (both existing routes).
//   - Quick Access: static navigation, plus the capability matrix summary.
//
// Live refresh: every REFRESH_INTERVAL_MS while the Dashboard view is shown
// AND the browser tab is visible (paused otherwise, resumed on return). The
// fast panels refresh every tick; the heavier sources (counts, storage,
// tasks, registry, capabilities) every SLOW_EVERY_TICKS ticks. Refreshes are
// chained with setTimeout, so two never overlap.
//
// Resource trends come from up to MAX_SAMPLES real samples taken by this page
// — nothing is interpolated. Disk read/write rates are deltas of IRIS's
// cumulative counters between two real samples; a negative delta (counters
// reset, e.g. IRIS restarted) is skipped, not charted. Nothing here is
// invented: missing or failed data is shown as unavailable.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { countBy, renderDonut, renderStackedBar, topCategories } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention
const REFRESH_INTERVAL_MS = 15000;
const SLOW_EVERY_TICKS = 4;
const MAX_SAMPLES = 60;
const RECENT_ACTIVITY_LIMIT = 5;
const SVG_NS = "http://www.w3.org/2000/svg";

const $ = (id) => document.getElementById(id);

const dom = {
  view: $("view-dashboard"),
  connectionStatus: $("connection-status"),
  connectionStatusLabel: $("connection-status-label"),
  headerVersion: $("header-version-meta"),
  loadingState: $("loading-state"),
  errorBanner: $("error-banner"),
  errorBannerText: $("error-banner-text"),
  statGrid: $("stat-grid"),
  refreshButton: $("refresh-button"),
  liveStatus: $("dashboard-live-status"),
  liveLabel: $("dashboard-live-label"),
  uptime: $("stat-uptime"),
  license: $("stat-license"),
  licenseMeta: $("stat-license-meta"),
  monitorWarning: $("dashboard-monitor-warning"),
  healthEmpty: $("dashboard-health-empty"),
  healthIndicators: $("dashboard-health-indicators"),
  healthFacts: $("dashboard-health-facts"),
  resourcesEmpty: $("dashboard-resources-empty"),
  resources: $("dashboard-resources"),
  storageEmpty: $("dashboard-storage-empty"),
  storage: $("dashboard-storage"),
  storageHint: $("dashboard-storage-hint"),
  alertsEmpty: $("dashboard-alerts-empty"),
  alertCounts: $("dashboard-alert-counts"),
  alertList: $("dashboard-alert-list"),
  processEmpty: $("dashboard-process-empty"),
  processState: $("dashboard-process-state"),
  processNamespace: $("dashboard-process-namespace"),
  processBusy: $("dashboard-process-busy"),
  activityEmpty: $("dashboard-activity-empty"),
  activityTableWrapper: $("dashboard-activity-table-wrapper"),
  activityTableBody: $("dashboard-activity-table-body"),
  operationsSummary: $("dashboard-operations-summary"),
  viewObservabilityButton: $("dashboard-view-observability-button"),
  quicklinks: $("dashboard-quicklinks"),
  capabilitiesSummary: $("dashboard-capabilities-summary"),
  databasesViz: $("stat-databases-viz"),
  processesViz: $("stat-processes-viz"),
  webAppsViz: $("stat-web-apps-viz"),
  tasksViz: $("stat-tasks-viz"),
};

const STAT_CARDS = {
  namespaces: { valueEl: "stat-namespaces", cardSelector: '[data-card="namespaces"]' },
  databases: { valueEl: "stat-databases", cardSelector: '[data-card="databases"]' },
  processes: { valueEl: "stat-processes", cardSelector: '[data-card="processes"]' },
  webApps: { valueEl: "stat-web-apps", cardSelector: '[data-card="web-apps"]' },
  tasks: { valueEl: "stat-tasks", cardSelector: '[data-card="tasks"]' },
};

// IRIS System Dashboard indicators: [label, section, field]. Each is a
// status string IRIS reports ("Normal" when healthy).
const HEALTH_INDICATORS = [
  ["Database Space", "SystemUsage", "DatabaseSpace"],
  ["Database Journal", "SystemUsage", "DatabaseJournal"],
  ["Journal Space", "SystemUsage", "JournalSpace"],
  ["Lock Table", "SystemUsage", "LockTable"],
  ["Write Daemon", "SystemUsage", "WriteDaemon"],
  ["ECP Clients", "ECP", "ECPClients"],
  ["ECP Servers", "ECP", "ECPServers"],
  ["Shadow Connections", "ECP", "ShadowConnections"],
  ["Shadows", "ECP", "Shadows"],
];

// Resource trend series: [label, unit, sample → value (number or null)].
const RESOURCE_SERIES = [
  ["Global references / s", "", (s) => s.globalRefsPerSecond],
  ["Cache efficiency", "", (s) => s.cacheEfficiency],
  ["Disk reads / s", "", (s) => s.diskReadsPerSecond],
  ["Disk writes / s", "", (s) => s.diskWritesPerSecond],
  ["Processes (IRIS monitor)", "", (s) => s.processes],
  ["Web sessions", "", (s) => s.cspSessions],
];

let samples = []; // real samples, oldest first, at most MAX_SAMPLES
let tickCount = 0;
let timer = null;
let refreshing = false;
let lastSuccess = null; // Date of the last refresh with no failures
let lastRefreshFailed = false;
let databaseNames = new Map(); // Directory → Name, from the last database list
let loadedOnce = false;

// --- small helpers ---

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

function formatNumber(value, digits = 0) {
  if (typeof value !== "number" || !Number.isFinite(value)) return PLACEHOLDER;
  return value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

function formatMB(mb) {
  if (typeof mb !== "number") return PLACEHOLDER;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${formatNumber(mb)} MB`;
}

function fulfilled(result) {
  return result && result.status === "fulfilled" ? result.value : null;
}

function makeBadge(text, variant) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = text;
  return badge;
}

function makeInfoRow(label, value, { mono = false, title = "" } = {}) {
  const row = document.createElement("div");
  row.className = "info-list__row";
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.className = mono ? "info-list__value info-list__value--mono" : "info-list__value";
  if (value instanceof Node) dd.append(value);
  else dd.textContent = value;
  if (title) row.title = title;
  row.append(dt, dd);
  return row;
}

function setConnectionStatus(state, label) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
}

function setErrorBanner(message) {
  dom.errorBanner.hidden = !message;
  dom.errorBannerText.textContent = message || "";
}

// --- live status ---

function isDashboardShown() {
  return !dom.view.hidden;
}

function isActive() {
  return !document.hidden && isDashboardShown();
}

function setLive(state, label) {
  dom.liveStatus.dataset.state = state;
  dom.liveLabel.textContent = label;
}

function renderLiveStatus() {
  const updated = lastSuccess ? `updated ${lastSuccess.toLocaleTimeString()}` : "no successful update yet";
  if (document.hidden) {
    setLive("paused", `Paused while this tab is hidden · ${updated}`);
  } else if (!isDashboardShown()) {
    setLive("paused", `Paused · ${updated}`);
  } else if (refreshing && !loadedOnce) {
    setLive("checking", "Connecting…");
  } else if (lastRefreshFailed) {
    setLive("error", `Some data failed to refresh · last full update ${lastSuccess ? lastSuccess.toLocaleTimeString() : "never"}`);
  } else {
    setLive("live", `Live · every ${REFRESH_INTERVAL_MS / 1000} s · ${updated}`);
  }
}

// --- KPI row ---

function renderCountCard(key, result, extract) {
  const { valueEl, cardSelector } = STAT_CARDS[key];
  const valueNode = $(valueEl);
  const cardNode = dom.statGrid.querySelector(cardSelector);
  const value = fulfilled(result);
  if (value) {
    valueNode.textContent = String(extract(value));
    valueNode.classList.remove("stat-card__value--unavailable");
    cardNode.classList.remove("stat-card--error");
  } else {
    valueNode.textContent = "Unavailable";
    valueNode.classList.add("stat-card__value--unavailable");
    cardNode.classList.add("stat-card--error");
  }
}

function renderMicroBar(container, result, keyFn, max = 5) {
  const value = fulfilled(result);
  if (!value || !Array.isArray(value.result)) return;
  renderStackedBar(container, topCategories(countBy(value.result, keyFn), max), { compact: true });
}

function setUnavailable(node) {
  node.textContent = "Unavailable";
  node.classList.add("stat-card__value--unavailable");
}

function renderMonitorKpis(monitor) {
  if (!monitor) {
    setUnavailable(dom.uptime);
    setUnavailable(dom.license);
    dom.licenseMeta.textContent = "";
    return;
  }
  dom.uptime.classList.remove("stat-card__value--unavailable");
  dom.uptime.textContent = textOrPlaceholder(monitor.Status.UpTime.replace(/\s+/g, " "));
  const lic = monitor.Licensing;
  dom.license.classList.remove("stat-card__value--unavailable");
  // Spec: LicenseUse is a percentage, or "" when there is no license limit.
  dom.license.textContent = typeof lic.LicenseUse === "number" ? `${lic.LicenseUse}%` : "No limit";
  dom.licenseMeta.textContent =
    `limit ${formatNumber(lic.LicenseLimit)} units` +
    (typeof lic.LicenseUseHigh === "number" ? ` · peak ${lic.LicenseUseHigh}%` : "");
}

/** IRIS version/build in the global header, from GET /api/iris/info. */
function renderInfo(result) {
  const value = fulfilled(result);
  if (value) {
    const info = value.result;
    dom.headerVersion.textContent =
      `${info.serverVersion || "Unknown"} · ${info.product || "iris"} · API v${info.apiVersion ?? "?"}`;
    setConnectionStatus("connected", `Connected as ${info.username || "unknown user"}`);
  } else {
    dom.headerVersion.textContent = "";
    setConnectionStatus("error", "Could not reach IRIS");
  }
}

// --- System Health + Recent Alerts ---

function statusVariant(value) {
  if (typeof value !== "string") return "status-badge--neutral";
  return value.trim().toLowerCase() === "normal" ? "status-badge--ok" : "status-badge--warning";
}

function renderHealth(monitor) {
  dom.healthIndicators.replaceChildren();
  dom.healthFacts.replaceChildren();
  dom.healthEmpty.hidden = Boolean(monitor);
  dom.monitorWarning.hidden = !monitor || monitor.Status.SystemMonitor !== false;
  if (!monitor) return;

  for (const [label, section, field] of HEALTH_INDICATORS) {
    const value = monitor[section][field];
    const item = document.createElement("li");
    item.className = "dash-indicators__item";
    const name = document.createElement("span");
    name.textContent = label;
    item.append(name, makeBadge(textOrPlaceholder(value), statusVariant(value)));
    dom.healthIndicators.append(item);
  }
  dom.healthFacts.append(
    makeInfoRow("System Monitor", monitor.Status.SystemMonitor ? "Running" : "Not running"),
    makeInfoRow("Uptime", textOrPlaceholder(monitor.Status.UpTime.replace(/\s+/g, " ")), { mono: true }),
    makeInfoRow("Last Full Backup", textOrPlaceholder(monitor.Status.LastBackup), { mono: true }),
    makeInfoRow("Journal Entries", formatNumber(monitor.SystemUsage.JournalEntries), { mono: true }),
  );
}

function renderAlerts(monitor) {
  dom.alertCounts.replaceChildren();
  dom.alertList.replaceChildren();
  dom.alertsEmpty.hidden = Boolean(monitor);
  if (!monitor) return;

  const stale = monitor.Status.SystemMonitor === false;
  for (const [label, value] of [
    ["Serious alerts", monitor.Alerts.SeriousAlerts],
    ["Application errors", monitor.Alerts.ApplicationErrors],
  ]) {
    const card = document.createElement("div");
    card.className = "dash-alert-count";
    card.dataset.level = value > 0 ? "alert" : "ok";
    const number = document.createElement("span");
    number.className = "dash-alert-count__value";
    number.textContent = formatNumber(value);
    const text = document.createElement("span");
    text.className = "dash-alert-count__label";
    text.textContent = stale ? `${label} (may not be current)` : label;
    card.append(number, text);
    dom.alertCounts.append(card);
  }

  // Real, derived-only-by-comparison findings: each is a value IRIS reported.
  const findings = [];
  if (stale) findings.push(["warning", "IRIS System Monitor is not running — status indicators and alert counts are not being updated."]);
  for (const [label, section, field] of HEALTH_INDICATORS) {
    const value = monitor[section][field];
    if (typeof value === "string" && value.trim().toLowerCase() !== "normal") {
      findings.push(["warning", `${label}: ${value}`]);
    }
  }
  if (monitor.Status.LastBackup === "Never") findings.push(["info", "IRIS reports no full system backup (Last Backup: Never)."]);
  if (typeof monitor.Licensing.LicenseUse === "number" && monitor.Licensing.LicenseUse >= 90) {
    findings.push(["warning", `License use is at ${monitor.Licensing.LicenseUse}% of the limit.`]);
  }

  if (findings.length === 0) {
    const item = document.createElement("li");
    item.className = "dash-alert-list__item";
    item.dataset.level = "ok";
    item.textContent = "No indicator reports a non-Normal status.";
    dom.alertList.append(item);
    return;
  }
  for (const [level, message] of findings) {
    const item = document.createElement("li");
    item.className = "dash-alert-list__item";
    item.dataset.level = level;
    item.textContent = message;
    dom.alertList.append(item);
  }
}

// --- Resources (sampled trends) ---

function takeSample(monitor) {
  const perf = monitor.Performance;
  const usage = monitor.SystemUsage;
  const now = Date.now();
  const previous = samples[samples.length - 1];
  const rate = (current, before) => {
    if (!previous || typeof current !== "number" || typeof before !== "number") return null;
    const seconds = (now - previous.time) / 1000;
    const delta = current - before;
    // A negative delta means the cumulative counters reset (IRIS restarted).
    return seconds > 0 && delta >= 0 ? delta / seconds : null;
  };
  const sample = {
    time: now,
    globalRefsPerSecond: perf.GlobalRefsPerSecond,
    cacheEfficiency: perf.CacheEfficiency,
    diskReads: perf.DiskReads,
    diskWrites: perf.DiskWrites,
    diskReadsPerSecond: rate(perf.DiskReads, previous && previous.diskReads),
    diskWritesPerSecond: rate(perf.DiskWrites, previous && previous.diskWrites),
    processes: usage.Processes,
    cspSessions: usage.CSPSessions,
  };
  samples = [...samples, sample].slice(-MAX_SAMPLES);
}

function makeSparkline(values) {
  const width = 160;
  const height = 36;
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "dash-spark__chart");
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("aria-hidden", "true");
  const points = values.map((v, i) => [i, v]).filter(([, v]) => typeof v === "number" && Number.isFinite(v));
  if (points.length < 2) return svg;
  const min = Math.min(...points.map(([, v]) => v));
  const max = Math.max(...points.map(([, v]) => v));
  const span = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const coords = points.map(([i, v]) => `${(i * step).toFixed(1)},${(height - 3 - ((v - min) / span) * (height - 6)).toFixed(1)}`);
  const line = document.createElementNS(SVG_NS, "polyline");
  line.setAttribute("points", coords.join(" "));
  line.setAttribute("class", "dash-spark__line");
  svg.append(line);
  return svg;
}

function renderResources(monitorAvailable) {
  dom.resourcesEmpty.hidden = monitorAvailable || samples.length > 0;
  dom.resources.replaceChildren();
  if (samples.length === 0) return;
  const spanSeconds = samples.length > 1 ? Math.round((samples[samples.length - 1].time - samples[0].time) / 1000) : 0;
  for (const [label, unit, pick] of RESOURCE_SERIES) {
    const values = samples.map(pick);
    const numeric = values.filter((v) => typeof v === "number" && Number.isFinite(v));
    const current = values[values.length - 1];
    const tile = document.createElement("div");
    tile.className = "dash-spark";
    const head = document.createElement("div");
    head.className = "dash-spark__head";
    const name = document.createElement("span");
    name.className = "dash-spark__label";
    name.textContent = label;
    const value = document.createElement("span");
    value.className = "dash-spark__value";
    value.textContent = typeof current === "number" ? `${formatNumber(current, label.startsWith("Cache") ? 2 : 1)}${unit}` : PLACEHOLDER;
    head.append(name, value);
    const meta = document.createElement("span");
    meta.className = "dash-spark__meta";
    meta.textContent = numeric.length
      ? `min ${formatNumber(Math.min(...numeric), 1)} · max ${formatNumber(Math.max(...numeric), 1)} · ${numeric.length} sample${numeric.length === 1 ? "" : "s"}${spanSeconds ? ` over ${Math.floor(spanSeconds / 60)}m ${spanSeconds % 60}s` : ""}`
      : "needs two samples";
    tile.setAttribute("role", "img");
    tile.setAttribute("aria-label", `${label}: ${value.textContent}. ${meta.textContent}`);
    tile.append(head, makeSparkline(values), meta);
    dom.resources.append(tile);
  }
}

// --- Database Storage ---

function renderStorage(result) {
  const value = fulfilled(result);
  dom.storage.replaceChildren();
  if (!value || !Array.isArray(value.result)) {
    dom.storageEmpty.hidden = false;
    return;
  }
  dom.storageEmpty.hidden = true;
  const entries = [...value.result].sort((a, b) => b.Size - a.Size);
  const largest = Math.max(1, ...entries.map((e) => e.Size));
  const total = entries.reduce((sum, e) => sum + (typeof e.Size === "number" ? e.Size : 0), 0);
  dom.storageHint.textContent = `Allocated size of ${entries.length} local databases · ${formatMB(total)} in total (GET /v2/database-dirs).`;
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "dash-storage__row";
    row.title = entry.Directory;
    const label = document.createElement("span");
    label.className = "dash-storage__name";
    label.textContent = databaseNames.get(entry.Directory) || entry.Directory;
    const track = document.createElement("span");
    track.className = "dash-storage__track";
    const fill = document.createElement("span");
    fill.className = "dash-storage__fill";
    const limited = typeof entry.MaxSize === "number" && entry.MaxSize > 0;
    // With a numeric MaxSize the bar shows real utilization; otherwise it is
    // relative to the largest database.
    fill.style.width = `${Math.max(2, (limited ? entry.Size / entry.MaxSize : entry.Size / largest) * 100)}%`;
    track.append(fill);
    const size = document.createElement("span");
    size.className = "dash-storage__size";
    size.textContent = limited ? `${formatMB(entry.Size)} of ${formatMB(entry.MaxSize)}` : formatMB(entry.Size);
    row.append(label, track, size);
    if (typeof entry.Status === "string" && !entry.Status.startsWith("Mounted")) {
      row.append(makeBadge(entry.Status, "status-badge--warning"));
    }
    dom.storage.append(row);
  }
}

// --- Process Distribution ---

function renderProcesses(result, monitor) {
  const value = fulfilled(result);
  dom.processState.replaceChildren();
  dom.processNamespace.replaceChildren();
  dom.processBusy.replaceChildren();
  if (!value || !Array.isArray(value.result)) {
    dom.processEmpty.hidden = false;
  } else {
    dom.processEmpty.hidden = true;
    const processes = value.result;
    renderDonut(dom.processState, topCategories(countBy(processes, (p) => p.State || "Unknown"), 6), {
      size: 72,
      centerValue: processes.length,
      centerLabel: "processes",
    });
    renderStackedBar(dom.processNamespace, topCategories(countBy(processes, (p) => p.Nspace || "(none)"), 6));
  }
  const busy = monitor ? monitor.SystemUsage.BusyProcesses.filter((b) => b.Process !== "" && b.Commands > 0) : [];
  if (busy.length === 0) {
    dom.processBusy.append(makeInfoRow("Busiest", monitor ? "IRIS reports no busy processes" : "Unavailable"));
  } else {
    for (const b of busy.slice(0, 5)) dom.processBusy.append(makeInfoRow(`PID ${b.Process}`, formatNumber(b.Commands), { mono: true }));
  }
}

// --- Recent Operations ---

const STATUS_BADGE_CLASS = {
  success: "status-badge--ok",
  ok: "status-badge--ok",
  dry_run: "status-badge--neutral",
  skipped: "status-badge--neutral",
  not_applicable: "status-badge--neutral",
  confirmation_required: "status-badge--warning",
  required_not_received: "status-badge--warning",
};

function makeCell(content) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  if (content instanceof Node) cell.append(content);
  else {
    cell.textContent = content;
    cell.title = content;
  }
  return cell;
}

function renderRecentActivity(result) {
  dom.activityTableBody.replaceChildren();
  const value = fulfilled(result);
  const traces = value && Array.isArray(value.traces) ? value.traces : [];
  if (traces.length === 0) {
    dom.activityTableWrapper.hidden = true;
    dom.activityEmpty.hidden = false;
    dom.activityEmpty.textContent = value
      ? "No operations have been executed yet through this Command Center. Try the Operations view."
      : "Could not load recent operations.";
    return;
  }
  dom.activityEmpty.hidden = true;
  dom.activityTableWrapper.hidden = false;
  for (const trace of traces.slice(0, RECENT_ACTIVITY_LIMIT)) {
    const status = typeof trace.status === "string" ? trace.status : null;
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(trace.operation_name)),
      makeCell(makeBadge(textOrPlaceholder(status).replace(/_/g, " "), (status && STATUS_BADGE_CLASS[status]) || "status-badge--error")),
      makeCell(formatDuration(trace.duration_ms)),
      makeCell(formatTimestamp(trace.start_time)),
    );
    dom.activityTableBody.append(row);
  }
}

function renderOperationsSummary(operationsResult, tracesResult) {
  const operations = fulfilled(operationsResult);
  const traces = fulfilled(tracesResult);
  const parts = [];
  if (operations && Array.isArray(operations.operations)) {
    const mutating = operations.operations.filter((op) => op.kind === "mutating").length;
    parts.push(`${operations.operations.length} operations registered · ${mutating} mutating`);
  }
  if (traces && Array.isArray(traces.traces)) {
    parts.push(`${traces.traces.length} trace${traces.traces.length === 1 ? "" : "s"} recorded this session`);
  }
  if (parts.length) dom.operationsSummary.textContent = parts.join(" · ");
  else if (operationsResult) dom.operationsSummary.textContent = "Operations registry unavailable.";
}

function renderCapabilitiesSummary(result) {
  const value = fulfilled(result);
  if (!value || !Array.isArray(value.capabilities)) {
    dom.capabilitiesSummary.textContent = "";
    return;
  }
  const available = value.capabilities.filter((c) => c.available).length;
  dom.capabilitiesSummary.textContent = `${available} of ${value.capabilities.length} tracked capabilities available`;
}

// --- refresh cycle ---

async function refresh({ includeSlow }) {
  if (refreshing) return;
  refreshing = true;
  dom.refreshButton.disabled = true;
  dom.refreshButton.classList.toggle("btn--spinning", true);
  dom.loadingState.hidden = loadedOnce;
  renderLiveStatus();

  const fast = {
    info: IrisApi.getInfo(),
    monitor: IrisApi.getMonitorDashboard(),
    processes: IrisApi.getProcesses(),
    traces: IrisApi.getExecutionTraces(),
  };
  const slow = includeSlow
    ? {
        namespaces: IrisApi.getNamespaces(),
        databases: IrisApi.getDatabases(),
        webApps: IrisApi.getWebApps(),
        tasks: IrisApi.getTaskOverview(),
        storage: IrisApi.getDatabaseStorage(),
        operations: IrisApi.getOperations(),
        capabilities: IrisApi.getCapabilities(),
      }
    : {};
  const keys = [...Object.keys(fast), ...Object.keys(slow)];
  const settled = await Promise.allSettled([...Object.values(fast), ...Object.values(slow)]);
  const r = Object.fromEntries(keys.map((key, i) => [key, settled[i]]));

  const monitorValue = fulfilled(r.monitor);
  const monitor = monitorValue && monitorValue.result ? monitorValue.result : null;
  if (monitor) takeSample(monitor);

  renderInfo(r.info);
  renderMonitorKpis(monitor);
  renderHealth(monitor);
  renderAlerts(monitor);
  renderResources(Boolean(monitor));
  renderProcesses(r.processes, monitor);
  renderCountCard("processes", r.processes, (body) => body.result.length);
  renderMicroBar(dom.processesViz, r.processes, (p) => p.State || "Unknown");
  renderRecentActivity(r.traces);

  if (includeSlow) {
    const databases = fulfilled(r.databases);
    if (databases && Array.isArray(databases.result)) {
      databaseNames = new Map(databases.result.map((db) => [db.Directory, db.Name]));
    }
    renderCountCard("namespaces", r.namespaces, (body) => body.result.length);
    renderCountCard("databases", r.databases, (body) => body.result.length);
    renderCountCard("webApps", r.webApps, (body) => body.result.length);
    renderCountCard("tasks", r.tasks, (body) => body.result.length);
    renderMicroBar(dom.databasesViz, r.databases, (db) => db.Status || "Unknown");
    renderMicroBar(dom.webAppsViz, r.webApps, (app) => (app.Enabled ? "Enabled" : "Disabled"), 2);
    // Run State from the tasks overview's backend-derived `State` — the same
    // grouping the Tasks view uses; never the task list's own Suspended flag.
    renderMicroBar(dom.tasksViz, r.tasks, (task) => task.State || "Unknown");
    renderStorage(r.storage);
    renderCapabilitiesSummary(r.capabilities);
    renderOperationsSummary(r.operations, r.traces);
  } else {
    renderOperationsSummary(null, r.traces);
  }

  const failures = keys.filter((key) => r[key].status === "rejected");
  lastRefreshFailed = failures.length > 0;
  if (failures.length === keys.length) {
    setErrorBanner("Could not load dashboard data right now. The Command Center backend may be unreachable.");
  } else if (failures.length > 0) {
    setErrorBanner(`Some dashboard data could not be loaded (${failures.length} of ${keys.length} sources). The rest is shown below.`);
  } else {
    setErrorBanner(null);
    lastSuccess = new Date();
  }

  loadedOnce = true;
  refreshing = false;
  dom.loadingState.hidden = true;
  dom.refreshButton.disabled = false;
  dom.refreshButton.classList.toggle("btn--spinning", false);
  renderLiveStatus();
}

function stopPolling() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function scheduleNext() {
  stopPolling();
  if (!isActive()) {
    renderLiveStatus();
    return;
  }
  timer = setTimeout(async () => {
    timer = null;
    if (!isActive()) {
      renderLiveStatus();
      return;
    }
    tickCount += 1;
    await refresh({ includeSlow: tickCount % SLOW_EVERY_TICKS === 0 });
    scheduleNext();
  }, REFRESH_INTERVAL_MS);
}

/** Loads everything now and (re)starts the live cycle. Called at startup,
 * on Refresh, and when the Dashboard is shown again. */
export async function loadDashboard() {
  stopPolling();
  tickCount = 0;
  await refresh({ includeSlow: true });
  scheduleNext();
}

/** Called when the Dashboard view is shown (app.js's navigation callback):
 * refreshes immediately and resumes polling. */
export function onDashboardShown() {
  if (!refreshing) loadDashboard();
}

export function initDashboardControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadDashboard();
  });

  // Pause while the tab is hidden; resume (with an immediate refresh) when
  // it is visible again and the Dashboard is the current view.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      stopPolling();
      renderLiveStatus();
    } else if (isDashboardShown()) {
      loadDashboard();
    }
  });

  dom.viewObservabilityButton.addEventListener("click", () => {
    navigateTo("observability");
  });

  // Each quicklink card just navigates; the target view loads itself.
  dom.quicklinks.querySelectorAll("[data-quicklink]").forEach((button) => {
    button.addEventListener("click", () => {
      navigateTo(button.dataset.quicklink);
    });
  });

  // The count cards double as navigation shortcuts to their views.
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
