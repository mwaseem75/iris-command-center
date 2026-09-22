// Namespaces view: fetches GET /api/iris/namespaces to render the IRIS
// Namespace Explorer — summary cards, one card per namespace, a
// database-sharing topology section, and a read-only detail drawer — and
// exposes exactly one mutating capability, namespace.create, via the
// "New Namespace" wizard drawer, which calls IrisApi.createNamespace()
// (POST /api/iris/namespaces, backend/app/routes/namespaces.py). That is
// the ONLY mutating HTTP call this module ever makes, and it is reachable
// ONLY through the wizard's own explicit Confirm & Create button — see
// submitCreate() below. This view never constructs its own authorization/
// confirmation logic for it: the wizard only stages the operator's
// choices (Configure -> Review -> explicit confirmation) and forwards
// them to the existing authorization/execution/verification framework,
// which alone decides whether the request is allowed to proceed.
//
// The wizard's Review step also calls IrisApi.createNamespace() a SECOND
// way — with dryRun=true — to show a real, server-validated preview
// before the operator can confirm. That call is sent as (confirmed=true,
// dryRun=true): OperationExecutor.execute() checks confirmation BEFORE
// branching on dry_run (app/execution/executor.py), so `confirmed: true`
// is required just to reach the dry-run branch at all — verified against
// the actual running backend, not assumed. It still can never mutate
// IRIS (see NamespaceCreateHandler.dry_run(), which never calls put()/
// post_async_task() and returns "No PUT or POST request was sent."), so
// it is not counted as "execution": only the final, explicit Confirm &
// Create click (dryRun=false) in submitCreate() below does that.
//
// This view also calls IrisApi.getDatabases() (read-only, GET /api/iris/
// databases) to populate the wizard's Globals/Routines/Temp Globals
// Database selectors from real, live database names — never a
// hardcoded/guessed list.
//
// Fields shown in the read-only cards/topology/drawer are exactly the
// ones backend/app/models/iris.py's
// NamespaceEntry actually defines (Name, Globals, Routines, SysGlobals,
// SysRoutines, Library, TempGlobals) — nothing invented; verified against
// the live response (see docs/api-capability-matrix.md's "GET
// /v2/namespaces" entry). There is no "interoperability enabled" or
// similar field anywhere in this response, so no such summary card exists
// here — inventing one would violate this project's "no fabricated data"
// rule (see CLAUDE.md). Every derived number below (distinct Globals/
// Routines database counts, the database-color grouping) is computed
// client-side from these same seven real fields, never fetched or
// guessed separately.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

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

// The "New Namespace" wizard — a second, separate drawer from the
// read-only detail drawer above (dom.*), so viewing an existing
// namespace's fields and creating a new one never share, and can never
// accidentally clobber, the same DOM state.
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

// The fields the operator configured and reviewed — set only by
// handleCreateNext(), read by renderReviewPreview()/submitCreate(),
// exactly the same "choose -> confirm -> execute" staging operations.js
// already uses for journal.update_purge_archived. `confirmed` is always
// sent as `true` from submitCreate() alone, reachable only via the
// Confirm & Create button's own click handler — never on drawer open,
// never on a field change, never on the Review step's own (non-mutating,
// dryRun=true) preview call.
let pendingCreateFields = null;

// Whether the Review step's own dry-run call came back as a validated,
// creatable request — the Confirm & Create button stays disabled unless
// this AND the acknowledgment checkbox are both true (see
// updateConfirmButtonEnabled()), so the operator can never confirm past a
// request the backend's own validation has already rejected.
let reviewIsValid = false;

// This project's own defensive, CLIENT-SIDE mirror of
// NamespaceCreateParameters' Name format check (backend/app/execution/
// namespace_create_handler.py) — used only to fail obviously-invalid
// input fast, before spending a round trip on it. It is not this app's
// authorization logic and does not replace it: every Review step still
// re-validates for real against live IRIS data via a dry-run call below,
// and the backend re-validates again, independently, on the real
// (non-dry-run) request — see CLAUDE.md's "Do not duplicate backend
// authorization logic in JavaScript".
const NAMESPACE_NAME_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,30}$/;

