// Observability view: an OpenTelemetry-inspired trace explorer over the
// Command Center's own execution traces. It fetches GET
// /api/iris/observability/traces ONLY — a read-only listing of the traces
// the backend's OperationExecutor records for every operation attempt (see
// backend/app/observability/). No other endpoint is called from this
// module, and no mutating HTTP method is used anywhere in it. This view
// never triggers an operation itself.
//
// Everything shown comes from the real ExecutionTrace/Span schema:
//   trace: trace_id, operation_name, status, start_time, end_time,
//          duration_ms, authorization/confirmation/execution/
//          verification_result, spans[]
//   span:  name, status ("ok" | "error" | "skipped"), start_time, end_time,
//          duration_ms, attributes{}, events[]
// Nothing is invented. Notably, a trace has no "target" field, so none is
// shown, and span events are listed only when a span actually recorded
// some.
//
// Waterfall timing, honestly: each span's `duration_ms` is measured with a
// high-resolution timer, while its `start_time`/`end_time` are wall-clock
// timestamps with the OS clock's resolution. So bar WIDTHS use the precise
// duration and bar POSITIONS use the recorded start offset from the trace's
// start; the scale grows to fit if a recorded start plus its duration runs
// past the trace total, rather than clipping or re-deriving positions.
//
// The Begin/End time filter and the search box are client-side only —
// filtering never re-fetches.
//
// Cross-links: with Investigation, correlation is TIME PROXIMITY only
// ("Investigate audit records" uses this trace's own start/end time);
// Dashboard and Demo Activity call focusTrace() to open one trace here.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention
const STAGE_ORDER = ["authorization", "confirmation", "execution", "verification"];

const dom = {
  loadingState: document.getElementById("observability-loading-state"),
  errorBanner: document.getElementById("observability-error-banner"),
  errorBannerText: document.getElementById("observability-error-banner-text"),
  refreshButton: document.getElementById("observability-refresh-button"),
  statTotal: document.getElementById("observability-stat-total"),
  statSuccess: document.getElementById("observability-stat-success"),
  statDryRun: document.getElementById("observability-stat-dryrun"),
  statOther: document.getElementById("observability-stat-other"),
  statOtherLabel: document.getElementById("observability-stat-other-label"),
  filterForm: document.getElementById("observability-filter-form"),
  filterBegin: document.getElementById("observability-filter-begin"),
  filterEnd: document.getElementById("observability-filter-end"),
  filterClearButton: document.getElementById("observability-filter-clear-button"),
  unavailable: document.getElementById("observability-unavailable"),
  workspace: document.getElementById("observability-workspace"),
  countLabel: document.getElementById("observability-count"),
  search: document.getElementById("observability-search"),
  traceList: document.getElementById("observability-trace-list"),
  empty: document.getElementById("observability-empty"),
  emptyText: document.getElementById("observability-empty-text"),
  detailEmpty: document.getElementById("observability-detail-empty"),
  detailBody: document.getElementById("observability-detail-body"),
};

// The full list from the last successful fetch (newest first, as the
// backend returns it) — filters only ever re-render a subset of this.
let allTraces = [];
let visibleTraces = [];
let selectedTraceId = null;
let loadFailed = false;
// A trace another view asked to open (focusTrace()); scrolled into view
// once the next render contains it, then cleared.
let pendingFocusTraceId = null;
let onInvestigateTimeWindow = null;

// How far either side of a trace's own start/end time the Investigation
// cross-link window extends — wide enough to absorb normal clock skew.
const CROSS_LINK_PADDING_MS = 30_000;

// --- formatting ---

function pad2(n) {
  return String(n).padStart(2, "0");
}

// "YYYY-MM-DD HH:MM:SS" in UTC — this view's own filter format, and what
// is sent to investigation.js's setTimeWindow().
function formatUtc(date) {
  return (
    `${date.getUTCFullYear()}-${pad2(date.getUTCMonth() + 1)}-${pad2(date.getUTCDate())} ` +
    `${pad2(date.getUTCHours())}:${pad2(date.getUTCMinutes())}:${pad2(date.getUTCSeconds())}`
  );
}

function formatUtcIso(iso) {
  if (typeof iso !== "string" || !iso) return PLACEHOLDER;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : formatUtc(date);
}

