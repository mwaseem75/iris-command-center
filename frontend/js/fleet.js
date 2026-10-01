// Fleet Overview ("All Active Instances"): one monitoring section per active
// IRIS instance, each read on its own. Nothing is added up across instances.
// Read-only; it has no change controls.
//
// Each active instance is read by id through the same instance-scoped read
// routes as the other pages: the Primary without ?instance=, the others with
// their own id, never ?instance=all, and a failed instance never falls back
// to the Primary.
// - /info: the IRIS version;
// - /monitor/dashboard: uptime, database and journal status, alerts, global
//   references/s, web sessions, license use and the performance counters;
// - /processes: the process count (the list the Processes page shows);
// - /health: the health status and its number of findings.
// While the page is shown and the tab visible, /monitor/dashboard is read
// again every REFRESH_INTERVAL_MS and everything every FULL_EVERY_TICKS
// ticks; the Global References trend is drawn from those samples, like the
// Dashboard's, so it's a live trend that starts when the page is opened (no
// history is stored or fetched). The metric cards' mini charts use the same
// samples, and the process counts from the full reads. A value an instance didn't return shows as "—", and an
// instance that answered nothing shows as unavailable while the others still
// load.
//
// Every View link selects that instance in the instance selector and opens the
// existing page for it. An instance that can't be read is shown unavailable
// with its links disabled; if the selector can't select an instance (it
// doesn't answer its check), the link says so in that section instead.

import { IrisApi, ApiError } from "./api.js";
import { makeSparkline, renderTrendChart } from "./dashboard.js";
import { refreshInstanceContext, selectInstanceContext } from "./instance-context.js";
import { navigateTo } from "./nav.js";
import { focusWebSessions } from "./web-apps.js";

const PLACEHOLDER = "—";
const REFRESH_INTERVAL_MS = 15000;
const FULL_EVERY_TICKS = 4;
const MAX_SAMPLES = 60;
const COLORS = ["var(--color-success)", "var(--color-chart-2)", "var(--color-chart-6)", "var(--color-chart-1)",
  "var(--color-warning)"];

// Where each View link goes: [page, its name, element to scroll to there].
// Web Sessions sits below the asynchronously loaded app list, so the Web Apps
// page brings it into view itself once it has loaded (focusWebSessions).
const TARGETS = {
  details: ["dashboard", "Dashboard"],
  health: ["health-center", "Health Center"],
  databases: ["databases", "Databases"],
  journal: ["journal", "Journal"],
  processes: ["processes", "Processes"],
  performance: ["dashboard", "Dashboard (System Resource Usage)", "dashboard-resources-title"],
  sessions: ["web-apps", "Web Apps (Web Sessions)", null, "web-sessions"],
  license: ["dashboard", "Dashboard (License)", "stat-license"],
};

const FOCUS = { "web-sessions": focusWebSessions };

const $ = (id) => document.getElementById(id);

const dom = {
  view: $("view-fleet"),
  refresh: $("fleet-refresh-button"),
  updated: $("fleet-updated"),
  count: $("fleet-count"),
  error: $("fleet-error"),
  errorText: $("fleet-error-text"),
  instances: $("fleet-instances"),
  note: $("fleet-note"),
};

let instances = [];           // from GET /api/iris/instances
const reads = new Map();      // instance id -> { results: {key: settled}, round: [keys read last] }
const samples = new Map();    // instance id -> [{ time, globalRefsPerSecond, cspSessions }], oldest first
const processCounts = new Map();  // instance id -> process counts from the full reads, oldest first
const sections = new Map();   // instance id -> its <article>
let loadToken = 0;
let timer = null;
let tickCount = 0;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function settledValue(settled) {
  return settled && settled.status === "fulfilled" ? settled.value : null;
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

function formatNumber(value, digits = 0) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: digits })
    : PLACEHOLDER;
}

function formatCompact(value) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(undefined, { notation: "compact", maximumFractionDigits: 1 })
    : PLACEHOLDER;
}

function shortVersion(serverVersion) {
  if (typeof serverVersion !== "string") return PLACEHOLDER;
  const match = serverVersion.match(/\b(20\d\d\.\d+(?:\.\d+)?)\s*\(Build ([^)]+)\)/);
  return match ? `IRIS ${match[1]} (${match[2]})` : serverVersion;
}

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1).replace(/_/g, " ");
}

function activeInstances() {
  return instances.filter((instance) => instance.active);
}

