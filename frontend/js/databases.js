// Databases page: summary cards, a status bar, a card per database and a
// detail drawer, from GET /api/iris/databases.
//
// GET /api/iris/namespaces is also loaded (the same call the Namespaces page
// makes) to show which namespaces use a database in the drawer. If it
// fails, that section just says unavailable.
//
// Drawer actions:
// - View Info (read-only): storage facts from GET /api/iris/databases/info
//   (see INFO_FIELDS).
// - Run Integrity Check (read-only): shows IRIS's raw task envelope (State,
//   Console, Failure Reason, Result, times). We've never run a real one, so
//   Result is shown as JSON rather than named fields.
// - Mount and Dismount: "Check" does a dry run, then the real request is only
//   sent from the Confirm button (submitMount / submitDismount) after a
//   valid preview and the checkbox. The backend does the authorization.
//
// The "New Database" wizard (database.create) works like the New Namespace
// wizard: Configure -> Review (dry run) -> confirm -> create -> result. The
// real request is only sent from Confirm & Create (submitCreate).
//
// The drawer shows all DatabaseEntry fields (Name, Directory, Server,
// ClusterMountMode, MountRequired, MountAtStartup, StreamLocation, Status).
// Sizes come separately from View Info, only when you click it.
//
// The wizard fields (Directory, Resource Name, Size, Global Journal State,
// Encryption) match DatabaseCreateParameters. There's no Name field:
// databases are identified by Directory, and the verification result
// doesn't include a name either.

import { IrisApi, ApiError } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";
import { navigateTo } from "./nav.js";
import { countBy, renderStackedBar, topCategories } from "./viz.js";

const PLACEHOLDER = "—";  // shown for empty values

const dom = {
  loadingState: document.getElementById("databases-loading-state"),
  errorBanner: document.getElementById("databases-error-banner"),
  errorBannerText: document.getElementById("databases-error-banner-text"),
  refreshButton: document.getElementById("databases-refresh-button"),
  backButton: document.getElementById("databases-back-button"),
  connectionStatus: document.getElementById("databases-connection-status"),
  connectionStatusLabel: document.getElementById("databases-connection-status-label"),
  connectionDetail: document.getElementById("databases-connection-detail"),
  countLabel: document.getElementById("databases-count"),
  empty: document.getElementById("databases-empty"),
  content: document.getElementById("databases-content"),
  summaryCount: document.getElementById("databases-summary-count"),
  summaryMounted: document.getElementById("databases-summary-mounted"),
  summaryReadWrite: document.getElementById("databases-summary-read-write"),
  overview: document.getElementById("databases-overview"),
  overviewViz: document.getElementById("databases-overview-viz"),
  cardGrid: document.getElementById("databases-card-grid"),
  drawerBackdrop: document.getElementById("databases-drawer-backdrop"),
  drawer: document.getElementById("databases-drawer"),
  drawerTitle: document.getElementById("databases-drawer-title"),
  drawerStatusBadge: document.getElementById("databases-drawer-status-badge"),
  drawerFields: document.getElementById("databases-drawer-fields"),
  drawerUsage: document.getElementById("databases-drawer-usage"),
  drawerClose: document.getElementById("databases-drawer-close"),
  drawerInfoButton: document.getElementById("databases-drawer-info-button"),
  drawerInfoLoading: document.getElementById("databases-drawer-info-loading"),
  drawerInfoError: document.getElementById("databases-drawer-info-error"),
  drawerInfoErrorText: document.getElementById("databases-drawer-info-error-text"),
  drawerInfoFields: document.getElementById("databases-drawer-info-fields"),
  drawerIntegrityButton: document.getElementById("databases-drawer-integrity-button"),
  drawerIntegrityLoading: document.getElementById("databases-drawer-integrity-loading"),
  drawerIntegrityError: document.getElementById("databases-drawer-integrity-error"),
  drawerIntegrityErrorText: document.getElementById("databases-drawer-integrity-error-text"),
  drawerIntegrityFields: document.getElementById("databases-drawer-integrity-fields"),
  drawerIntegrityStateBadge: document.getElementById("databases-drawer-integrity-state-badge"),
  drawerIntegrityConsoleLabel: document.getElementById("databases-drawer-integrity-console-label"),
  drawerIntegrityConsole: document.getElementById("databases-drawer-integrity-console"),
  drawerMountCheckButton: document.getElementById("databases-drawer-mount-check-button"),
  drawerMountReadOnly: document.getElementById("databases-drawer-mount-read-only"),
  drawerMountLoading: document.getElementById("databases-drawer-mount-loading"),
  drawerMountLoadingText: document.getElementById("databases-drawer-mount-loading-text"),
  drawerMountError: document.getElementById("databases-drawer-mount-error"),
  drawerMountErrorText: document.getElementById("databases-drawer-mount-error-text"),
  drawerMountConfirm: document.getElementById("databases-drawer-mount-confirm"),
  drawerMountPreviewText: document.getElementById("databases-drawer-mount-preview-text"),
  drawerMountAckCheckbox: document.getElementById("databases-drawer-mount-ack-checkbox"),
  drawerMountConfirmButton: document.getElementById("databases-drawer-mount-confirm-button"),
  drawerMountResult: document.getElementById("databases-drawer-mount-result"),
  issuesBody: document.getElementById("databases-issues-body"),
  resolveFlow: document.getElementById("databases-resolve-flow"),
  resolveTitle: document.getElementById("databases-resolve-title"),
  resolveSteps: document.getElementById("databases-resolve-steps"),
  drawerDismountCheckButton: document.getElementById("databases-drawer-dismount-check-button"),
  drawerDismountLoading: document.getElementById("databases-drawer-dismount-loading"),
  drawerDismountLoadingText: document.getElementById("databases-drawer-dismount-loading-text"),
  drawerDismountError: document.getElementById("databases-drawer-dismount-error"),
  drawerDismountErrorText: document.getElementById("databases-drawer-dismount-error-text"),
  drawerDismountConfirm: document.getElementById("databases-drawer-dismount-confirm"),
  drawerDismountPreviewText: document.getElementById("databases-drawer-dismount-preview-text"),
  drawerDismountAckCheckbox: document.getElementById("databases-drawer-dismount-ack-checkbox"),
  drawerDismountConfirmButton: document.getElementById("databases-drawer-dismount-confirm-button"),
  drawerDismountResult: document.getElementById("databases-drawer-dismount-result"),
};

