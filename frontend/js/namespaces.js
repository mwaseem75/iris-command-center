// Namespaces page: summary cards, a card per namespace, a database-sharing
// view and a detail drawer, all from GET /api/iris/namespaces.
//
// The "New Namespace" wizard is the one change this page can make
// (namespace.create via IrisApi.createNamespace). It goes Configure ->
// Review -> confirm; the real request is only sent from Confirm & Create
// (submitCreate). The backend decides whether it's allowed.
//
// The Review step also calls createNamespace with dryRun=true to get a
// preview validated by the server. It has to send confirmed=true too,
// because the executor checks confirmation before looking at dry_run. The
// dry run never sends the PUT/POST.
//
// The wizard's database dropdowns are filled from GET /api/iris/databases.
//
// The cards show the NamespaceEntry fields (Name, Globals, Routines,
// SysGlobals, SysRoutines, Library, TempGlobals). There's no
// "interoperability enabled" field in the response, so there's no card for
// it. The database counts and colors are worked out from those fields.

import { IrisApi, ApiError } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—";  // shown for empty values

const dom = {
  loadingState: document.getElementById("namespaces-loading-state"),
  errorBanner: document.getElementById("namespaces-error-banner"),
  errorBannerText: document.getElementById("namespaces-error-banner-text"),
  refreshButton: document.getElementById("namespaces-refresh-button"),
  backButton: document.getElementById("namespaces-back-button"),
  connectionStatus: document.getElementById("namespaces-connection-status"),
  connectionStatusLabel: document.getElementById("namespaces-connection-status-label"),
  connectionDetail: document.getElementById("namespaces-connection-detail"),
  countLabel: document.getElementById("namespaces-count"),
  empty: document.getElementById("namespaces-empty"),
  content: document.getElementById("namespaces-content"),
  summaryCount: document.getElementById("namespaces-summary-count"),
  summaryGlobals: document.getElementById("namespaces-summary-globals"),
  summaryRoutines: document.getElementById("namespaces-summary-routines"),
  cardGrid: document.getElementById("namespaces-card-grid"),
  topology: document.getElementById("namespaces-topology"),
  drawerBackdrop: document.getElementById("namespaces-drawer-backdrop"),
  drawer: document.getElementById("namespaces-drawer"),
  drawerTitle: document.getElementById("namespaces-drawer-title"),
  drawerBadge: document.getElementById("namespaces-drawer-badge"),
  drawerFields: document.getElementById("namespaces-drawer-fields"),
  drawerTopology: document.getElementById("namespaces-drawer-topology"),
  drawerClose: document.getElementById("namespaces-drawer-close"),
};

// The New Namespace wizard. It's a separate drawer from the detail drawer
// above, so the two never share DOM state.
const createDom = {
  openButton: document.getElementById("namespaces-create-button"),
  backdrop: document.getElementById("namespace-create-backdrop"),
  drawer: document.getElementById("namespace-create-drawer"),
  close: document.getElementById("namespace-create-close"),
  stepLabel: document.getElementById("namespace-create-step-label"),

  // Step 1: Configure
  form: document.getElementById("namespace-create-form"),
  nameInput: document.getElementById("namespace-create-name"),
  globalsSelect: document.getElementById("namespace-create-globals"),
  routinesSelect: document.getElementById("namespace-create-routines"),
  tempGlobalsSelect: document.getElementById("namespace-create-temp-globals"),
  interopInput: document.getElementById("namespace-create-interop"),
  error: document.getElementById("namespace-create-error"),
  errorText: document.getElementById("namespace-create-error-text"),

  // Step 2: Review
  review: document.getElementById("namespace-create-review"),
  previewLoading: document.getElementById("namespace-create-preview-loading"),
  reviewContent: document.getElementById("namespace-create-review-content"),
  summaryList: document.getElementById("namespace-create-summary-list"),
  previewError: document.getElementById("namespace-create-preview-error"),
  previewErrorText: document.getElementById("namespace-create-preview-error-text"),
  ackCheckbox: document.getElementById("namespace-create-ack-checkbox"),
  confirmButton: document.getElementById("namespace-create-confirm-button"),
  backButton: document.getElementById("namespace-create-back-button"),

  // Step 3: Executing
  executingState: document.getElementById("namespace-create-executing-state"),

  // Step 4: Result
  resultSection: document.getElementById("namespace-create-result"),
  resultList: document.getElementById("namespace-create-result-list"),
  retryButton: document.getElementById("namespace-create-retry-button"),
  doneButton: document.getElementById("namespace-create-done-button"),
};

