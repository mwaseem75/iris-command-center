// Extensions & Integrations page: external language servers, file-system
// access purposes and wallet collections (three GETs), with KPI cards and a
// detail panel per language server.
//
// Language servers have a known shape (Name, Port, Type), so that table has
// fixed columns. IRIS's list doesn't say whether a server is running, so the
// status shown is just "Configured". The other two lists have only ever come
// back empty, so their columns are taken from whatever fields IRIS returns.

import { IrisApi } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";

const PLACEHOLDER = "—";  // shown for empty values
const SVG_NS = "http://www.w3.org/2000/svg";

const STATUS_NOTE = "Listed in IRIS's external language server configuration. IRIS doesn't report whether it's running.";

// Chart palette slot per server type, so each type keeps its color.
const TYPE_TONES = {
  ".NET": 1, ML: 5, JDBC: 3, Java: 4, ODBC: 2, Python: 6, R: 1, XSLT: 4,
};

const PUZZLE_PATH =
  "M10 3.5h4v3a1.5 1.5 0 1 0 3 0v-.5h3.5v4.5h-.5a1.5 1.5 0 1 0 0 3h.5v4.5H16v-.5a1.5 1.5 0 1 0-3 0v.5H3.5V14H4a1.5 1.5 0 1 0 0-3h-.5V6.5H7v.5a1.5 1.5 0 1 0 3 0v-3.5z";
const PYTHON_PATH =
  "M12 3c-3 0-4.5 1-4.5 3v2.5H12V9H5.5C3.8 9 3 10.5 3 12.5S3.8 16 5.5 16H7v-2.5c0-1.7 1.2-3 3-3h4.5c1.4 0 2.5-1.1 2.5-2.5V6c0-2-1.5-3-5-3zM12 21c3 0 4.5-1 4.5-3v-2.5H12V15h6.5c1.7 0 2.5-1.5 2.5-3.5S20.2 8 18.5 8H17v2.5c0 1.7-1.2 3-3 3H9.5C8.1 13.5 7 14.6 7 16v2c0 2 1.5 3 5 3z";

const dom = {
  loadingState: document.getElementById("extensions-loading-state"),
  errorBanner: document.getElementById("extensions-error-banner"),
  errorBannerText: document.getElementById("extensions-error-banner-text"),
  refreshButton: document.getElementById("extensions-refresh-button"),
  connectionStatus: document.getElementById("extensions-connection-status"),
  connectionStatusLabel: document.getElementById("extensions-connection-status-label"),
  connectionDetail: document.getElementById("extensions-connection-detail"),
  kpiServers: document.getElementById("extensions-kpi-servers"),
  kpiServersMeta: document.getElementById("extensions-kpi-servers-meta"),
  kpiFs: document.getElementById("extensions-kpi-fs"),
  kpiFsMeta: document.getElementById("extensions-kpi-fs-meta"),
  kpiWallet: document.getElementById("extensions-kpi-wallet"),
  kpiWalletMeta: document.getElementById("extensions-kpi-wallet-meta"),
  kpiTotal: document.getElementById("extensions-kpi-total"),
  kpiTotalMeta: document.getElementById("extensions-kpi-total-meta"),
  extLangWrapper: document.getElementById("extensions-ext-lang-servers-table-wrapper"),
  extLangBody: document.getElementById("extensions-ext-lang-servers-table-body"),
  extLangEmpty: document.getElementById("extensions-ext-lang-servers-empty"),
  fsPurposesWrapper: document.getElementById("extensions-fs-access-purposes-table-wrapper"),
  fsPurposesThead: document.getElementById("extensions-fs-access-purposes-thead"),
  fsPurposesBody: document.getElementById("extensions-fs-access-purposes-table-body"),
  fsPurposesEmpty: document.getElementById("extensions-fs-access-purposes-empty"),
  fsPurposesEmptyTitle: document.getElementById("extensions-fs-access-purposes-empty-title"),
  fsPurposesEmptyText: document.getElementById("extensions-fs-access-purposes-empty-text"),
  walletWrapper: document.getElementById("extensions-wallet-collections-table-wrapper"),
  walletThead: document.getElementById("extensions-wallet-collections-thead"),
  walletBody: document.getElementById("extensions-wallet-collections-table-body"),
  walletEmpty: document.getElementById("extensions-wallet-collections-empty"),
  walletEmptyTitle: document.getElementById("extensions-wallet-collections-empty-title"),
  walletEmptyText: document.getElementById("extensions-wallet-collections-empty-text"),
  openWalletButton: document.getElementById("extensions-open-wallet"),
  drawer: document.getElementById("extensions-drawer"),
  drawerBackdrop: document.getElementById("extensions-drawer-backdrop"),
  drawerClose: document.getElementById("extensions-drawer-close"),
  drawerIcon: document.getElementById("extensions-drawer-icon"),
  drawerTitle: document.getElementById("extensions-drawer-title"),
  drawerType: document.getElementById("extensions-drawer-type"),
  drawerFields: document.getElementById("extensions-drawer-fields"),
  drawerRelated: document.getElementById("extensions-drawer-related"),
  drawerPython: document.getElementById("extensions-drawer-python"),
  drawerJson: document.getElementById("extensions-drawer-json"),
};

