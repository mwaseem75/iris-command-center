// Processes view: fetches GET /api/iris/processes ONLY and renders a
// read-only Processes Explorer — per-State KPI cards, the State
// Distribution strip, a client-side search/filter toolbar, a compact
// table, and a detail drawer. No other endpoint is called from this
// module, no mutating HTTP method is used anywhere in it, and there are
// deliberately no process actions (suspend/resume/terminate): the
// Can* capability flags are displayed as the facts IRIS reported, never
// wired to anything.
//
// Every value shown is a field backend/app/models/iris.py's ProcessEntry
// actually defines — the table shows a subset, the drawer shows all 21
// (see DRAWER_FIELDS). Every count (KPI cards, distribution, "Showing N of
// M") is computed from the same already-fetched array — nothing invented,
// no extra fetch. See docs/api-capability-matrix.md for how that shape was
// originally verified against a real IRIS instance.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { countBy, renderStackedBar, topCategories } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

// Same palette order viz.js's renderStackedBar() assigns, so a State's KPI
// card accent matches its segment in the State Distribution strip.
const CHART_COLORS = [1, 2, 3, 4, 5, 6].map((n) => `var(--color-chart-${n})`);
const NEUTRAL_COLOR = "var(--color-chart-neutral)";
const OVERVIEW_MAX_CATEGORIES = 6;

const dom = {
  loadingState: document.getElementById("processes-loading-state"),
  errorBanner: document.getElementById("processes-error-banner"),
  errorBannerText: document.getElementById("processes-error-banner-text"),
  refreshButton: document.getElementById("processes-refresh-button"),
  backButton: document.getElementById("processes-back-button"),
  connectionStatus: document.getElementById("processes-connection-status"),
  connectionStatusLabel: document.getElementById("processes-connection-status-label"),
  connectionDetail: document.getElementById("processes-connection-detail"),
  countLabel: document.getElementById("processes-count"),
  content: document.getElementById("processes-content"),
  summaryGrid: document.getElementById("processes-summary-grid"),
  tableWrapper: document.getElementById("processes-table-wrapper"),
  tableBody: document.getElementById("processes-table-body"),
  empty: document.getElementById("processes-empty"),
  overview: document.getElementById("processes-overview"),
  overviewViz: document.getElementById("processes-overview-viz"),
  filterForm: document.getElementById("processes-filter-form"),
  filterSearch: document.getElementById("processes-filter-search"),
  filterState: document.getElementById("processes-filter-state"),
  filterNamespace: document.getElementById("processes-filter-namespace"),
  filterClear: document.getElementById("processes-filter-clear-button"),
  filterCount: document.getElementById("processes-filter-count"),
  filterEmpty: document.getElementById("processes-filter-empty"),
  drawerBackdrop: document.getElementById("processes-drawer-backdrop"),
  drawer: document.getElementById("processes-drawer"),
  drawerTitle: document.getElementById("processes-drawer-title"),
  drawerStateBadge: document.getElementById("processes-drawer-state-badge"),
  drawerFields: document.getElementById("processes-drawer-fields"),
  drawerClose: document.getElementById("processes-drawer-close"),
};

// [drawer label, ProcessEntry field, value kind] — every field
// backend/app/models/iris.py's ProcessEntry defines, in the same order the
// model declares them. The raw field name is also shown as the label's
// tooltip so an administrator can map it back to IRIS's own naming.
const DRAWER_FIELDS = [
  ["Job", "Job", "mono"],
  ["PID", "Pid", "mono"],
  ["Username", "Username", "text"],
  ["Device", "Device", "mono"],
  ["Namespace", "Nspace", "text"],
  ["Routine", "Routine", "mono"],
  ["Commands", "Commands", "mono"],
  ["Globals", "Globals", "mono"],
  ["State", "State", "mono"],
  ["Client Name", "ClientName", "text"],
  ["EXE Name", "EXEname", "mono"],
  ["IP Address", "IPAddress", "mono"],
  ["Can Be Examined", "CanBeExamined", "bool"],
  ["Can Be Suspended", "CanBeSuspended", "bool"],
  ["Can Be Terminated", "CanBeTerminated", "bool"],
  ["Can Receive Broadcast", "CanReceiveBroadcast", "bool"],
  ["Private Global Block Count", "PrvGblBlkCnt", "mono"],
  ["OS Username", "OSUserName", "text"],
  ["CPU Time", "CPUTime", "cpu"],
  ["Parent PID", "ParentPid", "mono"],
  ["Elapsed Time", "ElapsedTime", "mono"],
];