// What the user configured and reviewed. Set by handleCreateNext(), read by
// renderReviewPreview()/submitCreate(). `confirmed: true` is only sent from
// submitCreate(), i.e. the Confirm & Create button.
let pendingCreateFields = null;

// Whether the Review dry run said the request is OK. Confirm & Create
// stays disabled unless this and the checkbox are both true.
let reviewIsValid = false;

// Same name check as NamespaceCreateParameters on the backend, just to
// catch obvious typos early. The dry run and the real request are still
// validated by the backend.
const NAMESPACE_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,30}$/;

// The last fetched list; the drawer looks namespaces up here by name.
let allNamespaces = [];

// Color map from the last render, so the drawer colors databases the same
// way as the cards and the sharing view.
let currentColorMap = new Map();

// One color per database name, used on the cards and the sharing view so
// the same database always has the same color. Uses the chart palette
// (--color-chart-1..6) and cycles after that.
const CHIP_COLORS = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
];

// [label, NamespaceEntry field] in model order.
const DRAWER_FIELDS = [
  ["Name", "Name"],
  ["Globals Database", "Globals"],
  ["Routines Database", "Routines"],
  ["System Globals Database", "SysGlobals"],
  ["System Routines Database", "SysRoutines"],
  ["Library Database", "Library"],
  ["Temp Globals Database", "TempGlobals"],
];

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

/**
 * System namespaces (%SYS, %ALL, ...) are the ones starting with %. There's
 * no separate flag for it.
 */
function isSystemNamespace(name) {
  return typeof name === "string" && name.startsWith("%");
}

const SYSTEM_NAMESPACE_TITLE =
  "System namespace — its name starts with %, IRIS's own convention for system-reserved namespaces.";

/**
 * Give each Globals/Routines/TempGlobals database the next color in
 * CHIP_COLORS, in the order they first appear.
 */
function buildDbColorMap(namespaces) {
  const map = new Map();
  for (const ns of namespaces) {
    for (const value of [ns.Globals, ns.Routines, ns.TempGlobals]) {
      if (typeof value === "string" && value && !map.has(value)) {
        map.set(value, CHIP_COLORS[map.size % CHIP_COLORS.length]);
      }
    }
  }
  return map;
}

/**
 * Colored pill for a database. `label` is the full text (e.g. "Globals:
 * IRISSYS" on a card, just "IRISSYS" in the sharing view).
 */
function makeDbChip(label, dbName, colorMap) {
  const chip = document.createElement("span");
  chip.className = "db-chip";
  chip.title = label;

  const dot = document.createElement("span");
  dot.className = "db-chip__dot";
  dot.style.background = colorMap.get(dbName) || "var(--color-text-faint)";

  const text = document.createElement("span");
  text.className = "db-chip__label";
  text.textContent = label;

  chip.append(dot, text);
  return chip;
}

function renderSummary(namespaces) {
  dom.summaryCount.textContent = String(namespaces.length);

  const globalsDbs = new Set(namespaces.map((ns) => ns.Globals).filter(Boolean));
  const routinesDbs = new Set(namespaces.map((ns) => ns.Routines).filter(Boolean));
  dom.summaryGlobals.textContent = String(globalsDbs.size);
  dom.summaryRoutines.textContent = String(routinesDbs.size);
}