// HH:MM:SS.mmm (UTC) straight from the ISO string, so sub-second digits
// are the recorded ones, not re-rounded.
function formatUtcTimeOfDay(iso) {
  if (typeof iso !== "string") return PLACEHOLDER;
  const match = /T(\d{2}:\d{2}:\d{2})(\.\d{1,3})?/.exec(iso);
  return match ? `${match[1]}${match[2] || ""}` : formatUtcIso(iso);
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

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatDuration(ms) {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return PLACEHOLDER;
  if (ms < 1000) return `${ms.toFixed(2)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatTick(ms) {
  if (ms === 0) return "0 ms";
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 1000) return `${Number(ms.toFixed(1))} ms`;
  return `${Number((ms / 1000).toFixed(2))} s`;
}

function shortId(id) {
  const text = textOrPlaceholder(id);
  return text.length > 12 ? `${text.slice(0, 12)}…` : text;
}

function capitalize(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

function humanizeKey(key) {
  return String(key).replace(/_/g, " ");
}

function formatAttributeValue(value) {
  if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : PLACEHOLDER;
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value !== null && typeof value === "object") return JSON.stringify(value);
  return String(value);
}

// --- status badges (same status -> color mapping used across the app) ---

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

// Built via document.createElement + .textContent — never innerHTML — so a
// status/attribute value can never be interpreted as markup.
function makeStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${statusBadgeClass(status)}`;
  badge.textContent = textOrPlaceholder(status).replace(/_/g, " ");
  return badge;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// --- page state helpers ---

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling synchronously, before any await, makes a second rapid
  // Refresh click a no-op — the same pattern used in every other view.
  dom.refreshButton.disabled = isLoading;
  dom.refreshButton.classList.toggle("btn--spinning", isLoading);
}

function setErrorBanner(message) {
  dom.errorBanner.hidden = !message;
  dom.errorBannerText.textContent = message || "";
}

function setUnavailable(unavailable) {
  loadFailed = unavailable;
  dom.unavailable.hidden = !unavailable;
  dom.workspace.hidden = unavailable;
}

// --- summary bar: real counts over the currently filtered traces ---

function renderSummary(traces) {
  if (loadFailed) {
    for (const node of [dom.statTotal, dom.statSuccess, dom.statDryRun, dom.statOther]) node.textContent = PLACEHOLDER;
    dom.statOtherLabel.textContent = "Other Outcomes";
    dom.statOtherLabel.title = "";
    return;
  }
  const counts = new Map();
  for (const trace of traces) {
    const key = typeof trace.status === "string" ? trace.status : "unknown";
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  const success = counts.get("success") || 0;
  const dryRun = counts.get("dry_run") || 0;
  const other = [...counts.entries()].filter(([status]) => status !== "success" && status !== "dry_run");
  dom.statTotal.textContent = String(traces.length);
  dom.statSuccess.textContent = String(success);
  dom.statDryRun.textContent = String(dryRun);
  dom.statOther.textContent = String(other.reduce((sum, [, n]) => sum + n, 0));
  // The backend's own status names, never a made-up category.
  dom.statOtherLabel.textContent =
    other.length === 1 ? capitalize(humanizeKey(other[0][0])) : "Other Outcomes";
  dom.statOtherLabel.title = other.length
    ? other.map(([status, n]) => `${humanizeKey(status)}: ${n}`).join(" · ")
    : "Every trace is a success or a dry run.";
}

// --- trace explorer (left) ---

function matchesTimeWindow(trace, begin, end) {
  if (!begin && !end) return true;
  const start = new Date(trace.start_time);
  if (Number.isNaN(start.getTime())) return false;
  if (begin && start < begin) return false;
  if (end && start > end) return false;
  return true;
}

function matchesSearch(trace, query) {
  if (!query) return true;
  const name = typeof trace.operation_name === "string" ? trace.operation_name.toLowerCase() : "";
  const id = typeof trace.trace_id === "string" ? trace.trace_id.toLowerCase() : "";
  return name.includes(query) || id.includes(query);
}

function buildTraceItem(trace) {
  const item = document.createElement("li");
  const button = el("button", "obs-trace");
  button.type = "button";
  button.dataset.traceId = textOrPlaceholder(trace.trace_id);
  button.setAttribute("aria-pressed", String(trace.trace_id === selectedTraceId));
  button.title = `Trace ${textOrPlaceholder(trace.trace_id)}`;

  const top = el("span", "obs-trace__row");
  top.append(el("span", "obs-trace__name", textOrPlaceholder(trace.operation_name)), makeStatusBadge(trace.status));
  const bottom = el("span", "obs-trace__row obs-trace__meta");
  bottom.append(
    el("span", "obs-trace__time", formatUtcIso(trace.start_time)),
    el("span", "obs-trace__duration", formatDuration(trace.duration_ms)),
  );
  const id = el("span", "obs-trace__id", shortId(trace.trace_id));

  button.append(top, bottom, id);
  button.addEventListener("click", () => selectTrace(trace.trace_id));
  item.append(button);
  return item;
}

function renderList() {
  dom.traceList.replaceChildren();
  const filtered = visibleTraces.length !== allTraces.length;
  dom.countLabel.textContent = allTraces.length
    ? filtered
      ? `Showing ${visibleTraces.length} of ${allTraces.length} traces · times in UTC`
      : `${allTraces.length} trace${allTraces.length === 1 ? "" : "s"} · newest first · times in UTC`
    : "Select a trace to view its execution details.";

  dom.empty.hidden = visibleTraces.length > 0;
  if (visibleTraces.length === 0) {
    dom.emptyText.textContent = allTraces.length
      ? "No traces match the current time range or search."
      : "No operation attempts have been recorded yet.";
    return;
  }
  const fragment = document.createDocumentFragment();
  for (const trace of visibleTraces) fragment.append(buildTraceItem(trace));
  dom.traceList.append(fragment);
}

function markSelectedInList() {
  dom.traceList.querySelectorAll(".obs-trace").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.traceId === selectedTraceId));
  });
}

