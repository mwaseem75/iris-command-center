// Tasks page: KPI cards, a Run State bar, four views (All Tasks with
// search/filters and the table, Upcoming, Schedule, Last Runs) and a detail
// drawer (Overview / Schedule / Execution / Settings tabs).
//
// The views only use data this page already reads: Upcoming and Last Runs
// come from the overview (NextScheduled, and each task's most recent run in
// its /v2/task/info), and Schedule from each task's existing detail read.
// Last Runs is not a history: IRIS's task info keeps only the latest run.
//
// Reads:
// - GET /api/iris/tasks/overview: every task with its /v2/task/info and a
//   `State` worked out by the backend,
// - GET /api/iris/tasks/manager: the Task Manager status,
// - GET /api/iris/tasks/detail?id=: one task's full config, when its drawer
//   opens (sensitive Settings are redacted by the backend).
// The one change it can make is Run Now in the drawer (task.run_now, see
// below).
//
// We don't use the list's `Suspended` flag, which reported false for
// suspended tasks; `State` comes from /v2/task/info instead. If a task's
// info couldn't be read, it shows "Unknown".
//
// Timestamps are shown as IRIS returns them (no timezone given).
// NextScheduled isn't always a date ("" or "Runs After #1:00"), so it's
// never parsed.

import { IrisApi, ApiError } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";
import { navigateTo } from "./nav.js";
import { countBy, renderStackedBar } from "./viz.js";

const PLACEHOLDER = "—";  // shown for empty values

const dom = {
  loadingState: document.getElementById("tasks-loading-state"),
  errorBanner: document.getElementById("tasks-error-banner"),
  errorBannerText: document.getElementById("tasks-error-banner-text"),
  refreshButton: document.getElementById("tasks-refresh-button"),
  backButton: document.getElementById("tasks-back-button"),
  connectionStatus: document.getElementById("tasks-connection-status"),
  connectionStatusLabel: document.getElementById("tasks-connection-status-label"),
  connectionDetail: document.getElementById("tasks-connection-detail"),
  countLabel: document.getElementById("tasks-count"),
  content: document.getElementById("tasks-content"),
  empty: document.getElementById("tasks-empty"),
  summaryGrid: document.getElementById("tasks-summary-grid"),
  overview: document.getElementById("tasks-overview"),
  overviewViz: document.getElementById("tasks-overview-viz"),
  filterForm: document.getElementById("tasks-filter-form"),
  filterSearch: document.getElementById("tasks-filter-search"),
  filterState: document.getElementById("tasks-filter-state"),
  filterType: document.getElementById("tasks-filter-type"),
  filterNamespace: document.getElementById("tasks-filter-namespace"),
  filterClear: document.getElementById("tasks-filter-clear-button"),
  filterCount: document.getElementById("tasks-filter-count"),
  filterEmpty: document.getElementById("tasks-filter-empty"),
  tableWrapper: document.getElementById("tasks-table-wrapper"),
  tableBody: document.getElementById("tasks-table-body"),
  drawerBackdrop: document.getElementById("tasks-drawer-backdrop"),
  drawer: document.getElementById("tasks-drawer"),
  drawerTitle: document.getElementById("tasks-drawer-title"),
  drawerStateBadge: document.getElementById("tasks-drawer-state-badge"),
  drawerTypeBadge: document.getElementById("tasks-drawer-type-badge"),
  drawerClose: document.getElementById("tasks-drawer-close"),
  drawerTabs: document.getElementById("tasks-drawer-tabs"),
  drawerLoading: document.getElementById("tasks-drawer-loading"),
  drawerError: document.getElementById("tasks-drawer-error"),
  drawerErrorText: document.getElementById("tasks-drawer-error-text"),
  panels: {
    overview: document.getElementById("tasks-panel-overview"),
    schedule: document.getElementById("tasks-panel-schedule"),
    execution: document.getElementById("tasks-panel-execution"),
    settings: document.getElementById("tasks-panel-settings"),
  },
  settingsList: document.getElementById("tasks-settings-list"),
  viewTabs: document.getElementById("tasks-view-tabs"),
  views: {
    all: document.getElementById("tasks-view-all"),
    upcoming: document.getElementById("tasks-view-upcoming"),
    schedule: document.getElementById("tasks-view-schedule"),
    lastruns: document.getElementById("tasks-view-lastruns"),
  },
  upcomingManager: document.getElementById("tasks-upcoming-manager"),
  upcomingManagerText: document.getElementById("tasks-upcoming-manager-text"),
  upcomingGroups: document.getElementById("tasks-upcoming-groups"),
  scheduleLoading: document.getElementById("tasks-schedule-loading"),
  scheduleWarning: document.getElementById("tasks-schedule-warning"),
  scheduleWarningText: document.getElementById("tasks-schedule-warning-text"),
  scheduleWrapper: document.getElementById("tasks-schedule-wrapper"),
  scheduleBody: document.getElementById("tasks-schedule-body"),
  lastRunsBody: document.getElementById("tasks-lastruns-body"),
};

const DRAWER_TABS = ["overview", "schedule", "execution", "settings"];

// TaskExtraInfo.Status codes (negative values). Others are shown as-is.
const STATUS_CODES = {
  "-1": "Running (JobRunning)",
  "-2": "Untrapped error (JobUntrappedError)",
  "-3": "Error before execution (JobSetupError)",
  "-4": "Timed out trying to job (JobTimeout)",
  "-5": "Error after execution (JobPostProcessError)",
};
const ERROR_STATUS_CODES = new Set(["-2", "-3", "-4", "-5"]);

// "YYYY-MM-DD HH:MM[:SS]", the date formats task timestamps use. Only
// decides the label; the text is always shown as IRIS sent it.
const DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/;

// KPI cards: [label, State filter value (null for Total), predicate].
const SUMMARY_CARDS = [
  ["Total", null, () => true],
  ["Running", "Running", (task) => task.State === "Running"],
  ["Not Running", "Not Running", (task) => task.State === "Not Running"],
  ["Suspended", "Suspended", (task) => task.State === "Suspended"],
];
const CARD_COLORS = [
  "var(--color-accent)",
  "var(--color-chart-2)",
  "var(--color-chart-neutral)",
  "var(--color-chart-4)",
  "var(--color-chart-3)",
];

// Fields the search box matches against.
const SEARCH_FIELDS = ["Name", "Description", "Namespace", "Type"];

