// Databases view: fetches GET /api/iris/databases ONLY and renders a
// read-only administrator table of configured IRIS databases. No other
// endpoint is called from this module, and no mutating HTTP method is used
// anywhere in it.
//
// Fields shown are exactly a subset of the ones backend/app/models/iris.py's
// DatabaseEntry actually defines (Name, Directory, Server, Status,
// MountAtStartup, MountRequired, ClusterMountMode) — nothing invented. See
// docs/api-capability-matrix.md for how that shape was originally verified
// against a real IRIS instance.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("databases-loading-state"),
  errorBanner: document.getElementById("databases-error-banner"),
  errorBannerText: document.getElementById("databases-error-banner-text"),
  refreshButton: document.getElementById("databases-refresh-button"),
  connectionStatus: document.getElementById("databases-connection-status"),
  connectionStatusLabel: document.getElementById("databases-connection-status-label"),
  connectionDetail: document.getElementById("databases-connection-detail"),
  countLabel: document.getElementById("databases-count"),
  tableWrapper: document.getElementById("databases-table-wrapper"),
  tableBody: document.getElementById("databases-table-body"),
  empty: document.getElementById("databases-empty"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js/system.js/processes.js.
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
// never innerHTML — so a database name/directory containing HTML-special
// characters can never be interpreted as markup.
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function renderDatabases(databases) {
  dom.tableBody.replaceChildren();

  if (!Array.isArray(databases) || databases.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${databases.length} database${databases.length === 1 ? "" : "s"}`;

  for (const db of databases) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(db.Name), { mono: true }),
      makeCell(textOrPlaceholder(db.Status)),
      makeCell(textOrPlaceholder(db.Directory), { mono: true }),
      makeCell(textOrPlaceholder(db.Server), { mono: true }),
      makeCell(formatBoolean(db.MountAtStartup)),
      makeCell(formatBoolean(db.MountRequired)),
      makeCell(formatBoolean(db.ClusterMountMode)),
    );
    dom.tableBody.append(row);
  }
}

/**
 * Fetches GET /api/iris/databases and renders it. This is the ONLY network
 * call this module makes — no mutating request exists anywhere in this file.
 */
export async function loadDatabases() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getDatabases();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load database information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading database information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderDatabases(null);
    setLoading(false);
    return;
  }

  const databases = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (databases === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected database information.");
    renderDatabases(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js/processes.js.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  renderDatabases(databases);
  setLoading(false);
}

export function initDatabasesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadDatabases();
  });
}