// --- trace details (right) ---

function buildMetaItem(label, value, { mono = false, title = "" } = {}) {
  const item = el("div", "obs-meta__item");
  const valueEl = el("dd", mono ? "obs-meta__value obs-meta__value--mono" : "obs-meta__value");
  if (value instanceof Node) valueEl.append(value);
  else valueEl.textContent = value;
  if (title) valueEl.title = title;
  item.append(el("dt", "obs-meta__label", label), valueEl);
  return item;
}

function buildTraceIdValue(traceId) {
  const wrap = el("span", "obs-traceid");
  wrap.append(el("span", "", shortId(traceId)));
  if (typeof traceId === "string" && navigator.clipboard) {
    const copy = el("button", "obs-icon-btn", "Copy");
    copy.type = "button";
    copy.title = "Copy the full trace ID";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(traceId);
        copy.textContent = "Copied";
      } catch {
        copy.textContent = "Copy failed";
      }
      setTimeout(() => {
        copy.textContent = "Copy";
      }, 1500);
    });
    wrap.append(copy);
  }
  return wrap;
}

function orderedSpans(trace) {
  const spans = Array.isArray(trace.spans) ? trace.spans.filter((s) => s && typeof s === "object") : [];
  const rank = (name) => {
    const index = STAGE_ORDER.indexOf(name);
    return index === -1 ? STAGE_ORDER.length : index;
  };
  // Stable: known stages in pipeline order, any other span after them in
  // its recorded order.
  return spans.map((span, i) => [span, i]).sort((a, b) => rank(a[0].name) - rank(b[0].name) || a[1] - b[1]).map(([s]) => s);
}

function spanOffsetMs(trace, span) {
  const traceStart = new Date(trace.start_time).getTime();
  const spanStart = new Date(span.start_time).getTime();
  if (Number.isNaN(traceStart) || Number.isNaN(spanStart)) return null;
  return Math.max(0, spanStart - traceStart);
}

// A rounded axis ceiling so tick labels read cleanly (1, 2, 2.5, 5 × 10^n).
function niceCeiling(value) {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 2.5, 5, 10]) if (step * power >= value) return step * power;
  return 10 * power;
}

function spanTone(span, index) {
  if (span.status === "error") return "error";
  if (span.status === "skipped") return "skipped";
  const stageIndex = STAGE_ORDER.indexOf(span.name);
  return `stage-${(stageIndex === -1 ? index : stageIndex) % 6 + 1}`;
}

