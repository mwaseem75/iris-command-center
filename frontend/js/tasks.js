// Tasks view: fetches GET /api/iris/tasks ONLY and renders a read-only
// administrator table of configured IRIS scheduled tasks. No other
// endpoint is called from this module, and no mutating HTTP method is
// used anywhere in it.
//
// Fields shown are exactly a subset of the ones backend/app/models/iris.py's
// TaskEntry actually defines (Name, Type, Namespace, Description,
// Suspended, LastFinished, NextScheduled) — nothing invented. See
// docs/api-capability-matrix.md for how that shape was originally verified
// against a real IRIS instance.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("tasks-loading-state"),
  errorBanner: document.getElementById("tasks-error-banner"),
  errorBannerText: document.getElementById("tasks-error-banner-text"),
  refreshButton: document.getElementById("tasks-refresh-button"),
  connectionStatus: document.getElementById("tasks-connection-status"),
  connectionStatusLabel: document.getElementById("tasks-connection-status-label"),
  connectionDetail: document.getElementById("tasks-connection-detail"),
  countLabel: document.getElementById("tasks-count"),
  tableWrapper: document.getElementById("tasks-table-wrapper"),
  tableBody: document.getElementById("tasks-table-body"),
  empty: document.getElementById("tasks-empty"),
};

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

// Table rows are always built via document.createElement + .textContent —
// never innerHTML — so a task name/description containing HTML-special
// characters can never be interpreted as markup.
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function renderTasks(tasks) {
  dom.tableBody.replaceChildren();

  if (!Array.isArray(tasks) || tasks.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${tasks.length} task${tasks.length === 1 ? "" : "s"}`;

  for (const task of tasks) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(task.Name), { mono: true }),
      makeCell(textOrPlaceholder(task.Namespace)),
      makeCell(textOrPlaceholder(task.Type)),
      makeCell(textOrPlaceholder(task.Description)),
      makeCell(formatBoolean(task.Suspended)),
      makeCell(textOrPlaceholder(task.LastFinished), { mono: true }),
      makeCell(textOrPlaceholder(task.NextScheduled), { mono: true }),
    );
    dom.tableBody.append(row);
  }
}

/**
 * Fetches GET /api/iris/tasks and renders it. This is the ONLY network call
 * this module makes — no mutating request exists anywhere in this file.
 */
export async function loadTasks() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getTasks();
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
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js/processes.js/databases.js/web-apps.js.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  renderTasks(tasks);
  setLoading(false);
}

export function initTasksControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadTasks();
  });
}