// Real ProcessEntry fields the free-text search matches against.
const SEARCH_FIELDS = [
  "Pid", "Job", "Username", "Nspace", "Routine", "State", "Device",
  "ClientName", "EXEname", "IPAddress", "OSUserName", "ParentPid",
];

// The full list from the last successful fetch — filtering and the drawer
// both read from this; neither triggers a re-fetch.
let allProcesses = [];

// The Pid of whichever process the drawer currently shows (Pid is unique
// per live process), so a Refresh can re-render it with fresh values — or
// close the drawer honestly if that process no longer exists.
let currentDrawerPid = null;

// System daemons report an empty Nspace. It's offered as its own filter
// choice under this value, since "" already means "All namespaces" and
// parentheses can't appear in a real IRIS namespace name.
const NO_NAMESPACE = "(none)";

const stateKey = (proc) => proc.State || "Unknown";
const namespaceKey = (proc) => proc.Nspace || NO_NAMESPACE;

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js and system.js.
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

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatBoolean(value) {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : PLACEHOLDER;
}

function formatCpuTime(value) {
  // ProcessEntry.CPUTime is a plain int (milliseconds, per IRIS's own
  // %SYS.ProcessQuery convention) — not documented in our own OpenAPI
  // schema beyond "int", so the unit label is applied, not invented data.
  return typeof value === "number" ? `${value} ms` : PLACEHOLDER;
}

/** Classifies a real IRIS process State code (e.g. "RUN", "RUNW", "EVTW",
 * "READ", "HANG", "SEMW", "LOCK") into one of this app's existing
 * status-badge color variants — purely presentational; the badge text is
 * always the real, verbatim State. Actively running reads green, lock
 * waits and suspended processes amber (worth an administrator's glance),
 * and every other wait state neutral — idle waiting is normal. */
function stateBadgeVariant(state) {
  if (typeof state !== "string" || state.length === 0) return "status-badge--neutral";
  const upper = state.toUpperCase();
  if (upper.startsWith("RUN")) return "status-badge--ok";
  if (upper.includes("LOCK") || upper.includes("SUSP")) return "status-badge--warning";
  return "status-badge--neutral";
}

