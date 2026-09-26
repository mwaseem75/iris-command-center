// Investigation view: fetches GET /api/iris/security/audit/enabled and GET
// /api/iris/security/audit/records (via IrisApi.getAuditEnabled/
// getAuditRecords) and renders them. No other endpoint is called from this
// module, and no mutating HTTP method is used anywhere in it — IRIS itself
// runs the audit-record query as an async task (POST-then-poll), but that
// happens entirely on the backend (see backend/app/routes/iris.py's
// get_audit_records); this view only ever sends a GET.
//
// Fields shown are exactly a subset of what backend/app/models/iris.py's
// AuditRecordEntry actually defines (Time/EventType/Event/Username/
// Namespace/Authentication/ClientIPAddress/Description) — nothing invented.
// See docs/api-capability-matrix.md's "POST /v2/security/audit/records"
// entry for how that shape was verified against a real IRIS instance.
//
// Cross-links with Observability (backend/app/observability/,
// frontend/js/observability.js): the only correlation this app ever draws
// between an execution trace and an audit record is TIME PROXIMITY — there
// is no shared ID linking the two, since the Command Center's own
// execution traces and IRIS's own audit log are two entirely separate
// systems. `setTimeWindow()` lets Observability jump here with a time
// window pre-filled (see app.js); the "Traces near this time" button per
// row below does the reverse, using this record's own UTCTimeStamp — never
// an invented or assumed IRIS-side link between the two systems.
//
// Layout: KPI cards and an Audit Activity Timeline computed only from the
// returned records (real timestamps and counts), the filters, the audit
// table, and a centered event-detail workspace. The workspace lists the
// Command Center traces that started inside that same ±30 s window (read
// from GET /api/iris/observability/traces — the Command Center's own trace
// store, not IRIS) with an Open Trace action.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { assignColors, countBy, topCategories } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

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
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Search click a no-op — the same pattern already used and
  // reviewed in the other views.
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

// Table rows are always built via document.createElement + .textContent —
// never innerHTML — so a description/event-data value containing
// HTML-special characters can never be interpreted as markup.
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

// How far either side of a record's/trace's own timestamp the cross-link
// window extends — wide enough to absorb normal clock/processing skew
// between this backend and IRIS, without being so wide it defeats the
// point of narrowing the search.
const CROSS_LINK_PADDING_MS = 30_000;

function pad2(n) {
  return String(n).padStart(2, "0");
}

// Formats a JS Date as "YYYY-MM-DD HH:MM:SS" in UTC — the shape
// observability.js's own (UTC) time filter expects. Distinct from this
// view's OWN beginDateTime/endDateTime filters, which IRIS interprets in
// the server's LOCAL time (see docs/api-capability-matrix.md's "POST
// /v2/security/audit/records" entry) — never conflated with this.
function formatUtcForObservabilityFilter(date) {
  return (
    `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())} ` +
    `${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}:${pad2(date.getUTCSeconds())}`
  );
}

// AuditRecordEntry.UTCTimeStamp (backend/app/models/iris.py) looks like
// "2026-09-19 14:10:36.808" — genuinely UTC, but not directly
// Date-parseable without normalizing to ISO 8601 first.
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
// The Command Center's own execution traces from the last search (GET
// /api/iris/observability/traces — the in-memory store, not IRIS), used
// only for the ±30 s correlation. null = could not be loaded.
let lastTraces = null;

// Observability's identical-looking filter card updates instantly on every
// keystroke (it's just re-rendering already-fetched data). This view's
// filters map to real server-side query parameters, so a true "instant"
// re-fetch per keystroke isn't appropriate — but leaving the two views with
// opposite interaction models (type-and-see vs. type-then-click-Search) is
// confusing given they're directly cross-linked to each other. Debouncing
// gets the same "just start typing" feel without hammering the backend on
// every character. The Search button/Enter still work immediately, for an
// operator who wants a result right away.
const AUTO_SEARCH_DEBOUNCE_MS = 500;
let autoSearchTimer = null;

function scheduleAutoSearch() {
  if (autoSearchTimer) clearTimeout(autoSearchTimer);
  autoSearchTimer = setTimeout(() => {
    autoSearchTimer = null;
    loadInvestigation();
  }, AUTO_SEARCH_DEBOUNCE_MS);
}

/** Reads the server-side filter values into the plain object shape
 * IrisApi.getAuditRecords()/the backend's get_audit_records route expect —
 * exactly the documented, optional query parameters, nothing invented. The
 * Event Type / Event / Username / Namespace dropdowns are NOT sent: they are
 * built from the returned records and narrow them in place (see
 * applyRecordFilters), so choosing one never makes the other options vanish. */
function collectFilters() {
  return {
    beginDateTime: dom.filterBegin.value.trim(),
    endDateTime: dom.filterEnd.value.trim(),
    jsonSearch: dom.filterSearch.value.trim(),
    ascending: dom.filterOrder.value,
  };
}