// What one instance returned, as plain values (null where it didn't answer).
function summarize(instance) {
  const entry = reads.get(instance.id);
  if (!entry) return { state: "loading" };
  const value = (key) => settledValue(entry.results[key]);
  const report = value("health");
  // /health answers 200 with status "unavailable" when it couldn't reach
  // IRIS, so that answer alone doesn't make an instance reachable.
  const health = report && report.status !== "unavailable" ? report : null;
  const processes = resultOf(value("processes"));
  const reachable = entry.round.some((key) =>
    entry.results[key].status === "fulfilled" && (key !== "health" || health !== null));
  const failure = entry.round.map((key) => entry.results[key]).find((settled) => settled.status === "rejected");
  return {
    state: reachable ? "ok" : "unavailable",
    error: failure && failure.reason instanceof ApiError && failure.reason.status ? `HTTP ${failure.reason.status}` : null,
    info: resultOf(value("info")),
    monitor: resultOf(value("monitor")),
    processes: Array.isArray(processes) ? processes.length : null,
    health,
  };
}

// --- one instance's section ---

// With `unavailable`, the link is disabled: that instance can't be opened.
function link(instance, target, text, className = "fleet-link", unavailable = false) {
  const [view, page, anchor, focus] = TARGETS[target];
  const button = el("button", className, text);
  button.type = "button";
  button.dataset.fleetOpen = instance.id;
  button.dataset.fleetView = view;
  if (anchor) button.dataset.fleetAnchor = anchor;
  if (focus) button.dataset.fleetFocus = focus;
  button.title = `Select ${instance.name} and open ${page}`;
  if (unavailable) {
    button.disabled = true;
    button.title = `${instance.name} isn't reachable right now, so its pages can't be opened`;
  }
  return button;
}

function statusTone(text) {
  if (typeof text !== "string" || !text) return "neutral";
  return text === "Normal" ? "ok" : "warning";
}

// One fact in the header row; with a target it's a button to that page.
function fact(instance, label, value, { meta, tone, target, title, unavailable } = {}) {
  const node = target ? link(instance, target, undefined, "fleet-fact fleet-fact--link", unavailable) : el("div", "fleet-fact");
  node.append(el("span", "fleet-fact__label", label));
  const valueNode = el("span", "fleet-fact__value", value);
  if (tone) {
    valueNode.classList.add("fleet-fact__value--dot");
    valueNode.dataset.tone = tone;
  }
  node.append(valueNode);
  if (meta) node.append(el("span", "fleet-fact__meta", meta));
  if (title && !unavailable) node.title = node.title ? `${title} ${node.title}.` : title;
  return node;
}

function renderHead(instance, s) {
  const head = el("div", "fleet-instance__head");
  const identity = el("div", "fleet-instance__identity");
  const icon = el("span", "fleet-instance__icon", "⬢");
  icon.setAttribute("aria-hidden", "true");
  const names = el("div", "fleet-instance__names");
  const name = el("h3", "fleet-instance__name", instance.name);
  if (instance.primary) name.append(el("span", "fleet-instance__badge", "★ Primary"));
  names.append(name, el("span", "fleet-instance__host", connectionOf(instance)));
  identity.append(icon, names);

  const usage = s.monitor?.SystemUsage;
  const journal = [usage?.DatabaseJournal, usage?.JournalSpace];
  const journalStatus = journal.every((value) => value === "Normal")
    ? "Normal"
    : journal.find((value) => typeof value === "string" && value && value !== "Normal") ?? PLACEHOLDER;
  const alerts = s.monitor?.Alerts?.SeriousAlerts;
  const findings = s.health && Array.isArray(s.health.findings) ? s.health.findings.length : null;
  const status = { loading: ["Loading…", "neutral"], unavailable: ["Unavailable", "error"], ok: ["Connected", "ok"] }[s.state];
  const unavailable = s.state === "unavailable";

  const facts = el("div", "fleet-instance__facts");
  facts.append(
    fact(instance, "Status", status[0], { tone: status[1], meta: shortVersion(s.info?.serverVersion) }),
    fact(instance, "Uptime", typeof s.monitor?.Status?.UpTime === "string" ? s.monitor.Status.UpTime.replace(/\s+/g, " ") : PLACEHOLDER),
    fact(instance, "Database", usage?.DatabaseSpace || PLACEHOLDER, { tone: statusTone(usage?.DatabaseSpace), target: "databases", unavailable,
      title: "Database space (IRIS System Dashboard)." }),
    fact(instance, "Journal", journalStatus, { tone: statusTone(journalStatus === PLACEHOLDER ? null : journalStatus), target: "journal", unavailable,
      title: `Database journal: ${usage?.DatabaseJournal || PLACEHOLDER} · Journal space: ${usage?.JournalSpace || PLACEHOLDER}.` }),
    fact(instance, "Alerts", formatNumber(alerts), {
      tone: typeof alerts === "number" ? (alerts > 0 ? "warning" : "ok") : null,
      meta: s.health ? `Health: ${capitalize(s.health.status)} · ${findings} finding${findings === 1 ? "" : "s"}` : "No health report",
      target: "health",
      unavailable,
      title: "Serious alerts (IRIS System Dashboard) and the health checks.",
    }),
  );
  head.append(identity, facts, link(instance, "details", "View Details →", "btn btn--primary fleet-instance__details", unavailable));
  return head;
}