// The last fetched overview; filtering and the Overview tab read from it.
let allTasks = [];
let managerStatus = null;  // Task Manager status, or null if unavailable
let currentDrawerId = null;
let currentDetail = null;
let detailRequestSeq = 0;
let activeDrawerTab = "overview";

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disable right away so a double click doesn't fire two requests.
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

function formatList(value) {
  return Array.isArray(value) && value.length > 0 ? value.join(", ") : PLACEHOLDER;
}

function stateLabel(task) {
  return task.State || "Unknown";
}

function stateBadgeVariant(state) {
  if (state === "Running") return "status-badge--ok";
  if (state === "Suspended") return "status-badge--warning";
  return "status-badge--neutral";
}

/**
 * Info's LastFinished has seconds, the list's only minutes; use the
 * more precise one.
 */
function lastFinishedOf(task) {
  return task.Info ? task.Info.LastFinished : task.LastFinished;
}

/**
 * [text, title] for NextScheduled, which can be a datetime, "" or text like
 * "Runs After #1:00". Not parsed.
 */
function describeNextScheduled(value) {
  if (typeof value !== "string" || value === "") {
    return [PLACEHOLDER, "IRIS reports no next scheduled time"];
  }
  if (DATETIME_PATTERN.test(value)) return [value, value];
  return [value, "Reported by IRIS as text, not a date"];
}

function formatStatusCode(value) {
  if (typeof value !== "string" || value === "") return PLACEHOLDER;
  return STATUS_CODES[value] ? `${value} — ${STATUS_CODES[value]}` : value;
}

// Rows are built with createElement/textContent (no innerHTML).
function makeCell(text, { mono = false, title = text } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = title;
  return cell;
}

function makeBadge(text, variant) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = text;
  return badge;
}

function makeBadgeCell(badge, title) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  if (title) cell.title = title;
  cell.append(badge);
  return cell;
}

/**
 * Last Result cell: the Error text from /v2/task/info ("Success", "" or an
 * error), with a badge only for "Success" or a known error Status code.
 */
function makeResultCell(task) {
  const info = task.Info;
  if (!info || info.Error === "") return makeCell(PLACEHOLDER);
  if (ERROR_STATUS_CODES.has(info.Status)) {
    return makeBadgeCell(makeBadge(info.Error, "status-badge--error"), formatStatusCode(info.Status));
  }
  if (info.Error === "Success") return makeBadgeCell(makeBadge("Success", "status-badge--ok"));
  return makeCell(info.Error);
}

function makeInfoRow(label, field, text, { mono = false } = {}) {
  const row = document.createElement("div");
  row.className = "info-list__row";

  const dt = document.createElement("dt");
  dt.textContent = label;
  if (field) {
    const fieldName = document.createElement("span");
    fieldName.className = "info-list__field";
    fieldName.textContent = field;
    dt.append(fieldName);
  }

  const dd = document.createElement("dd");
  dd.className = mono ? "info-list__value info-list__value--mono" : "info-list__value";
  dd.textContent = text;

  row.append(dt, dd);
  return row;
}

function makeSection(title, rows) {
  const section = document.createElement("div");
  section.className = "ns-drawer__section";
  const heading = document.createElement("h4");
  heading.className = "ns-drawer__section-title";
  heading.textContent = title;
  const list = document.createElement("dl");
  list.className = "info-list";
  list.append(...rows);
  section.append(heading, list);
  return section;
}

// --- KPI cards, Run State bar, filters, table ---

function renderSummary() {
  dom.summaryGrid.replaceChildren();
  SUMMARY_CARDS.forEach(([label, stateValue, predicate], i) => {
    const card = document.createElement("article");
    card.className = "stat-card stat-card--interactive";
    card.style.setProperty("--stat-card-accent", CARD_COLORS[i % CARD_COLORS.length]);
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.dataset.cardIndex = String(i);
    card.title = stateValue ? `Filter to ${label}` : "Clear the State filter";

    const labelEl = document.createElement("h3");
    labelEl.className = "stat-card__label";
    labelEl.textContent = label;

    const valueEl = document.createElement("p");
    valueEl.className = "stat-card__value";
    valueEl.textContent = String(allTasks.filter(predicate).length);

    card.append(labelEl, valueEl);
    dom.summaryGrid.append(card);
  });

  // Tasks whose info couldn't be read. Only shown when there are some.
  const unknown = allTasks.filter((task) => task.State === null || task.State === undefined).length;
  if (unknown > 0) {
    dom.summaryGrid.append(makeStaticCard("State Unknown", String(unknown), "var(--color-chart-neutral)"));
  }

  // LastStarted "" means never started.
  const neverStarted = allTasks.filter((task) => task.Info && task.Info.LastStarted === "").length;
  const neverCard = makeStaticCard("Never Started", String(neverStarted), CARD_COLORS[4]);
  neverCard.title = "Tasks whose LastStarted is empty (IRIS: never started)";
  dom.summaryGrid.append(neverCard);

  const managerCard = makeStaticCard(
    "Task Manager",
    managerStatus === null ? "Unavailable" : managerStatus,
    "var(--color-accent)",
  );
  if (managerStatus === null) {
    managerCard.querySelector(".stat-card__value").classList.add("stat-card__value--unavailable");
  }
  managerCard.title = "GET /v2/task/manager";
  dom.summaryGrid.append(managerCard);

  syncSummaryActiveState();
}

function makeStaticCard(label, value, accent) {
  const card = document.createElement("article");
  card.className = "stat-card";
  card.style.setProperty("--stat-card-accent", accent);
  const labelEl = document.createElement("h3");
  labelEl.className = "stat-card__label";
  labelEl.textContent = label;
  const valueEl = document.createElement("p");
  valueEl.className = "stat-card__value";
  valueEl.textContent = value;
  card.append(labelEl, valueEl);
  return card;
}

function syncSummaryActiveState() {
  for (const card of dom.summaryGrid.querySelectorAll(".stat-card[data-card-index]")) {
    const [, stateValue] = SUMMARY_CARDS[Number(card.dataset.cardIndex)];
    const isActive = stateValue ? dom.filterState.value === stateValue : dom.filterState.value === "";
    card.classList.toggle("stat-card--active", isActive);
    card.setAttribute("aria-pressed", String(isActive));
  }
}

function applyCardFilter(index) {
  const [, stateValue] = SUMMARY_CARDS[index];
  // Clicking the active card again clears the filter.
  dom.filterState.value = !stateValue || dom.filterState.value === stateValue ? "" : stateValue;
  renderTable();
}

