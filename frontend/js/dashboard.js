// Dashboard view: fetches read-only IRIS data via IrisApi and renders it.
// Rendering is kept separate from fetching (api.js) so each can change
// independently — e.g. swapping how data is fetched later shouldn't
// require touching any DOM code here.

import { IrisApi, ApiError } from "./api.js";

const dom = {
  connectionStatus: document.getElementById("connection-status"),
  connectionStatusLabel: document.getElementById("connection-status-label"),
  loadingState: document.getElementById("loading-state"),
  errorBanner: document.getElementById("error-banner"),
  errorBannerText: document.getElementById("error-banner-text"),
  statGrid: document.getElementById("stat-grid"),
  lastUpdated: document.getElementById("last-updated"),
  refreshButton: document.getElementById("refresh-button"),
};

const STAT_CARDS = {
  namespaces: { valueEl: "stat-namespaces", cardSelector: '[data-card="namespaces"]' },
  databases: { valueEl: "stat-databases", cardSelector: '[data-card="databases"]' },
  processes: { valueEl: "stat-processes", cardSelector: '[data-card="processes"]' },
  webApps: { valueEl: "stat-web-apps", cardSelector: '[data-card="web-apps"]' },
  tasks: { valueEl: "stat-tasks", cardSelector: '[data-card="tasks"]' },
};

function setConnectionStatus(state, label) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
}

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  dom.statGrid.style.opacity = isLoading ? "0.5" : "1";
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

/** result is a fulfilled/rejected entry from Promise.allSettled. `extract`
 * pulls the count (or value) out of a successful envelope. Renders a plain
 * unavailable state on failure rather than propagating the error into the
 * DOM — one failed card never blocks the others from rendering. */
function renderCountCard(key, result, extract) {
  const { valueEl, cardSelector } = STAT_CARDS[key];
  const valueNode = document.getElementById(valueEl);
  const cardNode = dom.statGrid.querySelector(cardSelector);

  if (result.status === "fulfilled") {
    valueNode.textContent = String(extract(result.value));
    valueNode.classList.remove("stat-card__value--unavailable");
    cardNode.classList.remove("stat-card--error");
  } else {
    valueNode.textContent = "Unavailable";
    valueNode.classList.add("stat-card__value--unavailable");
    cardNode.classList.add("stat-card--error");
  }
}

function renderInfoCard(result) {
  const versionNode = document.getElementById("stat-version");
  const versionMetaNode = document.getElementById("stat-version-meta");

  if (result.status === "fulfilled") {
    const info = result.value.result;
    // Response shape verified against the backend's InfoResult model —
    // apiVersion, serverVersion, product are the fields it actually returns.
    versionNode.textContent = info.serverVersion || "Unknown";
    versionMetaNode.textContent = `${info.product || "iris"} • API v${info.apiVersion ?? "?"}`;
    versionNode.classList.remove("stat-card__value--unavailable");
    setConnectionStatus("connected", `Connected as ${info.username || "unknown user"}`);
  } else {
    versionNode.textContent = "Unavailable";
    versionNode.classList.add("stat-card__value--unavailable");
    versionMetaNode.textContent = "";
    setConnectionStatus("error", "Could not reach IRIS");
  }
}

function describeFailures(results) {
  const failures = Object.entries(results).filter(([, r]) => r.status === "rejected");
  if (failures.length === 0) return null;

  // Deliberately generic/non-alarming: never surface raw error objects,
  // status codes tied to auth, or anything resembling a header/token.
  if (failures.length === Object.keys(results).length) {
    return "Could not load dashboard data right now. The Command Center backend may be unreachable.";
  }
  return `Some dashboard data could not be loaded (${failures.length} of ${Object.keys(results).length} sections). The rest is shown below.`;
}

/**
 * Fetches all dashboard data and renders it. Uses Promise.allSettled so one
 * failing endpoint never prevents the others from displaying — required by
 * this step's "handle partial API failures gracefully".
 */
export async function loadDashboard() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionStatus("checking", "Checking connection…");

  const [info, namespaces, databases, processes, webApps, tasks] = await Promise.allSettled([
    IrisApi.getInfo(),
    IrisApi.getNamespaces(),
    IrisApi.getDatabases(),
    IrisApi.getProcesses(),
    IrisApi.getWebApps(),
    IrisApi.getTasks(),
  ]);

  renderInfoCard(info);
  renderCountCard("namespaces", namespaces, (body) => body.result.length);
  renderCountCard("databases", databases, (body) => body.result.length);
  renderCountCard("processes", processes, (body) => body.result.length);
  renderCountCard("webApps", webApps, (body) => body.result.length);
  renderCountCard("tasks", tasks, (body) => body.result.length);

  const results = { info, namespaces, databases, processes, webApps, tasks };
  setErrorBanner(describeFailures(results));

  dom.lastUpdated.textContent = `Last updated ${new Date().toLocaleTimeString()}`;
  setLoading(false);
}

export function initDashboardControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadDashboard();
  });
}

// Re-exported only so a future test/module can construct a matching error
// type without importing api.js directly.
export { ApiError };
