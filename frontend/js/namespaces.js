// Namespaces view: fetches GET /api/iris/namespaces ONLY and renders a
// read-only administrator table of configured IRIS namespaces. No other
// endpoint is called from this module, and no mutating HTTP method is used
// anywhere in it.
//
// Fields shown are exactly the ones backend/app/models/iris.py's
// NamespaceEntry actually defines (Name, Globals, Routines, SysGlobals,
// SysRoutines, Library, TempGlobals) — nothing invented. See
// docs/api-capability-matrix.md for how that shape was originally verified
// against a real IRIS instance.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("namespaces-loading-state"),
  errorBanner: document.getElementById("namespaces-error-banner"),
  errorBannerText: document.getElementById("namespaces-error-banner-text"),
  refreshButton: document.getElementById("namespaces-refresh-button"),
  connectionStatus: document.getElementById("namespaces-connection-status"),
  connectionStatusLabel: document.getElementById("namespaces-connection-status-label"),
  connectionDetail: document.getElementById("namespaces-connection-detail"),
  countLabel: document.getElementById("namespaces-count"),
  tableWrapper: document.getElementById("namespaces-table-wrapper"),
  tableBody: document.getElementById("namespaces-table-body"),
  empty: document.getElementById("namespaces-empty"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js/system.js/databases.js.
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

// Table rows are always built via document.createElement + .textContent —
// never innerHTML — so a namespace name containing HTML-special characters
// can never be interpreted as markup.
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function renderNamespaces(namespaces) {
  dom.tableBody.replaceChildren();

  if (!Array.isArray(namespaces) || namespaces.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${namespaces.length} namespace${namespaces.length === 1 ? "" : "s"}`;

  for (const ns of namespaces) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(ns.Name), { mono: true }),
      makeCell(textOrPlaceholder(ns.Globals), { mono: true }),
      makeCell(textOrPlaceholder(ns.Routines), { mono: true }),
      makeCell(textOrPlaceholder(ns.SysGlobals), { mono: true }),
      makeCell(textOrPlaceholder(ns.SysRoutines), { mono: true }),
      makeCell(textOrPlaceholder(ns.Library), { mono: true }),
      makeCell(textOrPlaceholder(ns.TempGlobals), { mono: true }),
    );
    dom.tableBody.append(row);
  }
}

/**
 * Fetches GET /api/iris/namespaces and renders it. This is the ONLY network
 * call this module makes — no mutating request exists anywhere in this file.
 */
export async function loadNamespaces() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getNamespaces();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load namespace information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading namespace information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderNamespaces(null);
    setLoading(false);
    return;
  }

  const namespaces = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (namespaces === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected namespace information.");
    renderNamespaces(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js/databases.js.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  renderNamespaces(namespaces);
  setLoading(false);
}

export function initNamespacesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadNamespaces();
  });
}