function makeStateBadge(state) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${stateBadgeVariant(state)}`;
  badge.textContent = textOrPlaceholder(state);
  return badge;
}

// Table rows are always built via document.createElement + .textContent —
// never innerHTML — so a routine/device/username containing HTML-special
// characters can never be interpreted as markup.
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

/** A real State-value distribution over the already-fetched array — the
 * same countBy()/topCategories() result the KPI cards are built from, so
 * the two always agree. Hidden entirely when there's nothing to show. */
function renderOverview(stateCounts) {
  if (stateCounts.length === 0) {
    dom.overview.hidden = true;
    return;
  }
  dom.overview.hidden = false;
  renderStackedBar(dom.overviewViz, topCategories(stateCounts, OVERVIEW_MAX_CATEGORIES));
}

function makeSummaryCard({ label, value, accent, state, title }) {
  const card = document.createElement("article");
  card.className = "stat-card stat-card--interactive";
  card.dataset.state = state;
  card.style.setProperty("--stat-card-accent", accent);
  card.setAttribute("role", "button");
  card.setAttribute("tabindex", "0");
  card.title = title;

  const labelEl = document.createElement("h3");
  labelEl.className = "stat-card__label";
  labelEl.textContent = label;

  const valueEl = document.createElement("p");
  valueEl.className = "stat-card__value";
  valueEl.textContent = String(value);

  card.append(labelEl, valueEl);
  return card;
}

/** One "Total" card plus one card per real State value, each count read
 * straight off the fetched array. Clicking a State card toggles the State
 * filter; clicking Total clears it. */
function renderSummary(processes, stateCounts) {
  dom.summaryGrid.replaceChildren(
    makeSummaryCard({
      label: "Total",
      value: processes.length,
      accent: "var(--color-accent)",
      state: "",
      title: "Show all states",
    }),
  );

  // Mirror viz.js's color assignment: with more than OVERVIEW_MAX_CATEGORIES
  // states, the tail is folded into a neutral "Other" segment in the bar.
  const folded = stateCounts.length > OVERVIEW_MAX_CATEGORIES;
  stateCounts.forEach(({ key, count }, i) => {
    const accent =
      folded && i >= OVERVIEW_MAX_CATEGORIES - 1 ? NEUTRAL_COLOR : CHART_COLORS[i % CHART_COLORS.length];
    dom.summaryGrid.append(
      makeSummaryCard({
        label: key,
        value: count,
        accent,
        state: key,
        title: `Filter to State ${key}`,
      }),
    );
  });
  syncSummaryActiveState();
}

function syncSummaryActiveState() {
  const active = dom.filterState.value;
  for (const card of dom.summaryGrid.querySelectorAll(".stat-card")) {
    const isActive = card.dataset.state === active;
    card.classList.toggle("stat-card--active", isActive);
    card.setAttribute("aria-pressed", String(isActive));
  }
}

/** Rebuilds a <select>'s options from real values, keeping the current
 * selection if that value still exists after a refresh. */
function populateSelect(select, allLabel, values) {
  const previous = select.value;
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = allLabel;
  select.replaceChildren(allOption);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  select.value = values.includes(previous) ? previous : "";
}

function populateFilters(stateCounts) {
  populateSelect(dom.filterState, "All states", stateCounts.map((c) => c.key));
  const namespaces = countBy(allProcesses, namespaceKey)
    .map((c) => c.key)
    .sort((a, b) => a.localeCompare(b));
  populateSelect(dom.filterNamespace, "All namespaces", namespaces);
}

function matchesFilters(proc, query, state, namespace) {
  if (state && stateKey(proc) !== state) return false;
  if (namespace && namespaceKey(proc) !== namespace) return false;
  if (!query) return true;
  return SEARCH_FIELDS.some((field) => {
    const value = proc[field];
    return value !== null && value !== undefined && String(value).toLowerCase().includes(query);
  });
}

function renderTable() {
  const query = dom.filterSearch.value.trim().toLowerCase();
  const state = dom.filterState.value;
  const namespace = dom.filterNamespace.value;
  const visible = allProcesses.filter((proc) => matchesFilters(proc, query, state, namespace));

  dom.tableBody.replaceChildren();
  for (const proc of visible) {
    const row = document.createElement("tr");
    row.className = "data-table__row--clickable";
    row.dataset.pid = String(proc.Pid);
    row.tabIndex = 0;
    row.setAttribute("aria-label", `View details for process ${textOrPlaceholder(proc.Pid)}`);

    const stateCell = document.createElement("td");
    stateCell.className = "data-table__cell";
    stateCell.append(makeStateBadge(proc.State));

    row.append(
      makeCell(textOrPlaceholder(proc.Pid), { mono: true }),
      makeCell(textOrPlaceholder(proc.Job), { mono: true }),
      makeCell(textOrPlaceholder(proc.Nspace)),
      makeCell(textOrPlaceholder(proc.Username)),
      makeCell(textOrPlaceholder(proc.Routine), { mono: true }),
      stateCell,
      makeCell(textOrPlaceholder(proc.Device), { mono: true }),
      makeCell(textOrPlaceholder(proc.ElapsedTime), { mono: true }),
      makeCell(formatCpuTime(proc.CPUTime), { mono: true }),
    );
    dom.tableBody.append(row);
  }

  const filtered = query !== "" || state !== "" || namespace !== "";
  dom.tableWrapper.hidden = visible.length === 0;
  dom.filterEmpty.hidden = visible.length !== 0;
  dom.filterClear.disabled = !filtered;
  dom.filterCount.textContent = filtered
    ? `Showing ${visible.length} of ${allProcesses.length}`
    : `Showing all ${allProcesses.length}`;
  syncSummaryActiveState();
}

function openDrawer(pid) {
  const proc = allProcesses.find((entry) => String(entry.Pid) === String(pid));
  if (!proc) return;
  currentDrawerPid = proc.Pid;
  renderDrawer(proc);

  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (wasHidden) dom.drawerClose.focus();
}

function renderDrawer(proc) {
  dom.drawerTitle.textContent = `PID ${textOrPlaceholder(proc.Pid)}`;
  dom.drawerStateBadge.className = `status-badge ${stateBadgeVariant(proc.State)}`;
  dom.drawerStateBadge.textContent = textOrPlaceholder(proc.State);

  dom.drawerFields.replaceChildren();
  for (const [label, key, kind] of DRAWER_FIELDS) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = label;
    dt.title = key;

    const dd = document.createElement("dd");
    dd.className = kind === "text" || kind === "bool"
      ? "info-list__value"
      : "info-list__value info-list__value--mono";
    if (kind === "bool") dd.textContent = formatBoolean(proc[key]);
    else if (kind === "cpu") dd.textContent = formatCpuTime(proc[key]);
    else dd.textContent = textOrPlaceholder(proc[key]);

    row.append(dt, dd);
    dom.drawerFields.append(row);
  }
}

function closeDrawer() {
  currentDrawerPid = null;
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

/** After a refresh, keep an open drawer in sync with the new data — or
 * close it if that process is no longer running. */
function refreshOpenDrawer() {
  if (currentDrawerPid === null) return;
  const proc = allProcesses.find((entry) => entry.Pid === currentDrawerPid);
  if (proc) renderDrawer(proc);
  else closeDrawer();
}

function renderProcesses(processes) {
  if (!Array.isArray(processes) || processes.length === 0) {
    allProcesses = [];
    dom.overview.hidden = true;
    dom.content.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    dom.tableBody.replaceChildren();
    closeDrawer();
    return;
  }

  allProcesses = processes;
  dom.content.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${processes.length} process${processes.length === 1 ? "" : "es"}`;

  const stateCounts = countBy(processes, stateKey);
  populateFilters(stateCounts);
  renderSummary(processes, stateCounts);
  renderOverview(stateCounts);
  renderTable();
  refreshOpenDrawer();
}