// A compact metric card: label and View on top, the value beside a small
// chart of that instance's own readings, one line of context below.
function tile(instance, label, value, gadget, meta, target, live = false) {
  const node = el("div", "fleet-tile");
  const top = el("div", "fleet-tile__top");
  top.append(el("span", "fleet-tile__label", label), link(instance, target, "View →"));
  const body = el("div", "fleet-tile__body");
  body.append(el("span", "fleet-tile__value", value), gadget);
  node.append(top, body, el("span", live ? "fleet-tile__meta fleet-tile__meta--live" : "fleet-tile__meta", meta));
  return node;
}

// Mini bar chart of the last few counts, scaled to the largest.
function miniBars(counts) {
  const bars = el("div", "fleet-tile__gadget fleet-bars-mini");
  const top = Math.max(1, ...counts);
  for (const count of counts) {
    const bar = el("span", "fleet-bars-mini__bar");
    bar.style.height = `${Math.max(8, (count / top) * 100)}%`;
    bar.title = String(count);
    bars.append(bar);
  }
  return bars;
}

function sparkline(values) {
  const box = el("div", "fleet-tile__gadget fleet-tile__spark");
  box.append(makeSparkline(values));
  return box;
}

// Usage bar with a tick at the peak.
function usageBar(percent, peak) {
  const bar = el("div", "fleet-tile__gadget fleet-usage");
  const clamp = (value) => `${Math.max(0, Math.min(100, value))}%`;
  const fill = el("span", "fleet-usage__fill");
  fill.style.width = typeof percent === "number" ? clamp(percent) : "0%";
  bar.append(fill);
  if (typeof peak === "number") {
    const mark = el("span", "fleet-usage__peak");
    mark.style.left = clamp(peak);
    mark.title = `peak ${peak}%`;
    bar.append(mark);
  }
  return bar;
}

function renderTiles(instance, s) {
  const perf = s.monitor?.Performance;
  const licensing = s.monitor?.Licensing;
  const license = licensing?.LicenseUse;
  const peak = licensing?.LicenseUseHigh;
  const series = samples.get(instance.id) || [];
  const counts = (processCounts.get(instance.id) || []).slice(-12);
  const change = counts.length > 1 ? counts[counts.length - 1] - counts[counts.length - 2] : null;
  const refs = series.map((sample) => sample.globalRefsPerSecond).filter((v) => typeof v === "number");
  const sessions = series.map((sample) => sample.cspSessions);

  const tiles = el("div", "fleet-instance__tiles");
  tiles.append(
    tile(instance, "Processes", formatNumber(s.processes), miniBars(counts),
      change === null ? "first reading" : change === 0 ? "no change since last read"
        : `${change > 0 ? "▲" : "▼"} ${Math.abs(change)} since last read`, "processes"),
    tile(instance, "Global References / sec",
      typeof perf?.GlobalRefsPerSecond === "number" ? `${formatNumber(perf.GlobalRefsPerSecond)} /s` : PLACEHOLDER,
      sparkline(series.map((sample) => sample.globalRefsPerSecond)),
      refs.length > 1 ? `range ${formatNumber(Math.min(...refs))}–${formatNumber(Math.max(...refs))} /s` : "sampling every 15 s",
      "performance"),
    tile(instance, "Web Sessions", formatNumber(s.monitor?.SystemUsage?.CSPSessions), sparkline(sessions),
      "live · every 15 s", "sessions", true),
    tile(instance, "License Usage", typeof license === "number" ? `${license}%` : license === "" ? "No limit" : PLACEHOLDER,
      usageBar(typeof license === "number" ? license : null, peak),
      typeof peak === "number" ? `peak ${peak}%` : PLACEHOLDER, "license"),
  );
  return tiles;
}