function buildWaterfall(trace, spans) {
  const section = el("section", "obs-section");
  const head = el("div", "obs-section__head");
  const titles = el("div");
  titles.append(
    el("h4", "obs-section__title", "Execution Timeline"),
    el("p", "obs-section__subtitle", "Time spent in each recorded stage of the execution pipeline."),
  );
  head.append(titles, el("span", "obs-section__meta", `Total ${formatDuration(trace.duration_ms)}`));
  section.append(head);

  if (spans.length === 0) {
    section.append(el("p", "obs-detail__placeholder", "No spans were recorded for this trace."));
    return section;
  }

  // Scale: the trace total, grown if any recorded start + duration exceeds it.
  const rows = spans.map((span, index) => {
    const duration = typeof span.duration_ms === "number" && Number.isFinite(span.duration_ms) ? span.duration_ms : null;
    return { span, index, duration, offset: spanOffsetMs(trace, span) };
  });
  const traceTotal = typeof trace.duration_ms === "number" && Number.isFinite(trace.duration_ms) ? trace.duration_ms : 0;
  const extent = Math.max(traceTotal, ...rows.map((r) => (r.offset ?? 0) + (r.duration ?? 0)));
  // A round tick step (1, 2, 2.5, 5 x 10^n) giving about five intervals;
  // the scale is a whole number of steps, so ticks and gridlines line up.
  const step = niceCeiling(extent / 5);
  const intervals = Math.max(1, Math.ceil(extent / step - 1e-9));
  const scale = step * intervals;
  const pct = (ms) => `${Math.min(100, Math.max(0, (ms / scale) * 100))}%`;

  const chart = el("div", "obs-waterfall");
  chart.style.setProperty("--obs-grid-step", `${100 / intervals}%`);
  chart.setAttribute("role", "img");
  chart.setAttribute(
    "aria-label",
    `Execution timeline: ${rows.map((r) => `${r.span.name} ${r.span.status}, ${formatDuration(r.duration)}`).join("; ")}`,
  );

  const axis = el("div", "obs-waterfall__axis");
  axis.append(el("span", "obs-waterfall__label"));
  const ticks = el("div", "obs-waterfall__ticks");
  for (let i = 0; i <= intervals; i += 1) {
    const tick = el("span", "obs-waterfall__tick", formatTick(step * i));
    tick.style.left = `${(i / intervals) * 100}%`;
    ticks.append(tick);
  }
  axis.append(ticks);
  chart.append(axis);

  for (const { span, index, duration, offset } of rows) {
    const row = el("div", "obs-waterfall__row");
    const label = el("span", "obs-waterfall__label");
    label.append(el("span", `obs-dot obs-dot--${spanTone(span, index)}`), el("span", "", capitalize(textOrPlaceholder(span.name))));
    const track = el("div", "obs-waterfall__track");

    if (span.status === "skipped") {
      const reason = span.attributes && span.attributes.reason ? ` · ${humanizeKey(span.attributes.reason)}` : "";
      track.append(el("span", "obs-waterfall__skipped", `skipped${reason}`));
    } else if (duration === null || offset === null) {
      track.append(el("span", "obs-waterfall__skipped", "no timing recorded"));
    } else {
      const bar = el("span", `obs-waterfall__bar obs-waterfall__bar--${spanTone(span, index)}`);
      bar.style.left = pct(offset);
      bar.style.width = pct(duration);
      bar.title = `${span.name}: ${formatDuration(duration)} (starts ${formatDuration(offset)} after the trace start) · ${span.status}`;
      // Always just after the bar; the track reserves a right margin for it,
      // and the scale never ends before the last bar.
      const value = el("span", "obs-waterfall__value", formatDuration(duration));
      value.style.left = pct(offset + duration);
      track.append(bar, value);
    }
    row.append(label, track);
    chart.append(row);
  }
  section.append(
    chart,
    el(
      "p",
      "obs-section__note",
      "Bar widths are each span's measured duration; positions are its recorded start time relative to the trace start (wall-clock resolution).",
    ),
  );
  return section;
}