/**
 * A "System" badge for %-prefixed namespaces (see isSystemNamespace()).
 * Returns null otherwise.
 */
function makeSystemBadge(name) {
  if (!isSystemNamespace(name)) return null;
  const badge = document.createElement("span");
  badge.className = "status-badge status-badge--neutral";
  badge.textContent = "System";
  badge.title = SYSTEM_NAMESPACE_TITLE;
  return badge;
}

function renderNamespaceCards(namespaces, colorMap) {
  dom.cardGrid.replaceChildren();

  for (const ns of namespaces) {
    const card = document.createElement("article");
    card.className = "namespace-card";
    card.dataset.namespace = ns.Name;
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.setAttribute("aria-label", `View details for namespace ${textOrPlaceholder(ns.Name)}`);

    const header = document.createElement("div");
    header.className = "namespace-card__header";
    const name = document.createElement("h4");
    name.className = "namespace-card__name";
    name.textContent = textOrPlaceholder(ns.Name);
    header.append(name);
    const badge = makeSystemBadge(ns.Name);
    if (badge) header.append(badge);

    const chips = document.createElement("div");
    chips.className = "namespace-card__chips";
    chips.append(
      makeDbChip(`Globals: ${textOrPlaceholder(ns.Globals)}`, ns.Globals, colorMap),
      makeDbChip(`Routines: ${textOrPlaceholder(ns.Routines)}`, ns.Routines, colorMap),
    );

    const link = document.createElement("span");
    link.className = "stat-card__link";
    link.textContent = "View details →";

    card.append(header, chips, link);
    dom.cardGrid.append(card);
  }
}

/**
 * Header row (Namespace / Globals DB / Routines DB / Temp Globals DB),
 * shared by the page's sharing view and the drawer's mini version.
 */
function buildTopologyHeader() {
  const header = document.createElement("div");
  header.className = "topology-header";
  for (const label of ["Namespace", "Globals DB", "Routines DB", "Temp Globals DB"]) {
    const span = document.createElement("span");
    span.textContent = label;
    if (label === "Namespace") span.style.minWidth = "68px";
    header.append(span);
  }
  return header;
}

/**
 * One row: Namespace -> Globals -> Routines -> Temp Globals. Shared by the
 * sharing view and the drawer.
 */
function buildTopologyRow(ns, colorMap) {
  const row = document.createElement("div");
  row.className = "topology-row";

  const name = document.createElement("span");
  name.className = "topology-row__name";
  name.textContent = textOrPlaceholder(ns.Name);
  row.append(name);

  for (const value of [ns.Globals, ns.Routines, ns.TempGlobals]) {
    const arrow = document.createElement("span");
    arrow.className = "topology-arrow";
    arrow.textContent = "→";
    arrow.setAttribute("aria-hidden", "true");
    row.append(arrow, makeDbChip(textOrPlaceholder(value), value, colorMap));
  }

  return row;
}

function renderTopology(namespaces, colorMap) {
  dom.topology.replaceChildren();
  dom.topology.append(buildTopologyHeader());
  for (const ns of namespaces) {
    dom.topology.append(buildTopologyRow(ns, colorMap));
  }
}

// --- New Namespace wizard: Configure -> Review (dry run) -> confirm ->
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

/**
 * Build a <select>'s options from the database list. `includeEmpty` adds a
 * "use the IRIS default" option (for Temp Globals).
 */
function fillDatabaseSelect(selectEl, names, placeholder, includeEmpty) {
  selectEl.replaceChildren();

  const placeholderOption = document.createElement("option");
  placeholderOption.value = "";
  placeholderOption.textContent = placeholder;
  if (!includeEmpty) {
    placeholderOption.disabled = true;
    placeholderOption.selected = true;
  }
  selectEl.append(placeholderOption);

  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    selectEl.append(option);
  }
}

