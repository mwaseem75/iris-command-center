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

import { IrisApi, ApiError } from "./api.js";

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
  filterForm: document.getElementById("investigation-filter-form"),
  filterBegin: document.getElementById("investigation-filter-begin"),
  filterEnd: document.getElementById("investigation-filter-end"),
  filterEventTypes: document.getElementById("investigation-filter-event-types"),
  filterUsername: document.getElementById("investigation-filter-username"),
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

/** Reads the current filter form values into the plain object shape
 * IrisApi.getAuditRecords()/the backend's get_audit_records route expect —
 * exactly the documented, optional query parameters, nothing invented. */
function collectFilters() {
  return {
    beginDateTime: dom.filterBegin.value.trim(),
    endDateTime: dom.filterEnd.value.trim(),
    eventTypes: dom.filterEventTypes.value.trim(),
    usernames: dom.filterUsername.value.trim(),
    jsonSearch: dom.filterSearch.value.trim(),
    ascending: dom.filterOrder.value,
  };
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

function renderRecords(settled, auditEnabled) {
  dom.tableBody.replaceChildren();

  if (settled.status !== "fulfilled") {
    dom.tableWrapper.hidden = true;
    dom.empty.textContent = "Could not load audit records.";
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  const records = Array.isArray(settled.value.result) ? settled.value.result : [];

  if (records.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.textContent =
      auditEnabled === false
        ? "Auditing is disabled on this instance, so there is nothing to search."
        : "No audit records match these filters.";
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.empty.hidden = true;
  dom.tableWrapper.hidden = false;
  dom.countLabel.textContent = `${records.length} record${records.length === 1 ? "" : "s"}`;

  for (const record of records) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(record.TimeStamp), { mono: true }),
      makeCell(textOrPlaceholder(record.EventType)),
      makeCell(textOrPlaceholder(record.Event)),
      makeCell(textOrPlaceholder(record.Username), { mono: true }),
      makeCell(textOrPlaceholder(record.Namespace)),
      makeCell(textOrPlaceholder(record.Authentication)),
      makeCell(textOrPlaceholder(record.ClientIPAddress), { mono: true }),
      makeCell(textOrPlaceholder(record.Description)),
    );

    const actionsCell = document.createElement("td");
    actionsCell.className = "data-table__cell";
    const window_ = computeObservabilityTimeWindow(record.UTCTimeStamp);
    if (onInvestigateTraces && window_) {
      const tracesButton = document.createElement("button");
      tracesButton.className = "btn";
      tracesButton.type = "button";
      tracesButton.textContent = "Traces";
      tracesButton.title =
        "View execution traces recorded within 30 seconds of this audit record (UTC)";
      tracesButton.addEventListener("click", () => onInvestigateTraces(window_));
      actionsCell.append(tracesButton);
    }
    row.append(actionsCell);

    dom.tableBody.append(row);
  }
}

/**
 * Fetches both endpoints with the current filter values and renders them.
 * These are the ONLY network calls this module makes — no mutating request
 * exists anywhere in this file. Uses Promise.allSettled so one failing
 * endpoint never blocks the other from rendering, the same pattern used in
 * security.js/dashboard.js.
 */
export async function loadInvestigation() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…");

  const filters = collectFilters();
  const [auditEnabledResult, recordsResult] = await Promise.allSettled([
    IrisApi.getAuditEnabled(),
    IrisApi.getAuditRecords(filters),
  ]);

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
  dom.filterEventTypes.value = "";
  dom.filterUsername.value = "";
  dom.filterSearch.value = "";
}

/**
 * `onInvestigateTraces`, when provided, is called with `{ begin, end }`
 * (UTC, formatted for observability.js's own time filter) whenever the
 * operator clicks a row's "Traces" cross-link button — see app.js for how
 * it's wired to actually switch views.
 */
export function initInvestigationControls({ onInvestigateTraces: callback } = {}) {
  onInvestigateTraces = typeof callback === "function" ? callback : null;

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
  [dom.filterBegin, dom.filterEnd, dom.filterEventTypes, dom.filterUsername, dom.filterSearch].forEach(
    (input) => {
      input.addEventListener("input", scheduleAutoSearch);
    },
  );
  dom.filterOrder.addEventListener("change", scheduleAutoSearch);
}
