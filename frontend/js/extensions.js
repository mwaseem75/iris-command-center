// Extensions page: external language servers, file-system access purposes
// and wallet collections (three GETs).
//
// Language servers have a known shape (Name, Port, Type), so that table has
// fixed columns. The other two have only ever come back empty, so their
// columns are taken from whatever fields IRIS returns.

import { IrisApi } from "./api.js";

const PLACEHOLDER = "—";  // shown for empty values

const dom = {
  loadingState: document.getElementById("extensions-loading-state"),
  errorBanner: document.getElementById("extensions-error-banner"),
  errorBannerText: document.getElementById("extensions-error-banner-text"),
  refreshButton: document.getElementById("extensions-refresh-button"),
  connectionStatus: document.getElementById("extensions-connection-status"),
  connectionStatusLabel: document.getElementById("extensions-connection-status-label"),
  connectionDetail: document.getElementById("extensions-connection-detail"),
  extLangWrapper: document.getElementById("extensions-ext-lang-servers-table-wrapper"),
  extLangBody: document.getElementById("extensions-ext-lang-servers-table-body"),
  extLangEmpty: document.getElementById("extensions-ext-lang-servers-empty"),
  fsPurposesWrapper: document.getElementById("extensions-fs-access-purposes-table-wrapper"),
  fsPurposesThead: document.getElementById("extensions-fs-access-purposes-thead"),
  fsPurposesBody: document.getElementById("extensions-fs-access-purposes-table-body"),
  fsPurposesEmpty: document.getElementById("extensions-fs-access-purposes-empty"),
  walletWrapper: document.getElementById("extensions-wallet-collections-table-wrapper"),
  walletThead: document.getElementById("extensions-wallet-collections-thead"),
  walletBody: document.getElementById("extensions-wallet-collections-table-body"),
  walletEmpty: document.getElementById("extensions-wallet-collections-empty"),
};

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

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatValue(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

// Built with createElement/textContent (no innerHTML).
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function renderExtLangServers(settled) {
  dom.extLangBody.replaceChildren();

  if (settled.status !== "fulfilled") {
    dom.extLangWrapper.hidden = true;
    dom.extLangEmpty.textContent = "Could not load external language servers.";
    dom.extLangEmpty.hidden = false;
    return;
  }

  const servers =
    settled.value && Array.isArray(settled.value.result) ? settled.value.result : [];

  if (servers.length === 0) {
    dom.extLangWrapper.hidden = true;
    dom.extLangEmpty.textContent = "No external language servers reported.";
    dom.extLangEmpty.hidden = false;
    return;
  }

  dom.extLangEmpty.hidden = true;
  dom.extLangWrapper.hidden = false;

  for (const server of servers) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(server.Name), { mono: true }),
      makeCell(textOrPlaceholder(server.Port), { mono: true }),
      makeCell(textOrPlaceholder(server.Type)),
    );
    dom.extLangBody.append(row);
  }
}

// Columns come from the fields IRIS actually returned.
function renderDynamicList(settled, { wrapper, thead, body, empty, notLoadedMessage, emptyMessage }) {
  body.replaceChildren();
  thead.replaceChildren();

  if (settled.status !== "fulfilled") {
    wrapper.hidden = true;
    empty.textContent = notLoadedMessage;
    empty.hidden = false;
    return;
  }

  const items =
    settled.value && Array.isArray(settled.value.result) ? settled.value.result : [];

  if (items.length === 0) {
    wrapper.hidden = true;
    empty.textContent = emptyMessage;
    empty.hidden = false;
    return;
  }

  empty.hidden = true;
  wrapper.hidden = false;

  const columns = Object.keys(items[0]);
  const headRow = document.createElement("tr");
  for (const column of columns) {
    const th = document.createElement("th");
    th.setAttribute("scope", "col");
    th.textContent = column;
    headRow.append(th);
  }
  thead.append(headRow);

  for (const item of items) {
    const row = document.createElement("tr");
    for (const column of columns) {
      row.append(makeCell(formatValue(item[column])));
    }
    body.append(row);
  }
}

function describeFailures(results) {
  const entries = Object.values(results);
  const failures = entries.filter((r) => r.status === "rejected");
  if (failures.length === 0) return null;
  if (failures.length === entries.length) {
    return "Could not load extension data right now. The Command Center backend may be unreachable.";
  }
  return `Some extension data could not be loaded (${failures.length} of ${entries.length} sections). The rest is shown below.`;
}

/**
 * Load all three and render them. allSettled so one failure doesn't stop
 * the others from showing.
 */
export async function loadExtensions() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  const [extLangServers, fsAccessPurposes, walletCollections] = await Promise.allSettled([
    IrisApi.getExtLangServers(),
    IrisApi.getFsAccessPurposes(),
    IrisApi.getWalletCollections(),
  ]);

  renderExtLangServers(extLangServers);
  renderDynamicList(fsAccessPurposes, {
    wrapper: dom.fsPurposesWrapper,
    thead: dom.fsPurposesThead,
    body: dom.fsPurposesBody,
    empty: dom.fsPurposesEmpty,
    notLoadedMessage: "Could not load file system access purposes.",
    emptyMessage: "No file system access purposes reported.",
  });
  renderDynamicList(walletCollections, {
    wrapper: dom.walletWrapper,
    thead: dom.walletThead,
    body: dom.walletBody,
    empty: dom.walletEmpty,
    notLoadedMessage: "Could not load wallet collections.",
    emptyMessage: "No wallet collections reported.",
  });

  const results = { extLangServers, fsAccessPurposes, walletCollections };
  setErrorBanner(describeFailures(results));

  const settledList = Object.values(results);
  const allFailed = settledList.every((r) => r.status === "rejected");
  const anyFailed = settledList.some((r) => r.status === "rejected");
  if (allFailed) {
    setConnectionState("error", "Could not reach IRIS", "");
  } else if (anyFailed) {
    setConnectionState("degraded", "Connected (with warnings)", "");
  } else {
    setConnectionState("connected", "Connected", "");
  }

  setLoading(false);
}

export function initExtensionsControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadExtensions();
  });
}