function panel(instance, title, target, body, caption) {
  const node = el("section", "info-card fleet-panel");
  const head = el("div", "fleet-panel__head");
  head.append(el("h4", "fleet-panel__title", title), link(instance, target, "View →"));
  node.append(head);
  if (caption) node.append(el("p", "fleet-panel__caption", caption));
  node.append(body);
  return node;
}

function renderLower(instance, s) {
  const trend = el("div", "dash-trend fleet-trend");
  renderTrendChart(trend, samples.get(instance.id) || [], "Global references / s", (sample) => sample.globalRefsPerSecond);

  const perf = s.monitor?.Performance;
  const table = el("table", "data-table data-table--compact fleet-perf");
  const thead = el("thead");
  const headRow = el("tr");
  headRow.append(el("th", undefined, "Metric"), el("th", undefined, "Value"));
  thead.append(headRow);
  const tbody = el("tbody");
  const rows = [
    ["Cache Efficiency", formatNumber(perf?.CacheEfficiency, 2), perf?.CacheEfficiency],
    ["Global References Since Startup", formatCompact(perf?.GlobalRefs), perf?.GlobalRefs],
    ["Disk Reads Since Startup", formatCompact(perf?.DiskReads), perf?.DiskReads],
    ["Disk Writes Since Startup", formatCompact(perf?.DiskWrites), perf?.DiskWrites],
  ];
  for (const [metric, text, exact] of rows) {
    const row = el("tr");
    const cell = el("td", "data-table__cell", text);
    if (typeof exact === "number") cell.title = exact.toLocaleString();
    row.append(el("td", "data-table__cell", metric), cell);
    tbody.append(row);
  }
  table.append(thead, tbody);

  const lower = el("div", "fleet-instance__lower");
  lower.append(
    panel(instance, "Global References / Second (live)", "performance", trend,
      "Current trend, sampled every 15 s while this page is open. Not historical data."),
    panel(instance, "Performance Context", "performance", table),
  );
  return lower;
}

function renderSection(instance) {
  let section = sections.get(instance.id);
  if (!section) {
    section = el("article", "fleet-instance");
    section.dataset.instanceId = instance.id;
    sections.set(instance.id, section);
  }
  const index = activeInstances().indexOf(instance);
  section.style.setProperty("--fleet-instance-color", COLORS[Math.max(0, index) % COLORS.length]);
  section.setAttribute("aria-label", instance.primary ? `${instance.name} (Primary)` : instance.name);
  const s = summarize(instance);
  section.dataset.state = s.state;
  section.replaceChildren(renderHead(instance, s));
  if (s.state === "ok") {
    section.append(renderTiles(instance, s), renderLower(instance, s));
  } else if (s.state === "unavailable") {
    const notice = el("p", "fleet-instance__notice",
      `${instance.name} could not be read${s.error ? ` (${s.error})` : ""}. The other instances are not affected.`);
    notice.setAttribute("role", "status");
    section.append(notice);
  }
  return section;
}

function renderAll() {
  const active = activeInstances();
  for (const id of [...sections.keys()]) {
    if (!active.some((instance) => instance.id === id)) {
      sections.delete(id);
      reads.delete(id);
      samples.delete(id);
      processCounts.delete(id);
    }
  }
  dom.count.textContent = `${active.length} / ${instances.length}`;
  dom.instances.replaceChildren(...(active.length
    ? active.map(renderSection)
    : [el("p", "info-card__empty", "No active instances. Activate one on the Instances page.")]));
  const inactive = instances.length - active.length;
  dom.note.hidden = inactive === 0;
  dom.note.textContent = inactive
    ? `${inactive} inactive instance${inactive === 1 ? " is" : "s are"} not shown (see the Instances page).`
    : "";
}

// --- loading ---