// The full list from the last successful fetch — the drawer looks a
// namespace back up here by name when a card is clicked (event
// delegation), rather than re-fetching or capturing per-card closures.
let allNamespaces = [];

// The color map from the most recent render — the drawer reuses it (via
// openDrawer(), called after render) so its "Database Relationships"
// section colors a database identically to the page's own card grid and
// topology section, rather than computing its own separate mapping.
let currentColorMap = new Map();

// A stable, deterministic color per distinct database name, reused
// identically on namespace cards and in the topology section so the SAME
// database always renders as the SAME color dot everywhere on this page
// — the same qualitative palette app.css's dashboard donuts/bars use
// (--color-chart-1..6), cycling for any additional distinct names.
const CHIP_COLORS = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
  "var(--color-chart-6)",
];

// [label, NamespaceEntry field] — every field the drawer shows, in the
// same order the backend model declares them.
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
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js/system.js/databases.js.
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

/** Distinguishes a system namespace (e.g. %SYS, %ALL) from a normal one
 * (e.g. USER) using only the real `Name` field already in the response —
 * no separate "is system" flag exists anywhere in NamespaceEntry, so this
 * derives the distinction from IRIS's own, real naming convention (every
 * system-reserved namespace/database in this API's data is `%`-prefixed;
 * see e.g. the `%Admin_*` privilege names and `%SYS`/`%ALL` themselves)
 * rather than inventing a new field. */
function isSystemNamespace(name) {
  return typeof name === "string" && name.startsWith("%");
}

const SYSTEM_NAMESPACE_TITLE =
  "System namespace — its name starts with %, IRIS's own convention for system-reserved namespaces.";

/** Assigns each distinct real Globals/Routines/TempGlobals database name
 * (across all namespaces) the next color in CHIP_COLORS, in first-seen
 * order — never invents a database name, only colors the ones actually
 * present in the fetched data. */
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

/** A small colored pill naming one real database value. `label` is the
 * full visible text (callers decide whether to prefix it with the
 * field's role, e.g. "Globals: IRISSYS" on a card vs. just "IRISSYS" in
 * the topology section, which has its own column header for that). */
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

/** A small "System" badge (reusing the app's existing status-badge
 * component, not a new one) for a namespace whose Name is `%`-prefixed —
 * see isSystemNamespace() for why that's the real, existing-data-only
 * signal used. Returns null for a normal namespace, so callers can skip
 * appending anything. */
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

/** The shared four-column header row (Namespace / Globals DB / Routines
 * DB / Temp Globals DB) — used above both the page-level topology (one
 * row per namespace) and the drawer's single-namespace "Database
 * Relationships" mini-topology, so both use the exact same visual
 * language rather than two similar-but-different layouts. */
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

/** One chip-chained row: Namespace -> Globals -> Routines -> Temp
 * Globals. Shared by the page-level topology and the drawer's
 * relationships section — see buildTopologyHeader()'s docstring. */
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

// --- "New Namespace" wizard: Configure -> Review (dry-run preview) ->
// explicit confirmation -> create -> result ---

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

/** Builds one <select>'s options from a real list of database names
 * fetched live from IrisApi.getDatabases() — never a hardcoded list (see
 * populateDatabaseSelects()). `includeEmpty` gives the optional Temp
 * Globals selector a real "use the IRIS default" choice instead of a
 * disabled placeholder. */
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

/** Populates the Globals/Routines/Temp Globals Database selectors from
 * the existing, already-used-elsewhere GET /api/iris/databases (via
 * IrisApi.getDatabases()) — the only source of database names this
 * wizard ever uses. Called each time the wizard opens, so the list is
 * always current, never stale/cached from a previous session. */
