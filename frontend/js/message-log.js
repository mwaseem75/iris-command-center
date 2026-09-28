// Message Log (Investigation page): IRIS's messages.log, read-only.
//
// Reads GET /api/iris/messages-log once per load: the newest entries (the
// backend reads only the tail of the file), newest first. Search, the level
// filter and paging are local over those entries, with no further request.
// Rows open a detail drawer with the full message. Nothing here changes IRIS.
//
// Timestamps are shown exactly as IRIS writes them (MM/DD/YY-HH:MM:SS:mmm,
// no timezone); they're never parsed.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—";
const PAGE_SIZE = 50;

// IRIS severity 0-3.
const LEVEL_BADGES = {
  0: "status-badge--neutral",
  1: "status-badge--warning",
  2: "status-badge--error",
  3: "status-badge--error",
};

const dom = {
  section: document.getElementById("message-log-section"),
  refresh: document.getElementById("message-log-refresh"),
  form: document.getElementById("message-log-filter-form"),
  search: document.getElementById("message-log-search"),
  level: document.getElementById("message-log-level"),
  meta: document.getElementById("message-log-meta"),
  loading: document.getElementById("message-log-loading"),
  error: document.getElementById("message-log-error"),
  errorText: document.getElementById("message-log-error-text"),
  empty: document.getElementById("message-log-empty"),
  tableWrapper: document.getElementById("message-log-table-wrapper"),
  tableBody: document.getElementById("message-log-table-body"),
  pager: document.getElementById("message-log-pager"),
  pageInfo: document.getElementById("message-log-page-info"),
  pagePrev: document.getElementById("message-log-page-prev"),
  pageNext: document.getElementById("message-log-page-next"),
  drawerBackdrop: document.getElementById("message-log-drawer-backdrop"),
  drawer: document.getElementById("message-log-drawer"),
  drawerTitle: document.getElementById("message-log-drawer-title"),
  drawerLevel: document.getElementById("message-log-drawer-level"),
  drawerClose: document.getElementById("message-log-drawer-close"),
  drawerFields: document.getElementById("message-log-drawer-fields"),
  drawerMessage: document.getElementById("message-log-drawer-message"),
};

let log = null;        // the last response, or null
let entries = [];      // log.entries
let filtered = [];     // entries matching the search and level
let page = 0;
let loadSeq = 0;

function textOrPlaceholder(value) {
  if (value === null || value === undefined || value === "") return PLACEHOLDER;
  return String(value);
}

function firstLine(message) {
  const text = String(message || "");
  const end = text.indexOf("\n");
  return end === -1 ? text : `${text.slice(0, end)} …`;
}