function renderOverview() {
  dom.overview.hidden = false;
  renderStackedBar(dom.overviewViz, countBy(allTasks, stateLabel));
}

/** Rebuild a <select>'s options, keeping the current choice if it's still there. */
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

function populateFilters() {
  const types = [...new Set(allTasks.map((task) => task.Type).filter(Boolean))].sort();
  populateSelect(dom.filterType, "All types", types);
  const namespaces = [...new Set(allTasks.map((task) => task.Namespace).filter(Boolean))].sort();
  populateSelect(dom.filterNamespace, "All namespaces", namespaces);
}

function matchesFilters(task, query) {
  const state = dom.filterState.value;
  if (state === "unknown" && task.State) return false;
  if (state && state !== "unknown" && task.State !== state) return false;
  if (dom.filterType.value && task.Type !== dom.filterType.value) return false;
  if (dom.filterNamespace.value && task.Namespace !== dom.filterNamespace.value) return false;
  if (!query) return true;
  if (String(task.Id) === query) return true;
  return SEARCH_FIELDS.some((field) => {
    const value = task[field];
    return typeof value === "string" && value.toLowerCase().includes(query);
  });
}

function renderTable() {
  const query = dom.filterSearch.value.trim().toLowerCase();
  const visible = allTasks.filter((task) => matchesFilters(task, query));

  dom.tableBody.replaceChildren();
  for (const task of visible) {
    const row = document.createElement("tr");
    row.className = "data-table__row--clickable";
    row.dataset.taskId = String(task.Id);
    row.tabIndex = 0;
    row.setAttribute("aria-label", `View details for task ${textOrPlaceholder(task.Name)}`);

    const state = stateLabel(task);
    const [nextText, nextTitle] = describeNextScheduled(task.NextScheduled);
    const nameCell = makeCell(textOrPlaceholder(task.Name));
    if (task.Description) nameCell.title = `${task.Name} — ${task.Description}`;
    row.append(
      makeCell(textOrPlaceholder(task.Id), { mono: true }),
      nameCell,
      makeBadgeCell(
        makeBadge(state, stateBadgeVariant(state)),
        task.State ? "Derived from GET /v2/task/info" : "IRIS task info unavailable",
      ),
      makeCell(textOrPlaceholder(task.Type)),
      makeCell(textOrPlaceholder(task.Namespace)),
      makeCell(textOrPlaceholder(lastFinishedOf(task)), { mono: true }),
      makeCell(nextText, { mono: DATETIME_PATTERN.test(task.NextScheduled || ""), title: nextTitle }),
      makeResultCell(task),
    );
    dom.tableBody.append(row);
  }

  const filtered =
    query !== "" || [dom.filterState, dom.filterType, dom.filterNamespace].some((s) => s.value !== "");
  dom.tableWrapper.hidden = visible.length === 0;
  dom.filterEmpty.hidden = visible.length !== 0;
  dom.filterClear.disabled = !filtered;
  dom.filterCount.textContent = filtered
    ? `Showing ${visible.length} of ${allTasks.length}`
    : `Showing all ${allTasks.length}`;
  syncSummaryActiveState();
}

// --- Views: All Tasks | Upcoming | Schedule | Last Runs ---

const VIEW_TABS = ["all", "upcoming", "schedule", "lastruns"];
let activeView = "all";
// Schedule view: task Id -> its detail (null if it couldn't be read). Read
// when the Schedule tab opens, dropped on every refresh.
let scheduleDetails = null;
let scheduleRequestSeq = 0;

// A clickable row that opens the task's drawer (Run Now stays there).
function makeTaskRow(task) {
  const row = document.createElement("tr");
  row.className = "data-table__row--clickable";
  row.dataset.taskId = String(task.Id);
  row.tabIndex = 0;
  row.setAttribute("aria-label", `View details for task ${textOrPlaceholder(task.Name)}`);
  return row;
}

function makeStateCell(task) {
  const state = stateLabel(task);
  return makeBadgeCell(makeBadge(state, stateBadgeVariant(state)));
}

function makeViewTable(headers, rows) {
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrapper";
  const table = document.createElement("table");
  table.className = "data-table data-table--compact";
  const head = document.createElement("tr");
  for (const header of headers) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = header;
    head.append(th);
  }
  const thead = document.createElement("thead");
  thead.append(head);
  const tbody = document.createElement("tbody");
  tbody.append(...rows);
  table.append(thead, tbody);
  wrapper.append(table);
  return wrapper;
}

function makeViewGroup(title, headers, rows) {
  const section = document.createElement("section");
  section.className = "tasks-upcoming__group";
  const heading = document.createElement("h4");
  heading.className = "ns-drawer__section-title";
  heading.textContent = title;
  section.append(heading, makeViewTable(headers, rows));
  return section;
}

/**
 * Upcoming: tasks with a dated NextScheduled, soonest first, grouped by the
 * date IRIS reports (no timezone, so no "today"/"tomorrow" guessing). Text
 * values like "Runs After #1:00" and empty ones are listed as reported.
 */
function renderUpcoming() {
  const dated = [];
  const asText = [];
  const none = [];
  for (const task of allTasks) {
    const next = task.NextScheduled;
    if (typeof next === "string" && DATETIME_PATTERN.test(next)) dated.push(task);
    else if (typeof next === "string" && next !== "") asText.push(task);
    else none.push(task);
  }
  // The fixed "YYYY-MM-DD HH:MM[:SS]" format sorts correctly as text.
  dated.sort((a, b) => (a.NextScheduled < b.NextScheduled ? -1 : a.NextScheduled > b.NextScheduled ? 1 : 0));

  const groups = [];
  const byDate = new Map();
  for (const task of dated) {
    const date = task.NextScheduled.slice(0, 10);
    if (!byDate.has(date)) byDate.set(date, []);
    byDate.get(date).push(task);
  }
  const headers = ["Time", "Task", "State", "Type", "Namespace"];
  for (const [date, tasks] of byDate) {
    groups.push(makeViewGroup(date, headers, tasks.map((task) => {
      const row = makeTaskRow(task);
      row.append(
        makeCell(task.NextScheduled.slice(11), { mono: true, title: task.NextScheduled }),
        makeCell(textOrPlaceholder(task.Name)),
        makeStateCell(task),
        makeCell(textOrPlaceholder(task.Type)),
        makeCell(textOrPlaceholder(task.Namespace)),
      );
      return row;
    })));
  }
  const reported = (tasks, title, valueOf) => {
    if (tasks.length === 0) return;
    groups.push(makeViewGroup(title, ["Next Run (as reported)", "Task", "State", "Type", "Namespace"], tasks.map((task) => {
      const row = makeTaskRow(task);
      row.append(
        makeCell(valueOf(task), { title: "Reported by IRIS as text, not a date" }),
        makeCell(textOrPlaceholder(task.Name)),
        makeStateCell(task),
        makeCell(textOrPlaceholder(task.Type)),
        makeCell(textOrPlaceholder(task.Namespace)),
      );
      return row;
    })));
  };
  reported(asText, "Next run reported as text, not a date", (task) => task.NextScheduled);
  reported(none, "No next run reported (on demand or not scheduled)", () => PLACEHOLDER);
  dom.upcomingGroups.replaceChildren(...groups);

  // Scheduled tasks only run while the Task Manager is running.
  const message = managerStatus === null
    ? "The Task Manager status couldn't be read, so it's unknown whether these tasks will run."
    : managerStatus !== "Running"
      ? `The Task Manager is "${managerStatus}", so none of these tasks will run until it's running again.`
      : "";
  dom.upcomingManager.hidden = !message;
  dom.upcomingManagerText.textContent = message;
}