// The New Database wizard. Separate drawer from the detail drawer so they
// never share DOM state; same structure as the New Namespace wizard.
const createDom = {
  openButton: document.getElementById("databases-create-button"),
  backdrop: document.getElementById("database-create-backdrop"),
  drawer: document.getElementById("database-create-drawer"),
  close: document.getElementById("database-create-close"),
  stepLabel: document.getElementById("database-create-step-label"),

  // Step 1: Configure
  form: document.getElementById("database-create-form"),
  directoryInput: document.getElementById("database-create-directory"),
  resourceNameInput: document.getElementById("database-create-resource-name"),
  sizeInput: document.getElementById("database-create-size"),
  globalJournalStateInput: document.getElementById("database-create-global-journal-state"),
  encryptedInput: document.getElementById("database-create-encrypted"),
  error: document.getElementById("database-create-error"),
  errorText: document.getElementById("database-create-error-text"),

  // Step 2: Review
  review: document.getElementById("database-create-review"),
  previewLoading: document.getElementById("database-create-preview-loading"),
  reviewContent: document.getElementById("database-create-review-content"),
  summaryList: document.getElementById("database-create-summary-list"),
  previewError: document.getElementById("database-create-preview-error"),
  previewErrorText: document.getElementById("database-create-preview-error-text"),
  ackCheckbox: document.getElementById("database-create-ack-checkbox"),
  confirmButton: document.getElementById("database-create-confirm-button"),
  backButton: document.getElementById("database-create-back-button"),

  // Step 3: Executing
  executingState: document.getElementById("database-create-executing-state"),

  // Step 4: Result
  resultSection: document.getElementById("database-create-result"),
  resultList: document.getElementById("database-create-result-list"),
  retryButton: document.getElementById("database-create-retry-button"),
  doneButton: document.getElementById("database-create-done-button"),
};

// What the user configured and reviewed. Set by handleCreateNext(), read by
// renderReviewPreview()/submitCreate(). `confirmed: true` is only sent from
// submitCreate(), i.e. the Confirm & Create button.
let pendingCreateFields = null;

// Whether the Review dry run said the request is OK. Confirm & Create
// stays disabled unless this and the checkbox are both true.
let reviewIsValid = false;

// Same Directory check as DatabaseCreateParameters on the backend, just to
// catch obvious mistakes early. The dry run and the real request are still
// validated by the backend.
const DIRECTORY_PATTERN = /^\/[^\0]{0,499}$/;

/**
 * Same as the backend's _normalize_directory(): add a trailing slash (IRIS
 * always returns one) so "/x" and "/x/" match. Case is kept (Linux paths).
 */
function normalizeDirectory(directory) {
  return `${directory.replace(/\/+$/, "")}/`;
}

/**
 * Same as the backend's _derive_expected_name(): last path segment,
 * uppercased. Only used to spot likely name collisions before creating.
 */
function deriveExpectedName(directory) {
  const segments = directory.split("/").filter(Boolean);
  if (segments.length === 0) return null;
  return segments[segments.length - 1].toUpperCase();
}

// The last fetched list; the drawer looks databases up here by name.
let allDatabases = [];
let onOpenTrace = null;  // app.js helper that opens a trace in Observability

// Namespaces from the last fetch, only for "Namespace Usage". null means
// it failed to load (different from an empty list), so the drawer can say
// "unavailable" instead of "none".
let allNamespaces = null;

// Directory of the database in the drawer, used by View Info.
let currentDrawerDirectory = null;

// [label, DatabaseEntry field, value kind] in model order.
const DRAWER_FIELDS = [
  ["Name", "Name", "text"],
  ["Status", "Status", "text"],
  ["Directory", "Directory", "mono"],
  ["Server", "Server", "mono"],
  ["Stream Location", "StreamLocation", "mono"],
  ["Mount at Startup", "MountAtStartup", "bool"],
  ["Mount Required", "MountRequired", "bool"],
  ["Cluster Mount Mode", "ClusterMountMode", "bool"],
];

// [label, DatabaseInfoResult field, value kind] in model order, for View
// Info.
const INFO_FIELDS = [
  ["Size", "Size", "text"],
  ["Expansion Size", "ExpansionSize", "text"],
  ["Max Size", "MaxSize", "text"],
  ["Block Size", "BlockSize", "text"],
  ["Blocks", "Blocks", "text"],
  ["Available Space", "AvailableSpace", "text"],
  ["Disk Free", "DiskFree", "text"],
  ["End Free", "EndFree", "text"],
  ["Last Expansion Time", "LastExpansionTime", "text"],
  ["Mounted", "Mounted", "bool"],
  ["Full", "Full", "bool"],
  ["Encrypted", "Encrypted", "bool"],
  ["Encryption Key ID", "EncryptionKeyID", "mono"],
  ["Read Only Reason", "ReadOnlyReason", "text"],
  ["Mirrored", "Mirrored", "bool"],
  ["Mirror Set Name", "MirrorSetName", "text"],
  ["Mirror DB Name", "MirrorDBName", "text"],
  ["Mirror Failover DB", "MirrorFailoverDB", "bool"],
  ["SFN", "SFN", "text"],
];

// [namespace field, role label]: the NamespaceEntry fields that name a
// database, used by findReferencingNamespaces().
const NAMESPACE_DB_ROLE_FIELDS = [
  ["Globals", "Globals"],
  ["Routines", "Routines"],
  ["SysGlobals", "System Globals"],
  ["SysRoutines", "System Routines"],
  ["Library", "Library"],
  ["TempGlobals", "Temp Globals"],
];

/**
 * Status bar over the same list as the cards. Hidden when there's nothing
 * to show.
 */
function renderOverview(databases) {
  if (!Array.isArray(databases) || databases.length === 0) {
    dom.overview.hidden = true;
    return;
  }
  dom.overview.hidden = false;
  const entries = topCategories(countBy(databases, (db) => db.Status || "Unknown"), 6);
  renderStackedBar(dom.overviewViz, entries);
}

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

function formatBoolean(value) {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : PLACEHOLDER;
}

/**
 * For values with no known shape (like the integrity check Result): show
 * objects/arrays as JSON text instead of guessing fields.
 */
