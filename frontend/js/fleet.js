// Fleet Overview ("Multi-IRIS Command Center"): every active IRIS instance
// side by side. Read-only; it has no change controls.
//
// Each active instance is read on its own, by id, through the same
// instance-scoped read routes as the other pages (the Primary without
// ?instance=):
// - /info (version), /namespaces, /databases, /processes, /web-apps, /tasks
//   for the counts;
// - /health for the health status and findings;
// - /monitor/dashboard for uptime, license use and current activity;
// - /databases/storage for allocated database size.
// Nothing is estimated: a value an instance didn't return shows as "—", and
// an instance that answered nothing is shown as unavailable while the others
// still load. Opening an instance selects it in the header selector.

import { IrisApi, ApiError } from "./api.js";
import { selectInstanceContext } from "./instance-context.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—";
const COLORS = ["var(--color-chart-1)", "var(--color-chart-2)", "var(--color-chart-6)", "var(--color-chart-4)",
  "var(--color-chart-3)", "var(--color-chart-5)"];
const SEVERITIES = [
  ["critical", "Critical", "var(--color-error)"],
  ["high", "High", "var(--color-chart-2)"],
  ["medium", "Medium", "var(--color-warning)"],
  ["low", "Low", "var(--color-chart-1)"],
];
const HEALTH_BADGES = {
  healthy: "status-badge--ok",
  warning: "status-badge--warning",
  partial: "status-badge--warning",
  critical: "status-badge--error",
  unavailable: "status-badge--neutral",
};

const $ = (id) => document.getElementById(id);

const dom = {
  refresh: $("fleet-refresh-button"),
  updated: $("fleet-updated"),
  error: $("fleet-error"),
  errorText: $("fleet-error-text"),
  kpis: $("fleet-kpis"),
  namespacesChart: $("fleet-namespaces-chart"),
  healthRings: $("fleet-health-rings"),
  findingsChart: $("fleet-findings-chart"),
  findingsLegend: $("fleet-findings-legend"),
  tableBody: $("fleet-table-body"),
  manage: $("fleet-manage-button"),
  storageChart: $("fleet-storage-chart"),
  activityBody: $("fleet-activity-body"),
  findingsList: $("fleet-findings-list"),
};

let instances = [];         // from GET /api/iris/instances
let results = new Map();    // instance id -> what that instance returned
let showAll = false;
let loadToken = 0;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fulfilled(result) {
  return result && result.status === "fulfilled" ? result.value : null;
}

function resultOf(response) {
  return response && response.result !== undefined ? response.result : null;
}

function connectionOf(instance) {
  try {
    return new URL(instance.base_url).host;
  } catch {
    return "";
  }
}

function formatNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : PLACEHOLDER;
}

function shortVersion(serverVersion) {
  if (typeof serverVersion !== "string") return PLACEHOLDER;
  const match = serverVersion.match(/\b(20\d\d\.\d+(?:\.\d+)?)\s*\(Build ([^)]+)\)/);
  return match ? `${match[1]} (${match[2]})` : serverVersion;
}

function activeInstances() {
  return instances.filter((instance) => instance.active);
}

// What one instance returned, as plain values (null where it didn't answer).
function summarize(instance) {
  const result = results.get(instance.id);
  if (!result) return { state: instance.active ? "loading" : "inactive" };
  const list = (key) => {
    const value = resultOf(fulfilled(result[key]));
    return Array.isArray(value) ? value : null;
  };
  const info = resultOf(fulfilled(result.info));
  const monitor = resultOf(fulfilled(result.monitor));
  const health = fulfilled(result.health);
  // /health answers 200 with status "unavailable" when it couldn't reach IRIS,
  // so that answer alone doesn't make an instance reachable or count findings.
  const healthAnswered = Boolean(health) && health.status !== "unavailable";
  const storage = list("storage");
  const answered = Object.entries(result).some(([key, settled]) =>
    settled.status === "fulfilled" && (key !== "health" || healthAnswered));
  return {
    state: answered ? "ok" : "unavailable",
    version: info ? info.serverVersion : null,
    namespaces: list("namespaces"),
    databases: list("databases"),
    processes: list("processes"),
    webApps: list("webApps"),
    tasks: list("tasks"),
    health,
    findings: healthAnswered && Array.isArray(health.findings) ? health.findings : null,
    monitor,
    storageMb: storage ? storage.reduce((sum, db) => sum + (typeof db.Size === "number" ? db.Size : 0), 0) : null,
  };
}

function label(instance) {
  return instance.primary ? `${instance.name} (Primary)` : instance.name;
}