// "YYYY-MM-DD HH:MM:SS" as a UTC timestamp, only to subtract two of them
// (both are IRIS's own local time, so the difference is right).
const FULL_DATETIME = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/;

function timestampOf(value) {
  const match = typeof value === "string" ? FULL_DATETIME.exec(value) : null;
  if (!match) return null;
  const [, y, mo, d, h, mi, s] = match.map(Number);
  return Date.UTC(y, mo - 1, d, h, mi, s);
}

function formatDuration(start, end) {
  const from = timestampOf(start);
  const to = timestampOf(end);
  if (from === null || to === null || to < from) return PLACEHOLDER;
  const seconds = Math.round((to - from) / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${seconds % 60} s`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/**
 * Last Runs: each task's most recent run from its /v2/task/info (the only
 * run IRIS reports there), newest first; never-run tasks last.
 */
function renderLastRuns() {
  const ran = allTasks.filter((task) => task.Info && task.Info.LastStarted);
  const rest = allTasks.filter((task) => !(task.Info && task.Info.LastStarted));
  ran.sort((a, b) => (a.Info.LastStarted < b.Info.LastStarted ? 1 : a.Info.LastStarted > b.Info.LastStarted ? -1 : 0));

  dom.lastRunsBody.replaceChildren(
    ...ran.map((task) => {
      const info = task.Info;
      const row = makeTaskRow(task);
      row.append(
        makeCell(textOrPlaceholder(task.Name)),
        makeCell(info.LastStarted, { mono: true }),
        makeCell(textOrPlaceholder(info.LastFinished), { mono: true }),
        makeCell(formatDuration(info.LastStarted, info.LastFinished), { mono: true }),
        makeResultCell(task),
        makeCell(textOrPlaceholder(info.LastSchedule), { mono: true }),
      );
      return row;
    }),
    ...rest.map((task) => {
      const row = makeTaskRow(task);
      const started = task.Info ? "Never run" : "Unknown (task info unavailable)";
      row.append(
        makeCell(textOrPlaceholder(task.Name)),
        makeCell(started),
        makeCell(PLACEHOLDER),
        makeCell(PLACEHOLDER),
        makeCell(PLACEHOLDER),
        makeCell(textOrPlaceholder(task.Info ? task.Info.LastSchedule : ""), { mono: true }),
      );
      return row;
    }),
  );
}

function describePeriod(detail) {
  const every = asPositiveInt(detail.TimePeriodEvery);
  const period = textOrPlaceholder(detail.TimePeriod);
  if (["Daily", "Weekly", "Monthly", "Monthly Special"].includes(detail.TimePeriod) && every) {
    return `${period}, every ${every}`;
  }
  return period;
}

function describeTimeOfDay(detail) {
  if (detail.TimePeriod === "On Demand" || detail.TimePeriod === "Run After") return PLACEHOLDER;
  if (detail.DailyFrequency === "Several") {
    const increment = textOrPlaceholder(detail.DailyIncrement);
    return `Every ${increment} ${textOrPlaceholder(detail.DailyFrequencyTime)}, ${textOrPlaceholder(detail.DailyStartTime)}–${textOrPlaceholder(detail.DailyEndTime)}`;
  }
  return `Once at ${textOrPlaceholder(detail.DailyStartTime)}`;
}

/** Schedule: one row per task from its detail (null = couldn't be read). */
function renderSchedule() {
  if (!scheduleDetails) return;
  let unreadable = 0;
  dom.scheduleBody.replaceChildren(...allTasks.map((task) => {
    const detail = scheduleDetails.get(task.Id);
    const row = makeTaskRow(task);
    const [nextText, nextTitle] = describeNextScheduled(task.NextScheduled);
    if (!detail) {
      unreadable += 1;
      row.append(
        makeCell(textOrPlaceholder(task.Name)),
        makeCell("Schedule unavailable (the task's details couldn't be read)"),
        makeCell(PLACEHOLDER), makeCell(PLACEHOLDER), makeCell(PLACEHOLDER),
        makeCell(nextText, { title: nextTitle }),
      );
      return row;
    }
    const summary = describeSchedule(detail);
    row.append(
      makeCell(textOrPlaceholder(task.Name)),
      makeCell(summary || "Not describable from the documented encoding — open the task for the raw fields"),
      makeCell(describePeriod(detail)),
      makeCell(describeTimeOfDay(detail)),
      makeCell(`${textOrPlaceholder(detail.StartDate)} – ${detail.EndDate ? detail.EndDate : "no end"}`, { mono: true }),
      makeCell(nextText, { mono: DATETIME_PATTERN.test(task.NextScheduled || ""), title: nextTitle }),
    );
    return row;
  }));
  dom.scheduleWrapper.hidden = false;
  dom.scheduleWarning.hidden = unreadable === 0;
  dom.scheduleWarningText.textContent = unreadable
    ? `${unreadable} task${unreadable === 1 ? "'s" : "s'"} details couldn't be read.`
    : "";
}

/** Read every task's detail (the existing GET /api/iris/tasks/detail), once per refresh. */
async function loadScheduleDetails() {
  if (scheduleDetails) {
    renderSchedule();
    return;
  }
  const seq = ++scheduleRequestSeq;
  const ids = allTasks.map((task) => task.Id);
  dom.scheduleLoading.hidden = false;
  dom.scheduleWrapper.hidden = true;
  dom.scheduleWarning.hidden = true;
  const details = await Promise.all(ids.map((id) =>
    IrisApi.getTaskDetail(id, selectedInstanceId())
      .then((response) => (response && response.result && typeof response.result === "object" ? response.result : null))
      .catch(() => null)));
  if (seq !== scheduleRequestSeq) return;  // a refresh replaced the list meanwhile
  scheduleDetails = new Map(ids.map((id, i) => [id, details[i]]));
  dom.scheduleLoading.hidden = true;
  renderSchedule();
}

function renderActiveView() {
  if (activeView === "upcoming") renderUpcoming();
  else if (activeView === "schedule") loadScheduleDetails();
  else if (activeView === "lastruns") renderLastRuns();
}

function setView(view) {
  if (!VIEW_TABS.includes(view)) return;
  activeView = view;
  for (const tab of dom.viewTabs.querySelectorAll("[data-view-tab]")) {
    const selected = tab.dataset.viewTab === view;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  }
  for (const [name, panel] of Object.entries(dom.views)) panel.hidden = name !== view;
  renderActiveView();
}

// Rows in every view open the task's drawer.
function handleRowClick(event) {
  const row = event.target.closest("tr[data-task-id]");
  if (row) openDrawer(Number(row.dataset.taskId));
}

function handleRowKey(event) {
  if (event.key !== "Enter" && event.key !== " ") return;
  const row = event.target.closest("tr[data-task-id]");
  if (!row) return;
  event.preventDefault();
  openDrawer(Number(row.dataset.taskId));
}

// --- Detail drawer ---

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const ORDINALS = { 1: "first", 2: "second", 3: "third", 4: "fourth", 5: "last" };

function plural(count, unit) {
  return count === 1 ? unit : `${count} ${unit}s`;
}

function asPositiveInt(value) {
  const n = typeof value === "number" ? value : typeof value === "string" && /^\d+$/.test(value) ? Number(value) : NaN;
  return Number.isInteger(n) && n > 0 ? n : null;
}

/**
 * Describe the schedule in plain words from the TimePeriod/DailyFrequency
 * fields (Weekly days 1=Sunday ... 7=Saturday; Monthly day 31 = last day;
 * Monthly Special "week^day", week 5 = last). Returns null for anything
 * else, and the drawer just shows the raw fields.
 */
function describeSchedule(detail) {
  const every = asPositiveInt(detail.TimePeriodEvery);
  const day = String(detail.TimePeriodDay ?? "");
  let when;
  switch (detail.TimePeriod) {
    case "On Demand":
      return "On demand only — not scheduled";
    case "Run After":
      return "After another task completes (see Run After GUID)";
    case "Daily":
      if (!every) return null;
      when = every === 1 ? "Every day" : `Every ${every} days`;
      break;
    case "Weekly": {
      if (!every || !/^[1-7]+$/.test(day)) return null;
      const days = [...day].map((d) => WEEKDAYS[Number(d) - 1]).join(", ");
      when = `Every ${plural(every, "week")} on ${days}`;
      break;
    }
    case "Monthly": {
      const dom31 = asPositiveInt(day);
      if (!every || !dom31 || dom31 > 31) return null;
      when = `Every ${plural(every, "month")} on ${dom31 === 31 ? "the last day" : `day ${dom31}`}`;
      break;
    }
    case "Monthly Special": {
      const match = /^([1-5])\^([1-7])$/.exec(day);
      if (!every || !match) return null;
      when = `Every ${plural(every, "month")} on the ${ORDINALS[match[1]]} ${WEEKDAYS[Number(match[2]) - 1]}`;
      break;
    }
    default:
      return null;
  }

  if (detail.DailyFrequency === "Once") {
    return detail.DailyStartTime ? `${when} at ${detail.DailyStartTime}` : when;
  }
  if (detail.DailyFrequency === "Several") {
    const increment = asPositiveInt(detail.DailyIncrement);
    const unit = { Minutes: "minute", Hourly: "hour" }[detail.DailyFrequencyTime];
    if (!increment || !unit) return null;
    return `${when}, every ${plural(increment, unit)} from ${detail.DailyStartTime} to ${detail.DailyEndTime}`;
  }
  return null;
}

// --- Run Now (task.run_now, the only change on this page) ---
//
// Same flow as Enabled State in the Web Apps drawer. "Check" sends a dry
// run (runTaskNow(fields, true, true); the dry run still needs
// confirmed=true to get past the executor, and never sends the POST). Only
// a successful preview shows the confirm button, which needs the checkbox
// ticked, and only its click handler sends the real request. The backend
// does the checks (System/Maintenance, suspended, running); this just
// shows what it says.
//
// The section is built once per task and re-attached on each Overview
// render, so a preview or result survives the detail load and the list
// reload after a run.
let runSection = null;
let runSectionTaskId = null;

function makeRunResultRows(result) {
  const rows = [
    makeInfoRow("Status", null, textOrPlaceholder(result.status)),
    makeInfoRow("Detail", null, textOrPlaceholder(result.detail)),
  ];
  if (result.handler_result) rows.push(makeInfoRow("Execution Detail", null, textOrPlaceholder(result.handler_result.detail)));
  if (result.verification) {
    rows.push(makeInfoRow("Verification Status", null, textOrPlaceholder(result.verification.status)));
    rows.push(makeInfoRow("Verification Detail", null, textOrPlaceholder(result.verification.detail)));
  }
  return rows;
}

function buildRunNowSection(task) {
  const section = makeSection("Run Now", []);
  section.dataset.primaryOnly = "";
  const hint = document.createElement("p");
  hint.className = "ns-hint";
  hint.textContent =
    "Asks IRIS's Task Manager to run this task now, through the authorization → confirmation → execution → " +
    "verification framework. Check is a read-only dry run; nothing is sent to IRIS until you explicitly confirm. " +
    "Only User tasks can be run — IRIS's System and Maintenance tasks, suspended tasks and running tasks are " +
    "refused by the backend. The Task Manager polls every 60 seconds, so a run may start up to a minute later.";

  const checkButton = document.createElement("button");
  checkButton.type = "button";
  checkButton.className = "btn";
  checkButton.textContent = "Check Run Now";

  const loading = document.createElement("div");
  loading.className = "loading-state";
  loading.hidden = true;
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  spinner.setAttribute("aria-hidden", "true");
  const loadingText = document.createElement("span");
  loading.append(spinner, loadingText);

  const error = document.createElement("div");
  error.className = "banner banner--error";
  error.setAttribute("role", "alert");
  error.hidden = true;

  const confirm = document.createElement("div");
  confirm.hidden = true;
  const preview = document.createElement("div");
  preview.className = "banner banner--warning";
  preview.setAttribute("role", "alert");
  const ackLabel = document.createElement("label");
  ackLabel.className = "ns-form-checkbox";
  const ack = document.createElement("input");
  ack.type = "checkbox";
  const ackText = document.createElement("span");
  ackText.textContent = `I understand this will run ${task.Name} now on the IRIS instance.`;
  ackLabel.append(ack, ackText);
  const confirmRow = document.createElement("div");
  confirmRow.className = "btn-row";
  const confirmButton = document.createElement("button");
  confirmButton.type = "button";
  confirmButton.className = "btn btn--warning";
  confirmButton.textContent = "Confirm & Run Now";
  confirmButton.disabled = true;
  confirmRow.append(confirmButton);
  confirm.append(preview, ackLabel, confirmRow);

  const resultList = document.createElement("dl");
  resultList.className = "info-list";
  resultList.hidden = true;

  const taskId = task.Id;
  const isCurrent = () => currentDrawerId === taskId && runSectionTaskId === taskId;
  let pendingFields = null;
  const clearPreview = () => {
    pendingFields = null;
    confirm.hidden = true;
    ack.checked = false;
    confirmButton.disabled = true;
  };
  const setBusy = (busy, message) => {
    checkButton.disabled = busy;
    loading.hidden = !busy;
    loadingText.textContent = message || "";
  };
  const showError = (message) => {
    error.textContent = message;
    error.hidden = false;
  };

  checkButton.addEventListener("click", async () => {
    const fields = { Id: taskId };
    clearPreview();
    error.hidden = true;
    resultList.hidden = true;
    setBusy(true, "Checking with IRIS (dry run)…");
    try {
      const result = await IrisApi.runTaskNow(fields, true, true);
      if (!isCurrent()) return;
      const handlerResult = result && result.handler_result;
      if (result.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
        pendingFields = fields;
        preview.textContent = handlerResult.detail;
        confirm.hidden = false;
      } else {
        // Unauthorized, protected, suspended, running, unknown task... shown as
        // the backend explained it.
        showError((handlerResult && handlerResult.detail) || result.detail || "This run could not be validated against IRIS.");
      }
    } catch (err) {
      if (!isCurrent()) return;
      showError(
        err instanceof ApiError
          ? "Could not reach the Command Center backend to check this run."
          : "An unexpected error occurred while checking this run.",
      );
    } finally {
      if (isCurrent()) setBusy(false);
    }
  });

  ack.addEventListener("change", () => {
    confirmButton.disabled = !(pendingFields && ack.checked);
  });

  // The only place that sends a real request. Only reachable from this
  // button, after a successful preview and the checkbox.
  confirmButton.addEventListener("click", async () => {
    const fields = pendingFields;
    if (!fields) return;
    clearPreview();
    setBusy(true, "Asking IRIS to run this task…");
    let result;
    try {
      result = await IrisApi.runTaskNow(fields, true, false);
    } catch (err) {
      result = {
        status: "request_failed",
        detail:
          err instanceof ApiError
            ? "Could not reach the Command Center backend to run this task."
            : "An unexpected error occurred while running this task.",
      };
    }
    if (!isCurrent()) return;
    setBusy(false);
    resultList.replaceChildren(...makeRunResultRows(result));
    resultList.hidden = false;
    if (result.status === "success" || result.status === "verification_failed") {
      // Reload the task list instead of patching it locally; the re-render
      // re-attaches this section.
      await loadTasks();
    }
  });

  section.append(hint, checkButton, loading, error, confirm, resultList);
  return section;
}

function runNowSectionFor(task) {
  if (!runSection || runSectionTaskId !== task.Id) {
    runSectionTaskId = task.Id;
    runSection = buildRunNowSection(task);
  }
  return runSection;
}

function renderOverviewPanel(task) {
  const info = task.Info;
  const [nextText] = describeNextScheduled(task.NextScheduled);
  const identity = [
    makeInfoRow("ID", "Id", textOrPlaceholder(task.Id), { mono: true }),
    makeInfoRow("Name", "Name", textOrPlaceholder(task.Name)),
    makeInfoRow("Description", "Description", textOrPlaceholder(task.Description)),
    makeInfoRow("Type", "Type", textOrPlaceholder(task.Type)),
    makeInfoRow("Namespace", "Namespace", textOrPlaceholder(task.Namespace)),
  ];
  if (currentDetail) {
    identity.push(makeInfoRow("Task Class", "TaskClass", textOrPlaceholder(currentDetail.TaskClass), { mono: true }));
  }

  const panel = dom.panels.overview;
  panel.replaceChildren(makeSection("Task", identity));

  if (!info) {
    const note = document.createElement("p");
    note.className = "ns-hint";
    note.textContent = "IRIS task info (GET /v2/task/info) could not be read for this task, so its run state and last run are unknown.";
    panel.append(makeSection("Run State", [makeInfoRow("State", null, "Unknown")]), note, runNowSectionFor(task));
    return;
  }

  panel.append(
    makeSection("Run State", [
      makeInfoRow("State", null, stateLabel(task)),
      makeInfoRow("Suspended", "Suspended", formatBoolean(info.Suspended)),
      makeInfoRow("Status", "Status", formatStatusCode(info.Status), { mono: true }),
      makeInfoRow("Last Result", "Error", textOrPlaceholder(info.Error)),
    ]),
    makeSection("Last & Next Run", [
      makeInfoRow("Last Scheduled", "LastSchedule", info.LastSchedule === "" ? "Never run" : info.LastSchedule, { mono: true }),
      makeInfoRow("Last Started", "LastStarted", info.LastStarted === "" ? "Never started" : info.LastStarted, { mono: true }),
      makeInfoRow("Last Finished", "LastFinished", textOrPlaceholder(info.LastFinished), { mono: true }),
      makeInfoRow("Next Scheduled", "NextScheduled", textOrPlaceholder(info.NextScheduled), { mono: true }),
      makeInfoRow("Next Scheduled (task list)", "NextScheduled", nextText, { mono: true }),
    ]),
    runNowSectionFor(task),
  );
}

function renderSchedulePanel(detail) {
  const summary = describeSchedule(detail);
  dom.panels.schedule.replaceChildren(
    makeSection("Summary", [
      makeInfoRow("Schedule", null, summary || "Not describable from the documented encoding — see raw fields below"),
    ]),
    makeSection("Recurrence", [
      makeInfoRow("Time Period", "TimePeriod", textOrPlaceholder(detail.TimePeriod)),
      makeInfoRow("Every", "TimePeriodEvery", textOrPlaceholder(detail.TimePeriodEvery), { mono: true }),
      makeInfoRow("Day", "TimePeriodDay", textOrPlaceholder(detail.TimePeriodDay), { mono: true }),
      makeInfoRow("Run After GUID", "RunAfterGUID", textOrPlaceholder(detail.RunAfterGUID), { mono: true }),
    ]),
    makeSection("Time of Day", [
      makeInfoRow("Daily Frequency", "DailyFrequency", textOrPlaceholder(detail.DailyFrequency)),
      makeInfoRow("Frequency Unit", "DailyFrequencyTime", textOrPlaceholder(detail.DailyFrequencyTime)),
      makeInfoRow("Increment", "DailyIncrement", textOrPlaceholder(detail.DailyIncrement), { mono: true }),
      makeInfoRow("Start Time", "DailyStartTime", textOrPlaceholder(detail.DailyStartTime), { mono: true }),
      makeInfoRow("End Time", "DailyEndTime", textOrPlaceholder(detail.DailyEndTime), { mono: true }),
    ]),
    makeSection("Date Range", [
      makeInfoRow("Start Date", "StartDate", textOrPlaceholder(detail.StartDate), { mono: true }),
      makeInfoRow("End Date", "EndDate", textOrPlaceholder(detail.EndDate), { mono: true }),
    ]),
    makeSection("Expiration", [
      makeInfoRow("Expires", "Expires", formatBoolean(detail.Expires)),
      makeInfoRow("Days", "ExpiresDays", textOrPlaceholder(detail.ExpiresDays), { mono: true }),
      makeInfoRow("Hours", "ExpiresHours", textOrPlaceholder(detail.ExpiresHours), { mono: true }),
      makeInfoRow("Minutes", "ExpiresMinutes", textOrPlaceholder(detail.ExpiresMinutes), { mono: true }),
    ]),
  );
}

function renderExecutionPanel(detail) {
  dom.panels.execution.replaceChildren(
    makeSection("Job", [
      makeInfoRow("Task Class", "TaskClass", textOrPlaceholder(detail.TaskClass), { mono: true }),
      makeInfoRow("Namespace", "NameSpace", textOrPlaceholder(detail.NameSpace)),
      makeInfoRow("Run As User", "RunAsUser", textOrPlaceholder(detail.RunAsUser), { mono: true }),
      makeInfoRow("Priority", "Priority", textOrPlaceholder(detail.Priority)),
      makeInfoRow("Batch Mode", "IsBatch", formatBoolean(detail.IsBatch)),
      makeInfoRow("Mirror Status", "MirrorStatus", textOrPlaceholder(detail.MirrorStatus)),
    ]),
    makeSection("Error & Restart Handling", [
      makeInfoRow("Suspend On Error", "SuspendOnError", formatBoolean(detail.SuspendOnError)),
      makeInfoRow("Suspend If Terminated", "SuspendTerminated", formatBoolean(detail.SuspendTerminated)),
      makeInfoRow("Reschedule On Start", "RescheduleOnStart", formatBoolean(detail.RescheduleOnStart)),
    ]),
    makeSection("Output", [
      makeInfoRow("Output Directory", "OutputDirectory", textOrPlaceholder(detail.OutputDirectory), { mono: true }),
      makeInfoRow("Output File", "OutputFilename", textOrPlaceholder(detail.OutputFilename), { mono: true }),
      makeInfoRow("Open Output File", "OpenOutputFile", formatBoolean(detail.OpenOutputFile)),
      makeInfoRow("Output Is Binary", "OutputFileIsBinary", formatBoolean(detail.OutputFileIsBinary)),
    ]),
    makeSection("Notifications", [
      makeInfoRow("Email Output", "EmailOutput", formatBoolean(detail.EmailOutput)),
      makeInfoRow("On Completion", "EmailOnCompletion", formatList(detail.EmailOnCompletion)),
      makeInfoRow("On Error", "EmailOnError", formatList(detail.EmailOnError)),
      makeInfoRow("On Expiration", "EmailOnExpiration", formatList(detail.EmailOnExpiration)),
    ]),
  );
}

function formatSettingValue(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (typeof value === "object") return JSON.stringify(value);
  return textOrPlaceholder(value);
}

function renderSettingsPanel(detail) {
  const settings = detail.Settings && typeof detail.Settings === "object" ? detail.Settings : {};
  const redacted = new Set(Array.isArray(detail.RedactedSettings) ? detail.RedactedSettings : []);
  const keys = Object.keys(settings);
  if (keys.length === 0) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "This task class reports no settings.";
    dom.settingsList.replaceChildren(empty);
    return;
  }
  dom.settingsList.replaceChildren(
    ...keys.map((key) =>
      makeInfoRow(
        key,
        null,
        redacted.has(key) ? "Redacted by Command Center" : formatSettingValue(settings[key]),
        { mono: !redacted.has(key) },
      ),
    ),
  );
}