/**
 * Fill the Globals/Routines/Temp Globals dropdowns from GET
 * /api/iris/databases. Done every time the wizard opens so the list is
 * current.
 */
async function populateDatabaseSelects() {
  const loadingLabel = "Loading databases…";
  fillDatabaseSelect(createDom.globalsSelect, [], loadingLabel, false);
  fillDatabaseSelect(createDom.routinesSelect, [], loadingLabel, false);
  fillDatabaseSelect(createDom.tempGlobalsSelect, [], loadingLabel, true);

  let names = [];
  let loadError = false;
  try {
    const response = await IrisApi.getDatabases(selectedInstanceId());
    names = Array.isArray(response && response.result)
      ? response.result.map((db) => db && db.Name).filter((name) => typeof name === "string" && name)
      : [];
  } catch {
    loadError = true;
  }

  if (loadError || names.length === 0) {
    const message = loadError ? "Could not load databases." : "No databases found.";
    fillDatabaseSelect(createDom.globalsSelect, [], message, false);
    fillDatabaseSelect(createDom.routinesSelect, [], message, false);
    fillDatabaseSelect(createDom.tempGlobalsSelect, [], message, true);
    return;
  }

  fillDatabaseSelect(createDom.globalsSelect, names, "Select a database…", false);
  fillDatabaseSelect(createDom.routinesSelect, names, "Select a database…", false);
  fillDatabaseSelect(createDom.tempGlobalsSelect, names, "IRIS default", true);
}

function openCreateDrawer() {
  resetCreateWizard();
  createDom.backdrop.hidden = false;
  createDom.drawer.hidden = false;
  createDom.nameInput.focus();
  populateDatabaseSelects();
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
  return {
    Name: createDom.nameInput.value.trim(),
    Globals: createDom.globalsSelect.value,
    Routines: createDom.routinesSelect.value,
    TempGlobals: createDom.tempGlobalsSelect.value || null,
    Interop: createDom.interopInput.checked,
  };
}

/**
 * Quick checks before the dry run: required fields, no % prefix, and the
 * name format (NAMESPACE_NAME_PATTERN). Returns a message, or null if
 * nothing's obviously wrong. The backend still has the final say.
 */
function validateCreateFields(fields) {
  if (!fields.Name || !fields.Globals || !fields.Routines) {
    return "Name, Globals Database, and Routines Database are all required.";
  }
  if (fields.Name.startsWith("%")) {
    return "System-namespace names (starting with %) cannot be created through this operation.";
  }
  if (!NAMESPACE_NAME_PATTERN.test(fields.Name)) {
    return "Name must start with a letter and contain only letters, digits, and underscores (max 31 characters).";
  }
  return null;
}

function updateConfirmButtonEnabled() {
  createDom.confirmButton.disabled = !(reviewIsValid && createDom.ackCheckbox.checked);
}

/**
 * Render the Review step: what will be sent, plus what the dry run found.
 * If the dry run rejects it (e.g. the namespace exists), show the reason
 * and keep Confirm & Create disabled.
 */