function formatBytes(bytes) {
  if (typeof bytes !== "number") return PLACEHOLDER;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function makeCell(text, className = "data-table__cell") {
  const cell = document.createElement("td");
  cell.className = className;
  cell.textContent = text;
  return cell;
}

function makeBadge(entry) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${LEVEL_BADGES[entry.level] || "status-badge--neutral"}`;
  badge.textContent = textOrPlaceholder(entry.level_name);
  return badge;
}

function matches(entry, query, level) {
  if (level === "1+" ? entry.level < 1 : level !== "" && String(entry.level) !== level) return false;
  if (!query) return true;
  return [entry.message, entry.source, entry.pid, entry.timestamp]
    .some((value) => String(value ?? "").toLowerCase().includes(query));
}

function applyFilters() {
  const query = dom.search.value.trim().toLowerCase();
  const level = dom.level.value;
  filtered = entries.filter((entry) => matches(entry, query, level));
  page = 0;
  render();
}

function render() {
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  page = Math.min(page, pages - 1);
  const start = page * PAGE_SIZE;
  const visible = filtered.slice(start, start + PAGE_SIZE);

  dom.tableBody.replaceChildren(...visible.map((entry, i) => {
    const row = document.createElement("tr");
    row.className = "data-table__row--clickable";
    row.dataset.index = String(start + i);
    row.tabIndex = 0;
    row.setAttribute("aria-label", `View message from ${textOrPlaceholder(entry.timestamp)}`);
    const levelCell = document.createElement("td");
    levelCell.className = "data-table__cell";
    levelCell.append(makeBadge(entry));
    const message = makeCell(firstLine(entry.message), "data-table__cell message-log__cell-message");
    message.title = entry.message;
    row.append(
      makeCell(textOrPlaceholder(entry.timestamp), "data-table__cell data-table__cell--mono"),
      makeCell(textOrPlaceholder(entry.pid), "data-table__cell data-table__cell--mono"),
      levelCell,
      makeCell(textOrPlaceholder(entry.source)),
      message,
    );
    return row;
  }));

  const hasEntries = entries.length > 0;
  dom.tableWrapper.hidden = visible.length === 0;
  dom.empty.hidden = visible.length !== 0 || !log;
  dom.empty.textContent = hasEntries ? "No messages match the current search and level." : "The message log is empty.";
  dom.pager.hidden = filtered.length === 0;  // always shown with entries, like the audit pager
  dom.pageInfo.textContent = filtered.length
    ? `Showing ${start + 1}–${start + visible.length} of ${filtered.length} (page ${page + 1} of ${pages})`
    : "";
  dom.pagePrev.disabled = page === 0;
  dom.pageNext.disabled = page >= pages - 1;
}

function renderMeta() {
  if (!log) {
    dom.meta.textContent = "";
    return;
  }
  const parts = [
    `${entries.length} entries from ${textOrPlaceholder(log.path)} (${formatBytes(log.size_bytes)})`,
  ];
  if (log.truncated) parts.push(`only the newest part of the file is shown (last ${formatBytes(log.read_bytes)} read)`);
  dom.meta.textContent = parts.join(" · ");
}

function openDrawer(index) {
  const entry = filtered[index];
  if (!entry) return;
  dom.drawerTitle.textContent = `${textOrPlaceholder(entry.source)} · ${textOrPlaceholder(entry.timestamp)}`;
  dom.drawerLevel.className = `status-badge ${LEVEL_BADGES[entry.level] || "status-badge--neutral"}`;
  dom.drawerLevel.textContent = textOrPlaceholder(entry.level_name);
  dom.drawerFields.replaceChildren(...[
    ["Timestamp", entry.timestamp],
    ["PID", entry.pid],
    ["Level", `${textOrPlaceholder(entry.level_name)} (${textOrPlaceholder(entry.level)})`],
    ["Source", entry.source],
  ].map(([label, value]) => {
    const row = document.createElement("div");
    row.className = "info-list__row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.className = "info-list__value info-list__value--mono";
    dd.textContent = textOrPlaceholder(value);
    row.append(dt, dd);
    return row;
  }));
  dom.drawerMessage.textContent = entry.message;
  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (wasHidden) dom.drawerClose.focus();
}

function closeDrawer() {
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

/** GET /api/iris/messages-log and render. Filters and page are kept. */
export async function loadMessageLog() {
  const seq = ++loadSeq;
  dom.loading.hidden = false;
  dom.error.hidden = true;
  dom.refresh.disabled = true;
  try {
    const response = await IrisApi.getMessagesLog();
    if (seq !== loadSeq) return;
    log = response && Array.isArray(response.entries) ? response : null;
    entries = log ? log.entries : [];
    if (!log) {
      dom.errorText.textContent = "The backend didn't return the expected message log.";
      dom.error.hidden = false;
    }
  } catch (err) {
    if (seq !== loadSeq) return;
    log = null;
    entries = [];
    dom.errorText.textContent = err instanceof ApiError
      ? "Could not read IRIS's message log. The Command Center backend or IRIS may be unreachable."
      : "An unexpected error occurred while reading the message log.";
    dom.error.hidden = false;
  } finally {
    if (seq === loadSeq) {
      dom.loading.hidden = true;
      dom.refresh.disabled = false;
    }
  }
  if (seq !== loadSeq) return;
  renderMeta();
  const keepPage = page;
  applyFilters();
  page = keepPage;
  render();
}

export function initMessageLogControls() {
  dom.refresh.addEventListener("click", () => {
    loadMessageLog();
  });
  dom.form.addEventListener("submit", (event) => event.preventDefault());
  dom.search.addEventListener("input", applyFilters);
  dom.level.addEventListener("change", applyFilters);
  dom.pagePrev.addEventListener("click", () => {
    page = Math.max(0, page - 1);
    render();
  });
  dom.pageNext.addEventListener("click", () => {
    page += 1;
    render();
  });
  dom.tableBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-index]");
    if (row) openDrawer(Number(row.dataset.index));
  });
  dom.tableBody.addEventListener("keydown", (event) => {
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
}