// The last fetched server list; the detail panel reads from it.
let allServers = [];
let onOpenWallet = null;
let onOpenEmbeddedPython = null;

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

function resultList(settled) {
  if (settled.status !== "fulfilled") return null;
  return settled.value && Array.isArray(settled.value.result) ? settled.value.result : [];
}

// Built with createElement/textContent (no innerHTML).
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function makeBadge(text, variant, title) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = text;
  if (title) badge.title = title;
  return badge;
}

// Fill `container` with the server type's icon (Python gets its own glyph).
function fillTypeIcon(container, type) {
  const tone = TYPE_TONES[type] || 1;
  container.style.setProperty("--ext-tone", `var(--color-chart-${tone})`);
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", type === "Python" ? PYTHON_PATH : PUZZLE_PATH);
  svg.append(path);
  container.replaceChildren(svg);
}

// --- KPI cards ---

function setKpi(valueEl, metaEl, count, metaText) {
  valueEl.textContent = count === null ? PLACEHOLDER : String(count);
  metaEl.textContent = metaText;
  metaEl.title = metaText;
}

function renderKpis(servers, purposes, collections) {
  if (servers === null) {
    setKpi(dom.kpiServers, dom.kpiServersMeta, null, "Unavailable");
  } else {
    const types = new Set(servers.map((s) => s.Type)).size;
    setKpi(
      dom.kpiServers,
      dom.kpiServersMeta,
      servers.length,
      servers.length ? `${types} ${types === 1 ? "type" : "types"} configured` : "None configured",
    );
  }
  setKpi(dom.kpiFs, dom.kpiFsMeta, purposes === null ? null : purposes.length,
    purposes === null ? "Unavailable" : purposes.length ? "Configured" : "Not configured");
  setKpi(dom.kpiWallet, dom.kpiWalletMeta, collections === null ? null : collections.length,
    collections === null ? "Unavailable" : collections.length ? "Configured" : "Not configured");

  const lists = [servers, purposes, collections];
  if (lists.every((list) => list === null)) {
    setKpi(dom.kpiTotal, dom.kpiTotalMeta, null, "Unavailable");
    return;
  }
  const total = lists.reduce((sum, list) => sum + (list ? list.length : 0), 0);
  setKpi(
    dom.kpiTotal,
    dom.kpiTotalMeta,
    total,
    lists.includes(null) ? "Configured (some lists failed to load)" : "Configured across all three lists",
  );
}

// --- language servers ---

function renderExtLangServers(servers) {
  dom.extLangBody.replaceChildren();

  if (servers === null) {
    dom.extLangWrapper.hidden = true;
    dom.extLangEmpty.textContent = "Could not load external language servers.";
    dom.extLangEmpty.hidden = false;
    return;
  }
  if (servers.length === 0) {
    dom.extLangWrapper.hidden = true;
    dom.extLangEmpty.textContent = "No external language servers reported.";
    dom.extLangEmpty.hidden = false;
    return;
  }

  dom.extLangEmpty.hidden = true;
  dom.extLangWrapper.hidden = false;

  servers.forEach((server, index) => {
    const row = document.createElement("tr");
    row.className = "data-table__row--clickable";
    row.dataset.index = String(index);
    row.tabIndex = 0;
    row.setAttribute("aria-label", `View details for ${textOrPlaceholder(server.Name)}`);

    const nameCell = document.createElement("td");
    nameCell.className = "data-table__cell";
    const nameWrap = document.createElement("span");
    nameWrap.className = "ext-name";
    const icon = document.createElement("span");
    icon.className = "ext-type-icon ext-type-icon--sm";
    icon.setAttribute("aria-hidden", "true");
    fillTypeIcon(icon, server.Type);
    const name = document.createElement("span");
    name.textContent = textOrPlaceholder(server.Name);
    nameWrap.append(icon, name);
    nameCell.append(nameWrap);
    nameCell.title = textOrPlaceholder(server.Name);

    const typeCell = document.createElement("td");
    typeCell.className = "data-table__cell";
    typeCell.append(makeBadge(textOrPlaceholder(server.Type), "status-badge--accent"));

    const statusCell = document.createElement("td");
    statusCell.className = "data-table__cell";
    statusCell.append(makeBadge("Configured", "status-badge--neutral", STATUS_NOTE));

    const actionCell = document.createElement("td");
    actionCell.className = "data-table__cell";
    const view = document.createElement("button");
    view.type = "button";
    view.className = "btn ext-view-btn";
    view.textContent = "View →";
    view.tabIndex = -1;
    actionCell.append(view);

    row.append(
      nameCell,
      typeCell,
      makeCell(textOrPlaceholder(server.Port), { mono: true }),
      statusCell,
      actionCell,
    );
    dom.extLangBody.append(row);
  });
}