function formatUnknownValue(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

/**
 * Map a Status string ("Mounted/RW", "Mounted/R", ...) to a badge color.
 * The badge text is always the status itself. Anything not starting with
 * "Mounted" is shown as an error.
 */
function statusBadgeVariant(status) {
  if (typeof status !== "string" || status.length === 0) return "status-badge--neutral";
  if (status.includes("RW")) return "status-badge--ok";
  if (status.startsWith("Mounted")) return "status-badge--warning";
  return "status-badge--error";
}

function makeStatusBadge(status) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${statusBadgeVariant(status)}`;
  badge.textContent = textOrPlaceholder(status);
  return badge;
}

/**
 * Map an async task State ("Finished", "Failed", "Canceled", "Running",
 * "Queued") to a badge color. The badge shows the State itself.
 */
function taskStateBadgeVariant(state) {
  if (typeof state !== "string" || state.length === 0) return "status-badge--neutral";
  if (state === "Finished") return "status-badge--ok";
  if (state === "Failed" || state === "Canceled") return "status-badge--error";
  return "status-badge--warning";
}

/**
 * Small pill for a value, the same .db-chip as on Namespaces but without
 * the color dot. Used for mount flags on cards and namespace names in the
 * drawer.
 */
function makeChip(label, { title } = {}) {
  const chip = document.createElement("span");
  chip.className = "db-chip";
  if (title) chip.title = title;
  const text = document.createElement("span");
  text.className = "db-chip__label";
  text.textContent = label;
  chip.append(text);
  return chip;
}

function renderSummary(databases) {
  dom.summaryCount.textContent = String(databases.length);

  const mountedCount = databases.filter(
    (db) => typeof db.Status === "string" && db.Status.startsWith("Mounted"),
  ).length;
  const readWriteCount = databases.filter(
    (db) => typeof db.Status === "string" && db.Status.includes("RW"),
  ).length;

  dom.summaryMounted.textContent = String(mountedCount);
  dom.summaryReadWrite.textContent = String(readWriteCount);
}

function renderDatabaseCards(databases) {
  dom.cardGrid.replaceChildren();

  for (const db of databases) {
    const card = document.createElement("article");
    // Same card component as the Namespaces page.
    card.className = "namespace-card";
    card.dataset.database = db.Name;
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-label", `View details for database ${textOrPlaceholder(db.Name)}`);

    const header = document.createElement("div");
    header.className = "namespace-card__header";
    const name = document.createElement("h4");
    name.className = "namespace-card__name";
    name.textContent = textOrPlaceholder(db.Name);
    header.append(name, makeStatusBadge(db.Status));

    const directory = document.createElement("p");
    directory.className = "db-card__directory";
    directory.title = textOrPlaceholder(db.Directory);
    directory.textContent = textOrPlaceholder(db.Directory);

    // Only the flags worth pointing out; MountAtStartup is the usual case.
    // The drawer shows all three. No chip row if there's nothing to show.
    const chips = document.createElement("div");
    chips.className = "namespace-card__chips";
    if (db.MountRequired === true) chips.append(makeChip("Mount Required"));
    if (db.ClusterMountMode === true) chips.append(makeChip("Cluster Mount"));

    const link = document.createElement("span");
    link.className = "stat-card__link";
    link.textContent = "View details →";

    card.append(header, directory);
    if (chips.childElementCount > 0) card.append(chips);
    card.append(link);
    dom.cardGrid.append(card);
  }
}

/**
 * Namespaces whose Globals/Routines/SysGlobals/SysRoutines/Library/
 * TempGlobals is this database. null if the namespace list didn't load
 * (see renderNamespaceUsage()).
 */
function findReferencingNamespaces(databaseName) {
  if (!Array.isArray(allNamespaces)) return null;

  const referencing = [];
  for (const ns of allNamespaces) {
    const roles = NAMESPACE_DB_ROLE_FIELDS.filter(([field]) => ns[field] === databaseName).map(
      ([, label]) => label,
    );
    if (roles.length > 0) referencing.push({ name: ns.Name, roles });
  }
  return referencing;
}

function renderNamespaceUsage(databaseName) {
  dom.drawerUsage.replaceChildren();
  const referencing = findReferencingNamespaces(databaseName);

  if (referencing === null) {
    const note = document.createElement("p");
    note.className = "ns-hint";
    note.textContent = "Namespace usage is unavailable (could not load namespaces).";
    dom.drawerUsage.append(note);
    return;
  }

  if (referencing.length === 0) {
    const note = document.createElement("p");
    note.className = "ns-hint";
    note.textContent = "No namespaces reference this database.";
    dom.drawerUsage.append(note);
    return;
  }

  const chips = document.createElement("div");
  chips.className = "namespace-card__chips";
  for (const { name, roles } of referencing) {
    chips.append(makeChip(textOrPlaceholder(name), { title: `${name} — ${roles.join(", ")}` }));
  }
  dom.drawerUsage.append(chips);
}

/**
 * Reset Storage Info each time the drawer opens, so one database's info
 * is never shown for another.
 */
function resetDrawerInfo() {
  dom.drawerInfoLoading.hidden = true;
  dom.drawerInfoError.hidden = true;
  dom.drawerInfoFields.hidden = true;
  dom.drawerInfoFields.replaceChildren();
  dom.drawerInfoButton.disabled = false;
}

/** Render the DatabaseInfoResult fields (INFO_FIELDS) as IRIS returned them. */
function renderDatabaseInfo(info) {
  dom.drawerInfoFields.replaceChildren();
  for (const [label, key, kind] of INFO_FIELDS) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.className = kind === "mono" ? "info-list__value info-list__value--mono" : "info-list__value";
    dd.textContent = kind === "bool" ? formatBoolean(info[key]) : textOrPlaceholder(info[key]);

    row.append(dt, dd);
    dom.drawerInfoFields.append(row);
  }
  dom.drawerInfoFields.hidden = false;
}

/**
 * The only getDatabaseInfo() call, from the drawer's View Info button.
 * Read-only, so no confirmation needed.
 */
async function handleViewInfoClick() {
  if (!currentDrawerDirectory) return;

  dom.drawerInfoButton.disabled = true;
  dom.drawerInfoError.hidden = true;
  dom.drawerInfoFields.hidden = true;
  dom.drawerInfoLoading.hidden = false;

  try {
    const response = await IrisApi.getDatabaseInfo(currentDrawerDirectory, selectedInstanceId());
    const info = response && response.result;
    if (!info) {
      throw new ApiError("IRIS did not return the expected storage info.");
    }
    renderDatabaseInfo(info);
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not load storage info. The Command Center backend may be unreachable, or IRIS did not return a usable result."
        : "An unexpected error occurred while loading storage info.";
    dom.drawerInfoErrorText.textContent = message;
    dom.drawerInfoError.hidden = false;
  } finally {
    dom.drawerInfoLoading.hidden = true;
    dom.drawerInfoButton.disabled = false;
  }
}

/** Reset the Integrity Check section each time the drawer opens. */
function resetDrawerIntegrityCheck() {
  dom.drawerIntegrityLoading.hidden = true;
  dom.drawerIntegrityError.hidden = true;
  dom.drawerIntegrityFields.hidden = true;
  dom.drawerIntegrityFields.replaceChildren();
  dom.drawerIntegrityStateBadge.hidden = true;
  dom.drawerIntegrityConsoleLabel.hidden = true;
  dom.drawerIntegrityConsole.hidden = true;
  dom.drawerIntegrityConsole.textContent = "";
  dom.drawerIntegrityButton.disabled = false;
}

/**
 * Render the task envelope as returned:
 * - State goes in the badge next to the button so it's easy to see.
 * - Console is shown in full in a scrollable monospace box (hidden if
 *   empty).
 * - Failure Reason, Result and the times go in the info list. Result is
 *   shown with formatUnknownValue() since we don't know its shape.
 */
function renderIntegrityCheckResult(task) {
  dom.drawerIntegrityStateBadge.className = `status-badge ${taskStateBadgeVariant(task.State)}`;
  dom.drawerIntegrityStateBadge.textContent = textOrPlaceholder(task.State);
  dom.drawerIntegrityStateBadge.hidden = false;

  if (Array.isArray(task.Console) && task.Console.length > 0) {
    dom.drawerIntegrityConsole.textContent = task.Console.map((line) => formatUnknownValue(line)).join("\n");
    dom.drawerIntegrityConsoleLabel.hidden = false;
    dom.drawerIntegrityConsole.hidden = false;
  }

  dom.drawerIntegrityFields.replaceChildren();

  const rows = [];
  if (task.FailureReason) {
    rows.push(["Failure Reason", textOrPlaceholder(task.FailureReason)]);
  }
  rows.push(["Result", formatUnknownValue(task.Result)]);
  rows.push(["Time Queued", textOrPlaceholder(task.TimeQueued)]);
  rows.push(["Time Started", textOrPlaceholder(task.TimeStarted)]);
  rows.push(["Time Finished", textOrPlaceholder(task.TimeFinished)]);

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "info-list__row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.className = "info-list__value info-list__value--mono";
    dd.textContent = value;
    row.append(dt, dd);
    dom.drawerIntegrityFields.append(row);
  }
  dom.drawerIntegrityFields.hidden = false;
}

/**
 * The only checkDatabaseIntegrity() call, from the Run Integrity Check
 * button. Read-only, so no confirmation needed.
 */
async function handleRunIntegrityCheckClick() {
  if (!currentDrawerDirectory) return;

  dom.drawerIntegrityButton.disabled = true;
  dom.drawerIntegrityError.hidden = true;
  dom.drawerIntegrityFields.hidden = true;
  // Clear the previous run's badge and console too, so a failed second run
  // doesn't show the first run's "Finished" next to the error.
  dom.drawerIntegrityStateBadge.hidden = true;
  dom.drawerIntegrityConsoleLabel.hidden = true;
  dom.drawerIntegrityConsole.hidden = true;
  dom.drawerIntegrityConsole.textContent = "";
  dom.drawerIntegrityLoading.hidden = false;

  try {
    const task = await IrisApi.checkDatabaseIntegrity(currentDrawerDirectory, selectedInstanceId());
    if (!task || typeof task !== "object") {
      throw new ApiError("IRIS did not return the expected integrity-check result.");
    }
    renderIntegrityCheckResult(task);
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not run the integrity check. The Command Center backend may be unreachable, or IRIS did not return a usable result."
        : "An unexpected error occurred while running the integrity check.";
    dom.drawerIntegrityErrorText.textContent = message;
    dom.drawerIntegrityError.hidden = false;
  } finally {
    dom.drawerIntegrityLoading.hidden = true;
    dom.drawerIntegrityButton.disabled = false;
  }
}

// --- Issue resolution tracker ---
//
// When the drawer is opened from Resolve Issues, the Mount section shows the
// whole path. Every step's state comes from the existing flow: the detected
// issue, its recommended operation, the Check Mount dry run, the checkbox,
// the real mount's result and verification, and its execution trace.

const RESOLVE_STEPS = [
  ["detected", "Detected issue"],
  ["recommended", "Recommended fix"],
  ["check", "Dry-run check"],
  ["confirm", "Confirmation"],
  ["execute", "Execution"],
  ["verify", "Verification"],
  ["trace", "Trace"],
];
const STEP_STATE_LABELS = {
  done: "Done",
  current: "Next",
  running: "In progress",
  failed: "Failed",
  skipped: "Skipped",
  pending: "Pending",
};

// The issue being resolved in the open drawer, with each step's state and
// detail text; null when the drawer wasn't opened from Resolve Issues.
let resolving = null;

// Render the steps into `list`. `steps` maps step key -> { state, detail }.
function renderResolveSteps(list, steps, { compact = false } = {}) {
  list.replaceChildren();
  RESOLVE_STEPS.forEach(([key, label], index) => {
    const step = steps[key] || { state: "pending" };
    const item = document.createElement("li");
    item.className = "resolve-step";
    item.dataset.state = step.state;
    if (step.state === "current" || step.state === "running") item.setAttribute("aria-current", "step");

    const marker = document.createElement("span");
    marker.className = "resolve-step__marker";
    marker.setAttribute("aria-hidden", "true");
    marker.textContent = step.state === "done" ? "✓" : step.state === "failed" ? "!" : String(index + 1);

    const body = document.createElement("span");
    body.className = "resolve-step__body";
    const name = document.createElement("span");
    name.className = "resolve-step__label";
    name.textContent = label;
    const state = document.createElement("span");
    state.className = "resolve-step__state";
    state.textContent = STEP_STATE_LABELS[step.state] || step.state;
    body.append(name, state);
    if (!compact && step.detail) {
      const detail = document.createElement("span");
      detail.className = "resolve-step__detail";
      detail.textContent = step.detail;
      body.append(detail);
    }
    item.title = step.detail ? `${label}: ${step.detail}` : label;
    item.append(marker, body);
    list.append(item);
  });
}

function issueSteps(issue) {
  return {
    detected: { state: "done", detail: `${textOrPlaceholder(issue.database)} is ${textOrPlaceholder(issue.status)}` },
    recommended: { state: "done", detail: `${textOrPlaceholder(issue.recommended_operation)} (read-write)` },
    check: { state: "current", detail: "Run Check Mount below (dry run, nothing is changed)." },
  };
}

function setResolveStep(key, state, detail) {
  if (!resolving) return;
  resolving.steps[key] = { state, detail };
  renderResolveFlow();
}

function renderResolveFlow() {
  if (!resolving) {
    dom.resolveFlow.hidden = true;
    return;
  }
  dom.resolveTitle.textContent =
    `Resolving: ${textOrPlaceholder(resolving.issue.database)} is ${textOrPlaceholder(resolving.issue.status)}`;
  renderResolveSteps(dom.resolveSteps, resolving.steps);
  dom.resolveFlow.hidden = false;
}

function startResolution(issue) {
  resolving = { database: issue.database, issue, steps: issueSteps(issue) };
  renderResolveFlow();
}

// A changed request (e.g. the Read-only toggle) needs a new dry run.
function resetResolutionToCheck() {
  if (!resolving) return;
  const { detected, recommended } = resolving.steps;
  resolving.steps = {
    detected,
    recommended,
    check: { state: "current", detail: "Run Check Mount again for the changed request." },
  };
  renderResolveFlow();
}

// What was previewed with Check Mount. Set by a successful dry run,
// cleared on any change (drawer reopen, Read-only toggle). Confirm & Mount
// needs this and the checkbox.
let pendingMountFields = null;

function updateMountConfirmEnabled() {
  dom.drawerMountConfirmButton.disabled = !(pendingMountFields && dom.drawerMountAckCheckbox.checked);
}

/** Throw away the preview; Check Mount has to be run again. */
function clearMountPreview() {
  pendingMountFields = null;
  dom.drawerMountConfirm.hidden = true;
  dom.drawerMountAckCheckbox.checked = false;
  updateMountConfirmEnabled();
}

function resetDrawerMount() {
  clearMountPreview();
  dom.drawerMountReadOnly.checked = false;
  dom.drawerMountLoading.hidden = true;
  dom.drawerMountError.hidden = true;
  dom.drawerMountResult.hidden = true;
  dom.drawerMountResult.replaceChildren();
  dom.drawerMountCheckButton.disabled = false;
}

function showMountError(message) {
  dom.drawerMountErrorText.textContent = message;
  dom.drawerMountError.hidden = false;
}

/**
 * Preview: mountDatabase(fields, true, true). The dry run needs
 * confirmed=true to get past the executor and never sends the mount. A
 * rejection (e.g. "already mounted") is shown and no confirm button
 * appears.
 */
async function handleMountCheckClick() {
  const directory = currentDrawerDirectory;
  if (!directory) return;

  const fields = { Directory: directory, ReadOnly: dom.drawerMountReadOnly.checked };
  // Label the traces as part of this resolution (Observability shows it).
  if (resolving) fields.resolution_issue_type = resolving.issue.kind;
  clearMountPreview();
  dom.drawerMountError.hidden = true;
  dom.drawerMountResult.hidden = true;
  dom.drawerMountCheckButton.disabled = true;
  dom.drawerMountLoadingText.textContent = "Checking mount state…";
  dom.drawerMountLoading.hidden = false;
  setResolveStep("check", "running", "Checking the mount request against IRIS (dry run)…");

  try {
    const preview = await IrisApi.mountDatabase(fields, true, true);
    if (currentDrawerDirectory !== directory) return;  // drawer switched to another database
    const handlerResult = preview && preview.handler_result;
    if (preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
      pendingMountFields = fields;
      dom.drawerMountPreviewText.textContent = handlerResult.detail;
      dom.drawerMountConfirm.hidden = false;
      updateMountConfirmEnabled();
      setResolveStep("check", "done", handlerResult.detail);
      setResolveStep("confirm", "current", "Tick the checkbox, then Confirm & Mount.");
    } else {
      const message =
        (handlerResult && handlerResult.detail) ||
        preview.detail ||
        "This mount request could not be validated against IRIS.";
      showMountError(message);
      setResolveStep("check", "failed", message);
    }
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not reach the Command Center backend to check this database's mount state."
        : "An unexpected error occurred while checking this database's mount state.";
    showMountError(message);
    setResolveStep("check", "failed", message);
  } finally {
    dom.drawerMountLoading.hidden = true;
    dom.drawerMountCheckButton.disabled = false;
  }
}

/**
 * Status, detail, execution detail and verification as the backend
 * returned them (same as renderCreateResult()).
 */
function renderMountResult(result) {
  dom.drawerMountResult.replaceChildren();
  const rows = [
    ["Status", textOrPlaceholder(result.status)],
    ["Detail", textOrPlaceholder(result.detail)],
  ];
  if (result.handler_result) {
    rows.push(["Execution Detail", textOrPlaceholder(result.handler_result.detail)]);
  }
  if (result.verification) {
    rows.push(["Verification Status", textOrPlaceholder(result.verification.status)]);
    rows.push(["Verification Detail", textOrPlaceholder(result.verification.detail)]);
  }
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "info-list__row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.className = "info-list__value";
    dd.textContent = value;
    row.append(dt, dd);
    dom.drawerMountResult.append(row);
  }
  dom.drawerMountResult.hidden = false;
}

// Update Execution and Verification from the backend's OperationResult.
function trackMountResult(result) {
  if (!resolving) return;
  const execDetail = (result.handler_result && result.handler_result.detail) || result.detail || "";
  const verification = result.verification;
  if (result.status === "success" || result.status === "verification_failed") {
    setResolveStep("execute", "done", execDetail);
    setResolveStep(
      "verify",
      verification && verification.status === "verified" ? "done" : "failed",
      verification ? verification.detail : result.detail,
    );
  } else {
    setResolveStep("execute", "failed", execDetail || `Not executed (${textOrPlaceholder(result.status)}).`);
    setResolveStep("verify", "skipped", "Nothing to verify: the mount didn't run.");
  }
}

/**
 * The only place that sends a real mount. Only reachable from Confirm &
 * Mount, after a successful Check Mount and the checkbox.
 */
async function submitMount() {
  const fields = pendingMountFields;
  if (!fields) return;

  clearMountPreview();
  dom.drawerMountCheckButton.disabled = true;
  dom.drawerMountLoadingText.textContent = "Mounting database…";
  dom.drawerMountLoading.hidden = false;
  setResolveStep("confirm", "done", "Confirmed.");
  setResolveStep("execute", "running", "Sending database.mount to IRIS…");

  const startedMs = Date.now();
  try {
    const result = await IrisApi.mountDatabase(fields, true, false);
    renderMountResult(result);
    trackMountResult(result);
    const trace = await appendMountTraceLink(startedMs);
    if (trace) setResolveStep("trace", "done", "Recorded. Use “Open execution trace” below.");
    else setResolveStep("trace", "skipped", "No matching execution trace was found.");
    if (result.status === "success") {
      // Reload the database list instead of patching local state.
      await loadDatabases();
      refreshDrawerStatus();
    }
  } catch (err) {
    const failed = {
      status: "request_failed",
      detail:
        err instanceof ApiError
          ? "Could not reach the Command Center backend to mount this database."
          : "An unexpected error occurred while mounting this database.",
    };
    renderMountResult(failed);
    trackMountResult(failed);
    setResolveStep("trace", "skipped", "The request didn't reach the backend.");
  } finally {
    dom.drawerMountLoading.hidden = true;
    dom.drawerMountCheckButton.disabled = false;
  }
}

// --- Dismount (database.dismount) ---
//
// Same flow as Mount: "Check Dismount" is a dry run
// (dismountDatabase(fields, true, true)), and only submitDismount() sends
// the real request, after a valid preview and the checkbox. The backend
// refuses system and critical databases.

// What was previewed with Check Dismount. Cleared when the database changes.
let pendingDismountFields = null;

function updateDismountConfirmEnabled() {
  dom.drawerDismountConfirmButton.disabled = !(pendingDismountFields && dom.drawerDismountAckCheckbox.checked);
}

function clearDismountPreview() {
  pendingDismountFields = null;
  dom.drawerDismountConfirm.hidden = true;
  dom.drawerDismountAckCheckbox.checked = false;
  updateDismountConfirmEnabled();
}

function resetDrawerDismount() {
  clearDismountPreview();
  dom.drawerDismountLoading.hidden = true;
  dom.drawerDismountError.hidden = true;
  dom.drawerDismountResult.hidden = true;
  dom.drawerDismountResult.replaceChildren();
  dom.drawerDismountCheckButton.disabled = false;
}

function showDismountError(message) {
  dom.drawerDismountErrorText.textContent = message;
  dom.drawerDismountError.hidden = false;
}

async function handleDismountCheckClick() {
  const directory = currentDrawerDirectory;
  if (!directory) return;

  const fields = { Directory: directory };
  clearDismountPreview();
  dom.drawerDismountError.hidden = true;
  dom.drawerDismountResult.hidden = true;
  dom.drawerDismountCheckButton.disabled = true;
  dom.drawerDismountLoadingText.textContent = "Checking mount state…";
  dom.drawerDismountLoading.hidden = false;

  try {
    const preview = await IrisApi.dismountDatabase(fields, true, true);
    if (currentDrawerDirectory !== directory) return;  // drawer switched to another database
    const handlerResult = preview && preview.handler_result;
    if (preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
      pendingDismountFields = fields;
      dom.drawerDismountPreviewText.textContent = handlerResult.detail;
      dom.drawerDismountConfirm.hidden = false;
      updateDismountConfirmEnabled();
    } else {
      // Protected, already dismounted, unknown directory... shown as the backend
      // explained it.
      showDismountError(
        (handlerResult && handlerResult.detail) || preview.detail || "This dismount request could not be validated against IRIS.",
      );
    }
  } catch (err) {
    showDismountError(
      err instanceof ApiError
        ? "Could not reach the Command Center backend to check this database's mount state."
        : "An unexpected error occurred while checking this database's mount state.",
    );
  } finally {
    dom.drawerDismountLoading.hidden = true;
    dom.drawerDismountCheckButton.disabled = false;
  }
}

function renderDismountResult(result) {
  const rows = [
    ["Status", textOrPlaceholder(result.status)],
    ["Detail", textOrPlaceholder(result.detail)],
  ];
  if (result.handler_result) rows.push(["Execution Detail", textOrPlaceholder(result.handler_result.detail)]);
  if (result.verification) {
    rows.push(["Verification Status", textOrPlaceholder(result.verification.status)]);
    rows.push(["Verification Detail", textOrPlaceholder(result.verification.detail)]);
  }
  dom.drawerDismountResult.replaceChildren(
    ...rows.map(([label, value]) => {
      const row = document.createElement("div");
      row.className = "info-list__row";
      const dt = document.createElement("dt");
      dt.textContent = label;
      const dd = document.createElement("dd");
      dd.className = "info-list__value";
      dd.textContent = value;
      row.append(dt, dd);
      return row;
    }),
  );
  dom.drawerDismountResult.hidden = false;
}

/**
 * The only place that sends a real dismount. Only reachable from Confirm &
 * Dismount, after a successful preview and the checkbox.
 */
async function submitDismount() {
  const fields = pendingDismountFields;
  if (!fields) return;

  clearDismountPreview();
  dom.drawerDismountCheckButton.disabled = true;
  dom.drawerDismountLoadingText.textContent = "Dismounting database…";
  dom.drawerDismountLoading.hidden = false;

  try {
    const result = await IrisApi.dismountDatabase(fields, true, false);
    renderDismountResult(result);
    if (result.status === "success" || result.status === "verification_failed") {
      // Reload the database list instead of patching local state.
      await loadDatabases();
      refreshDrawerStatus();
    }
  } catch (err) {
    renderDismountResult({
      status: "request_failed",
      detail:
        err instanceof ApiError
          ? "Could not reach the Command Center backend to dismount this database."
          : "An unexpected error occurred while dismounting this database.",
    });
  } finally {
    dom.drawerDismountLoading.hidden = true;
    dom.drawerDismountCheckButton.disabled = false;
  }
}

// After a mount/dismount, show the reloaded status in the open drawer's
// header (the rest of the drawer keeps the operation's result).
function refreshDrawerStatus() {
  const db = allDatabases.find((entry) => entry.Directory === currentDrawerDirectory);
  if (!db || dom.drawer.hidden) return;
  dom.drawerStatusBadge.className = `status-badge ${statusBadgeVariant(db.Status)}`;
  dom.drawerStatusBadge.textContent = textOrPlaceholder(db.Status);
}

function openDrawer(databaseName) {
  const db = allDatabases.find((entry) => entry.Name === databaseName);
  if (!db) return;

  dom.drawerTitle.textContent = textOrPlaceholder(db.Name);
  dom.drawerStatusBadge.className = `status-badge ${statusBadgeVariant(db.Status)}`;
  dom.drawerStatusBadge.textContent = textOrPlaceholder(db.Status);

  dom.drawerFields.replaceChildren();
  for (const [label, key, kind] of DRAWER_FIELDS) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.className = kind === "mono" ? "info-list__value info-list__value--mono" : "info-list__value";
    dd.textContent = kind === "bool" ? formatBoolean(db[key]) : textOrPlaceholder(db[key]);

    row.append(dt, dd);
    dom.drawerFields.append(row);
  }

  renderNamespaceUsage(db.Name);
  currentDrawerDirectory = db.Directory;
  resetDrawerInfo();
  resetDrawerIntegrityCheck();
  resetDrawerMount();
  resetDrawerDismount();
  resolving = null;
  renderResolveFlow();

  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawerClose.focus();
}

function closeDrawer() {
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
  resolving = null;
}

function renderDatabases(databases) {
  renderOverview(databases);

  if (!Array.isArray(databases) || databases.length === 0) {
    dom.content.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    allDatabases = [];
    closeDrawer();
    return;
  }

  allDatabases = databases;
  dom.empty.hidden = true;
  dom.content.hidden = false;
  dom.countLabel.textContent = `${databases.length} database${databases.length === 1 ? "" : "s"}`;

  renderSummary(databases);
  renderDatabaseCards(databases);
}

/**
 * Load namespaces for the Namespace Usage section. Doesn't throw: on
 * failure `allNamespaces` stays null and the section says unavailable.
 */
async function loadNamespacesForUsage() {
  try {
    const response = await IrisApi.getNamespaces(selectedInstanceId());
    allNamespaces = response && Array.isArray(response.result) ? response.result : null;
  } catch {
    allNamespaces = null;
  }
}

/**
 * Load GET /api/iris/databases and render it, plus the namespaces for the
 * drawer.
 */
export async function loadDatabases() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getDatabases(selectedInstanceId());
  } catch (err) {
    // ApiError messages are already safe to show (see api.js).
    const message =
      err instanceof ApiError
        ? "Could not load database information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading database information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderDatabases(null);
    setLoading(false);
    return;
  }

  const databases = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (databases === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected database information.");
    renderDatabases(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // IRIS returned warnings in status.errors.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  await loadNamespacesForUsage();

  renderDatabases(databases);
  setLoading(false);
  loadIssues();
}

// --- Resolve Issues: dismounted databases ---
//
// Issues come from GET /api/iris/issues (the backend skips system and
// mirrored databases). "Resolve Issue" opens the database's drawer at the
// Mount section with the resolution tracker, so the normal flow runs:
// detected issue -> recommended fix -> Check Mount (dry run) -> confirm ->
// Confirm & Mount -> verification -> trace.

function hint(text) {
  const p = document.createElement("p");
  p.className = "ns-hint";
  p.textContent = text;
  return p;
}

// "Why this fix?": the issue's fields plus the rules it matched (configured,
// not mounted, not a system database, not mirrored).
function whyThisFix(issue) {
  const details = document.createElement("details");
  details.className = "db-issue__why";
  const summary = document.createElement("summary");
  summary.textContent = "Why this fix?";
  const list = document.createElement("dl");
  list.className = "info-list";
  const yesNo = (value) => (value === true ? "Yes" : value === false ? "No" : PLACEHOLDER);
  for (const [label, value] of [
    ["Database", textOrPlaceholder(issue.database)],
    ["Mounted status", textOrPlaceholder(issue.status)],
    ["Mount Required", yesNo(issue.mount_required)],
    ["Mirrored", "No (mirrored databases are never reported)"],
    [
      "Why database.mount",
      `IRIS reports it "${textOrPlaceholder(issue.status)}"; it is a configured database, not an IRIS system ` +
        "database and not mirrored — so mounting it read-write through database.mount (with its own dry run, " +
        "confirmation and verification) restores access to its data.",
    ],
  ]) {
    const row = document.createElement("div");
    row.className = "info-list__row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.className = "info-list__value";
    dd.textContent = value;
    row.append(dt, dd);
    list.append(row);
  }
  details.append(summary, list);
  return details;
}

async function loadIssues() {
  if (selectedInstanceId()) return;  // issue resolution is Primary-only (the panel is hidden)
  let issues;
  try {
    const response = await IrisApi.getIssues();
    // Only database issues are resolved here; others resolve on their own page.
    issues = Array.isArray(response?.issues)
      ? response.issues.filter((issue) => issue.kind === "database_dismounted")
      : null;
  } catch {
    issues = null;
  }
  if (issues === null) {
    dom.issuesBody.replaceChildren(hint("Could not check for actionable issues right now."));
    return;
  }
  if (issues.length === 0) {
    dom.issuesBody.replaceChildren(hint("No actionable issues detected."));
    return;
  }
  dom.issuesBody.replaceChildren(
    ...issues.map((issue) => {
      const item = document.createElement("div");
      item.className = "db-issue";
      const text = document.createElement("div");
      const title = document.createElement("p");
      title.className = "db-issue__title";
      title.textContent = `Database ${textOrPlaceholder(issue.database)} is ${textOrPlaceholder(issue.status)}`;
      const recommended = document.createElement("p");
      recommended.className = "db-issue__fix";
      recommended.textContent = `Recommended: ${issue.recommended_operation} (read-write)`;
      const path = document.createElement("ol");
      path.className = "resolve-steps resolve-steps--compact";
      path.setAttribute("aria-label", "Resolution steps");
      renderResolveSteps(path, { ...issueSteps(issue), check: { state: "pending" } }, { compact: true });
      text.append(title, hint(issue.explanation), recommended, path, whyThisFix(issue));
      item.append(text);
      if (allDatabases.some((db) => db.Name === issue.database)) {
        const button = document.createElement("button");
        button.className = "btn btn--primary";
        button.type = "button";
        button.textContent = "Resolve Issue";
        button.addEventListener("click", () => {
          openDrawer(issue.database);
          startResolution(issue);
          dom.resolveFlow.scrollIntoView({ block: "center" });
          dom.drawerMountCheckButton.focus();
        });
        item.append(button);
      }
      return item;
    }),
  );
}

/**
 * After a real mount: link its execution trace (the newest database.mount
 * trace since `sinceMs`). Returns the trace, or null if none was found.
 */
async function appendMountTraceLink(sinceMs) {
  if (!onOpenTrace) return null;
  try {
    const traces = (await IrisApi.getExecutionTraces())?.traces || [];
    const trace = traces.find(
      (t) => t.operation_name === "database.mount" && new Date(t.start_time).getTime() >= sinceMs - 1000,
    );
    if (!trace) return null;
    const button = document.createElement("button");
    button.className = "dash-panel__link";
    button.type = "button";
    button.textContent = "Open execution trace →";
    button.addEventListener("click", () => {
      closeDrawer();
      onOpenTrace(trace.trace_id);
    });
    dom.drawerMountResult.append(button);
    return trace;
  } catch {
    // The trace link is just a shortcut; the mount result stands on its own.
    return null;
  }
}

// --- New Database wizard: Configure -> Review (dry run) -> confirm ->
// create -> result ---

function setWizardStep(label) {
  createDom.stepLabel.textContent = label;
}

function resetCreateWizard() {
  createDom.form.reset();
  createDom.form.hidden = false;
  createDom.error.hidden = true;

  createDom.review.hidden = true;
  createDom.previewLoading.hidden = true;
  createDom.reviewContent.hidden = true;
  createDom.previewError.hidden = true;
  createDom.ackCheckbox.checked = false;
  createDom.confirmButton.disabled = true;
  reviewIsValid = false;

  createDom.executingState.hidden = true;

  createDom.resultSection.hidden = true;
  createDom.retryButton.hidden = true;

  pendingCreateFields = null;
  setWizardStep("Step 1 of 2 · Configure");
}

function openCreateDrawer() {
  resetCreateWizard();
  createDom.backdrop.hidden = false;
  createDom.drawer.hidden = false;
  createDom.directoryInput.focus();
}

function closeCreateDrawer() {
  createDom.backdrop.hidden = true;
  createDom.drawer.hidden = true;
}

function showCreateError(message) {
  createDom.errorText.textContent = message;
  createDom.error.hidden = false;
}

function collectCreateFields() {
  const directory = createDom.directoryInput.value.trim();
  const resourceName = createDom.resourceNameInput.value.trim();
  const sizeRaw = createDom.sizeInput.value.trim();

  return {
    Directory: directory,
    ResourceName: resourceName || null,
    Size: sizeRaw === "" ? null : Number(sizeRaw),
    GlobalJournalState: createDom.globalJournalStateInput.checked,
    Encrypted: createDom.encryptedInput.checked,
  };
}

/**
 * Quick checks before the dry run: Directory is required and well formed,
 * and doesn't collide (by directory or derived name) with a database we
 * already loaded. Same logic as the backend's _validate(); the backend
 * still has the final say.
 */
function validateCreateFields(fields) {
  if (!fields.Directory) {
    return "Directory is required.";
  }
  if (!fields.Directory.startsWith("/")) {
    return 'Directory must be an absolute path (starting with "/").';
  }
  if (fields.Directory.split("/").includes("..")) {
    return 'Directory must not contain ".." path segments.';
  }
  if (!DIRECTORY_PATTERN.test(fields.Directory)) {
    return "Directory contains invalid characters or is too long.";
  }
  if (fields.Size !== null && (!Number.isInteger(fields.Size) || fields.Size < 0)) {
    return "Size must be zero or a positive integer when provided.";
  }

  const requestedDirectory = normalizeDirectory(fields.Directory);
  const existingDirectoryMatch = allDatabases.find(
    (db) => normalizeDirectory(db.Directory) === requestedDirectory,
  );
  if (existingDirectoryMatch) {
    return `A database already exists at this directory (${existingDirectoryMatch.Name}).`;
  }

  const expectedName = deriveExpectedName(fields.Directory);
  if (expectedName) {
    const existingNameMatch = allDatabases.find((db) => db.Name.toUpperCase() === expectedName);
    if (existingNameMatch) {
      return (
        `A database named "${existingNameMatch.Name}" already exists, and this directory ` +
        "would be expected to resolve to that same name."
      );
    }
  }

  return null;
}

function updateConfirmButtonEnabled() {
  createDom.confirmButton.disabled = !(reviewIsValid && createDom.ackCheckbox.checked);
}

/**
 * Render the Review step: what will be sent, plus what the dry run found.
 * If the dry run rejects it, show the reason and keep Confirm & Create
 * disabled.
 */
function renderReviewPreview(previewResult) {
  createDom.reviewContent.hidden = false;
  createDom.summaryList.replaceChildren();

  const rows = [
    ["Directory", pendingCreateFields.Directory],
    ["Resource Name", pendingCreateFields.ResourceName],
    ["Size", pendingCreateFields.Size],
    ["Global Journal State", pendingCreateFields.GlobalJournalState ? "Enabled" : "Disabled"],
    ["Encryption", pendingCreateFields.Encrypted ? "Enabled" : "Disabled"],
  ];
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "info-list__row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.className = "info-list__value";
    dd.textContent = textOrPlaceholder(value);
    row.append(dt, dd);
    createDom.summaryList.append(row);
  }

  const outcome = previewResult.handler_result && previewResult.handler_result.outcome;
  reviewIsValid = previewResult.status === "dry_run" && outcome === "success";

  if (reviewIsValid) {
    createDom.previewError.hidden = true;
  } else {
    const detail =
      (previewResult.handler_result && previewResult.handler_result.detail) ||
      previewResult.detail ||
      "This request could not be validated against IRIS.";
    createDom.previewErrorText.textContent = detail;
    createDom.previewError.hidden = false;
  }

  updateConfirmButtonEnabled();
}

/**
 * Submitting the form only validates and moves to Review, which runs a dry
 * run (createDatabase(fields, true, true)) for the preview. Nothing is
 * created here.
 */
async function handleCreateNext(event) {
  event.preventDefault();
  createDom.error.hidden = true;

  const fields = collectCreateFields();
  const validationError = validateCreateFields(fields);
  if (validationError) {
    showCreateError(validationError);
    return;
  }

  pendingCreateFields = fields;
  createDom.form.hidden = true;
  createDom.review.hidden = false;
  createDom.reviewContent.hidden = true;
  createDom.previewLoading.hidden = false;
  setWizardStep("Step 2 of 2 · Review");

  try {
    const previewResult = await IrisApi.createDatabase(fields, true, true);
    renderReviewPreview(previewResult);
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not reach the Command Center backend to validate this request."
        : "An unexpected error occurred while validating this request.";
    renderReviewPreview({ status: "request_failed", detail: message });
  } finally {
    createDom.previewLoading.hidden = true;
  }
}

function backToConfigureStep() {
  createDom.review.hidden = true;
  createDom.form.hidden = false;
  setWizardStep("Step 1 of 2 · Configure");
}

/**
 * Show what the backend returned: status, directory, detail, execution
 * detail and verification, as plain text. On failure there's an "Edit and
 * Retry" button (no automatic retry) and the fields keep what was
 * entered.
 */
function renderCreateResult(result) {
  createDom.resultList.replaceChildren();

  const isSuccess = result.status === "success";
  const directory =
    (result.handler_result && result.handler_result.data && result.handler_result.data.directory) ||
    (pendingCreateFields && pendingCreateFields.Directory);

  const rows = [["Status", textOrPlaceholder(result.status)]];
  if (directory) rows.push(["Directory", directory]);
  rows.push(["Detail", textOrPlaceholder(result.detail)]);
  if (result.handler_result) {
    rows.push(["Execution Detail", textOrPlaceholder(result.handler_result.detail)]);
  }
  if (result.verification) {
    rows.push(["Verification Status", textOrPlaceholder(result.verification.status)]);
    rows.push(["Verification Detail", textOrPlaceholder(result.verification.detail)]);
  }

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "info-list__row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.className = "info-list__value";
    dd.textContent = value;
    row.append(dt, dd);
    createDom.resultList.append(row);
  }

  createDom.review.hidden = true;
  createDom.resultSection.hidden = false;
  createDom.retryButton.hidden = isSuccess;
  setWizardStep(isSuccess ? "Complete" : "Result");
}

/**
 * The only real createDatabase call, from the Confirm & Create button.
 * `confirmed` is true and `dryRun` false because you only get here after a
 * validated preview, the checkbox and clicking Confirm.
 */
async function submitCreate() {
  if (!pendingCreateFields) return;

  createDom.confirmButton.disabled = true;
  createDom.backButton.disabled = true;
  createDom.review.hidden = true;
  createDom.executingState.hidden = false;

  try {
    const result = await IrisApi.createDatabase(pendingCreateFields, true, false);
    renderCreateResult(result);
    if (result.status === "success") {
      // Reload the page so the new database shows up.
      await loadDatabases();
    }
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not reach the Command Center backend to create this database."
        : "An unexpected error occurred while creating this database.";
    renderCreateResult({ status: "request_failed", detail: message });
  } finally {
    createDom.executingState.hidden = true;
    createDom.confirmButton.disabled = false;
    createDom.backButton.disabled = false;
  }
}

export function initDatabasesControls({ onOpenTrace: openTrace } = {}) {
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;
  dom.refreshButton.addEventListener("click", () => {
    loadDatabases();
  });
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });

  // One delegated listener for all database cards (same as Namespaces).
  dom.cardGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".namespace-card");
    if (card) openDrawer(card.dataset.database);
  });
  dom.cardGrid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".namespace-card");
    if (!card) return;
    event.preventDefault();
    openDrawer(card.dataset.database);
  });

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  dom.drawerInfoButton.addEventListener("click", () => {
    handleViewInfoClick();
  });
  dom.drawerIntegrityButton.addEventListener("click", () => {
    handleRunIntegrityCheckClick();
  });
  dom.drawerMountCheckButton.addEventListener("click", () => {
    handleMountCheckClick();
  });
  dom.drawerMountReadOnly.addEventListener("change", () => {
    clearMountPreview();
    resetResolutionToCheck();
  });
  dom.drawerMountAckCheckbox.addEventListener("change", updateMountConfirmEnabled);
  dom.drawerMountConfirmButton.addEventListener("click", () => {
    submitMount();
  });
  dom.drawerDismountCheckButton.addEventListener("click", () => {
    handleDismountCheckClick();
  });
  dom.drawerDismountAckCheckbox.addEventListener("change", updateDismountConfirmEnabled);
  dom.drawerDismountConfirmButton.addEventListener("click", () => {
    submitDismount();
  });

  createDom.openButton.addEventListener("click", openCreateDrawer);
  createDom.close.addEventListener("click", closeCreateDrawer);
  createDom.backdrop.addEventListener("click", closeCreateDrawer);
  createDom.form.addEventListener("submit", handleCreateNext);
  createDom.backButton.addEventListener("click", backToConfigureStep);
  createDom.ackCheckbox.addEventListener("change", updateConfirmButtonEnabled);
  createDom.confirmButton.addEventListener("click", () => {
    submitCreate();
  });
  createDom.retryButton.addEventListener("click", backToConfigureStep);
  createDom.doneButton.addEventListener("click", closeCreateDrawer);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!dom.drawer.hidden) closeDrawer();
    if (!createDom.drawer.hidden) closeCreateDrawer();
  });
}