async function readInstance(instance, full, token) {
  const id = instance.primary ? undefined : instance.id;
  const calls = full
    ? { info: IrisApi.getInfo(id), processes: IrisApi.getProcesses(id), health: IrisApi.getHealthReport(id),
      monitor: IrisApi.getMonitorDashboard(id) }
    : { monitor: IrisApi.getMonitorDashboard(id) };
  const keys = Object.keys(calls);
  const settled = await Promise.allSettled(Object.values(calls));
  if (token !== loadToken) return;
  const entry = reads.get(instance.id) || { results: {} };
  keys.forEach((key, i) => { entry.results[key] = settled[i]; });
  entry.round = keys;
  reads.set(instance.id, entry);
  const monitor = resultOf(settledValue(entry.results.monitor));
  if (settled[keys.indexOf("monitor")].status === "fulfilled" && monitor) {
    const list = samples.get(instance.id) || [];
    samples.set(instance.id, [...list, { time: Date.now(), globalRefsPerSecond: monitor.Performance?.GlobalRefsPerSecond,
      cspSessions: monitor.SystemUsage?.CSPSessions }].slice(-MAX_SAMPLES));
  }
  const processes = resultOf(settledValue(entry.results.processes));
  if (keys.includes("processes") && settled[keys.indexOf("processes")].status === "fulfilled" && Array.isArray(processes)) {
    processCounts.set(instance.id, [...(processCounts.get(instance.id) || []), processes.length].slice(-MAX_SAMPLES));
  }
  renderSection(instance);
}

async function refresh(full) {
  const token = loadToken;
  if (full) {
    let response;
    try {
      response = await IrisApi.getInstances();
    } catch (error) {
      if (token !== loadToken) return;
      dom.errorText.textContent = error instanceof ApiError
        ? `Could not load the instance list. ${error.message}`
        : "Could not load the instance list.";
      dom.error.hidden = false;
      return;
    }
    if (token !== loadToken) return;
    dom.error.hidden = true;
    instances = Array.isArray(response && response.instances) ? response.instances : [];
    renderAll();
  }
  // Each instance loads on its own; one that fails doesn't hold up the others.
  await Promise.all(activeInstances().map((instance) => readInstance(instance, full, token)));
  if (token === loadToken) dom.updated.textContent = new Date().toLocaleString();
}

function isActive() {
  return !document.hidden && !dom.view.hidden;
}

function stopPolling() {
  if (timer !== null) clearTimeout(timer);
  timer = null;
}

function scheduleNext() {
  stopPolling();
  if (!isActive()) return;
  timer = setTimeout(async () => {
    timer = null;
    if (!isActive()) return;
    const token = loadToken;
    tickCount += 1;
    await refresh(tickCount % FULL_EVERY_TICKS === 0);
    if (token === loadToken) scheduleNext();
  }, REFRESH_INTERVAL_MS);
}

/** Read every active instance now and (re)start the refresh cycle. */
export async function loadFleet() {
  stopPolling();
  tickCount = 0;
  const token = ++loadToken;
  dom.refresh.disabled = true;
  dom.refresh.classList.add("btn--spinning");
  await refresh(true);
  if (token !== loadToken) return;
  dom.refresh.disabled = false;
  dom.refresh.classList.remove("btn--spinning");
  scheduleNext();
}

// In that instance's section: its pages can't be opened right now.
function showNotSelectable(id) {
  const instance = instances.find((entry) => entry.id === id);
  const section = sections.get(id);
  if (!instance || !section) return;
  const notice = el("p", "fleet-instance__notice",
    `${instance.name} isn't reachable from the Command Center right now, so its pages can't be opened. Try Refresh All.`);
  notice.setAttribute("role", "status");
  notice.dataset.fleetBlocked = "true";
  const old = section.children ? [...section.children].find((child) => child.dataset && child.dataset.fleetBlocked) : null;
  if (old) old.replaceWith(notice);
  else section.append(notice);
}

export function initFleetControls() {
  dom.refresh.addEventListener("click", () => {
    loadFleet();
  });
  // A View link: select that instance in the instance selector, then open the page.
  dom.instances.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-fleet-view]");
    if (!button || button.disabled) return;
    const id = button.dataset.fleetOpen;
    // The selector only takes instances that answer now: check them first,
    // and if this one doesn't, say so rather than doing nothing.
    await refreshInstanceContext();
    if (!selectInstanceContext(id)) {
      showNotSelectable(id);
      return;
    }
    if (button.dataset.fleetFocus) FOCUS[button.dataset.fleetFocus]();
    navigateTo(button.dataset.fleetView);
    const anchor = button.dataset.fleetAnchor ? $(button.dataset.fleetAnchor) : null;
    if (anchor) anchor.scrollIntoView({ block: "start" });
  });
  // Pause while the tab is hidden; reload when it's visible again.
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopPolling();
    else if (!dom.view.hidden) loadFleet();
  });
}
