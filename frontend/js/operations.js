// Operations view: a "Supported Actions" catalog of the mutating operations
// the Command Center supports (risk level and required privilege come from
// the live registry, GET /api/iris/operations), plus the full UI flow for the
// one operation executed on this page — journal.update_purge_archived:
//
//   Review -> explicit confirmation -> [existing backend framework decides
//   authorization -> execution -> post-action verification] -> result
//
// The stages in brackets ALL happen server-side, inside the existing,
// already-tested POST /api/iris/journal/purge-archived route (see
// backend/app/routes/journal.py and backend/app/execution/executor.py).
// This file never re-implements, pre-checks, or second-guesses that
// decision — it only (a) shows the operation's own registry metadata and
// the current PurgeArchived value (both already-existing, already-used
// reads), and (b) sends exactly what the user explicitly chose
// (PurgeArchived + confirmed) to that one existing endpoint. There is no
// "force"/"bypass" field anywhere in this file, and nothing here executes
// automatically — the POST only ever fires from the Confirm & Execute
// button's own click handler.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention
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

// Module-level state for the execute panel only — never used to skip a
// server-side check, only to drive which UI stage (choose/confirm/result)
// is currently shown. Reset on every load and after every execution.
let journalOperation = null; // the operation's own registry metadata, from GET /api/iris/operations
let currentPurgeArchived = null; // last-known value, from GET /api/iris/journal/settings
let pendingTarget = null; // the value the user picked but has not yet confirmed
let journalSelected = false; // true once the user opened the journal action; nothing is preselected

// The supported mutating actions, grouped for the catalog. Only the friendly
// title/description/group and where the action is performed live here; risk
// level and required privilege always come from the registry. An action
// missing from the registry is not shown. `view` is the existing view whose
// own review/confirm flow performs the action; `null` = this page (journal).
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
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in the other views.
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
  // required_privileges is an OR-set (the caller needs ANY ONE of them —
  // see OperationDefinition's docstring), so " or " mirrors the backend's
  // own semantics rather than inventing new wording.
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

// Same status-badge convention already used by observability.js's trace
// status column — reused here so risk level and confirmation-required read
// as the same kind of at-a-glance safety signal, instead of plain table
// text next to a view whose whole purpose is "Act—safely."
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

// Built via document.createElement + .textContent — never innerHTML — so a
// registry value containing HTML-special characters is never markup.
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

/** Renders the Supported Actions catalog from the registry: only the
 * actions listed above that the registry actually defines, grouped. */
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

/** "Open →": the journal action shows this page's existing review/execute
 * panels; every other action goes to the existing view whose own
 * review/confirm flow performs it. Opening never executes anything. */
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

  // Shown only after the user opens the journal action — never preselected.
  if (!operation) {
    dom.reviewGrid.hidden = true;
    return;
  }

  dom.reviewGrid.hidden = !journalSelected;

  // The row explicitly naming the field execution would change
  // (PurgeArchived) is what satisfies "clearly show what execution
  // changes" — it is real, registry-sourced fact (the operation's own
  // description already names this field), not invented copy.
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

/**
 * Fetches GET /api/iris/operations and renders the catalog + review card.
 * This is a READ-ONLY call — no mutating request happens here.
 */
export async function loadOperations() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…");

  let response;
  try {
    response = await IrisApi.getOperations();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
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

  // Independent read (GET /api/iris/journal/settings) that populates the
  // execute panel's "current value" — only once the journal action has been
  // opened; it never confirms or executes anything itself.
  if (journalSelected) await loadCurrentPurgeArchived();
}

// --- Execute panel: Review -> explicit confirmation -> execute -> result ---

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

// Shows the "choose a value" stage and hides the confirm/result stages —
// the panel's default, at-rest state. Never called from an execution
// callback, only from load/cancel/after-result, so the page can never be
// left mid-confirmation by accident.
function showChooseStage() {
  pendingTarget = null;
  dom.executeChoose.hidden = false;
  dom.executeConfirm.hidden = true;
  dom.executeResult.hidden = true;
}

/**
 * Fetches the CURRENT PurgeArchived value via the existing, already-used
 * GET /api/iris/journal/settings — read-only, no confirmation needed to
 * merely look at it. Only updates the value display; deliberately never
 * touches which stage (choose/confirm/result) is showing, so calling this
 * after an execution never hides the result the user just got.
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
    // Generic, non-alarming — same discipline as every other view's error
    // handling.
    currentPurgeArchived = null;
    addInfoRow(dom.executeCurrentList, "Current PurgeArchived Value", "Could not load");
  }
}

/**
 * The view-load/Refresh path: refreshes the current value AND resets the
 * panel back to its at-rest "choose a value" stage. Never called from
 * executeConfirmed() (see refreshCurrentValueDisplay above) — only from
 * loadOperations(), i.e. on view load or an explicit Refresh click.
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

// The "choose a value" step — deliberately NOT the confirmation itself.
// Clicking one of these buttons only moves to a distinct confirm stage; it
// sends no request.
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

  // An audit-friendly record: operation, outcome, and both the
  // authorization/verification detail strings the backend already
  // produced — never re-worded or summarized away, so the exact reason for
  // any denial or failure stays traceable to its source.
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
 * The ONLY place in this file (or this view) that calls
 * IrisApi.executeJournalPurgeArchived — reachable ONLY via the Confirm &
 * Execute button's click handler below, never from page load, never from
 * loadOperations()/loadCurrentPurgeArchived(), and never automatically.
 * `confirmed` is always `true` here because this function only runs after
 * the user reached this stage via chooseTarget() and clicked Confirm —
 * there is no path that calls this with a fabricated confirmation.
 */
async function executeConfirmed() {
  if (pendingTarget === null) return;
  const target = pendingTarget;

  // Disabling synchronously, before any await, is what makes a second
  // rapid click a no-op — the same in-flight-request guard used by every
  // Refresh button elsewhere in this app.
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
    // Reflect whatever actually happened by re-reading the real current
    // value, rather than assuming the request succeeded — but WITHOUT
    // resetting the panel back to the choose stage, so the result stays
    // visible. Click Refresh to start another change.
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
