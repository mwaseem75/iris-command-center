// Operations page: a "Supported Actions" catalog of the changes the
// Command Center can make (risk and required privilege come from
// GET /api/iris/operations), plus the full flow for the one run on this
// page, journal.update_purge_archived:
//
//   Review -> confirm -> [backend: authorization -> execution -> verification] -> result
//
// The part in brackets happens on the server in
// POST /api/iris/journal/purge-archived. This file just shows the registry
// info and the current PurgeArchived value, and sends what the user picked
// (PurgeArchived + confirmed). Nothing runs on its own; the POST only comes
// from the Confirm & Execute button.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—";  // shown for empty values
const JOURNAL_OPERATION_NAME = "journal.update_purge_archived";

const dom = {
  loadingState: document.getElementById("operations-loading-state"),
  errorBanner: document.getElementById("operations-error-banner"),
  errorBannerText: document.getElementById("operations-error-banner-text"),
  refreshButton: document.getElementById("operations-refresh-button"),
  connectionStatus: document.getElementById("operations-connection-status"),
  connectionStatusLabel: document.getElementById("operations-connection-status-label"),
  countLabel: document.getElementById("operations-count"),
  empty: document.getElementById("operations-empty"),
  catalog: document.getElementById("operations-catalog"),
  selectHint: document.getElementById("operations-select-hint"),
  reviewGrid: document.getElementById("operations-review-grid"),
  reviewList: document.getElementById("operations-review-list"),
  executeLoadingState: document.getElementById("operations-execute-loading-state"),
  executeCurrentList: document.getElementById("operations-execute-current-list"),
  executeChoose: document.getElementById("operations-execute-choose"),
  setTrueButton: document.getElementById("operations-set-true-button"),
  setFalseButton: document.getElementById("operations-set-false-button"),
  executeConfirm: document.getElementById("operations-execute-confirm"),
  executeConfirmText: document.getElementById("operations-execute-confirm-text"),
  confirmButton: document.getElementById("operations-confirm-button"),
  cancelButton: document.getElementById("operations-cancel-button"),
  executingState: document.getElementById("operations-executing-state"),
  executeResult: document.getElementById("operations-execute-result"),
  resultList: document.getElementById("operations-result-list"),
};

// State for the execute panel: which step (choose/confirm/result) is
// showing. Reset on every load and after every run.
let journalOperation = null;  // registry entry, from GET /api/iris/operations
let currentPurgeArchived = null;  // last known value, from GET /api/iris/journal/settings
let pendingTarget = null;  // value picked but not confirmed yet
let journalSelected = false;  // true once the journal action is opened; nothing is preselected

// The actions in the catalog, grouped. Only the title, description, group
// and where it's done live here; risk and privilege come from the
// registry, and actions missing from the registry aren't shown. `view` is
// the page that performs it; `null` means this page (journal).
const CATALOG_GROUPS = ["Journal", "Namespaces", "Databases", "Web Applications", "Users", "Tasks"];
const SUPPORTED_ACTIONS = [
  {
    name: JOURNAL_OPERATION_NAME,
    title: "Update Journal Settings",
    description: "Choose whether IRIS deletes journal files once they have been archived (the PurgeArchived setting).",
    group: "Journal",
    view: null,
  },
  {
    name: "namespace.create",
    title: "Create Namespace",
    description: "Create a new namespace and map it to databases for its data and code.",
    group: "Namespaces",
    view: "namespaces",
  },
  {
    name: "database.create",
    title: "Create Database",
    description: "Create a new database in a directory on the IRIS server.",
    group: "Databases",
    view: "databases",
  },
  {
    name: "database.mount",
    title: "Mount Database",
    description: "Mount a database so its data becomes available to IRIS.",
    group: "Databases",
    view: "databases",
  },
  {
    name: "database.dismount",
    title: "Dismount Database",
    description: "Dismount a database; its data is unavailable until it is mounted again. System databases are protected.",
    group: "Databases",
    view: "databases",
  },
  {
    name: "web_app.set_enabled",
    title: "Enable / Disable Web Application",
    description: "Turn a web application on or off.",
    group: "Web Applications",
    view: "web-apps",
  },
  {
    name: "web_app.update_description",
    title: "Update Web Application Description",
    description: "Change the description text of a web application.",
    group: "Web Applications",
    view: "web-apps",
  },
  {
    name: "user.set_enabled",
    title: "Enable / Disable User",
    description: "Allow or block sign-in for an IRIS user account.",
    group: "Users",
    view: "security",
  },
  {
    name: "task.run_now",
    title: "Run Task Now",
    description: "Start a scheduled task immediately instead of waiting for its next scheduled run.",
    group: "Tasks",
    view: "tasks",
  },
];
const VIEW_LABEL = {
  namespaces: "Namespaces",
  databases: "Databases",
  "web-apps": "Web Applications",
  security: "Security",
  tasks: "Tasks",
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

function setConnectionState(state, label) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
}

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatKind(kind) {
  if (kind === "mutating") return "Mutating";
  if (kind === "read_only") return "Read-only";
  return textOrPlaceholder(kind);
}