function renderReviewPreview(previewResult) {
  createDom.reviewContent.hidden = false;
  createDom.summaryList.replaceChildren();

  const rows = [
    ["Name", pendingCreateFields.Name],
    ["Globals Database", pendingCreateFields.Globals],
    ["Routines Database", pendingCreateFields.Routines],
    ["Temp Globals Database", pendingCreateFields.TempGlobals || "IRIS default"],
    ["Interoperability", pendingCreateFields.Interop ? "Enabled after creation" : "Not enabled"],
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
 * Submitting the form only validates and moves to Review, which runs a
 * dry run (createNamespace(fields, true, true)) for the preview. Nothing is
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
    const previewResult = await IrisApi.createNamespace(fields, true, true);
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
 * Show what the backend returned: status, namespace, detail, execution
 * detail and verification. On failure there's an "Edit and Retry" button
 * (no automatic retry) and the fields keep what was entered.
 */
function renderCreateResult(result) {
  createDom.resultList.replaceChildren();

  const isSuccess = result.status === "success";
  const createdName =
    (result.handler_result && result.handler_result.data && result.handler_result.data.name) ||
    (pendingCreateFields && pendingCreateFields.Name);

  const rows = [["Status", textOrPlaceholder(result.status)]];
  if (createdName) rows.push(["Namespace", createdName]);
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
 * The only real createNamespace call, from the Confirm & Create button.
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
    const result = await IrisApi.createNamespace(pendingCreateFields, true, false);
    renderCreateResult(result);
    if (result.status === "success") {
      // Reload the page so the new namespace shows up everywhere.
      await loadNamespaces();
    }
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not reach the Command Center backend to create this namespace."
        : "An unexpected error occurred while creating this namespace.";
    renderCreateResult({ status: "request_failed", detail: message });
  } finally {
    createDom.executingState.hidden = true;
    createDom.confirmButton.disabled = false;
    createDom.backButton.disabled = false;
  }
}

function openDrawer(namespaceName) {
  const ns = allNamespaces.find((entry) => entry.Name === namespaceName);
  if (!ns) return;

  dom.drawerTitle.textContent = textOrPlaceholder(ns.Name);

  if (isSystemNamespace(ns.Name)) {
    dom.drawerBadge.hidden = false;
    dom.drawerBadge.title = SYSTEM_NAMESPACE_TITLE;
  } else {
    dom.drawerBadge.hidden = true;
  }

  dom.drawerFields.replaceChildren();
  for (const [label, key] of DRAWER_FIELDS) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.className = "info-list__value info-list__value--mono";
    dd.textContent = textOrPlaceholder(ns[key]);

    row.append(dt, dd);
    dom.drawerFields.append(row);
  }

  // Same layout as the sharing view, for just this namespace, with the same
  // colors.
  dom.drawerTopology.replaceChildren();
  dom.drawerTopology.append(buildTopologyHeader(), buildTopologyRow(ns, currentColorMap));

  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawerClose.focus();
}

function closeDrawer() {
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

function renderNamespaces(namespaces) {
  if (!Array.isArray(namespaces) || namespaces.length === 0) {
    dom.content.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    allNamespaces = [];
    closeDrawer();
    return;
  }

  allNamespaces = namespaces;
  dom.empty.hidden = true;
  dom.content.hidden = false;
  dom.countLabel.textContent = `${namespaces.length} namespace${namespaces.length === 1 ? "" : "s"}`;

  const colorMap = buildDbColorMap(namespaces);
  currentColorMap = colorMap;
  renderSummary(namespaces);
  renderNamespaceCards(namespaces, colorMap);
  renderTopology(namespaces, colorMap);
}

/** Load GET /api/iris/namespaces and render it. */
export async function loadNamespaces() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getNamespaces(selectedInstanceId());
  } catch (err) {
    // ApiError messages are already safe to show (see api.js).
    const message =
      err instanceof ApiError
        ? "Could not load namespace information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading namespace information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderNamespaces(null);
    setLoading(false);
    return;
  }

  const namespaces = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (namespaces === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected namespace information.");
    renderNamespaces(null);
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

  renderNamespaces(namespaces);
  setLoading(false);
}

export function initNamespacesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadNamespaces();
  });
  // Uses navigateTo(), like the other links between pages.
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });

  // One delegated listener for all namespace cards. Cards are
  // <article role="button" tabindex="0">, so Enter/Space are handled by
  // hand.
  dom.cardGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".namespace-card");
    if (card) openDrawer(card.dataset.namespace);
  });
  dom.cardGrid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".namespace-card");
    if (!card) return;
    event.preventDefault();
    openDrawer(card.dataset.namespace);
  });

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);

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