function clearDetailPanels() {
  dom.panels.schedule.replaceChildren();
  dom.panels.execution.replaceChildren();
  dom.settingsList.replaceChildren();
}

/**
 * Load GET /api/iris/tasks/detail for the open task. Only the latest
 * request's result is rendered.
 */
async function loadDrawerDetail(id) {
  const seq = ++detailRequestSeq;
  currentDetail = null;
  clearDetailPanels();
  dom.drawerError.hidden = true;
  dom.drawerLoading.hidden = false;

  try {
    const response = await IrisApi.getTaskDetail(id, selectedInstanceId());
    if (seq !== detailRequestSeq) return;
    const detail = response && response.result && typeof response.result === "object" ? response.result : null;
    if (!detail) {
      dom.drawerErrorText.textContent = "IRIS did not return the expected task configuration.";
      dom.drawerError.hidden = false;
      return;
    }
    currentDetail = detail;
    const task = allTasks.find((entry) => entry.Id === id);
    if (task) renderOverviewPanel(task);
    renderSchedulePanel(detail);
    renderExecutionPanel(detail);
    renderSettingsPanel(detail);
  } catch (err) {
    if (seq !== detailRequestSeq) return;
    dom.drawerErrorText.textContent =
      err instanceof ApiError && err.status === 404
        ? "IRIS reports no task with this ID. It may have been deleted — refresh the list."
        : err instanceof ApiError
          ? "Could not load this task's configuration."
          : "An unexpected error occurred while loading this task's configuration.";
    dom.drawerError.hidden = false;
  } finally {
    if (seq === detailRequestSeq) dom.drawerLoading.hidden = true;
  }
}

