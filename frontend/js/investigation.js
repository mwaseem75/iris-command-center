// Investigation page: GET /api/iris/security/audit/enabled and
// GET /api/iris/security/audit/records. (IRIS runs the audit query as an
// async task, but the backend handles that; this page only sends GETs.)
//
// Shows a subset of AuditRecordEntry: Time, EventType, Event, Username,
// Namespace, Authentication, ClientIPAddress, Description.
//
// Link with Observability: there's no shared id between our traces and
// IRIS's audit log, so the pages are linked by time only. setTimeWindow()
// lets Observability open this page with a time range filled in (see
// app.js), and each row's "Traces near this time" button goes the other
// way using the record's UTCTimeStamp.
//
// Layout: KPI cards and an activity timeline built from the returned
// records, filters, the audit table, and an event detail panel. The panel
// lists Command Center traces that started within +/-30 s of the event
// (from GET /api/iris/observability/traces), with an Open Trace button.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { assignColors, countBy, topCategories } from "./viz.js";

const PLACEHOLDER = "—";  // shown for empty values

const dom = {
  loadingState: document.getElementById("investigation-loading-state"),
  errorBanner: document.getElementById("investigation-error-banner"),
  errorBannerText: document.getElementById("investigation-error-banner-text"),
  searchButton: document.getElementById("investigation-search-button"),
  connectionStatus: document.getElementById("investigation-connection-status"),
  connectionStatusLabel: document.getElementById("investigation-connection-status-label"),
  auditEnabled: document.getElementById("investigation-audit-enabled"),
  countLabel: document.getElementById("investigation-count"),
  overview: document.getElementById("investigation-overview"),
  timeline: document.getElementById("investigation-timeline"),
  legend: document.getElementById("investigation-timeline-legend"),
  kpiEvents: document.getElementById("investigation-kpi-events"),
  kpiEventKinds: document.getElementById("investigation-kpi-event-kinds"),
  kpiEventKindsMeta: document.getElementById("investigation-kpi-event-kinds-meta"),
  kpiUsers: document.getElementById("investigation-kpi-users"),
  kpiNamespaces: document.getElementById("investigation-kpi-namespaces"),
  kpiRelated: document.getElementById("investigation-kpi-related"),
  kpiRelatedMeta: document.getElementById("investigation-kpi-related-meta"),
  openObservability: document.getElementById("investigation-open-observability"),
  drawer: document.getElementById("investigation-drawer"),
  drawerBackdrop: document.getElementById("investigation-drawer-backdrop"),
  drawerTitle: document.getElementById("investigation-drawer-title"),
  drawerType: document.getElementById("investigation-drawer-type"),
  drawerClose: document.getElementById("investigation-drawer-close"),
  drawerFields: document.getElementById("investigation-drawer-fields"),
  drawerRelated: document.getElementById("investigation-drawer-related"),
  drawerWindow: document.getElementById("investigation-drawer-window"),
  filterForm: document.getElementById("investigation-filter-form"),
  filterBegin: document.getElementById("investigation-filter-begin"),
  filterEnd: document.getElementById("investigation-filter-end"),
  filterEventTypes: document.getElementById("investigation-filter-event-types"),
  filterEvent: document.getElementById("investigation-filter-event"),
  filterUsername: document.getElementById("investigation-filter-username"),
  filterNamespace: document.getElementById("investigation-filter-namespace"),
  pager: document.getElementById("investigation-pager"),
  pageInfo: document.getElementById("investigation-page-info"),
  pagePrev: document.getElementById("investigation-page-prev"),
  pageNext: document.getElementById("investigation-page-next"),
  filterSearch: document.getElementById("investigation-filter-search"),
  filterOrder: document.getElementById("investigation-filter-order"),
  tableWrapper: document.getElementById("investigation-table-wrapper"),
  tableBody: document.getElementById("investigation-table-body"),
  empty: document.getElementById("investigation-empty"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disable right away so a double click doesn't fire two requests.
  dom.searchButton.disabled = isLoading;
  dom.searchButton.classList.toggle("btn--spinning", isLoading);
}

function setErrorBanner(message) {
  if (!message) {
    dom.errorBanner.hidden = true;
    return;
  }
  dom.errorBannerText.textContent = message;
  dom.errorBanner.hidden = false;
}

function setConnectionState(state, label) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
}

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

