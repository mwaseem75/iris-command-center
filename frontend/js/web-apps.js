// Web Apps view: fetches GET /api/iris/web-apps ONLY and renders a
// read-only administrator table of configured IRIS web applications. No
// other endpoint is called from this module, and no mutating HTTP method
// is used anywhere in it.
//
// Fields shown are exactly a subset of the ones backend/app/models/iris.py's
// WebAppEntry actually defines (Name, Namespace, Type, Enabled,
// AuthenticationMethods, Resource, IsSystemApp, DispatchClass) — nothing
// invented. See docs/api-capability-matrix.md for how that shape was
// originally verified against a real IRIS instance.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("web-apps-loading-state"),
  errorBanner: document.getElementById("web-apps-error-banner"),
  errorBannerText: document.getElementById("web-apps-error-banner-text"),
  refreshButton: document.getElementById("web-apps-refresh-button"),
  connectionStatus: document.getElementById("web-apps-connection-status"),
  connectionStatusLabel: document.getElementById("web-apps-connection-status-label"),
  connectionDetail: document.getElementById("web-apps-connection-detail"),
  countLabel: document.getElementById("web-apps-count"),
  tableWrapper: document.getElementById("web-apps-table-wrapper"),
  tableBody: document.getElementById("web-apps-table-body"),
  empty: document.getElementById("web-apps-empty"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js/system.js/processes.js/databases.js.
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

function formatAuthMethods(value) {
  return Array.isArray(value) && value.length > 0 ? value.join(", ") : PLACEHOLDER;
}

// Table rows are always built via document.createElement + .textContent —
// never innerHTML — so a web app name/resource containing HTML-special
// characters can never be interpreted as markup.
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function renderWebApps(webApps) {
  dom.tableBody.replaceChildren();

  if (!Array.isArray(webApps) || webApps.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${webApps.length} web app${webApps.length === 1 ? "" : "s"}`;

  for (const app of webApps) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(app.Name), { mono: true }),
      makeCell(textOrPlaceholder(app.Namespace)),
      makeCell(textOrPlaceholder(app.Type)),
      makeCell(formatBoolean(app.Enabled)),
      makeCell(formatAuthMethods(app.AuthenticationMethods)),
      makeCell(textOrPlaceholder(app.Resource), { mono: true }),
      makeCell(formatBoolean(app.IsSystemApp)),
      makeCell(textOrPlaceholder(app.DispatchClass), { mono: true }),
    );
    dom.tableBody.append(row);
  }
}

/**
 * Fetches GET /api/iris/web-apps and renders it. This is the ONLY network
 * call this module makes — no mutating request exists anywhere in this file.
 */
export async function loadWebApps() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getWebApps();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load web application information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading web application information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderWebApps(null);
    setLoading(false);
    return;
  }

  const webApps = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (webApps === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected web application information.");
    renderWebApps(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js/processes.js/databases.js.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  renderWebApps(webApps);
  setLoading(false);
}

export function initWebAppsControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadWebApps();
  });
}
