// System view: fetches GET /api/iris/info ONLY and renders a detailed,
// read-only technical breakdown. No other endpoint is called from this
// module, and no mutating HTTP method is used anywhere in it.
//
// Fields shown are exactly the ones backend/app/models/iris.py's
// InfoResult actually defines (apiVersion, username, serverVersion,
// systemMode, product, namespaces, privileges) — nothing invented. See
// docs/api-capability-matrix.md for how that shape was originally
// verified against a real IRIS instance.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("system-loading-state"),
  errorBanner: document.getElementById("system-error-banner"),
  errorBannerText: document.getElementById("system-error-banner-text"),
  refreshButton: document.getElementById("system-refresh-button"),
  connectionStatus: document.getElementById("system-connection-status"),
  connectionStatusLabel: document.getElementById("system-connection-status-label"),
  connectionDetail: document.getElementById("system-connection-detail"),
  product: document.getElementById("system-product"),
  serverVersion: document.getElementById("system-server-version"),
  apiVersion: document.getElementById("system-api-version"),
  systemMode: document.getElementById("system-mode"),
  username: document.getElementById("system-username"),
  namespacesList: document.getElementById("system-namespaces-list"),
  namespacesEmpty: document.getElementById("system-namespaces-empty"),
  privilegesList: document.getElementById("system-privileges-list"),
  privilegesEmpty: document.getElementById("system-privileges-empty"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op: a disabled <button> never
  // dispatches a click event, so only one load can ever be in flight —
  // the same pattern already used and reviewed in dashboard.js.
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

function clearFields() {
  dom.product.textContent = PLACEHOLDER;
  dom.serverVersion.textContent = PLACEHOLDER;
  dom.apiVersion.textContent = PLACEHOLDER;
  dom.systemMode.textContent = PLACEHOLDER;
  dom.username.textContent = PLACEHOLDER;
}

// DOM nodes are always created via document.createElement + .textContent
// below — never innerHTML — so a namespace/privilege name containing
// HTML-special characters can never be interpreted as markup.

function renderNamespaces(namespaces) {
  dom.namespacesList.replaceChildren();
  if (!Array.isArray(namespaces) || namespaces.length === 0) {
    dom.namespacesEmpty.hidden = false;
    return;
  }
  dom.namespacesEmpty.hidden = true;
  for (const ns of namespaces) {
    const item = document.createElement("li");
    item.className = "tag-list__item";
    item.textContent = ns && ns.name ? ns.name : "unknown";
    dom.namespacesList.append(item);
  }
}

function renderPrivileges(privileges) {
  dom.privilegesList.replaceChildren();
  const entries = privileges && typeof privileges === "object" ? Object.entries(privileges) : [];
  if (entries.length === 0) {
    dom.privilegesEmpty.hidden = false;
    return;
  }
  dom.privilegesEmpty.hidden = true;
  entries.sort(([a], [b]) => a.localeCompare(b));
  for (const [name, flag] of entries) {
    const held = Boolean(flag && flag.use);

    const item = document.createElement("li");
    item.className = "privilege-list__item";

    const nameEl = document.createElement("span");
    nameEl.className = "privilege-list__name";
    nameEl.textContent = name;

    const valueEl = document.createElement("span");
    valueEl.className = `privilege-list__value privilege-list__value--${held ? "granted" : "denied"}`;
    valueEl.textContent = held ? "Granted" : "Not granted";

    item.append(nameEl, valueEl);
    dom.privilegesList.append(item);
  }
}

/**
 * Fetches GET /api/iris/info and renders it. This is the ONLY network call
 * this module makes — no mutating request exists anywhere in this file.
 */
export async function loadSystemInfo() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getInfo();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load system information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading system information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    clearFields();
    renderNamespaces(null);
    renderPrivileges(null);
    setLoading(false);
    return;
  }

  const info = response && response.result ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (!info) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected system information.");
    clearFields();
    renderNamespaces(null);
    renderPrivileges(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. See
    // docs/api-capability-matrix.md for where this wrapper was verified.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", `Connected as ${info.username || "unknown user"}`, "");
    setErrorBanner(null);
  }

  dom.product.textContent = info.product || PLACEHOLDER;
  dom.serverVersion.textContent = info.serverVersion || PLACEHOLDER;
  dom.apiVersion.textContent = info.apiVersion ?? PLACEHOLDER;
  dom.systemMode.textContent = info.systemMode || PLACEHOLDER;
  dom.username.textContent = info.username || PLACEHOLDER;

  renderNamespaces(info.namespaces);
  renderPrivileges(info.privileges);

  setLoading(false);
}

export function initSystemControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadSystemInfo();
  });
}
