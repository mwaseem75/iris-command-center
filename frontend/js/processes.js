// Processes view: fetches GET /api/iris/processes ONLY and renders a
// read-only administrator table of running IRIS processes/jobs. No other
// endpoint is called from this module, and no mutating HTTP method is used
// anywhere in it.
//
// Fields shown are exactly a subset of the ones backend/app/models/iris.py's
// ProcessEntry actually defines (Pid, Job, Nspace, Username, Routine, State,
// Device, ElapsedTime, CPUTime) — nothing invented. See
// docs/api-capability-matrix.md for how that shape was originally verified
// against a real IRIS instance.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { countBy, renderStackedBar, topCategories } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

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
  tableWrapper: document.getElementById("processes-table-wrapper"),
  tableBody: document.getElementById("processes-table-body"),
  empty: document.getElementById("processes-empty"),
  overview: document.getElementById("processes-overview"),
  overviewViz: document.getElementById("processes-overview-viz"),
};

/** A real State-value distribution over the same `processes` array
 * renderProcesses() below already renders as a table — no extra fetch,
 * no invented category. Hidden entirely when there's nothing to show. */
function renderOverview(processes) {
  if (!Array.isArray(processes) || processes.length === 0) {
    dom.overview.hidden = true;
    return;
  }
  dom.overview.hidden = false;
  const entries = topCategories(countBy(processes, (p) => p.State || "Unknown"), 6);
  renderStackedBar(dom.overviewViz, entries);
}

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

function formatCpuTime(value) {
  // ProcessEntry.CPUTime is a plain int (milliseconds, per IRIS's own
  // %SYS.ProcessQuery convention) — not documented in our own OpenAPI
  // schema beyond "int", so the unit label is applied, not invented data.
  return typeof value === "number" ? `${value} ms` : PLACEHOLDER;
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

function renderProcesses(processes) {
  dom.tableBody.replaceChildren();
  renderOverview(processes);

  if (!Array.isArray(processes) || processes.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${processes.length} process${processes.length === 1 ? "" : "es"}`;

  for (const proc of processes) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(proc.Pid), { mono: true }),
      makeCell(textOrPlaceholder(proc.Job), { mono: true }),
      makeCell(textOrPlaceholder(proc.Nspace)),
      makeCell(textOrPlaceholder(proc.Username)),
      makeCell(textOrPlaceholder(proc.Routine), { mono: true }),
      makeCell(textOrPlaceholder(proc.State)),
      makeCell(textOrPlaceholder(proc.Device)),
      makeCell(textOrPlaceholder(proc.ElapsedTime), { mono: true }),
      makeCell(formatCpuTime(proc.CPUTime), { mono: true }),
    );
    dom.tableBody.append(row);
  }
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

export function initProcessesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadProcesses();
  });
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });
}