// --- KPI cards ---

function kpiCard(icon, tone, value, title, meta) {
  const card = el("article", `fleet-kpi fleet-kpi--${tone}`);
  card.append(el("span", "fleet-kpi__icon", icon));
  const body = el("div", "fleet-kpi__body");
  body.append(el("p", "fleet-kpi__value", value), el("h3", "fleet-kpi__title", title), el("p", "fleet-kpi__meta", meta));
  card.append(body);
  return card;
}

// Sum of `pick(summary)` over the active instances that returned it.
function total(summaries, pick) {
  const values = summaries.map(pick).filter((value) => typeof value === "number");
  return {
    value: values.length ? values.reduce((a, b) => a + b, 0) : null,
    meta: values.length === summaries.length
      ? `Across ${summaries.length} instance${summaries.length === 1 ? "" : "s"}`
      : `Across ${values.length} of ${summaries.length} instances`,
  };
}

function renderKpis(summaries) {
  const count = (key) => (s) => (s[key] ? s[key].length : null);
  const reachable = summaries.filter((s) => s.state === "ok").length;
  const namespaces = total(summaries, count("namespaces"));
  const processes = total(summaries, count("processes"));
  const tasks = total(summaries, count("tasks"));
  const findings = total(summaries, count("findings"));
  dom.kpis.replaceChildren(
    kpiCard("⬢", "accent", String(summaries.length), "Active Instances",
      `of ${instances.length} registered · ${reachable} reachable`),
    kpiCard("▦", "green", formatNumber(namespaces.value), "Total Namespaces", namespaces.meta),
    kpiCard("⚙", "violet", formatNumber(processes.value), "Processes", processes.meta),
    kpiCard("↻", "amber", formatNumber(tasks.value), "Scheduled Tasks", tasks.meta),
    kpiCard("⚠", "red", formatNumber(findings.value), "Health Findings", findings.meta),
  );
}

// --- charts (plain CSS bars and rings, like viz.js) ---

function renderColumnChart(container, columns) {
  container.replaceChildren();
  const max = Math.max(1, ...columns.flatMap((column) => column.segments.map((segment) => segment.value)),
    ...columns.map((column) => column.segments.reduce((sum, segment) => sum + segment.value, 0)));
  for (const column of columns) {
    const item = el("div", "fleet-bars__column");
    const totalValue = column.segments.reduce((sum, segment) => sum + segment.value, 0);
    item.append(el("span", "fleet-bars__value", column.missing ? PLACEHOLDER : String(totalValue)));
    const bar = el("div", "fleet-bars__bar");
    for (const segment of column.segments) {
      if (!segment.value) continue;
      const part = el("div", "fleet-bars__segment");
      part.style.height = `${(segment.value / max) * 100}%`;
      part.style.background = segment.color;
      part.title = `${column.name}: ${segment.label ? `${segment.label} ` : ""}${segment.value}`;
      bar.append(part);
    }
    item.append(bar, el("span", "fleet-bars__label", column.name));
    container.append(item);
  }
}

function ring(title, done, of, detail) {
  const box = el("div", "fleet-ring");
  const percent = of ? Math.round((done / of) * 100) : null;
  const circle = el("div", "fleet-ring__circle");
  circle.style.setProperty("--fleet-ring", `${percent ?? 0}%`);
  circle.append(el("span", "fleet-ring__value", percent === null ? PLACEHOLDER : `${percent}%`));
  box.append(circle, el("p", "fleet-ring__count", of ? `${done} / ${of}` : PLACEHOLDER), el("p", "fleet-ring__title", title));
  if (detail) box.title = detail;
  return box;
}

function renderHealthRings(summaries) {
  const ok = summaries.filter((s) => s.state === "ok");
  const databases = ok.flatMap((s) => s.databases || []);
  const webApps = ok.flatMap((s) => s.webApps || []);
  const healthy = summaries.filter((s) => s.health && s.health.status === "healthy").length;
  dom.healthRings.replaceChildren(
    ring("Instances Reachable", ok.length, summaries.length, "Instances that answered this refresh"),
    ring("Health Checks Passed", healthy, summaries.length, "Instances whose health report status is healthy"),
    ring("Databases Mounted", databases.filter((db) => typeof db.Status === "string" && db.Status.startsWith("Mounted")).length,
      databases.length, "Across the reachable instances"),
    ring("Web Apps Enabled", webApps.filter((app) => app.Enabled === true).length, webApps.length,
      "Across the reachable instances"),
  );
}