// --- detail panel ---

function addField(label, value, { mono = false, node = null } = {}) {
  const row = document.createElement("div");
  row.className = "info-list__row";
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.className = mono ? "info-list__value info-list__value--mono" : "info-list__value";
  if (node) dd.append(node);
  else dd.textContent = value;
  row.append(dt, dd);
  dom.drawerFields.append(row);
}

function openDrawer(index) {
  const server = allServers[index];
  if (!server) return;

  fillTypeIcon(dom.drawerIcon, server.Type);
  dom.drawerTitle.textContent = textOrPlaceholder(server.Name);
  dom.drawerType.textContent = textOrPlaceholder(server.Type);

  dom.drawerFields.replaceChildren();
  addField("Name", textOrPlaceholder(server.Name), { mono: true });
  addField("Type", textOrPlaceholder(server.Type));
  addField("Port", textOrPlaceholder(server.Port), { mono: true });
  const status = document.createElement("span");
  status.className = "ext-status-note";
  status.append(makeBadge("Configured", "status-badge--neutral"));
  const note = document.createElement("span");
  note.textContent = "IRIS doesn't report whether it's running.";
  status.append(note);
  addField("Status", "", { node: status });
  addField("Category", "External Language Server");

  // Embedded Python lives in the AI Assistant; only link to it.
  dom.drawerRelated.hidden = !(server.Type === "Python" && onOpenEmbeddedPython);
  dom.drawerJson.textContent = JSON.stringify(server, null, 2);

  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (wasHidden) dom.drawerClose.focus();
}

function closeDrawer() {
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

// --- file system purposes / wallet ---

// Columns come from the fields IRIS actually returned.
function renderDynamicList(items, { wrapper, thead, body, empty, emptyTitle, emptyText, notLoaded, noneTitle }) {
  body.replaceChildren();
  thead.replaceChildren();

  if (items === null || items.length === 0) {
    wrapper.hidden = true;
    empty.dataset.state = items === null ? "error" : "empty";
    emptyTitle.textContent = items === null ? notLoaded : noneTitle;
    emptyText.textContent = items === null
      ? "Try Refresh. The rest of the page is unaffected."
      : "IRIS reports none on this instance.";
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
    IrisApi.getExtLangServers(selectedInstanceId()),
    IrisApi.getFsAccessPurposes(selectedInstanceId()),
    IrisApi.getWalletCollections(selectedInstanceId()),
  ]);

  const servers = resultList(extLangServers);
  const purposes = resultList(fsAccessPurposes);
  const collections = resultList(walletCollections);

  allServers = servers || [];
  closeDrawer();
  renderKpis(servers, purposes, collections);
  renderExtLangServers(servers);
  renderDynamicList(purposes, {
    wrapper: dom.fsPurposesWrapper,
    thead: dom.fsPurposesThead,
    body: dom.fsPurposesBody,
    empty: dom.fsPurposesEmpty,
    emptyTitle: dom.fsPurposesEmptyTitle,
    emptyText: dom.fsPurposesEmptyText,
    notLoaded: "Could not load file system access purposes",
    noneTitle: "No file system access purposes configured",
  });
  renderDynamicList(collections, {
    wrapper: dom.walletWrapper,
    thead: dom.walletThead,
    body: dom.walletBody,
    empty: dom.walletEmpty,
    emptyTitle: dom.walletEmptyTitle,
    emptyText: dom.walletEmptyText,
    notLoaded: "Could not load wallet collections",
    noneTitle: "No wallet collections configured",
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

/**
 * `onOpenWallet()` shows the Security page's Wallet tab and
 * `onOpenEmbeddedPython()` opens Embedded Python diagnostics (both wired by
 * app.js).
 */
export function initExtensionsControls({ onOpenWallet: openWallet, onOpenEmbeddedPython: openPython } = {}) {
  onOpenWallet = typeof openWallet === "function" ? openWallet : null;
  onOpenEmbeddedPython = typeof openPython === "function" ? openPython : null;
  dom.openWalletButton.hidden = !onOpenWallet;
  fillTypeIcon(dom.drawerPython.querySelector(".ext-type-icon"), "Python");

  dom.refreshButton.addEventListener("click", () => {
    loadExtensions();
  });

  // One delegated listener for the rows (and their View buttons).
  dom.extLangBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-index]");
    if (row) openDrawer(Number(row.dataset.index));
  });
  dom.extLangBody.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("tr[data-index]");
    if (!row) return;
    event.preventDefault();
    openDrawer(Number(row.dataset.index));
  });

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDrawer();
  });

  dom.drawerPython.addEventListener("click", () => {
    closeDrawer();
    if (onOpenEmbeddedPython) onOpenEmbeddedPython();
  });
  dom.openWalletButton.addEventListener("click", () => {
    if (onOpenWallet) onOpenWallet();
  });
}