/**
 * Fetches GET /api/iris/processes and renders it. This is the ONLY network
 * call this module makes — no mutating request exists anywhere in this file.
 */
export async function loadProcesses() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getProcesses();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load process information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading process information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderProcesses(null);
    setLoading(false);
    return;
  }

  const processes = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (processes === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected process information.");
    renderProcesses(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  renderProcesses(processes);
  setLoading(false);
}

function toggleStateFilter(state) {
  // Clicking the already-active State card (or Total) clears the filter.
  dom.filterState.value = state && dom.filterState.value !== state ? state : "";
  renderTable();
}

export function initProcessesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadProcesses();
  });
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });

  // Filtering is purely client-side over the last fetched list — instant,
  // and never a new request.
  dom.filterForm.addEventListener("submit", (event) => event.preventDefault());
  dom.filterSearch.addEventListener("input", renderTable);
  dom.filterState.addEventListener("change", renderTable);
  dom.filterNamespace.addEventListener("change", renderTable);
  dom.filterClear.addEventListener("click", () => {
    dom.filterSearch.value = "";
    dom.filterState.value = "";
    dom.filterNamespace.value = "";
    renderTable();
  });

  // Event delegation for KPI cards and table rows — one listener each for
  // every current and future element, the same pattern databases.js's and
  // namespaces.js's card grids use.
  dom.summaryGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".stat-card");
    if (card) toggleStateFilter(card.dataset.state);
  });
  dom.summaryGrid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".stat-card");
    if (!card) return;
    event.preventDefault();
    toggleStateFilter(card.dataset.state);
  });

  dom.tableBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-pid]");
    if (row) openDrawer(row.dataset.pid);
  });
  dom.tableBody.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("tr[data-pid]");
    if (!row) return;
    event.preventDefault();
    openDrawer(row.dataset.pid);
  });

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDrawer();
  });
}