function formatPrivileges(privileges) {
  // required_privileges means any one of them, hence " or ".
  return Array.isArray(privileges) && privileges.length > 0
    ? privileges.join(" or ")
    : PLACEHOLDER;
}

function formatConfirmation(required) {
  return required ? "Yes" : "No";
}

function formatRisk(riskLevel) {
  if (typeof riskLevel !== "string" || !riskLevel) return PLACEHOLDER;
  return `${riskLevel.charAt(0).toUpperCase()}${riskLevel.slice(1)} risk`;
}

// Same badge style as the Observability status column, so risk and
// confirmation stand out.
const RISK_BADGE_CLASS = {
  none: "status-badge--neutral",
  low: "status-badge--ok",
  medium: "status-badge--warning",
  high: "status-badge--error",
};

function makeRiskBadge(riskLevel) {
  const key = typeof riskLevel === "string" ? riskLevel.toLowerCase() : "";
  const badge = document.createElement("span");
  badge.className = `status-badge ${RISK_BADGE_CLASS[key] || "status-badge--neutral"}`;
  badge.textContent = formatRisk(riskLevel);
  return badge;
}

// Built with createElement/textContent (no innerHTML).
function makeEl(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function makeActionCard(action, operation) {
  const card = makeEl("article", "ops-card");
  card.dataset.operation = action.name;

  const head = makeEl("div", "ops-card__head");
  head.append(makeEl("h4", "ops-card__title", action.title), makeRiskBadge(operation.risk_level));

  const description = makeEl("p", "ops-card__description", action.description);

  const facts = makeEl("dl", "ops-card__facts");
  for (const [label, value] of [
    ["Category", action.group],
    ["Required privilege", formatPrivileges(operation.required_privileges)],
  ]) {
    const row = makeEl("div", "ops-card__fact");
    row.append(makeEl("dt", "", label), makeEl("dd", "", value));
    facts.append(row);
  }

  const foot = makeEl("div", "ops-card__foot");
  foot.append(
    makeEl("span", "ops-card__where", action.view ? `Opens in ${VIEW_LABEL[action.view]}` : "Opens on this page"),
  );
  const open = makeEl("button", "btn ops-card__open", "Open →");
  open.type = "button";
  open.setAttribute("aria-label", `Open ${action.title}`);
  open.addEventListener("click", () => openAction(action));
  foot.append(open);

  card.append(head, description, facts, foot);
  return card;
}

/** Render the catalog: the actions above that exist in the registry, grouped. */
function renderCatalog(operations) {
  dom.catalog.replaceChildren();
  const byName = new Map(Array.isArray(operations) ? operations.map((op) => [op.name, op]) : []);
  const available = SUPPORTED_ACTIONS.filter((action) => byName.has(action.name));

  dom.empty.hidden = !Array.isArray(operations) || available.length > 0;
  dom.countLabel.textContent = available.length
    ? `${available.length} supported action${available.length === 1 ? "" : "s"}`
    : "";

  for (const group of CATALOG_GROUPS) {
    const actions = available.filter((action) => action.group === group);
    if (actions.length === 0) continue;
    const section = makeEl("section", "ops-group");
    section.append(makeEl("h3", "ops-group__title", group));
    const grid = makeEl("div", "ops-grid");
    for (const action of actions) grid.append(makeActionCard(action, byName.get(action.name)));
    section.append(grid);
    dom.catalog.append(section);
  }
}

function markOpened(name) {
  dom.catalog.querySelectorAll(".ops-card").forEach((card) => {
    card.classList.toggle("ops-card--selected", card.dataset.operation === name);
  });
}

/**
 * "Open ->": the journal action shows the panels on this page; the others
 * go to the page that performs them. Opening doesn't run anything.
 */
function openAction(action) {
  if (action.view) {
    navigateTo(action.view);
    return;
  }
  journalSelected = true;
  markOpened(action.name);
  dom.selectHint.hidden = true;
  dom.reviewGrid.hidden = !journalOperation;
  if (journalOperation) {
    loadCurrentPurgeArchived();
    dom.reviewGrid.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

function renderReview(operations) {
  dom.reviewList.replaceChildren();

  const operation = Array.isArray(operations)
    ? operations.find((op) => op && op.name === JOURNAL_OPERATION_NAME)
    : null;
  journalOperation = operation || null;

  // Only shown once the journal action is opened.
  if (!operation) {
    dom.reviewGrid.hidden = true;
    return;
  }

  dom.reviewGrid.hidden = !journalSelected;

  // This row says which field will change (PurgeArchived).
  const rows = [
    ["Operation ID", textOrPlaceholder(operation.name)],
    ["Description", textOrPlaceholder(operation.description)],
    ["Kind", formatKind(operation.kind)],
    ["Risk Level", textOrPlaceholder(operation.risk_level)],
    ["Required Privilege", formatPrivileges(operation.required_privileges)],
    ["Confirmation Required", formatConfirmation(operation.confirmation_required)],
    ["Field Changed by Execution", "PurgeArchived"],
  ];

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.className = "info-list__value info-list__value--mono";
    dd.textContent = value;

    row.append(dt, dd);
    dom.reviewList.append(row);
  }
}

/** Load GET /api/iris/operations and render the catalog and review card. */
export async function loadOperations() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…");

  let response;
  try {
    response = await IrisApi.getOperations();
  } catch (err) {
    // ApiError messages are already safe to show (see api.js).
    const message =
      err instanceof ApiError
        ? "Could not load operations. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading operations.";
    setConnectionState("error", "Could not reach the backend");
    setErrorBanner(message);
    renderCatalog(null);
    renderReview(null);
    setLoading(false);
    return;
  }

  const operations = response && Array.isArray(response.operations) ? response.operations : null;

  if (operations === null) {
    setConnectionState("error", "Backend returned no data");
    setErrorBanner("The backend did not return the expected operations list.");
    renderCatalog(null);
    renderReview(null);
    setLoading(false);
    return;
  }

  setConnectionState("connected", "Connected");
  setErrorBanner(null);
  renderCatalog(operations);
  markOpened(journalSelected ? JOURNAL_OPERATION_NAME : null);
  renderReview(operations);
  setLoading(false);

  // Read the current value for the execute panel, once the journal action
  // is open.
  if (journalSelected) await loadCurrentPurgeArchived();
}

// --- Execute panel: review -> confirm -> execute -> result ---

function addInfoRow(list, label, value, { mono = true } = {}) {
  const row = document.createElement("div");
  row.className = "info-list__row";

  const dt = document.createElement("dt");
  dt.textContent = label;

  const dd = document.createElement("dd");
  dd.className = mono ? "info-list__value info-list__value--mono" : "info-list__value";
  dd.textContent = value;

  row.append(dt, dd);
  list.append(row);
}

function formatBoolean(value) {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : PLACEHOLDER;
}

// Show the "choose a value" step and hide confirm/result. Called on load,
// cancel and after a result, never mid-run.
function showChooseStage() {
  pendingTarget = null;
  dom.executeChoose.hidden = false;
  dom.executeConfirm.hidden = true;
  dom.executeResult.hidden = true;
}

/**
 * Read the current PurgeArchived value (GET /api/iris/journal/settings).
 * Only updates the value shown, not which step is showing, so calling it
 * after a run doesn't hide the result.
 */
async function refreshCurrentValueDisplay() {
  dom.executeCurrentList.replaceChildren();
  try {
    const response = await IrisApi.getJournalSettings();
    const value =
      response && response.result && typeof response.result.PurgeArchived === "boolean"
        ? response.result.PurgeArchived
        : null;
    currentPurgeArchived = value;
    addInfoRow(dom.executeCurrentList, "Current PurgeArchived Value", formatBoolean(value));
  } catch {
    // Keep it low-key, like the other pages' errors.
    currentPurgeArchived = null;
    addInfoRow(dom.executeCurrentList, "Current PurgeArchived Value", "Could not load");
  }
}

/**
 * On load/Refresh: update the current value and go back to the "choose a
 * value" step. Not called after a run (see refreshCurrentValueDisplay).
 */
async function loadCurrentPurgeArchived() {
  dom.executeLoadingState.hidden = false;
  dom.executeChoose.hidden = true;
  dom.executeConfirm.hidden = true;
  dom.executeResult.hidden = true;

  await refreshCurrentValueDisplay();

  dom.executeLoadingState.hidden = true;
  showChooseStage();
}

// Picking a value only moves on to the confirm step; nothing is sent.
function chooseTarget(target) {
  pendingTarget = target;
  const privilegesText =
    journalOperation && Array.isArray(journalOperation.required_privileges)
      ? journalOperation.required_privileges.join(" or ")
      : PLACEHOLDER;
  dom.executeConfirmText.textContent =
    `You are about to change PurgeArchived from ${formatBoolean(currentPurgeArchived)} to ` +
    `${formatBoolean(target)}. Required privilege: ${privilegesText}. This calls the existing ` +
    "authorization and execution framework, which independently decides whether this is " +
    "allowed to proceed. Nothing has been sent yet.";
  dom.executeChoose.hidden = true;
  dom.executeConfirm.hidden = false;
  dom.executeResult.hidden = true;
}

function renderExecutionResult(result) {
  dom.resultList.replaceChildren();

  // Show the operation, the outcome, and the backend's authorization and
  // verification messages as-is, so the reason for a denial or failure is
  // clear.
  addInfoRow(dom.resultList, "Operation", textOrPlaceholder(result.operation_name));
  addInfoRow(dom.resultList, "Status", textOrPlaceholder(result.status));
  addInfoRow(dom.resultList, "Detail", textOrPlaceholder(result.detail), { mono: false });

  if (result.handler_result) {
    addInfoRow(
      dom.resultList,
      "Execution Detail",
      textOrPlaceholder(result.handler_result.detail),
      { mono: false },
    );
    const data = result.handler_result.data || {};
    if ("original_purge_archived" in data) {
      addInfoRow(dom.resultList, "Original Value", formatBoolean(data.original_purge_archived));
    }
    if ("requested_purge_archived" in data) {
      addInfoRow(dom.resultList, "Requested Value", formatBoolean(data.requested_purge_archived));
    }
  }

  if (result.verification) {
    addInfoRow(dom.resultList, "Verification Status", textOrPlaceholder(result.verification.status));
    addInfoRow(
      dom.resultList,
      "Verification Detail",
      textOrPlaceholder(result.verification.detail),
      { mono: false },
    );
  }

  addInfoRow(dom.resultList, "Recorded At", new Date().toLocaleString());

  dom.executeConfirm.hidden = true;
  dom.executeResult.hidden = false;
}

/**
 * The only call to IrisApi.executeJournalPurgeArchived, from the Confirm &
 * Execute button. `confirmed` is true because you only get here by picking
 * a value and clicking Confirm.
 */
async function executeConfirmed() {
  if (pendingTarget === null) return;
  const target = pendingTarget;

  // Disable right away so a double click doesn't fire two requests.
  dom.confirmButton.disabled = true;
  dom.cancelButton.disabled = true;
  dom.executeConfirm.hidden = true;
  dom.executingState.hidden = false;

  try {
    const result = await IrisApi.executeJournalPurgeArchived(target, true);
    renderExecutionResult(result);
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not reach the Command Center backend to execute this operation."
        : "An unexpected error occurred while executing this operation.";
    renderExecutionResult({
      operation_name: JOURNAL_OPERATION_NAME,
      status: "request_failed",
      detail: message,
    });
  } finally {
    dom.executingState.hidden = true;
    dom.confirmButton.disabled = false;
    dom.cancelButton.disabled = false;
    // Re-read the real value instead of assuming it worked, but stay on the
    // result step so it's still visible. Refresh to make another change.
    await refreshCurrentValueDisplay();
  }
}

export function initOperationsControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadOperations();
  });

  dom.setTrueButton.addEventListener("click", () => chooseTarget(true));
  dom.setFalseButton.addEventListener("click", () => chooseTarget(false));
  dom.cancelButton.addEventListener("click", () => showChooseStage());
  dom.confirmButton.addEventListener("click", () => {
    executeConfirmed();
  });
}