// Rows are built with createElement/textContent (no innerHTML).
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

// How far to widen the time window on each side, to allow for some clock
// and processing skew between the backend and IRIS.
const CROSS_LINK_PADDING_MS = 30_000;

function pad2(n) {
  return String(n).padStart(2, "0");
}

// Format a Date as "YYYY-MM-DD HH:MM:SS" in UTC, for observability.js's
// time filter. Not the same as this page's begin/end filters, which IRIS
// reads as server local time.
function formatUtcForObservabilityFilter(date) {
  return (
    `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())} ` +
    `${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}:${pad2(date.getUTCSeconds())}`
  );
}

// UTCTimeStamp looks like "2026-09-19 14:10:36.808": it's UTC, but needs
// converting to ISO 8601 before Date can parse it.
function parseUtcTimestamp(value) {
  if (typeof value !== "string" || !value) return null;
  const date = new Date(`${value.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function computeObservabilityTimeWindow(utcTimeStamp) {
  const center = parseUtcTimestamp(utcTimeStamp);
  if (!center) return null;
  return {
    begin: formatUtcForObservabilityFilter(new Date(center.getTime() - CROSS_LINK_PADDING_MS)),
    end: formatUtcForObservabilityFilter(new Date(center.getTime() + CROSS_LINK_PADDING_MS)),
  };
}

let onInvestigateTraces = null;
let onOpenTrace = null;
// Our own execution traces from the last search, only used for the +/-30 s
// matching. null if they couldn't be loaded.
let lastTraces = null;

// Observability filters as you type (it only re-renders), but here the
// filters are server query parameters. Searching on every key would hammer
// the backend, so we debounce instead, which feels about the same. Search
// and Enter still run right away.
const AUTO_SEARCH_DEBOUNCE_MS = 500;
let autoSearchTimer = null;

function scheduleAutoSearch() {
  if (autoSearchTimer) clearTimeout(autoSearchTimer);
  autoSearchTimer = setTimeout(() => {
    autoSearchTimer = null;
    loadInvestigation();
  }, AUTO_SEARCH_DEBOUNCE_MS);
}

/**
 * Collect the server-side filter values for getAuditRecords(). The Event
 * Type / Event / Username / Namespace dropdowns aren't sent: they're built
 * from the results and filter them locally (applyRecordFilters), so picking
 * one doesn't make the other options disappear.
 */
function collectFilters() {
  return {
    beginDateTime: dom.filterBegin.value.trim(),
    endDateTime: dom.filterEnd.value.trim(),
    jsonSearch: dom.filterSearch.value.trim(),
    ascending: dom.filterOrder.value,
  };
}

// [select, AuditRecordEntry field] for the local dropdown filters.
const RECORD_FILTERS = [
  [dom.filterEventTypes, "EventType"],
  [dom.filterEvent, "Event"],
  [dom.filterUsername, "Username"],
  [dom.filterNamespace, "Namespace"],
];

/**
 * Refill each dropdown with ALL plus the distinct values in `records` (with
 * counts). Keep the current choice if it's still there, otherwise ALL.
 */
function populateRecordFilters(records) {
  for (const [select, key] of RECORD_FILTERS) {
    const previous = select.value;
    const counts = countBy(records.filter((r) => typeof r[key] === "string" && r[key] !== ""), (r) => r[key])
      .sort((a, b) => a.key.localeCompare(b.key));
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "ALL";
    select.replaceChildren(
      all,
      ...counts.map(({ key: value, count }) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = `${value} (${count})`;
        return option;
      }),
    );
    select.value = counts.some((c) => c.key === previous) ? previous : "";
  }
}

function renderAuditEnabled(settled) {
  if (settled.status !== "fulfilled") {
    dom.auditEnabled.textContent = "";
    return null;
  }
  const response = settled.value;
  const enabled =
    response && response.result && typeof response.result.Enabled === "boolean"
      ? response.result.Enabled
      : undefined;
  dom.auditEnabled.textContent =
    enabled === true
      ? "Auditing is enabled on this instance."
      : enabled === false
        ? "Auditing is disabled on this instance — no audit records are being written."
        : "";
  return enabled;
}

// --- related Command Center traces (+/-30 s) ---

/**
 * Traces starting within the same +/-30 s window the "View in
 * Observability" link uses (observability.js's matchesTimeWindow() applies
 * it the same way), so the two agree. null if traces couldn't be loaded.
 */
function relatedTraces(record) {
  if (!Array.isArray(lastTraces)) return null;
  const window_ = computeObservabilityTimeWindow(record.UTCTimeStamp);
  if (!window_) return [];
  const begin = parseUtcTimestamp(window_.begin);
  const end = parseUtcTimestamp(window_.end);
  return lastTraces.filter((trace) => {
    const start = new Date(trace.start_time);
    return !Number.isNaN(start.getTime()) && start >= begin && start <= end;
  });
}

// --- KPI cards (counts over the returned records) ---

function distinctCount(records, key) {
  return new Set(records.map((r) => r[key]).filter((v) => typeof v === "string" && v !== "")).size;
}

function renderKpis(records) {
  const list = Array.isArray(records) ? records : null;
  dom.kpiEvents.textContent = list ? list.length.toLocaleString() : PLACEHOLDER;
  dom.kpiEventKinds.textContent = list ? String(distinctCount(list, "Event")) : PLACEHOLDER;
  dom.kpiEventKindsMeta.textContent = list ? `across ${distinctCount(list, "EventType")} event types` : "";
  dom.kpiUsers.textContent = list ? String(distinctCount(list, "Username")) : PLACEHOLDER;
  dom.kpiNamespaces.textContent = list ? String(distinctCount(list, "Namespace")) : PLACEHOLDER;
  if (!list || !Array.isArray(lastTraces)) {
    dom.kpiRelated.textContent = PLACEHOLDER;
    dom.kpiRelatedMeta.textContent = list ? "traces unavailable" : "trace within ±30 s";
    return;
  }
  const related = list.filter((r) => (relatedTraces(r) || []).length > 0).length;
  dom.kpiRelated.textContent = related.toLocaleString();
  dom.kpiRelatedMeta.textContent = "trace within ±30 s";
}

// --- Audit Activity Timeline ---

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function formatAxisLabel(date, spanMs) {
  const hm = `${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}`;
  return spanMs > 86_400_000 ? `${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())} ${hm}` : hm;
}

// Plot only the last 24 hours of the results (up to the newest record).
// Otherwise a few install-time records stretch the axis over months and
// squash everything recent together.
const TIMELINE_WINDOW_MS = 24 * 60 * 60 * 1000;

/**
 * One dot per record in the last 24 h, placed by UTCTimeStamp, with one
 * lane per event (top 6 events, the rest in "Other"). Older records are
 * counted in the caption.
 */
function renderTimeline(records) {
  const all = (Array.isArray(records) ? records : [])
    .map((record) => ({ record, time: parseUtcTimestamp(record.UTCTimeStamp) }))
    .filter((entry) => entry.time);
  if (all.length === 0) {
    dom.overview.hidden = true;
    return;
  }
  dom.overview.hidden = false;

  const newest = Math.max(...all.map((e) => e.time.getTime()));
  const dated = all.filter((e) => e.time.getTime() >= newest - TIMELINE_WINDOW_MS);
  const notShown = all.length - dated.length;

  const lanes = assignColors(topCategories(countBy(dated, (e) => e.record.Event || "Unknown"), 6));
  const laneOf = new Map(lanes.map((lane, i) => [lane.key, i]));
  const otherIndex = laneOf.has("Other") ? laneOf.get("Other") : null;
  const times = dated.map((e) => e.time.getTime());
  const min = Math.min(...times);
  const max = Math.max(...times);
  const span = max - min;

  const plot = el("div", "inv-timeline__plot");
  plot.style.setProperty("--inv-lanes", String(lanes.length));
  lanes.forEach((lane, i) => {
    const row = el("div", "inv-timeline__lane");
    row.style.top = `${((i + 0.5) / lanes.length) * 100}%`;
    plot.append(row);
  });
  for (const { record, time } of dated) {
    const laneIndex = laneOf.has(record.Event || "Unknown") ? laneOf.get(record.Event || "Unknown") : otherIndex;
    const lane = lanes[laneIndex];
    const dot = el("button", "inv-timeline__dot");
    dot.type = "button";
    dot.style.left = `${span ? ((time.getTime() - min) / span) * 100 : 50}%`;
    dot.style.top = `${((laneIndex + 0.5) / lanes.length) * 100}%`;
    dot.style.background = lane.color;
    const label = `${textOrPlaceholder(record.Event)} · ${textOrPlaceholder(record.UTCTimeStamp)} UTC`;
    dot.title = label;
    dot.setAttribute("aria-label", label);
    dot.addEventListener("click", () => openDetail(record));
    plot.append(dot);
  }

  const axis = el("div", "inv-timeline__axis");
  const ticks = span ? 5 : 1;
  for (let i = 0; i < ticks; i += 1) {
    const at = span ? min + (span * i) / (ticks - 1) : min;
    const tick = el("span", "inv-timeline__tick", formatAxisLabel(new Date(at), span));
    tick.style.left = `${span ? (i / (ticks - 1)) * 100 : 50}%`;
    axis.append(tick);
  }
  const caption = el("p", "inv-timeline__caption",
    `${formatUtcForObservabilityFilter(new Date(min))} → ${formatUtcForObservabilityFilter(new Date(max))} UTC · ` +
    `${dated.length.toLocaleString()} event${dated.length === 1 ? "" : "s"}` +
    (notShown
      ? ` · ${notShown.toLocaleString()} earlier record${notShown === 1 ? "" : "s"} not plotted (use Begin/End to explore them)`
      : ""));
  dom.timeline.replaceChildren(plot, axis, caption);

  dom.legend.replaceChildren(
    ...lanes.map((lane) => {
      const item = el("li", "inv-legend__item");
      const swatch = el("span", "inv-legend__swatch");
      swatch.style.background = lane.color;
      item.append(swatch, el("span", "inv-legend__label", lane.key), el("span", "inv-legend__count", lane.count.toLocaleString()));
      return item;
    }),
  );
}

// --- event detail panel ---

let currentDetailRecord = null;  // record shown in the detail panel

const DETAIL_FIELDS = [
  ["Time (server)", "TimeStamp"],
  ["Time (UTC)", "UTCTimeStamp"],
  ["Event Source", "EventSource"],
  ["Event Type", "EventType"],
  ["Event", "Event"],
  ["Username", "Username"],
  ["OS Username", "OSUsername"],
  ["Namespace", "Namespace"],
  ["Authentication", "Authentication"],
  ["Client IP", "ClientIPAddress"],
  ["Client Executable", "ClientExecutableName"],
  ["Routine", "RoutineSpec"],
  ["Process ID", "Pid"],
  ["Status", "Status"],
  ["Description", "Description"],
  ["Event Data", "EventData"],
];

function statusVariant(status) {
  return status === "success" ? "ok" : status === "dry_run" ? "neutral" : "error";
}

function renderRelated(record) {
  const related = relatedTraces(record);
  if (related === null) {
    dom.drawerRelated.replaceChildren(el("p", "ns-hint", "Command Center traces could not be loaded, so no correlation is shown."));
    return;
  }
  if (related.length === 0) {
    dom.drawerRelated.replaceChildren(
      el("p", "ns-hint", "No Command Center execution trace started within ±30 seconds of this event."),
    );
    return;
  }
  dom.drawerRelated.replaceChildren(
    ...related.map((trace) => {
      const card = el("div", "inv-related");
      const head = el("div", "inv-related__head");
      head.append(
        el("span", "inv-related__name", textOrPlaceholder(trace.operation_name)),
        el("span", `status-badge status-badge--${statusVariant(trace.status)}`,
          String(trace.status || PLACEHOLDER).replace(/_/g, " ")),
      );
      const meta = el("p", "inv-related__meta",
        `${textOrPlaceholder(trace.start_time)} · ` +
        `${typeof trace.duration_ms === "number" ? `${trace.duration_ms.toFixed(2)} ms` : PLACEHOLDER} · ` +
        `trace ${String(trace.trace_id || "").slice(0, 12)}…`);
      card.append(head, meta);
      if (onOpenTrace && trace.trace_id) {
        const open = el("button", "btn btn--primary inv-related__open", "Open Trace →");
        open.type = "button";
        open.addEventListener("click", () => {
          closeDetail();
          onOpenTrace(trace.trace_id);
        });
        card.append(open);
      }
      return card;
    }),
  );
}

function openDetail(record) {
  currentDetailRecord = record;
  dom.drawerTitle.textContent = textOrPlaceholder(record.Event);
  dom.drawerType.textContent = textOrPlaceholder(record.EventType);
  dom.drawerFields.replaceChildren(
    ...DETAIL_FIELDS.map(([label, key]) => {
      const row = el("div", "info-list__row");
      const value = el("dd", "info-list__value info-list__value--mono", textOrPlaceholder(record[key]));
      if (key === "EventData" || key === "Description") value.classList.add("inv-detail__long");
      row.append(el("dt", "", label), value);
      return row;
    }),
  );
  renderRelated(record);
  dom.drawerWindow.hidden = !(onInvestigateTraces && computeObservabilityTimeWindow(record.UTCTimeStamp));
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawerClose.focus();
}

function closeDetail() {
  currentDetailRecord = null;
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

// --- the audit event table ---

const PAGE_SIZE = 25;
let returnedRecords = [];  // last records returned for the server-side filters
let lastAuditEnabled; // from the same search
let currentPage = 0;

function renderRecords(settled, auditEnabled) {
  lastAuditEnabled = auditEnabled;
  currentPage = 0;

  if (settled.status !== "fulfilled") {
    returnedRecords = [];
    populateRecordFilters([]);
    dom.tableBody.replaceChildren();
    dom.tableWrapper.hidden = true;
    dom.pager.hidden = true;
    dom.empty.textContent = "Could not load audit records.";
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    renderKpis(null);
    renderTimeline(null);
    return;
  }

  returnedRecords = Array.isArray(settled.value.result) ? settled.value.result : [];
  populateRecordFilters(returnedRecords);
  applyRecordFilters();
}

/**
 * Filter the records by the dropdowns (ALL = no filter) and re-render the
 * KPIs, timeline and table.
 */
function applyRecordFilters() {
  const records = returnedRecords.filter((record) =>
    RECORD_FILTERS.every(([select, key]) => select.value === "" || record[key] === select.value),
  );
  renderKpis(records);
  renderTimeline(records);

  if (records.length === 0) {
    dom.tableBody.replaceChildren();
    dom.tableWrapper.hidden = true;
    dom.pager.hidden = true;
    dom.empty.textContent =
      returnedRecords.length > 0
        ? "No returned audit records match the selected Event Type / Event / Username / Namespace."
        : lastAuditEnabled === false
          ? "Auditing is disabled on this instance, so there is nothing to search."
          : "No audit records match these filters.";
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.empty.hidden = true;
  dom.tableWrapper.hidden = false;
  dom.countLabel.textContent =
    records.length === returnedRecords.length
      ? `${records.length} record${records.length === 1 ? "" : "s"}`
      : `${records.length} of ${returnedRecords.length} records`;
  renderTablePage(records);
}

/** Render one page (PAGE_SIZE) of `records` and the pager. */
function renderTablePage(records) {
  const pages = Math.max(1, Math.ceil(records.length / PAGE_SIZE));
  currentPage = Math.min(Math.max(currentPage, 0), pages - 1);
  const start = currentPage * PAGE_SIZE;
  const pageRecords = records.slice(start, start + PAGE_SIZE);

  dom.pager.hidden = false;
  dom.pageInfo.textContent =
    `Showing ${(start + 1).toLocaleString()}–${(start + pageRecords.length).toLocaleString()} ` +
    `of ${records.length.toLocaleString()} events · page ${currentPage + 1} of ${pages}`;
  dom.pagePrev.disabled = currentPage === 0;
  dom.pageNext.disabled = currentPage >= pages - 1;
  dom.pagePrev.onclick = () => { currentPage -= 1; renderTablePage(records); };
  dom.pageNext.onclick = () => { currentPage += 1; renderTablePage(records); };

  dom.tableBody.replaceChildren();
  for (const record of pageRecords) {
    const row = document.createElement("tr");
    row.className = "data-table__row--link";
    row.tabIndex = 0;
    row.title = "Open audit event details";

    const typeCell = document.createElement("td");
    typeCell.className = "data-table__cell";
    typeCell.append(el("span", "status-badge status-badge--neutral", textOrPlaceholder(record.EventType)));

    const related = relatedTraces(record);
    const relatedCell = makeCell(
      related === null ? PLACEHOLDER : related.length ? `${related.length} trace${related.length === 1 ? "" : "s"}` : PLACEHOLDER,
    );
    if (related && related.length) relatedCell.classList.add("inv-related-cell");

    row.append(
      makeCell(textOrPlaceholder(record.TimeStamp), { mono: true }),
      typeCell,
      makeCell(textOrPlaceholder(record.Event)),
      makeCell(textOrPlaceholder(record.Username), { mono: true }),
      makeCell(textOrPlaceholder(record.Namespace)),
      makeCell(textOrPlaceholder(record.Description)),
      relatedCell,
    );
    row.addEventListener("click", () => openDetail(record));
    row.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openDetail(record);
    });
    dom.tableBody.append(row);
  }
}

/**
 * Load both audit endpoints with the current filters (plus our trace list
 * for matching) and render. allSettled so one failure doesn't block the
 * others.
 */
export async function loadInvestigation() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…");

  const filters = collectFilters();
  const [auditEnabledResult, recordsResult, tracesResult] = await Promise.allSettled([
    IrisApi.getAuditEnabled(),
    IrisApi.getAuditRecords(filters),
    // From our own trace store, just for the +/-30 s matching. If it fails,
    // matching shows as unknown; the audit results are unaffected.
    IrisApi.getExecutionTraces(),
  ]);
  lastTraces =
    tracesResult.status === "fulfilled" && Array.isArray(tracesResult.value?.traces)
      ? tracesResult.value.traces
      : null;

  const auditEnabled = renderAuditEnabled(auditEnabledResult);
  renderRecords(recordsResult, auditEnabled);

  const results = { auditEnabledResult, recordsResult };
  const settledList = Object.values(results);
  const allFailed = settledList.every((r) => r.status === "rejected");
  const anyFailed = settledList.some((r) => r.status === "rejected");

  if (allFailed) {
    setConnectionState("error", "Could not reach IRIS");
    setErrorBanner(
      "Could not load investigation data right now. The Command Center backend may be unreachable.",
    );
  } else if (anyFailed) {
    setConnectionState("degraded", "Connected (with warnings)");
    setErrorBanner("Some investigation data could not be loaded. The rest is shown below.");
  } else {
    setConnectionState("connected", "Connected");
    setErrorBanner(null);
  }

  setLoading(false);
}

/**
 * Set the Begin/End filter (IRIS server local time) without fetching.
 * app.js calls this right before navigateTo("investigation"), which does
 * the fetch. Other filters are cleared so an old username or event type
 * doesn't narrow the results.
 */
export function setTimeWindow(beginDateTime, endDateTime) {
  dom.filterBegin.value = beginDateTime;
  dom.filterEnd.value = endDateTime;
  for (const [select] of RECORD_FILTERS) select.value = "";
  dom.filterSearch.value = "";
}

/**
 * `onInvestigateTraces` is called with `{ begin, end }` (UTC, in
 * observability.js's filter format) when someone clicks a row's "Traces"
 * button (see app.js).
 */
export function initInvestigationControls({ onInvestigateTraces: callback, onOpenTrace: openTrace } = {}) {
  onInvestigateTraces = typeof callback === "function" ? callback : null;
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;

  // Just navigation: Observability shows our own traces.
  dom.openObservability.addEventListener("click", () => navigateTo("observability"));

  // Event detail panel (modal behaviour comes from detail-workspace.js);
  // here we just open and close it.
  dom.drawerClose.addEventListener("click", closeDetail);
  dom.drawerBackdrop.addEventListener("click", closeDetail);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDetail();
  });
  dom.drawerWindow.addEventListener("click", () => {
    const record = currentDetailRecord;
    const window_ = record ? computeObservabilityTimeWindow(record.UTCTimeStamp) : null;
    if (!window_ || !onInvestigateTraces) return;
    closeDetail();
    onInvestigateTraces(window_);
  });

  // The Search button sits in the page header but is a submit button for
  // this form (form="investigation-filter-form"), so clicking it and pressing
  // Enter both end up here. A submit searches right away and cancels any
  // pending debounced search.
  dom.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (autoSearchTimer) {
      clearTimeout(autoSearchTimer);
      autoSearchTimer = null;
    }
    loadInvestigation();
  });

  // Typing (or changing Order) schedules a debounced search.
  [dom.filterBegin, dom.filterEnd, dom.filterSearch].forEach((input) => {
    input.addEventListener("input", scheduleAutoSearch);
  });
  dom.filterOrder.addEventListener("change", scheduleAutoSearch);

  // The dropdowns filter the loaded records right away, no fetch.
  for (const [select] of RECORD_FILTERS) {
    select.addEventListener("change", () => {
      currentPage = 0;
      applyRecordFilters();
    });
  }
}
