// Observability view: fetches GET /api/iris/observability/traces ONLY —
// a read-only listing of the in-memory execution traces the backend's
// OperationExecutor records for every operation attempt (see
// backend/app/observability/). No other endpoint is called from this
// module, and no mutating HTTP method is used anywhere in it. This view
// never triggers an operation itself — it only displays traces that
// already exist because something else (e.g. the Operations view) ran
// one.
//
// The Begin/End time filter below is entirely client-side (the same
// fetch-once-then-filter-in-memory approach capabilities.js already uses)
// — filtering never re-fetches from the backend.
//
// Cross-links with Investigation (frontend/js/investigation.js): the only
// correlation drawn between an execution trace and an IRIS audit record is
// TIME PROXIMITY — there is no shared ID between the Command Center's own
// execution traces and IRIS's own audit log. "Investigate audit records"
// below uses this trace's own start_time/end_time; investigation.js's
// "Traces" button does the reverse using an audit record's UTCTimeStamp.
// Neither direction invents or assumes any IRIS-side link.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("observability-loading-state"),
  errorBanner: document.getElementById("observability-error-banner"),
  errorBannerText: document.getElementById("observability-error-banner-text"),
  refreshButton: document.getElementById("observability-refresh-button"),
  connectionStatus: document.getElementById("observability-connection-status"),
  connectionStatusLabel: document.getElementById("observability-connection-status-label"),
  countLabel: document.getElementById("observability-count"),
  filterForm: document.getElementById("observability-filter-form"),
  filterBegin: document.getElementById("observability-filter-begin"),
  filterEnd: document.getElementById("observability-filter-end"),
  filterClearButton: document.getElementById("observability-filter-clear-button"),
  tableWrapper: document.getElementById("observability-table-wrapper"),
  tableBody: document.getElementById("observability-table-body"),
  empty: document.getElementById("observability-empty"),
};

// Which trace/span each expanded detail row belongs to, so a Refresh can
// re-render without losing which rows the user had open.
const expandedTraceIds = new Set();

// The full list from the last successful fetch — the time filter only
// ever re-renders a subset of this, never re-fetches it.
let allTraces = [];

let onInvestigateTimeWindow = null;

// How far either side of a trace's own start/end time the cross-link
// window extends — wide enough to absorb normal clock/processing skew
// between this backend and IRIS, without being so wide it defeats the
// point of narrowing the search.
const CROSS_LINK_PADDING_MS = 30_000;

function pad2(n) {
  return String(n).padStart(2, "0");
}

// Formats a JS Date as "YYYY-MM-DD HH:MM:SS" in UTC — matches both this
// view's own (UTC) time filter and, separately, what is sent to
// investigation.js's setTimeWindow() (IRIS's server-LOCAL time filter —
// this app never converts between the two timezones, since a trace's
// start/end time carries no information about the connected IRIS
// instance's own clock/timezone; see investigation.js's module header).
function formatUtc(date) {
  return (
    `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())} ` +
    `${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}:${pad2(date.getUTCSeconds())}`
  );
}

function parseFilterInput(value) {
  const trimmed = typeof value === "string" ? value.trim() : "";
  if (!trimmed) return null;
  const date = new Date(`${trimmed.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function computeInvestigationTimeWindow(startIso, endIso) {
  const start = new Date(startIso);
  if (Number.isNaN(start.getTime())) return null;
  const end = endIso ? new Date(endIso) : start;
  const endTime = Number.isNaN(end.getTime()) ? start.getTime() : end.getTime();
  return {
    begin: formatUtc(new Date(start.getTime() - CROSS_LINK_PADDING_MS)),
    end: formatUtc(new Date(endTime + CROSS_LINK_PADDING_MS)),
  };
}

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling synchronously, before any await, is what makes a second
  // rapid Refresh click a no-op — the same pattern already used and
  // reviewed in every other view.
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

function setConnectionState(state, label) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
}

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

const STATUS_BADGE_CLASS = {
  success: "status-badge--ok",
  ok: "status-badge--ok",
  dry_run: "status-badge--neutral",
  skipped: "status-badge--neutral",
  not_applicable: "status-badge--neutral",
  confirmation_required: "status-badge--warning",
  required_not_received: "status-badge--warning",
};

function statusBadgeClass(status) {
  if (typeof status !== "string") return "status-badge--neutral";
  return STATUS_BADGE_CLASS[status] || "status-badge--error";
}

// Badges/cells are always built via document.createElement + .textContent
// — never innerHTML — so a status/attribute value can never be
// interpreted as markup.
function makeStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${statusBadgeClass(status)}`;
  badge.textContent = textOrPlaceholder(status).replace(/_/g, " ");
  return badge;
}

function makeCell(content) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  if (content instanceof Node) {
    cell.append(content);
  } else {
    cell.textContent = content;
    cell.title = content;
  }
  return cell;
}

