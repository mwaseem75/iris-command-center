// System page: GET /api/iris/info, shown in detail, plus the Instance &
// Server card from two existing reads loaded alongside it: Embedded Python
// diagnostics (hostname, platform, CPUs, manager directory) and the System
// Dashboard (uptime). Either can fail on its own; its values then show
// "Unavailable". The API Findings table is static documentation.
//
// The /info fields are the ones InfoResult defines in
// backend/app/models/iris.py (apiVersion, username, serverVersion,
// systemMode, product, namespaces, privileges). /info has no instance name,
// so none is shown.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—";  // shown for empty values

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
  kpiVersion: document.getElementById("system-kpi-version"),
  kpiVersionMeta: document.getElementById("system-kpi-version-meta"),
  kpiApi: document.getElementById("system-kpi-api"),
  kpiNamespaces: document.getElementById("system-kpi-namespaces"),
  kpiPrivileges: document.getElementById("system-kpi-privileges"),
  kpiPrivilegesMeta: document.getElementById("system-kpi-privileges-meta"),
  namespacesCount: document.getElementById("system-namespaces-count"),
  privilegesCount: document.getElementById("system-privileges-count"),
  identityHostname: document.getElementById("system-identity-hostname"),
  identityPlatform: document.getElementById("system-identity-platform"),
  identityOs: document.getElementById("system-identity-os"),
  identityCpus: document.getElementById("system-identity-cpus"),
  identityMgr: document.getElementById("system-identity-mgr"),
  identityUptime: document.getElementById("system-identity-uptime"),
};

const UNAVAILABLE = "Unavailable";

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disable right away so a double click doesn't fire two requests.
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
  renderOverview(null);
}

// Release and build pulled out of serverVersion (e.g. "... 2026.2 (Build
// 221U) ..."). If they're not there, show the whole string.
function parseServerVersion(serverVersion) {
  if (typeof serverVersion !== "string" || !serverVersion) return null;
  const release = /\b(\d{4}\.\d+(?:\.\d+)?)\b/.exec(serverVersion);
  const build = /\(Build ([^)]+)\)/.exec(serverVersion);
  return { release: release ? release[1] : null, build: build ? build[1] : null };
}

/** KPI cards and counts, all from the same /info response. */
function renderOverview(info) {
  if (!info) {
    for (const node of [dom.kpiVersion, dom.kpiApi, dom.kpiNamespaces, dom.kpiPrivileges]) node.textContent = PLACEHOLDER;
    dom.kpiVersion.title = "";
    dom.kpiVersionMeta.textContent = "";
    dom.kpiPrivilegesMeta.textContent = "";
    dom.namespacesCount.textContent = "";
    dom.privilegesCount.textContent = "";
    return;
  }
  const parsed = parseServerVersion(info.serverVersion);
  dom.kpiVersion.textContent = parsed && parsed.release ? parsed.release : info.serverVersion || PLACEHOLDER;
  dom.kpiVersion.title = info.serverVersion || "";
  dom.kpiVersionMeta.textContent = [info.product, parsed && parsed.build ? `Build ${parsed.build}` : null]
    .filter(Boolean)
    .join(" · ");
  dom.kpiApi.textContent = info.apiVersion !== undefined && info.apiVersion !== null ? `v${info.apiVersion}` : PLACEHOLDER;

  const namespaces = Array.isArray(info.namespaces) ? info.namespaces.length : null;
  dom.kpiNamespaces.textContent = namespaces === null ? PLACEHOLDER : String(namespaces);
  dom.namespacesCount.textContent = namespaces === null ? "" : String(namespaces);

  const privileges = info.privileges && typeof info.privileges === "object" ? Object.values(info.privileges) : null;
  if (!privileges) {
    dom.kpiPrivileges.textContent = PLACEHOLDER;
    dom.kpiPrivilegesMeta.textContent = "";
    dom.privilegesCount.textContent = "";
    return;
  }
  const granted = privileges.filter((flag) => Boolean(flag && flag.use)).length;
  dom.kpiPrivileges.textContent = String(granted);
  dom.kpiPrivilegesMeta.textContent = `of ${privileges.length} reported`;
  dom.privilegesCount.textContent = `${granted} of ${privileges.length} granted`;
}

// Built with createElement/textContent (no innerHTML), so names with
// HTML characters are shown as text.

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

    item.dataset.held = String(held);
    item.title = `${name}: ${held ? "granted" : "not granted"} for this session`;
    item.append(nameEl, valueEl);
    dom.privilegesList.append(item);
  }
}

// What IRIS was built for, from serverVersion ("IRIS for UNIX (Ubuntu Server
// LTS for x86-64 Containers) 2026.2 (Build 221U) ..." -> "UNIX (Ubuntu ...)").
// Null if it isn't in that shape; the full string is shown above anyway.
function buildTargetOf(serverVersion) {
  if (typeof serverVersion !== "string") return null;
  const match = /^.+? for (.+?) \d{4}\.\d/.exec(serverVersion);
  return match ? match[1] : null;
}

function valueOrUnavailable(value) {
  return value === null || value === undefined || value === "" ? UNAVAILABLE : String(value);
}

/**
 * Instance & Server card. `diagnostics` / `monitor` are the fulfilled
 * responses or null if that read failed; `info` is /info's result or null.
 */
function renderIdentity(info, diagnostics, monitor) {
  dom.identityHostname.textContent = diagnostics ? valueOrUnavailable(diagnostics.hostname) : UNAVAILABLE;
  dom.identityPlatform.textContent = diagnostics ? valueOrUnavailable(diagnostics.platform) : UNAVAILABLE;
  dom.identityCpus.textContent = diagnostics ? valueOrUnavailable(diagnostics.cpu_count) : UNAVAILABLE;
  dom.identityMgr.textContent = diagnostics ? valueOrUnavailable(diagnostics.manager_directory) : UNAVAILABLE;
  dom.identityOs.textContent = info ? buildTargetOf(info.serverVersion) || PLACEHOLDER : UNAVAILABLE;
  const upTime = monitor && monitor.result && monitor.result.Status ? monitor.result.Status.UpTime : null;
  // IRIS pads it ("0d  2h 05m"); collapse the spaces for display only.
  dom.identityUptime.textContent = upTime ? String(upTime).replace(/\s+/g, " ").trim() : UNAVAILABLE;
}

async function settled(promise) {
  try {
    return await promise;
  } catch {
    return null;
  }
}

/** Load GET /api/iris/info and render it, with the identity reads alongside. */
export async function loadSystemInfo() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");
  const identityReads = Promise.all([settled(IrisApi.getPythonDiagnostics()), settled(IrisApi.getMonitorDashboard())]);

  let response;
  try {
    response = await IrisApi.getInfo();
  } catch (err) {
    // ApiError messages are already safe to show (see api.js).
    const message =
      err instanceof ApiError
        ? "Could not load system information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading system information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    clearFields();
    renderNamespaces(null);
    renderPrivileges(null);
    renderIdentity(null, ...(await identityReads));
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
    renderIdentity(null, ...(await identityReads));
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // IRIS returned warnings in status.errors.
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
  renderOverview(info);
  renderIdentity(info, ...(await identityReads));

  setLoading(false);
}

export function initSystemControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadSystemInfo();
  });
}