function spanDetails(span) {
  const attributes = span.attributes && typeof span.attributes === "object" ? span.attributes : {};
  const parts = Object.entries(attributes)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${humanizeKey(key)}: ${formatAttributeValue(value)}`);
  return parts.length ? parts.join(" · ") : PLACEHOLDER;
}

function buildStagesTable(spans) {
  const section = el("section", "obs-section");
  const head = el("div", "obs-section__head");
  const titles = el("div");
  titles.append(
    el("h4", "obs-section__title", "Execution Events"),
    el("p", "obs-section__subtitle", "Each recorded stage, with the attributes the framework recorded for it."),
  );
  head.append(titles);
  section.append(head);

  const wrapper = el("div", "table-wrapper obs-events");
  const table = el("table", "data-table data-table--compact");
  const thead = el("thead");
  const headRow = el("tr");
  for (const label of ["Time (UTC)", "Stage", "Status", "Details", "Duration"]) {
    const th = el("th", "", label);
    th.scope = "col";
    headRow.append(th);
  }
  thead.append(headRow);
  const tbody = el("tbody");

  const cell = (content, className = "") => {
    const td = el("td", `data-table__cell ${className}`.trim());
    if (content instanceof Node) td.append(content);
    else {
      td.textContent = content;
      td.title = content;
    }
    return td;
  };

  for (const span of spans) {
    const row = el("tr");
    row.append(
      cell(formatUtcTimeOfDay(span.start_time), "obs-events__mono"),
      cell(capitalize(textOrPlaceholder(span.name))),
      cell(makeStatusBadge(span.status)),
      cell(spanDetails(span), "obs-events__details"),
      cell(formatDuration(span.duration_ms), "obs-events__mono obs-events__num"),
    );
    tbody.append(row);
    // Span events, only when the span actually recorded any.
    for (const event of Array.isArray(span.events) ? span.events : []) {
      const eventRow = el("tr", "obs-events__event");
      eventRow.append(
        cell(formatUtcTimeOfDay(event.timestamp), "obs-events__mono"),
        cell(`↳ ${textOrPlaceholder(event.name)}`),
        cell(""),
        cell(spanDetails({ attributes: event.attributes }), "obs-events__details"),
        cell(""),
      );
      tbody.append(eventRow);
    }
  }
  table.append(thead, tbody);
  wrapper.append(table);
  section.append(wrapper);
  return section;
}

function buildRawData(trace) {
  const details = el("details", "obs-raw");
  details.append(el("summary", "obs-raw__summary", "View raw trace data"));
  // Exactly the sanitized trace the backend returned — no extra fields.
  details.append(el("pre", "obs-raw__pre", JSON.stringify(trace, null, 2)));
  return details;
}

function renderDetail() {
  const trace = visibleTraces.find((t) => t.trace_id === selectedTraceId) || null;
  dom.detailBody.replaceChildren();
  dom.detailBody.hidden = !trace;
  dom.detailEmpty.hidden = Boolean(trace);
  dom.detailEmpty.textContent = visibleTraces.length
    ? "Select a trace to view its execution details."
    : "No trace to show.";
  if (!trace) return;

  const spans = orderedSpans(trace);

  const header = el("div", "obs-detail__header");
  const titleRow = el("div", "obs-detail__titlerow");
  const name = el("h4", "obs-detail__name", textOrPlaceholder(trace.operation_name));
  titleRow.append(name, makeStatusBadge(trace.status));
  const actions = el("div", "obs-detail__actions");
  const window_ = computeInvestigationTimeWindow(trace.start_time, trace.end_time);
  if (onInvestigateTimeWindow && window_) {
    const investigate = el("button", "btn", "Investigate audit records");
    investigate.type = "button";
    investigate.title =
      "View IRIS audit records within 30 seconds of this trace (assumes the IRIS server clock is close to UTC)";
    investigate.addEventListener("click", () => onInvestigateTimeWindow(window_));
    actions.append(investigate);
  }
  titleRow.append(actions);

  const meta = el("dl", "obs-meta");
  meta.append(
    buildMetaItem("Duration", formatDuration(trace.duration_ms), { mono: true }),
    buildMetaItem("Started (UTC)", formatUtcIso(trace.start_time), { mono: true, title: textOrPlaceholder(trace.start_time) }),
    buildMetaItem("Trace ID", buildTraceIdValue(trace.trace_id), { mono: true, title: textOrPlaceholder(trace.trace_id) }),
  );

  // The trace's own per-stage result summary, exactly as recorded.
  const results = el("dl", "obs-results");
  for (const [label, value] of [
    ["Authorization", trace.authorization_result],
    ["Confirmation", trace.confirmation_result],
    ["Execution", trace.execution_result],
    ["Verification", trace.verification_result],
  ]) {
    const item = el("div", "obs-results__item");
    item.append(el("dt", "", label), el("dd", "", textOrPlaceholder(value).replace(/_/g, " ")));
    results.append(item);
  }

  header.append(titleRow, meta, results);
  dom.detailBody.append(header, buildWaterfall(trace, spans), buildStagesTable(spans), buildRawData(trace));
}

// --- selection / rendering ---

function selectTrace(traceId) {
  if (traceId === selectedTraceId) return;
  selectedTraceId = traceId;
  markSelectedInList();
  renderDetail();
}

/** Re-renders from the already-fetched `allTraces` list using the current
 * time filter and search — never triggers a network request. */
function applyFilters() {
  const begin = parseFilterInput(dom.filterBegin.value);
  const end = parseFilterInput(dom.filterEnd.value);
  const query = dom.search.value.trim().toLowerCase();
  visibleTraces = allTraces.filter((trace) => matchesTimeWindow(trace, begin, end) && matchesSearch(trace, query));

  // Keep the selection when it is still visible; otherwise select the
  // newest visible trace, so the workspace always shows something real.
  if (!visibleTraces.some((t) => t.trace_id === selectedTraceId)) {
    selectedTraceId = visibleTraces.length ? visibleTraces[0].trace_id : null;
  }

  renderSummary(visibleTraces);
  renderList();
  renderDetail();

  if (pendingFocusTraceId && visibleTraces.some((t) => t.trace_id === pendingFocusTraceId)) {
    const target = dom.traceList.querySelector(`.obs-trace[data-trace-id="${CSS.escape(pendingFocusTraceId)}"]`);
    pendingFocusTraceId = null;
    if (target) {
      target.scrollIntoView({ block: "nearest" });
      target.focus({ preventScroll: true });
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

  let response;
  try {
    response = await IrisApi.getExecutionTraces();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    setErrorBanner(
      err instanceof ApiError
        ? "Could not load execution traces. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading execution traces.",
    );
    allTraces = [];
    visibleTraces = [];
    setUnavailable(true);
    renderSummary([]);
    setLoading(false);
    return;
  }

  const traces = response && Array.isArray(response.traces) ? response.traces : null;
  if (traces === null) {
    setErrorBanner("The backend did not return the expected traces list.");
    allTraces = [];
    visibleTraces = [];
    setUnavailable(true);
    renderSummary([]);
    setLoading(false);
    return;
  }

  setUnavailable(false);
  allTraces = traces;
  applyFilters();
  setLoading(false);
}

/**
 * Sets the Begin/End (UTC) filter fields — never fetches anything itself.
 * Called by app.js right before nav.navigateTo("observability"), whose
 * view-opened load renders the fresh list with this filter applied.
 */
export function setTimeWindow(begin, end) {
  dom.filterBegin.value = begin;
  dom.filterEnd.value = end;
}

/**
 * Asks this view to open one trace: clears the time filter and search,
 * selects that trace, and scrolls/focuses it in the explorer on the next
 * render. Never fetches anything itself — called right before
 * nav.navigateTo("observability"), whose view-opened load renders the real,
 * freshly fetched trace list.
 */
export function focusTrace(traceId) {
  if (typeof traceId !== "string" || !traceId) return;
  dom.filterBegin.value = "";
  dom.filterEnd.value = "";
  dom.search.value = "";
  selectedTraceId = traceId;
  pendingFocusTraceId = traceId;
}

/**
 * `onInvestigateTimeWindow`, when provided, is called with `{ begin, end }`
 * whenever the operator clicks a trace's "Investigate audit records" button
 * — see app.js for how it switches views.
 */
export function initObservabilityControls({ onInvestigateTimeWindow: callback } = {}) {
  onInvestigateTimeWindow = typeof callback === "function" ? callback : null;
  dom.refreshButton.addEventListener("click", () => {
    loadExecutionTraces();
  });
  dom.filterBegin.addEventListener("input", () => {
    if (!loadFailed) applyFilters();
  });
  dom.filterEnd.addEventListener("input", () => {
    if (!loadFailed) applyFilters();
  });
  dom.search.addEventListener("input", () => {
    if (!loadFailed) applyFilters();
  });
  dom.filterClearButton.addEventListener("click", () => {
    dom.filterBegin.value = "";
    dom.filterEnd.value = "";
    if (!loadFailed) applyFilters();
  });
  dom.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
  });
}