function renderFindingsChart(active, summaries) {
  renderColumnChart(dom.findingsChart, active.map((instance, i) => {
    const findings = summaries[i].findings;
    return {
      name: instance.name,
      missing: findings === null,
      segments: SEVERITIES.map(([key, name, color]) => ({
        label: name, color, value: findings ? findings.filter((f) => f.severity === key).length : 0,
      })),
    };
  }));
  dom.findingsLegend.replaceChildren(...SEVERITIES.map(([, name, color]) => {
    const item = el("span", "fleet-legend__item", name);
    item.style.setProperty("--fleet-legend-color", color);
    return item;
  }));
}

function renderStorage(active, summaries) {
  dom.storageChart.replaceChildren();
  const max = Math.max(1, ...summaries.map((s) => s.storageMb || 0));
  active.forEach((instance, i) => {
    const mb = summaries[i].storageMb;
    const row = el("div", "fleet-hbars__row");
    const track = el("div", "fleet-hbars__track");
    const fill = el("div", "fleet-hbars__fill");
    fill.style.width = `${mb ? (mb / max) * 100 : 0}%`;
    fill.style.background = COLORS[i % COLORS.length];
    track.append(fill);
    const value = typeof mb === "number" ? (mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toLocaleString()} MB`) : PLACEHOLDER;
    row.append(el("span", "fleet-hbars__label", instance.name), track, el("span", "fleet-hbars__value", value));
    dom.storageChart.append(row);
  });
}

function renderActivity(active, summaries) {
  dom.activityBody.replaceChildren(...active.map((instance, i) => {
    const monitor = summaries[i].monitor;
    const row = el("tr");
    const cells = [
      instance.name,
      formatNumber(monitor?.Performance?.GlobalRefsPerSecond),
      typeof monitor?.Performance?.CacheEfficiency === "number" ? monitor.Performance.CacheEfficiency.toFixed(2) : PLACEHOLDER,
      formatNumber(monitor?.SystemUsage?.CSPSessions),
    ];
    for (const text of cells) row.append(el("td", "data-table__cell", text));
    return row;
  }));
}

function renderFindingsList(active, summaries) {
  const items = active.flatMap((instance, i) => (summaries[i].findings || []).map((finding) => ({ instance, finding })));
  const order = Object.fromEntries(SEVERITIES.map(([key], i) => [key, i]));
  items.sort((a, b) => (order[a.finding.severity] ?? 9) - (order[b.finding.severity] ?? 9));
  if (!items.length) {
    const reported = summaries.some((s) => s.findings !== null);
    dom.findingsList.replaceChildren(el("li", "fleet-findings__empty",
      reported ? "No findings reported by the health checks." : "No health report was returned."));
    return;
  }
  dom.findingsList.replaceChildren(...items.map(({ instance, finding }) => {
    const item = el("li", "fleet-findings__item");
    const severity = SEVERITIES.find(([key]) => key === finding.severity);
    const badge = el("span", "status-badge fleet-findings__severity", severity ? severity[1] : finding.severity);
    badge.style.setProperty("--fleet-severity", severity ? severity[2] : "var(--color-text-faint)");
    item.append(badge, el("span", "fleet-findings__instance", instance.name), el("span", "fleet-findings__title", finding.title));
    return item;
  }));
}

// --- Instances Overview table ---

function statusBadge(summary, instance) {
  let text;
  let variant;
  if (!instance.active) [text, variant] = ["Inactive", "status-badge--neutral"];
  else if (summary.state === "loading") [text, variant] = ["Loading…", "status-badge--neutral"];
  else if (summary.state === "unavailable") [text, variant] = ["Unavailable", "status-badge--error"];
  else if (summary.health) [text, variant] = [summary.health.status, HEALTH_BADGES[summary.health.status] || "status-badge--neutral"];
  else [text, variant] = ["No health report", "status-badge--warning"];
  return el("span", `status-badge ${variant}`, text.replace(/_/g, " "));
}

function renderTable() {
  const shown = showAll ? instances : activeInstances();
  dom.tableBody.replaceChildren(...shown.map((instance) => {
    const s = summarize(instance);
    const row = el("tr");
    row.dataset.instanceId = instance.id;
    const name = el("td", "data-table__cell");
    name.append(el("span", "fleet-table__name", instance.primary ? `${instance.name} ★` : instance.name),
      el("span", "fleet-table__meta", instance.primary ? `Primary · ${connectionOf(instance)}` : connectionOf(instance)));
    const status = el("td", "data-table__cell");
    status.append(statusBadge(s, instance));
    const count = (list) => (list ? String(list.length) : PLACEHOLDER);
    const license = s.monitor?.Licensing?.LicenseUse;
    const lastCheck = instance.last_check && instance.last_check.checked_at
      ? new Date(instance.last_check.checked_at).toLocaleString() : PLACEHOLDER;
    const open = el("td", "data-table__cell");
    if (instance.active) {
      const button = el("button", "btn btn--sm", "Open");
      button.type = "button";
      button.dataset.fleetOpen = instance.id;
      button.title = `Select ${instance.name} in the header and open its Dashboard`;
      open.append(button);
    }
    row.append(
      name, status,
      el("td", "data-table__cell", shortVersion(s.version)),
      el("td", "data-table__cell", count(s.namespaces)),
      el("td", "data-table__cell", count(s.databases)),
      el("td", "data-table__cell", count(s.processes)),
      el("td", "data-table__cell", count(s.webApps)),
      el("td", "data-table__cell", count(s.tasks)),
      el("td", "data-table__cell", count(s.findings)),
      el("td", "data-table__cell", s.monitor?.Status?.UpTime || PLACEHOLDER),
      el("td", "data-table__cell", typeof license === "number" ? `${license}%` : license === "" ? "No limit" : PLACEHOLDER),
      el("td", "data-table__cell", lastCheck),
      open,
    );
    return row;
  }));
}

function render() {
  const active = activeInstances();
  const summaries = active.map(summarize);
  renderKpis(summaries);
  renderColumnChart(dom.namespacesChart, active.map((instance, i) => ({
    name: instance.name,
    missing: !summaries[i].namespaces,
    segments: [{ color: COLORS[i % COLORS.length], value: summaries[i].namespaces ? summaries[i].namespaces.length : 0 }],
  })));
  renderHealthRings(summaries);
  renderFindingsChart(active, summaries);
  renderTable();
  renderStorage(active, summaries);
  renderActivity(active, summaries);
  renderFindingsList(active, summaries);
}

async function loadInstance(instance, token) {
  const id = instance.primary ? undefined : instance.id;
  const keys = ["info", "namespaces", "databases", "processes", "webApps", "tasks", "health", "monitor", "storage"];
  const settled = await Promise.allSettled([
    IrisApi.getInfo(id),
    IrisApi.getNamespaces(id),
    IrisApi.getDatabases(id),
    IrisApi.getProcesses(id),
    IrisApi.getWebApps(id),
    IrisApi.getTasks(id),
    IrisApi.getHealthReport(id),
    IrisApi.getMonitorDashboard(id),
    IrisApi.getDatabaseStorage(id),
  ]);
  if (token !== loadToken) return;
  results.set(instance.id, Object.fromEntries(keys.map((key, i) => [key, settled[i]])));
  render();
}

export async function loadFleet() {
  const token = ++loadToken;
  dom.refresh.disabled = true;
  dom.refresh.classList.add("btn--spinning");
  dom.error.hidden = true;
  try {
    const response = await IrisApi.getInstances();
    if (token !== loadToken) return;
    instances = Array.isArray(response && response.instances) ? response.instances : [];
  } catch (error) {
    if (token !== loadToken) return;
    dom.errorText.textContent = error instanceof ApiError
      ? `Could not load the instance list. ${error.message}`
      : "Could not load the instance list.";
    dom.error.hidden = false;
    dom.refresh.disabled = false;
    dom.refresh.classList.remove("btn--spinning");
    return;
  }
  results = new Map();
  render();
  // Each instance loads on its own; one that fails doesn't hold up the others.
  await Promise.all(activeInstances().map((instance) => loadInstance(instance, token)));
  if (token !== loadToken) return;
  dom.updated.textContent = new Date().toLocaleString();
  dom.refresh.disabled = false;
  dom.refresh.classList.remove("btn--spinning");
}

export function initFleetControls() {
  dom.refresh.addEventListener("click", () => {
    loadFleet();
  });
  dom.manage.addEventListener("click", () => navigateTo("instances"));
  document.querySelectorAll("[data-fleet-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      showAll = button.dataset.fleetFilter === "all";
      document.querySelectorAll("[data-fleet-filter]").forEach((other) => {
        other.setAttribute("aria-pressed", String(other === button));
      });
      renderTable();
    });
  });
  dom.tableBody.addEventListener("click", (event) => {
    const button = event.target.closest("[data-fleet-open]");
    if (button && selectInstanceContext(button.dataset.fleetOpen)) navigateTo("dashboard");
  });
}