// [select, AuditRecordEntry field] — the in-place dropdown filters.
const RECORD_FILTERS = [
  [dom.filterEventTypes, "EventType"],
  [dom.filterEvent, "Event"],
  [dom.filterUsername, "Username"],
  [dom.filterNamespace, "Namespace"],
];

/** Refills each dropdown with ALL + the distinct real values of its field in
 * `records` (with their counts), keeping the current choice when it is
 * still present, otherwise falling back to ALL. */
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

// --- related Command Center traces (existing ±30 s time-proximity rule) ---

/** Traces whose start_time falls inside the SAME ±30 s window the
 * "View in Observability" cross-link hands to observability.js (whose
 * matchesTimeWindow() applies it the same way) — so both always agree.
 * Returns null when traces could not be loaded (unknown, not "none"). */
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

// --- KPI cards (counts over the returned records only) ---

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

// --- Audit Activity Timeline (real UTC timestamps only) ---

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

// The timeline plots the latest 24 hours of the returned records (ending at
// the newest one): an instance's few install-time records would otherwise
// stretch the axis over months and squash every recent event together.
const TIMELINE_WINDOW_MS = 24 * 60 * 60 * 1000;

/** One dot per returned record in the latest 24 h of the results,
 * positioned by its own UTCTimeStamp, in one lane per event (top 6 real
 * Event values, the rest folded into a real "Other" lane). Older records
 * are counted in the caption, never dropped silently. */
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

// --- event detail workspace ---

let currentDetailRecord = null; // the record the open detail workspace shows

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
let returnedRecords = []; // the last records IRIS returned for the server-side filters
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

/** Narrows the returned records by the dropdowns (ALL = no filter) and
 * re-renders the KPIs, timeline and table from that same set. */
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

/** Renders one PAGE_SIZE page of `records` plus the pager. */
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
 * Fetches both audit endpoints with the current filter values (plus the
 * Command Center's own trace list, for correlation only) and renders them.
 * These are the ONLY network calls this module makes — all GETs; no
 * mutating request exists anywhere in this file. Uses Promise.allSettled so
 * one failing endpoint never blocks the others from rendering, the same
 * pattern used in security.js/dashboard.js.
 */
export async function loadInvestigation() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…");

  const filters = collectFilters();
  const [auditEnabledResult, recordsResult, tracesResult] = await Promise.allSettled([
    IrisApi.getAuditEnabled(),
    IrisApi.getAuditRecords(filters),
    // Read-only, from the Command Center's own trace store (not IRIS) —
    // only for the ±30 s related-trace correlation. A failure just leaves
    // the correlation unknown; it never affects the audit results.
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
 * Sets the Begin/End filter fields (IRIS server local time, per this
 * view's own convention) without fetching anything itself — called by
 * app.js right before nav.navigateTo("investigation"), so the navigation's
 * own view-opened callback performs the one real fetch, already using
 * these values. Also clears the other filters, so a stale username/event
 * type typed earlier can't silently narrow a cross-link's results.
 */
export function setTimeWindow(beginDateTime, endDateTime) {
  dom.filterBegin.value = beginDateTime;
  dom.filterEnd.value = endDateTime;
  for (const [select] of RECORD_FILTERS) select.value = "";
  dom.filterSearch.value = "";
}

/**
 * `onInvestigateTraces`, when provided, is called with `{ begin, end }`
 * (UTC, formatted for observability.js's own time filter) whenever the
 * operator clicks a row's "Traces" cross-link button — see app.js for how
 * it's wired to actually switch views.
 */
export function initInvestigationControls({ onInvestigateTraces: callback, onOpenTrace: openTrace } = {}) {
  onInvestigateTraces = typeof callback === "function" ? callback : null;
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;

  // Navigation only: Observability shows the Command Center's own traces.
  dom.openObservability.addEventListener("click", () => navigateTo("observability"));

  // Event detail workspace (shared .ns-drawer modal behaviour comes from
  // detail-workspace.js); this module only opens/closes it.
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

  // The Search button is type="submit" and associated with this form via
  // its `form="investigation-filter-form"` attribute (it lives in the view
  // header, outside the <form> itself) — so both clicking it AND pressing
  // Enter in any filter field fire this one `submit` event; there is no
  // separate click handler to keep in sync with it. An explicit submit
  // always searches immediately, cancelling any pending debounced search
  // so the two never race and fire twice.
  dom.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
    if (autoSearchTimer) {
      clearTimeout(autoSearchTimer);
      autoSearchTimer = null;
    }
    loadInvestigation();
  });

  // Live-ish filtering to match Observability's instant feel: typing (or
  // changing Order) schedules a debounced re-search rather than requiring
  // an explicit Search click every time.
  [dom.filterBegin, dom.filterEnd, dom.filterSearch].forEach((input) => {
    input.addEventListener("input", scheduleAutoSearch);
  });
  dom.filterOrder.addEventListener("change", scheduleAutoSearch);

  // The dropdowns narrow the already-returned records instantly — no fetch.
  for (const [select] of RECORD_FILTERS) {
    select.addEventListener("change", () => {
      currentPage = 0;
      applyRecordFilters();
    });
  }
}
