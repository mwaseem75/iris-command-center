// Observability view: fetches GET /api/iris/observability/traces ONLY —
// a read-only listing of the in-memory execution traces the backend's
// OperationExecutor records for every operation attempt (see
// backend/app/observability/). No other endpoint is called from this
// module, and no mutating HTTP method is used anywhere in it. This view
// never triggers an operation itself — it only displays traces that
// already exist because something else (e.g. the Operations view) ran
// one.

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
  tableWrapper: document.getElementById("observability-table-wrapper"),
  tableBody: document.getElementById("observability-table-body"),
  empty: document.getElementById("observability-empty"),
};

// Which trace/span each expanded detail row belongs to, so a Refresh can
// re-render without losing which rows the user had open.
const expandedTraceIds = new Set();

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

function toggleTraceDetail(traceId, traces) {
  if (expandedTraceIds.has(traceId)) {
    expandedTraceIds.delete(traceId);
  } else {
    expandedTraceIds.add(traceId);
  }
  renderTable(traces);
}

function renderTable(traces) {
  dom.tableBody.replaceChildren();

  if (!Array.isArray(traces) || traces.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${traces.length} trace${traces.length === 1 ? "" : "s"}`;

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
    toggleButton.addEventListener("click", () => toggleTraceDetail(trace.trace_id, traces));
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
    renderTable(null);
    setLoading(false);
    return;
  }

  const traces = response && Array.isArray(response.traces) ? response.traces : null;

  if (traces === null) {
    setConnectionState("error", "Backend returned no data");
    setErrorBanner("The backend did not return the expected traces list.");
    renderTable(null);
    setLoading(false);
    return;
  }

  setConnectionState("connected", "Connected");
  setErrorBanner(null);
  renderTable(traces);
  setLoading(false);
}

export function initObservabilityControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadExecutionTraces();
  });
}