async function populateDatabaseSelects() {
  const loadingLabel = "Loading databases…";
  fillDatabaseSelect(createDom.globalsSelect, [], loadingLabel, false);
  fillDatabaseSelect(createDom.routinesSelect, [], loadingLabel, false);
  fillDatabaseSelect(createDom.tempGlobalsSelect, [], loadingLabel, true);

  let names = [];
  let loadError = false;
  try {
    const response = await IrisApi.getDatabases();
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

/** Obvious-error, client-side-only checks — required fields (including a
 * real database selection, not just non-empty text, now that Globals/
 * Routines are <select>s), the %-prefixed system-namespace rule, and this
 * project's own defensive name-format mirror (see NAMESPACE_NAME_PATTERN
 * above). Returns a message string, or null when nothing obvious is
 * wrong. This is a fast-fail convenience only — the Review step's dry-run
 * call and the backend's own validation remain the real authority. */
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

/** Renders the Review step: a "Create Namespace" summary containing
 * exactly the fields that will be sent (requirement: "exactly what will
 * change"), plus whatever the dry-run preview call found. When the
 * backend's own dry-run validation rejects the request (e.g. the
 * namespace already exists), its exact detail text is shown and the
 * Confirm & Create button is kept disabled — the operator cannot confirm
 * past a request the backend has already told us would fail. */
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

/** The "choose values" step — deliberately NOT the confirmation itself.
 * Submitting the form only reads/validates the fields and moves to the
 * Review step, where it issues a real, non-mutating dry-run call
 * (IrisApi.createNamespace(fields, true, true) — `confirmed: true` is
 * required to reach the executor's dry-run branch at all, see the module
 * docstring above) for a server-validated preview. Nothing here, or in
 * that dry-run call, can mutate IRIS — see NamespaceCreateHandler.dry_run(),
 * which never calls put()/post_async_task(). */
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

/** An audit-friendly record of exactly what the backend returned — status,
 * created namespace name, detail, execution detail, and (when present)
 * verification status/detail — never re-worded or summarized away, the
 * same discipline operations.js's renderExecutionResult() already
 * follows. On failure, the "Edit and Retry" button is shown (never an
 * automatic retry) and the Step 1 field values are left exactly as
 * entered, since resetCreateWizard() only runs on drawer open. */
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
 * The ONLY place in this file that calls IrisApi.createNamespace with a
 * real (non-dry-run) request — reachable ONLY via the Confirm & Create
 * button's click handler below, never on drawer open, never on a field
 * change, never from the Review step's own preview call. `confirmed` is
 * always `true` and `dryRun` is always `false` here because this
 * function only runs after the operator reached Review via
 * handleCreateNext(), saw a validated preview, checked the
 * acknowledgment box, and clicked Confirm.
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
      // Refresh the whole view so the new namespace appears in the
      // summary cards, card grid, and topology — the same real GET
      // /api/iris/namespaces every other refresh already uses, not a
      // locally-patched-in guess at what IRIS now has.
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

  // Same visual language as the page-level topology (buildTopologyHeader/
  // buildTopologyRow), scoped to this one namespace, using the SAME color
  // map that section and the card grid already use — a database shown
  // here matches its color everywhere else on the page.
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

/**
 * Fetches GET /api/iris/namespaces and renders it. This is the ONLY network
 * call this module makes — no mutating request exists anywhere in this file.
 */
export async function loadNamespaces() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getNamespaces();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
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
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js/databases.js.
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
  // Same navigateTo() every other cross-view link in this app already
  // uses (see dashboard.js's quicklinks/KPI cards) — not a new/duplicate
  // navigation mechanism.
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });

  // Event delegation: one listener for every current and future namespace
  // card, rather than attaching/detaching a listener per card on every
  // refresh. Cards are <article role="button" tabindex="0">, not real
  // <button>s, so Enter/Space are wired manually to match native button
  // activation — the same pattern already used for the Dashboard's KPI
  // cards.
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