function formatAttributeValue(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : PLACEHOLDER;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function buildInfoRow(label, value) {
  const row = document.createElement("div");
  row.className = "info-list__row";

  const dt = document.createElement("dt");
  dt.textContent = label;

  const dd = document.createElement("dd");
  dd.className = "info-list__value info-list__value--mono";
  dd.textContent = value;

  row.append(dt, dd);
  return row;
}

function buildSpanCard(span) {
  const card = document.createElement("div");
  card.className = "trace-detail__span";

  const title = document.createElement("div");
  title.className = "trace-detail__span-title";
  const nameEl = document.createElement("span");
  nameEl.textContent = textOrPlaceholder(span.name);
  title.append(nameEl, makeStatusBadge(span.status));
  card.append(title);

  const meta = document.createElement("p");
  meta.className = "trace-detail__span-meta";
  meta.textContent = `${formatDuration(span.duration_ms)} · ${formatTimestamp(span.start_time)}`;
  card.append(meta);

  const attributes = span.attributes && typeof span.attributes === "object" ? span.attributes : {};
  const list = document.createElement("dl");
  list.className = "info-list";
  const attrEntries = Object.entries(attributes);
  if (attrEntries.length === 0) {
    const empty = document.createElement("p");
    empty.className = "info-card__empty";
    empty.textContent = "No attributes recorded.";
    card.append(empty);
  } else {
    for (const [key, value] of attrEntries) {
      list.append(buildInfoRow(key, formatAttributeValue(value)));
    }
    card.append(list);
  }

  if (Array.isArray(span.events) && span.events.length > 0) {
    const eventsList = document.createElement("dl");
    eventsList.className = "info-list";
    for (const evt of span.events) {
      eventsList.append(buildInfoRow(evt.name, formatTimestamp(evt.timestamp)));
    }
    card.append(eventsList);
  }

  return card;
}

// Fixed stage order for the waterfall below — matches the order
// app/observability/tracer.py always records spans in (authorization ->
// confirmation -> execution -> verification), but this is looked up by
// name, not assumed by array position.
const WATERFALL_STAGES = ["authorization", "confirmation", "execution", "verification"];

/** A compact, proportional-by-duration visual timeline for the same four
 * spans buildSpanCard() below already renders as detail cards — this is
 * an additional, purely visual summary of the exact same trace/span data
 * already fetched from GET /api/iris/observability/traces, nothing new is
 * fetched or invented. Each segment's width (via CSS flex-grow) is
 * proportional to that span's real `duration_ms`; a small flex-grow floor
 * only keeps an exactly-zero-duration (e.g. skipped) stage visibly
 * present in the track — the duration shown in its tooltip/legend text is
 * always the real, unrounded value from the trace itself. Returns null if
 * the trace has none of the four expected spans (defensive; every real
 * trace recorded by TraceRecorder.finish() has all four).
 */
function buildWaterfall(trace) {
  const spans = Array.isArray(trace.spans) ? trace.spans : [];
  const spansByName = new Map(spans.map((span) => [span.name, span]));

  const track = document.createElement("div");
  track.className = "trace-detail__waterfall-track";

  const legend = document.createElement("div");
  legend.className = "trace-detail__waterfall-legend";

  let stageCount = 0;
  for (const stageName of WATERFALL_STAGES) {
    const span = spansByName.get(stageName);
    if (!span) continue;
    stageCount += 1;

    const duration = typeof span.duration_ms === "number" ? span.duration_ms : 0;
    // Reuses the exact same status -> badge-color mapping already used for
    // every other status badge in this file, so a segment's color always
    // means the same thing here as it does everywhere else in the app.
    const colorSuffix = statusBadgeClass(span.status).replace("status-badge--", "");

    const segment = document.createElement("div");
    segment.className = `trace-detail__waterfall-segment trace-detail__waterfall-segment--${colorSuffix}`;
    segment.style.flexGrow = String(Math.max(duration, 0.05));
    segment.title = `${stageName} — ${textOrPlaceholder(span.status)} — ${formatDuration(duration)}`;
    track.append(segment);

    const legendItem = document.createElement("span");
    legendItem.className = "trace-detail__waterfall-legend-item";
    const dot = document.createElement("span");
    dot.className = `trace-detail__waterfall-dot trace-detail__waterfall-dot--${colorSuffix}`;
    legendItem.append(dot, document.createTextNode(`${stageName} ${formatDuration(duration)}`));
    legend.append(legendItem);
  }

  if (stageCount === 0) return null;

  const wrapper = document.createElement("div");
  wrapper.className = "trace-detail__waterfall";
  wrapper.append(track, legend);
  return wrapper;
}

function buildTraceDetail(trace) {
  const container = document.createElement("div");
  container.className = "trace-detail";

  const summary = document.createElement("dl");
  summary.className = "info-list";
  summary.append(
    buildInfoRow("Authorization", textOrPlaceholder(trace.authorization_result)),
    buildInfoRow("Confirmation", textOrPlaceholder(trace.confirmation_result)),
    buildInfoRow("Execution", textOrPlaceholder(trace.execution_result)),
    buildInfoRow("Verification", textOrPlaceholder(trace.verification_result)),
  );
  container.append(summary);

  const waterfall = buildWaterfall(trace);
  if (waterfall) {
    container.append(waterfall);
  }

  const window_ = computeInvestigationTimeWindow(trace.start_time, trace.end_time);
  if (onInvestigateTimeWindow && window_) {
    const actions = document.createElement("div");
    actions.className = "btn-row";
    const investigateButton = document.createElement("button");
    investigateButton.className = "btn";
    investigateButton.type = "button";
    investigateButton.textContent = "Investigate audit records";
    investigateButton.title =
      "View IRIS audit records within 30 seconds of this trace (assumes the IRIS server clock is close to UTC)";
    investigateButton.addEventListener("click", () => onInvestigateTimeWindow(window_));
    actions.append(investigateButton);
    container.append(actions);
  }

  const spansGrid = document.createElement("div");
  spansGrid.className = "trace-detail__spans";
  const spans = Array.isArray(trace.spans) ? trace.spans : [];
  if (spans.length === 0) {
    const empty = document.createElement("p");
    empty.className = "info-card__empty";
    empty.textContent = "No spans recorded for this trace.";
    container.append(empty);
  } else {
    for (const span of spans) {
      spansGrid.append(buildSpanCard(span));
    }
    container.append(spansGrid);
  }

  return container;
}

function toggleTraceDetail(traceId) {
  if (expandedTraceIds.has(traceId)) {
    expandedTraceIds.delete(traceId);
  } else {
    expandedTraceIds.add(traceId);
  }
  applyFilters();
}

// `null` for either bound means "unfiltered" on that side. Compares
// against `trace.start_time` — a trace with no start_time (should never
// happen; every trace records one) is excluded rather than guessed into
// matching or not.
function matchesTimeWindow(trace, begin, end) {
  if (!begin && !end) return true;
  const start = new Date(trace.start_time);
  if (Number.isNaN(start.getTime())) return false;
  if (begin && start < begin) return false;
  if (end && start > end) return false;
  return true;
}

/** Re-renders from the already-fetched `allTraces` list using the current
 * time filter values — never triggers a network request. */
function applyFilters() {
  const begin = parseFilterInput(dom.filterBegin.value);
  const end = parseFilterInput(dom.filterEnd.value);
  renderTable(allTraces.filter((trace) => matchesTimeWindow(trace, begin, end)));
}

function renderTable(traces) {
  dom.tableBody.replaceChildren();

  if (!Array.isArray(traces) || traces.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.empty.textContent =
      allTraces.length > 0
        ? "No traces fall within this time window."
        : "No execution traces recorded yet. Traces appear here after an operation is attempted (e.g. from the Operations view).";
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent =
    traces.length === allTraces.length
      ? `${traces.length} trace${traces.length === 1 ? "" : "s"}`
      : `Showing ${traces.length} of ${allTraces.length} traces`;

  for (const trace of traces) {
    const isExpanded = expandedTraceIds.has(trace.trace_id);

    const row = document.createElement("tr");
    const traceIdText = textOrPlaceholder(trace.trace_id);
    row.append(
      makeCell(traceIdText.length > 12 ? `${traceIdText.slice(0, 12)}…` : traceIdText),
      makeCell(textOrPlaceholder(trace.operation_name)),
      makeCell(makeStatusBadge(trace.status)),
      makeCell(formatDuration(trace.duration_ms)),
      makeCell(formatTimestamp(trace.start_time)),
    );
    row.children[0].title = textOrPlaceholder(trace.trace_id);

    const toggleCell = document.createElement("td");
    toggleCell.className = "data-table__cell";
    const toggleButton = document.createElement("button");
    toggleButton.className = "btn";
    toggleButton.type = "button";
    toggleButton.textContent = isExpanded ? "Hide" : "Details";
    toggleButton.addEventListener("click", () => toggleTraceDetail(trace.trace_id));
    toggleCell.append(toggleButton);
    row.append(toggleCell);

    dom.tableBody.append(row);

    if (isExpanded) {
      const detailRow = document.createElement("tr");
      detailRow.className = "trace-detail-row";
      const detailCell = document.createElement("td");
      detailCell.className = "data-table__cell";
      detailCell.colSpan = 6;
      detailCell.append(buildTraceDetail(trace));
      detailRow.append(detailCell);
      dom.tableBody.append(detailRow);
    }
  }
}

/**
 * Fetches GET /api/iris/observability/traces and renders it. This is the
 * ONLY network call this module makes — no mutating request exists
 * anywhere in this file.
 */
export async function loadExecutionTraces() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…");

  let response;
  try {
    response = await IrisApi.getExecutionTraces();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load execution traces. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading execution traces.";
    setConnectionState("error", "Could not reach the backend");
    setErrorBanner(message);
    allTraces = [];
    renderTable(null);
    setLoading(false);
    return;
  }

  const traces = response && Array.isArray(response.traces) ? response.traces : null;

  if (traces === null) {
    setConnectionState("error", "Backend returned no data");
    setErrorBanner("The backend did not return the expected traces list.");
    allTraces = [];
    renderTable(null);
    setLoading(false);
    return;
  }

  setConnectionState("connected", "Connected");
  setErrorBanner(null);
  allTraces = traces;
  applyFilters();
  setLoading(false);
}

/**
 * Sets the Begin/End (UTC) filter fields and re-renders from the
 * already-fetched trace list — never fetches anything itself. Called by
 * app.js right before nav.navigateTo("observability"), so the
 * navigation's own view-opened callback performs the one real fetch,
 * after which this filter is naturally re-applied by loadExecutionTraces()
 * -> applyFilters().
 */
export function setTimeWindow(begin, end) {
  dom.filterBegin.value = begin;
  dom.filterEnd.value = end;
}

/**
 * `onInvestigateTimeWindow`, when provided, is called with
 * `{ begin, end }` (IRIS server local time, formatted for
 * investigation.js's own filters) whenever the operator clicks a trace's
 * "Investigate audit records" button — see app.js for how it's wired to
 * actually switch views.
 */
export function initObservabilityControls({ onInvestigateTimeWindow: callback } = {}) {
  onInvestigateTimeWindow = typeof callback === "function" ? callback : null;
  dom.refreshButton.addEventListener("click", () => {
    loadExecutionTraces();
  });

  // Filtering is client-side and instant — no network request, so every
  // input re-renders immediately rather than waiting for a submit/click.
  dom.filterBegin.addEventListener("input", applyFilters);
  dom.filterEnd.addEventListener("input", applyFilters);
  dom.filterClearButton.addEventListener("click", () => {
    dom.filterBegin.value = "";
    dom.filterEnd.value = "";
    applyFilters();
  });
  // Pressing Enter in a filter field would otherwise submit this <form>
  // and reload the page; filtering already happens live via the "input"
  // listeners above, so submitting just needs to be a harmless no-op.
  dom.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
  });
}