function setDrawerTab(tab) {
  activeDrawerTab = DRAWER_TABS.includes(tab) ? tab : "overview";
  for (const button of dom.drawerTabs.querySelectorAll("[role=tab]")) {
    const selected = button.dataset.tab === activeDrawerTab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  for (const name of DRAWER_TABS) dom.panels[name].hidden = name !== activeDrawerTab;
}

function openDrawer(id) {
  const task = allTasks.find((entry) => entry.Id === id);
  if (!task) return;
  const isSameTask = currentDrawerId === task.Id;
  currentDrawerId = task.Id;
  if (!isSameTask) {
    currentDetail = null;
    activeDrawerTab = "overview";
  }

  const state = stateLabel(task);
  dom.drawerTitle.textContent = textOrPlaceholder(task.Name);
  dom.drawerStateBadge.className = `status-badge ${stateBadgeVariant(state)}`;
  dom.drawerStateBadge.textContent = state;
  dom.drawerTypeBadge.textContent = textOrPlaceholder(task.Type);
  renderOverviewPanel(task);

  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (!isSameTask) dom.drawer.scrollTop = 0;
  if (wasHidden) dom.drawerClose.focus();
  setDrawerTab(activeDrawerTab);
  loadDrawerDetail(task.Id);
}

function closeDrawer() {
  currentDrawerId = null;
  currentDetail = null;
  detailRequestSeq += 1;  // ignore any detail response still in flight
  runSection = null;  // a reopened drawer gets a fresh Run Now section
  runSectionTaskId = null;
  activeDrawerTab = "overview";
  dom.drawerLoading.hidden = true;
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

function renderTasks(tasks) {
  if (!Array.isArray(tasks) || tasks.length === 0) {
    allTasks = [];
    dom.overview.hidden = true;
    dom.content.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    dom.tableBody.replaceChildren();
    closeDrawer();
    return;
  }

  allTasks = tasks;
  dom.content.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${tasks.length} task${tasks.length === 1 ? "" : "s"}`;

  populateFilters();
  renderSummary();
  renderOverview();
  renderTable();
  scheduleDetails = null;  // re-read on the next Schedule view
  scheduleRequestSeq += 1;
  renderActiveView();

  // After a refresh, reopen the drawer's task with fresh data, or close it if
  // the task is gone.
  if (currentDrawerId !== null) {
    if (allTasks.some((task) => task.Id === currentDrawerId)) openDrawer(currentDrawerId);
    else closeDrawer();
  }
}

/**
 * GET /api/iris/tasks/manager, as its Status string or null. If it fails,
 * the card just says Unavailable.
 */
async function fetchManagerStatus() {
  try {
    const response = await IrisApi.getTaskManager(selectedInstanceId());
    const status = response && response.result ? response.result.Status : null;
    return typeof status === "string" ? status : null;
  } catch {
    return null;
  }
}

/** Load the overview (and the Task Manager status in parallel) and render. */
export async function loadTasks() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  const managerPromise = fetchManagerStatus();

  let response;
  try {
    response = await IrisApi.getTaskOverview(selectedInstanceId());
  } catch (err) {
    // ApiError messages are already safe to show (see api.js).
    const message =
      err instanceof ApiError
        ? "Could not load task information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading task information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderTasks(null);
    setLoading(false);
    return;
  }

  const tasks = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (tasks === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected task information.");
    renderTasks(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // status.errors includes the backend's per-task "run state unavailable"
    // warnings.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  managerStatus = await managerPromise;
  renderTasks(tasks);
  setLoading(false);
}

export function initTasksControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadTasks();
  });
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });

  // Filtering is local, no request.
  dom.filterForm.addEventListener("submit", (event) => event.preventDefault());
  dom.filterSearch.addEventListener("input", renderTable);
  for (const select of [dom.filterState, dom.filterType, dom.filterNamespace]) {
    select.addEventListener("change", renderTable);
  }
  dom.filterClear.addEventListener("click", () => {
    dom.filterSearch.value = "";
    for (const select of [dom.filterState, dom.filterType, dom.filterNamespace]) select.value = "";
    renderTable();
  });

  // Delegated listeners for KPI cards and table rows.
  dom.summaryGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".stat-card[data-card-index]");
    if (card) applyCardFilter(Number(card.dataset.cardIndex));
  });
  dom.summaryGrid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".stat-card[data-card-index]");
    if (!card) return;
    event.preventDefault();
    applyCardFilter(Number(card.dataset.cardIndex));
  });

  for (const container of [dom.tableBody, dom.upcomingGroups, dom.scheduleBody, dom.lastRunsBody]) {
    container.addEventListener("click", handleRowClick);
    container.addEventListener("keydown", handleRowKey);
  }

  // Page views, with arrow-key switching (WAI-ARIA tabs pattern).
  dom.viewTabs.addEventListener("click", (event) => {
    const tab = event.target.closest("[data-view-tab]");
    if (tab) setView(tab.dataset.viewTab);
  });
  dom.viewTabs.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    const index = VIEW_TABS.indexOf(activeView);
    setView(VIEW_TABS[(index + step + VIEW_TABS.length) % VIEW_TABS.length]);
    dom.viewTabs.querySelector(`[data-view-tab="${activeView}"]`).focus();
  });

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDrawer();
  });

  // Drawer tabs, with arrow-key switching (WAI-ARIA tabs pattern).
  dom.drawerTabs.addEventListener("click", (event) => {
    const tab = event.target.closest("[role=tab]");
    if (tab) setDrawerTab(tab.dataset.tab);
  });
  dom.drawerTabs.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    const index = DRAWER_TABS.indexOf(activeDrawerTab);
    setDrawerTab(DRAWER_TABS[(index + step + DRAWER_TABS.length) % DRAWER_TABS.length]);
    dom.drawerTabs.querySelector(`[data-tab="${activeDrawerTab}"]`).focus();
  });
}
