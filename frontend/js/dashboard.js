// Dashboard: the landing page, a live overview of the connected instance.
// - KPI row: counts from the list routes, plus IRIS's own alert counters.
// - System Health and Resources: GET /api/iris/monitor/dashboard.
// - Issues & Recommendations: GET /api/iris/issues with its catalog entries.
// - Database Storage: GET /api/iris/databases/storage, with names from the
//   database list.
// - Process Distribution: GET /api/iris/processes.
// - Recent Operations: our execution traces plus the operations registry.
//
// Refreshes every REFRESH_INTERVAL_MS while the Dashboard is shown and the
// tab is visible. Fast panels update every tick; the heavier ones (counts,
// storage, tasks, registry) every SLOW_EVERY_TICKS. Refreshes are chained
// with setTimeout so they never overlap.
//
// Resource charts use up to MAX_SAMPLES samples taken by this page. Disk
// read/write rates are the difference between two samples of IRIS's
// cumulative counters; a negative difference (IRIS restarted) is skipped.
// Missing or failed data shows as unavailable.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { countBy, renderDonut, renderStackedBar, topCategories } from "./viz.js";

const PLACEHOLDER = "—";  // shown for empty values
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
  license: $("stat-license"),
  licenseMeta: $("stat-license-meta"),
  alertsCard: $("stat-alerts-card"),
  alerts: $("stat-alerts"),
  alertsMeta: $("stat-alerts-meta"),
  monitorWarning: $("dashboard-monitor-warning"),
  healthEmpty: $("dashboard-health-empty"),
  healthSummary: $("dashboard-health-summary"),
  healthIndicators: $("dashboard-health-indicators"),
  healthFacts: $("dashboard-health-facts"),
  resourcesEmpty: $("dashboard-resources-empty"),
  resources: $("dashboard-resources"),
  resourcesChart: $("dashboard-resources-chart"),
  storageEmpty: $("dashboard-storage-empty"),
  storageTotal: $("dashboard-storage-total"),
  storage: $("dashboard-storage"),
  storageHint: $("dashboard-storage-hint"),
  issuesCount: $("dashboard-issues-count"),
  issuesLabel: $("dashboard-issues-label"),
  issueList: $("dashboard-issue-list"),
  recommendations: $("dashboard-recommendations"),
  recommendationList: $("dashboard-recommendation-list"),
  processEmpty: $("dashboard-process-empty"),
  processState: $("dashboard-process-state"),
  processNamespace: $("dashboard-process-namespace"),
  activityEmpty: $("dashboard-activity-empty"),
  activityTableWrapper: $("dashboard-activity-table-wrapper"),
  activityTableBody: $("dashboard-activity-table-body"),
  operationsSummary: $("dashboard-operations-summary"),
  viewObservabilityButton: $("dashboard-view-observability-button"),
  openIssueResolverButton: $("dashboard-open-issue-resolver-button"),
  viewProcessesButton: $("dashboard-view-processes-button"),
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

// System Dashboard indicators: [label, section, field]. Each is a status
// string ("Normal" when healthy).
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

let samples = [];  // samples, oldest first, at most MAX_SAMPLES
let tickCount = 0;
let timer = null;
let refreshing = false;
let lastSuccess = null;  // time of the last refresh with no failures
let lastRefreshFailed = false;
let databaseNames = new Map(); // Directory → Name, from the last database list
let loadedOnce = false;
let onOpenTrace = null; // app.js: opens a trace in Observability's detail view

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

