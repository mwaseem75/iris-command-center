// Tasks view: a read-only Tasks Explorer — KPI cards, a Run State strip,
// a client-side search/filter toolbar, a compact table, and a detail
// drawer with Overview / Schedule / Execution / Settings tabs. It calls
// exactly three read-only endpoints and no mutating one:
//   - GET /api/iris/tasks/overview (IrisApi.getTaskOverview()): every task
//     merged with its GET /v2/task/info and the backend-derived `State`,
//   - GET /api/iris/tasks/manager (IrisApi.getTaskManager()): the Task
//     Manager's own status, fetched alongside the overview, and
//   - GET /api/iris/tasks/detail?id= (IrisApi.getTaskDetail()): one task's
//     full configuration, fetched only when its drawer opens. The backend
//     redacts sensitive Settings values before responding.
//
// Run state never comes from GET /v2/tasks' own `Suspended`: that flag was
// observed reporting false for suspended tasks, so the backend drops it and
// derives `State` from /v2/task/info (see backend/app/routes/iris.py's
// _task_state). A task whose info could not be read has State null and is
// shown as "Unknown", never guessed.
//
// Timestamps are shown exactly as IRIS returns them (no timezone is
// reported, so none is assumed). NextScheduled is not always a date —
// live values include "" and "Runs After #1:00" — and is never parsed.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { countBy, renderStackedBar } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

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
};

const DRAWER_TABS = ["overview", "schedule", "execution", "settings"];

// mainspec_v2.json's documented TaskExtraInfo.Status codes (negative
// values). Any other value is shown raw.
const STATUS_CODES = {
  "-1": "Running (JobRunning)",
  "-2": "Untrapped error (JobUntrappedError)",
  "-3": "Error before execution (JobSetupError)",
  "-4": "Timed out trying to job (JobTimeout)",
  "-5": "Error after execution (JobPostProcessError)",
};
const ERROR_STATUS_CODES = new Set(["-2", "-3", "-4", "-5"]);

// A "YYYY-MM-DD HH:MM[:SS]" value, the only date shapes observed or
// documented for task timestamps. Used only to decide how a value is
// labelled — the text itself is always shown exactly as IRIS sent it.
const DATETIME_PATTERN = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$/;

// KPI cards: [label, State filter value (or null for Total), predicate].
// Every count comes from the fetched overview — nothing invented.
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

// Real overview fields the free-text search matches against.
const SEARCH_FIELDS = ["Name", "Description", "Namespace", "Type"];

// The full overview from the last successful fetch — filtering and the
// drawer's Overview tab both read from this; neither triggers a re-fetch.
let allTasks = [];
let managerStatus = null; // GET /v2/task/manager's Status, or null if unavailable
let currentDrawerId = null;
let currentDetail = null;
let detailRequestSeq = 0;
let activeDrawerTab = "overview";

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js/system.js/processes.js/databases.js/web-apps.js.
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

/** Info's LastFinished carries seconds; the list's is truncated to the
 * minute. Both are real IRIS values — the more precise one is preferred. */
function lastFinishedOf(task) {
  return task.Info ? task.Info.LastFinished : task.LastFinished;
}

/** [text, title] for a NextScheduled value, which IRIS reports as a
 * datetime, "" or free text (e.g. "Runs After #1:00"). Never parsed. */
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

// Table rows/drawer rows are always built via document.createElement +
// .textContent — never innerHTML — so a name/description/setting value
// containing HTML-special characters can never be interpreted as markup.
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

/** The Last Result cell: IRIS's own Error text from /v2/task/info
 * ("Success", "" or error text), badged only where the spec's meaning is
 * unambiguous — "Success", or a documented error Status code. */
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

// --- KPI cards, Run State strip, filters, table ---

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

  // Tasks whose info could not be read — shown only when there are any,
  // so a card never claims a count of something that did not happen.
  const unknown = allTasks.filter((task) => task.State === null || task.State === undefined).length;
  if (unknown > 0) {
    dom.summaryGrid.append(makeStaticCard("State Unknown", String(unknown), "var(--color-chart-neutral)"));
  }

  // "Never Started" is the spec's own meaning of LastStarted "".
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
  // Clicking the already-active card clears the filter.
  dom.filterState.value = !stateValue || dom.filterState.value === stateValue ? "" : stateValue;
  renderTable();
}

function renderOverview() {
  dom.overview.hidden = false;
  renderStackedBar(dom.overviewViz, countBy(allTasks, stateLabel));
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
 * A plain-language schedule built ONLY from the TimePeriod/DailyFrequency
 * encoding mainspec_v2.json documents (e.g. Weekly day digits 1=Sunday …
 * 7=Saturday; Monthly day 31 = last day; Monthly Special "week^day", week 5
 * = last). Returns null — and the drawer shows only the raw fields — for
 * anything outside that encoding, rather than guessing.
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
    panel.append(makeSection("Run State", [makeInfoRow("State", null, "Unknown")]), note);
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

/** Fetches GET /api/iris/tasks/detail for the open drawer's task. Only the
 * most recent request's result is ever rendered. */
async function loadDrawerDetail(id) {
  const seq = ++detailRequestSeq;
  currentDetail = null;
  clearDetailPanels();
  dom.drawerError.hidden = true;
  dom.drawerLoading.hidden = false;

  try {
    const response = await IrisApi.getTaskDetail(id);
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
  detailRequestSeq += 1; // discard any in-flight detail response
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

  // After a refresh, re-open (and re-fetch) the drawer's task with fresh
  // data — or close it honestly if that task no longer exists.
  if (currentDrawerId !== null) {
    if (allTasks.some((task) => task.Id === currentDrawerId)) openDrawer(currentDrawerId);
    else closeDrawer();
  }
}

/** GET /api/iris/tasks/manager, reduced to its Status string or null. A
 * failure here never fails the page — the card just says Unavailable. */
async function fetchManagerStatus() {
  try {
    const response = await IrisApi.getTaskManager();
    const status = response && response.result ? response.result.Status : null;
    return typeof status === "string" ? status : null;
  } catch {
    return null;
  }
}

/**
 * Fetches GET /api/iris/tasks/overview (and, in parallel, the Task
 * Manager status) and renders them. No mutating request exists anywhere
 * in this file.
 */
export async function loadTasks() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  const managerPromise = fetchManagerStatus();

  let response;
  try {
    response = await IrisApi.getTaskOverview();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
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
    // status.errors includes the backend's own per-task "run state
    // unavailable" warnings — real, reported failures, not a threshold.
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

  // Filtering is purely client-side over the last fetched overview —
  // instant, and never a new request.
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

  // Event delegation for KPI cards and table rows — the same pattern
  // web-apps.js/processes.js/databases.js use.
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

  dom.tableBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-task-id]");
    if (row) openDrawer(Number(row.dataset.taskId));
  });
  dom.tableBody.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("tr[data-task-id]");
    if (!row) return;
    event.preventDefault();
    openDrawer(Number(row.dataset.taskId));
  });

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDrawer();
  });

  // Drawer tabs, with arrow-key switching per the WAI-ARIA tabs pattern.
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