/** Compact time-of-day for the Recent Operations table; full timestamp on hover. */
function formatTime(iso) {
  const full = formatTimestamp(iso);
  const date = new Date(iso);
  if (full === PLACEHOLDER || Number.isNaN(date.getTime())) return full;
  const span = document.createElement("span");
  span.textContent = date.toLocaleTimeString();
  span.title = full;
  return span;
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

function renderMonitorKpis(monitor, sysMon) {
  if (!monitor) {
    setUnavailable(dom.license);
    dom.licenseMeta.textContent = "";
    setUnavailable(dom.alerts);
    dom.alertsMeta.textContent = "";
    dom.alertsCard.classList.add("stat-card--error");
    delete dom.alertsCard.dataset.level;
    return;
  }
  // IRIS Alerts KPI: IRIS's serious-alert counter.
  const serious = monitor.Alerts.SeriousAlerts;
  dom.alerts.classList.remove("stat-card__value--unavailable");
  dom.alertsCard.classList.remove("stat-card--error");
  dom.alerts.textContent = formatNumber(serious);
  dom.alertsCard.dataset.level = serious > 0 ? "alert" : "ok";
  dom.alertsMeta.textContent =
    `serious · ${formatNumber(monitor.Alerts.ApplicationErrors)} app errors` + (sysMon === null ? " · may not be current" : "");

  const lic = monitor.Licensing;
  dom.license.classList.remove("stat-card__value--unavailable");
  // LicenseUse is a percentage, or "" when there's no license limit.
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

// --- System Health ---

function statusVariant(value) {
  if (typeof value !== "string") return "status-badge--neutral";
  return value.trim().toLowerCase() === "normal" ? "status-badge--ok" : "status-badge--warning";
}

// Whether the System Monitor is running, from the process list: its
// controller runs as %SYS.Monitor.Control in %SYS.
// We don't use the Status.SystemMonitor flag, because the REST endpoint
// casts a status string like "Normal" to boolean, so it's always false here.
// Returns the process (running), null (not running) or undefined (the
// process list didn't load).
function findSystemMonitorProcess(processesResult) {
  const value = fulfilled(processesResult);
  if (!value || !Array.isArray(value.result)) return undefined;
  return (
    value.result.find(
      (p) => typeof p.Routine === "string" && p.Routine.startsWith("%SYS.Monitor.Control") && p.Nspace === "%SYS",
    ) || null
  );
}

function describeSystemMonitor(sysMon) {
  if (sysMon === undefined) return "Unknown (process list unavailable)";
  if (sysMon === null) return "Not running (no %SYS.Monitor.Control process in %SYS)";
  return `Running (PID ${sysMon.Pid})`;
}

// Ring showing the share of indicators that say "Normal", with the count
// in the middle.
function renderHealthSummary(monitor) {
  dom.healthSummary.replaceChildren();
  if (!monitor) return;
  const values = HEALTH_INDICATORS.map(([, section, field]) => monitor[section][field]);
  const normal = values.filter((v) => typeof v === "string" && v.trim().toLowerCase() === "normal").length;
  const ring = document.createElement("div");
  ring.className = "dash-health-ring";
  ring.style.setProperty("--ring-fill", `${(normal / values.length) * 360}deg`);
  ring.title = HEALTH_INDICATORS.map(([label], i) => `${label}: ${textOrPlaceholder(values[i])}`).join("\n");
  const hole = document.createElement("div");
  hole.className = "dash-health-ring__hole";
  const count = document.createElement("span");
  count.className = "dash-health-ring__value";
  count.textContent = `${normal}/${values.length}`;
  const label = document.createElement("span");
  label.className = "dash-health-ring__label";
  label.textContent = "Normal";
  hole.append(count, label);
  ring.append(hole);
  dom.healthSummary.dataset.level = normal === values.length ? "ok" : "warning";
  dom.healthSummary.append(ring);
}

function makeCheck(level, text) {
  const item = document.createElement("li");
  item.className = "dash-checks__item";
  item.dataset.level = level;
  const icon = document.createElement("span");
  icon.className = "dash-checks__icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = level === "ok" ? "\u2713" : level === "warning" ? "!" : "?";
  const label = document.createElement("span");
  label.textContent = text;
  item.append(icon, label);
  return item;
}

function renderHealth(monitor, sysMon) {
  dom.healthIndicators.replaceChildren();
  dom.healthFacts.replaceChildren();
  dom.healthEmpty.hidden = Boolean(monitor);
  dom.monitorWarning.hidden = !monitor || sysMon !== null;
  renderHealthSummary(monitor);
  if (!monitor) return;

  // Each check just restates a value from IRIS or the process list.
  const checks = [];
  if (sysMon === undefined) checks.push(["unknown", "System Monitor: unknown (process list unavailable)"]);
  else if (sysMon === null) checks.push(["warning", "System Monitor not running"]);
  else checks.push(["ok", `System Monitor running (PID ${sysMon.Pid})`]);
  const abnormal = HEALTH_INDICATORS.filter(([, section, field]) => {
    const value = monitor[section][field];
    return typeof value !== "string" || value.trim().toLowerCase() !== "normal";
  });
  if (abnormal.length === 0) checks.push(["ok", `All ${HEALTH_INDICATORS.length} status indicators Normal`]);
  for (const [label, section, field] of abnormal) {
    checks.push(["warning", `${label}: ${textOrPlaceholder(monitor[section][field])}`]);
  }
  const serious = monitor.Alerts.SeriousAlerts;
  checks.push(serious > 0 ? ["warning", `${formatNumber(serious)} serious alerts reported`] : ["ok", "No serious alerts reported"]);
  const backup = monitor.Status.LastBackup;
  checks.push(backup === "Never" ? ["warning", "No full backup recorded"] : ["ok", `Last full backup: ${textOrPlaceholder(backup)}`]);
  for (const [level, text] of checks) dom.healthIndicators.append(makeCheck(level, text));

  dom.healthFacts.append(
    makeInfoRow("System Monitor", describeSystemMonitor(sysMon)),
    makeInfoRow("Uptime", textOrPlaceholder(monitor.Status.UpTime.replace(/\s+/g, " ")), { mono: true }),
    makeInfoRow("Journal Entries", formatNumber(monitor.SystemUsage.JournalEntries), { mono: true }),
  );
}

// --- Issues & Recommendations ---
//
// Active issues from GET /api/iris/issues, each explained with its Issue
// Resolution Catalog entry (the response's `resolutions`). "Review &
// Resolve" opens the Issue Resolver page; nothing is run from here.

const SEVERITY_ORDER = ["low", "medium", "high", "critical"];
const SEVERITY_BADGE = {
  critical: "status-badge--error",
  high: "status-badge--error",
  medium: "status-badge--warning",
  low: "status-badge--neutral",
};

function issueStatusItem(badgeText, badgeClass, message, level) {
  const item = document.createElement("li");
  item.className = "dash-alert-list__item";
  item.dataset.level = level;
  const text = document.createElement("span");
  text.className = "dash-alert-list__text";
  text.textContent = message;
  item.append(makeBadge(badgeText, badgeClass), text);
  return item;
}

// The resource each issue is about: name, then detail · status.
function issueResource(issue) {
  if (issue.kind === "web_app_namespace_missing") {
    return [issue.web_app, `namespace ${textOrPlaceholder(issue.namespace)} (missing) · ${issue.enabled ? "Enabled" : "Disabled"}`];
  }
  return [issue.database, `${textOrPlaceholder(issue.directory)} · ${textOrPlaceholder(issue.status)}`];
}

// Issue checks that couldn't run (their IRIS data couldn't be read).
function issueChecksUnavailableItem(body, resolutions) {
  const unavailable = Array.isArray(body?.issue_checks_unavailable) ? body.issue_checks_unavailable : [];
  if (!unavailable.length) return null;
  const names = unavailable.map((kind) => resolutions[kind]?.title || kind).join(", ");
  return issueStatusItem("Unavailable", "status-badge--warning",
    `Some issue checks couldn't run (${names}); IRIS data for them couldn't be read.`, "info");
}

function renderIssues(settled) {
  if (!settled) return;  // not refreshed this time, keep what's shown
  const body = settled.status === "fulfilled" ? settled.value : null;
  const issues = Array.isArray(body?.issues) ? body.issues : null;
  const resolutions = body?.resolutions && typeof body.resolutions === "object" ? body.resolutions : {};
  dom.issueList.replaceChildren();

  if (issues === null) {
    renderRecommendations(null);
    dom.issuesCount.textContent = PLACEHOLDER;
    dom.issuesLabel.textContent = "Could not check for issues right now.";
    dom.issueList.append(issueStatusItem("Info", "status-badge--neutral", "The issue check didn't respond. Try Refresh.", "info"));
    return;
  }

  dom.issuesCount.textContent = String(issues.length);
  renderRecommendations(body);
  const unavailableItem = issueChecksUnavailableItem(body, resolutions);
  if (issues.length === 0) {
    dom.issuesLabel.textContent = "active issues";
    dom.issueList.append(unavailableItem ||
      issueStatusItem("OK", "status-badge--ok", "No actionable issues detected.", "ok"));
    return;
  }

  const severities = issues.map((issue) => resolutions[issue.kind]?.severity).filter((s) => SEVERITY_ORDER.includes(s));
  const highest = severities.sort((a, b) => SEVERITY_ORDER.indexOf(b) - SEVERITY_ORDER.indexOf(a))[0];
  dom.issuesLabel.textContent =
    `active ${issues.length === 1 ? "issue" : "issues"}` + (highest ? ` · highest severity ${highest}` : "");

  for (const issue of issues) {
    const resolution = resolutions[issue.kind];
    const severity = resolution?.severity;
    const item = document.createElement("li");
    item.className = "dash-issue";

    const badge = makeBadge(
      severity ? severity.charAt(0).toUpperCase() + severity.slice(1) : "Issue",
      SEVERITY_BADGE[severity] || "status-badge--warning",
    );
    const body_ = document.createElement("div");
    body_.className = "dash-issue__body";
    // The title also opens the Issue Resolver, like "Review & Resolve".
    const title = document.createElement("p");
    title.className = "dash-issue__title";
    const titleLink = document.createElement("button");
    titleLink.className = "dash-issue__title-link";
    titleLink.type = "button";
    const [resourceName, resourceDetail] = issueResource(issue);
    titleLink.textContent = `${resolution ? resolution.title : textOrPlaceholder(issue.kind)}: ${textOrPlaceholder(resourceName)}`;
    titleLink.title = "Open in the Issue Resolver";
    titleLink.addEventListener("click", () => navigateTo("issue-resolver"));
    title.append(titleLink);
    const resource = document.createElement("p");
    resource.className = "dash-issue__resource";
    resource.textContent = resourceDetail;
    const explanation = document.createElement("p");
    explanation.className = "dash-issue__text";
    explanation.textContent = resolution
      ? `${resolution.explanation} Recommended: ${resolution.recommended_solution}`
      : issue.explanation;
    body_.append(title, resource, explanation);

    const review = document.createElement("button");
    review.className = "dash-panel__link dash-issue__action";
    review.type = "button";
    review.textContent = "Review & Resolve →";
    review.addEventListener("click", () => navigateTo("issue-resolver"));

    item.append(badge, body_, review);
    dom.issueList.append(item);
  }
  if (unavailableItem) dom.issueList.append(unavailableItem);
}

// Recommendations from the same response (`recommendations`,
// `recommendations_unavailable`): suggested changes, not issues. "Review"
// opens the page where the recommended operation already runs, with its own
// authorization and confirmation; nothing is run from here.

const RECOMMENDATION_PAGES = {
  "journal.update_purge_archived": "operations",
};

const RECOMMENDATION_CHECKS = {
  journal_purge_archived_off: "journal settings",
};

function formatEvidence(evidence) {
  return (Array.isArray(evidence) ? evidence : [])
    .map((e) => `${textOrPlaceholder(e.source)} ${textOrPlaceholder(e.field)}: ${textOrPlaceholder(String(e.value))}`)
    .join(" · ");
}

function formatParameters(parameters) {
  return Object.entries(parameters && typeof parameters === "object" ? parameters : {})
    .map(([name, value]) => `${name}=${value}`)
    .join(", ");
}

function recommendationItem(rec) {
  const severity = typeof rec.severity === "string" ? rec.severity : "";
  const item = document.createElement("li");
  item.className = "dash-issue dash-recommendation";

  const badge = makeBadge(
    severity ? severity.charAt(0).toUpperCase() + severity.slice(1) : "Info",
    SEVERITY_BADGE[severity] || "status-badge--neutral",
  );
  const body_ = document.createElement("div");
  body_.className = "dash-issue__body";
  const title = document.createElement("p");
  title.className = "dash-issue__title";
  title.textContent = `${textOrPlaceholder(rec.title)}: ${textOrPlaceholder(rec.target)}`;
  const explanation = document.createElement("p");
  explanation.className = "dash-issue__text";
  explanation.textContent = textOrPlaceholder(rec.explanation);
  const evidence = document.createElement("p");
  evidence.className = "dash-issue__resource";
  evidence.textContent = `Evidence: ${formatEvidence(rec.evidence) || PLACEHOLDER}`;
  const operation = document.createElement("p");
  operation.className = "dash-issue__resource";
  const params = formatParameters(rec.parameters);
  operation.textContent = `Operation: ${textOrPlaceholder(rec.recommended_operation)}${params ? ` (${params})` : ""}`;
  body_.append(title, explanation, evidence, operation);

  const review = document.createElement("button");
  review.className = "dash-panel__link dash-issue__action";
  review.type = "button";
  review.textContent = "Review →";
  const page = RECOMMENDATION_PAGES[rec.recommended_operation] || "operations";
  review.title = "Opens the Operations page, where this operation runs with its own confirmation";
  review.addEventListener("click", () => navigateTo(page));

  item.append(badge, body_, review);
  return item;
}

function renderRecommendations(body) {
  const recommendations = Array.isArray(body?.recommendations) ? body.recommendations : null;
  const unavailable = Array.isArray(body?.recommendations_unavailable) ? body.recommendations_unavailable : [];
  dom.recommendationList.replaceChildren();
  // An older backend without recommendations: keep the section hidden.
  dom.recommendations.hidden = recommendations === null;
  if (recommendations === null) return;

  for (const rec of recommendations) dom.recommendationList.append(recommendationItem(rec));
  if (unavailable.length) {
    const checks = unavailable.map((kind) => RECOMMENDATION_CHECKS[kind] || kind).join(", ");
    dom.recommendationList.append(issueStatusItem("Unavailable", "status-badge--warning",
      `Some recommendation checks couldn't run (${checks}); IRIS data for them couldn't be read.`, "info"));
  }
  if (recommendations.length === 0 && unavailable.length === 0) {
    dom.recommendationList.append(issueStatusItem("OK", "status-badge--ok", "No recommendations right now.", "ok"));
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
    // A negative difference means the counters reset (IRIS restarted).
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
  const height = 28;
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
  // Area under the line, only across the actual samples.
  const firstX = (points[0][0] * step).toFixed(1);
  const lastX = (points[points.length - 1][0] * step).toFixed(1);
  const area = document.createElementNS(SVG_NS, "polygon");
  area.setAttribute("points", `${firstX},${height} ${coords.join(" ")} ${lastX},${height}`);
  area.setAttribute("class", "dash-spark__area");
  const line = document.createElementNS(SVG_NS, "polyline");
  line.setAttribute("points", coords.join(" "));
  line.setAttribute("class", "dash-spark__line");
  svg.append(area, line);
  return svg;
}

// Round the axis max so gridline labels look clean (1, 2, 2.5, 5 x 10^n).
function niceCeiling(value) {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= value) return step * power;
  return 10 * power;
}

function formatClock(time) {
  return new Date(time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// Trend chart for one series: y axis from zero, gridlines, sample times.
function renderTrendChart(label, pick) {
  dom.resourcesChart.replaceChildren();
  const values = samples.map(pick);
  const points = values.map((v, i) => [i, v]).filter(([, v]) => typeof v === "number" && Number.isFinite(v));
  const head = document.createElement("div");
  head.className = "dash-trend__head";
  const title = document.createElement("span");
  title.className = "dash-trend__title";
  title.textContent = label;
  const legend = document.createElement("span");
  legend.className = "dash-trend__legend";
  legend.textContent = `${points.length} sample${points.length === 1 ? "" : "s"}`;
  head.append(title, legend);
  dom.resourcesChart.append(head);
  if (points.length < 2) {
    const wait = document.createElement("p");
    wait.className = "dash-trend__wait";
    wait.textContent = "The chart appears after two samples (15 s apart).";
    dom.resourcesChart.append(wait);
    return;
  }
  const top = niceCeiling(Math.max(...points.map(([, v]) => v)));
  const width = 600;
  const height = 150;
  const step = width / (values.length - 1);
  const y = (v) => height - (v / top) * height;

  const body = document.createElement("div");
  body.className = "dash-trend__body";
  const axis = document.createElement("div");
  axis.className = "dash-trend__axis";
  for (const fraction of [1, 0.75, 0.5, 0.25, 0]) {
    const tick = document.createElement("span");
    tick.textContent = formatNumber(top * fraction, top < 10 ? 2 : 0);
    axis.append(tick);
  }
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("preserveAspectRatio", "none");
  svg.setAttribute("class", "dash-trend__chart");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${label}, ${points.length} samples, latest ${formatNumber(points[points.length - 1][1], 1)}`);
  for (const fraction of [0.25, 0.5, 0.75, 1]) {
    const grid = document.createElementNS(SVG_NS, "line");
    grid.setAttribute("x1", "0");
    grid.setAttribute("x2", String(width));
    grid.setAttribute("y1", String(y(top * fraction)));
    grid.setAttribute("y2", String(y(top * fraction)));
    grid.setAttribute("class", "dash-trend__grid");
    svg.append(grid);
  }
  const coords = points.map(([i, v]) => `${(i * step).toFixed(1)},${y(v).toFixed(1)}`);
  const area = document.createElementNS(SVG_NS, "polygon");
  area.setAttribute("points", `${(points[0][0] * step).toFixed(1)},${height} ${coords.join(" ")} ${(points[points.length - 1][0] * step).toFixed(1)},${height}`);
  area.setAttribute("class", "dash-trend__area");
  const line = document.createElementNS(SVG_NS, "polyline");
  line.setAttribute("points", coords.join(" "));
  line.setAttribute("class", "dash-trend__line");
  svg.append(area, line);
  // The plot box has a fixed size in CSS and the SVG fills it, so the first
  // line doesn't resize the panel.
  const plot = document.createElement("div");
  plot.className = "dash-trend__plot";
  plot.append(svg);
  body.append(axis, plot);

  const times = document.createElement("div");
  times.className = "dash-trend__times";
  const count = Math.min(5, samples.length);
  for (let k = 0; k < count; k += 1) {
    const index = Math.round((k * (samples.length - 1)) / Math.max(1, count - 1));
    const tick = document.createElement("span");
    tick.textContent = formatClock(samples[index].time);
    times.append(tick);
  }
  dom.resourcesChart.append(body, times);
}

function renderResources(monitorAvailable) {
  dom.resourcesEmpty.hidden = monitorAvailable || samples.length > 0;
  dom.resources.replaceChildren();
  dom.resourcesChart.replaceChildren();
  if (samples.length === 0) return;
  renderTrendChart("Global references / s", (s) => s.globalRefsPerSecond);
  const spanSeconds = samples.length > 1 ? Math.round((samples[samples.length - 1].time - samples[0].time) / 1000) : 0;
  RESOURCE_SERIES.forEach(([label, unit, pick], index) => {
    const values = samples.map(pick);
    const numeric = values.filter((v) => typeof v === "number" && Number.isFinite(v));
    const current = values[values.length - 1];
    const tile = document.createElement("div");
    tile.className = "dash-spark";
    tile.style.setProperty("--spark-color", `var(--color-chart-${(index % 6) + 1})`);
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
  });
}

// --- Database Storage ---

function renderStorage(result) {
  const value = fulfilled(result);
  dom.storage.replaceChildren();
  dom.storageTotal.replaceChildren();
  if (!value || !Array.isArray(value.result)) {
    dom.storageEmpty.hidden = false;
    return;
  }
  dom.storageEmpty.hidden = true;
  const entries = [...value.result].sort((a, b) => b.Size - a.Size);
  const largest = Math.max(1, ...entries.map((e) => e.Size));
  const total = entries.reduce((sum, e) => sum + (typeof e.Size === "number" ? e.Size : 0), 0);
  dom.storageHint.textContent = `Total: ${formatMB(total)}`;
  dom.storageHint.title = `Allocated size of ${entries.length} local databases (GET /v2/database-dirs).`;

  // Share of total allocated size: the five largest, then Other.
  const nameOf = (entry) => databaseNames.get(entry.Directory) || entry.Directory;
  const shares = entries.slice(0, 5).map((e) => ({ key: nameOf(e), count: e.Size }));
  const rest = entries.slice(5).reduce((sum, e) => sum + e.Size, 0);
  if (rest > 0) shares.push({ key: "Other", count: rest });
  const bar = document.createElement("div");
  renderStackedBar(bar, shares, { compact: true, formatValue: (e) => formatMB(e.count) });
  const caption = document.createElement("div");
  caption.className = "dash-storage-total__caption";
  const allocated = document.createElement("span");
  allocated.className = "dash-storage-total__value";
  allocated.textContent = `${formatMB(total)} allocated`;
  const count = document.createElement("span");
  count.textContent = `${entries.length} databases`;
  caption.append(allocated, count);
  dom.storageTotal.append(bar, caption);

  entries.forEach((entry, index) => {
    const row = document.createElement("div");
    row.className = "dash-storage__row";
    row.title = entry.Directory;
    row.style.setProperty("--bar-color", index < 5 ? `var(--color-chart-${index + 1})` : "var(--color-chart-neutral)");
    const label = document.createElement("span");
    label.className = "dash-storage__name";
    label.textContent = nameOf(entry);
    const track = document.createElement("span");
    track.className = "dash-storage__track";
    const fill = document.createElement("span");
    fill.className = "dash-storage__fill";
    const limited = typeof entry.MaxSize === "number" && entry.MaxSize > 0;
    // With a numeric MaxSize the bar shows real usage; otherwise it's relative
    // to the largest database.
    fill.style.width = `${Math.max(2, (limited ? entry.Size / entry.MaxSize : entry.Size / largest) * 100)}%`;
    track.append(fill);
    const share = document.createElement("span");
    share.className = "dash-storage__share";
    share.textContent = total > 0 ? `${Math.round((entry.Size / total) * 100)}%` : PLACEHOLDER;
    share.title = "Share of the total allocated size";
    const size = document.createElement("span");
    size.className = "dash-storage__size";
    size.textContent = limited ? `${formatMB(entry.Size)} / ${formatMB(entry.MaxSize)}` : formatMB(entry.Size);
    row.append(label, track, share, size);
    if (typeof entry.Status === "string" && !entry.Status.startsWith("Mounted")) {
      row.append(makeBadge(entry.Status, "status-badge--warning"));
    }
    dom.storage.append(row);
  });
}

// --- Process Distribution ---

function renderProcesses(result) {
  const value = fulfilled(result);
  dom.processState.replaceChildren();
  dom.processNamespace.replaceChildren();
  if (!value || !Array.isArray(value.result)) {
    dom.processEmpty.hidden = false;
  } else {
    dom.processEmpty.hidden = true;
    const processes = value.result;
    renderDonut(dom.processState, topCategories(countBy(processes, (p) => p.State || "Unknown"), 6), {
      size: 116,
      centerValue: processes.length,
      centerLabel: "total",
      formatValue: (e) => `${e.count} (${Math.round((e.count / Math.max(1, processes.length)) * 100)}%)`,
    });
    renderStackedBar(dom.processNamespace, topCategories(countBy(processes, (p) => p.Nspace || "(none)"), 6));
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
    if (onOpenTrace && typeof trace.trace_id === "string") {
      // Each row opens its trace in Observability.
      row.className = "data-table__row--link";
      row.tabIndex = 0;
      row.title = `Open trace ${trace.trace_id} in Observability`;
      row.addEventListener("click", () => onOpenTrace(trace.trace_id));
      row.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onOpenTrace(trace.trace_id);
      });
    }
    row.append(
      makeCell(textOrPlaceholder(trace.operation_name)),
      makeCell(makeBadge(textOrPlaceholder(status).replace(/_/g, " "), (status && STATUS_BADGE_CLASS[status]) || "status-badge--error")),
      makeCell(formatDuration(trace.duration_ms)),
      makeCell(formatTime(trace.start_time)),
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
        issues: IrisApi.getIssues(),
      }
    : {};
  const keys = [...Object.keys(fast), ...Object.keys(slow)];
  const settled = await Promise.allSettled([...Object.values(fast), ...Object.values(slow)]);
  const r = Object.fromEntries(keys.map((key, i) => [key, settled[i]]));

  const monitorValue = fulfilled(r.monitor);
  const monitor = monitorValue && monitorValue.result ? monitorValue.result : null;
  if (monitor) takeSample(monitor);

  renderInfo(r.info);
  const sysMon = findSystemMonitorProcess(r.processes);
  renderMonitorKpis(monitor, sysMon);
  renderHealth(monitor, sysMon);
  renderIssues(r.issues);
  renderResources(Boolean(monitor));
  renderProcesses(r.processes);
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
    // Run state from the overview's `State` (same grouping as the Tasks page),
    // not the list's Suspended flag.
    renderMicroBar(dom.tasksViz, r.tasks, (task) => task.State || "Unknown");
    renderStorage(r.storage);
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

/**
 * Load everything now and (re)start the refresh cycle. Called at startup,
 * on Refresh and when the Dashboard is shown again.
 */
export async function loadDashboard() {
  stopPolling();
  tickCount = 0;
  await refresh({ includeSlow: true });
  scheduleNext();
}

/** Called when the Dashboard is shown: refresh now and resume polling. */
export function onDashboardShown() {
  if (!refreshing) loadDashboard();
}

/**
 * With `onOpenTrace(traceId)`, clicking a Recent Operations row opens that
 * trace in Observability.
 */
export function initDashboardControls({ onOpenTrace: openTrace } = {}) {
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;
  dom.refreshButton.addEventListener("click", () => {
    loadDashboard();
  });

  // Pause while the tab is hidden; resume (and refresh) when it's visible
  // and the Dashboard is showing.
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
  dom.openIssueResolverButton.addEventListener("click", () => {
    navigateTo("issue-resolver");
  });
  dom.viewProcessesButton.addEventListener("click", () => {
    navigateTo("processes");
  });

  // The count cards also link to their pages.
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

// Re-exported so other code can use the error type without importing api.js.
export { ApiError };
