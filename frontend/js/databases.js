// Databases view: fetches GET /api/iris/databases (via IrisApi.getDatabases())
// as the source of truth for the Database Explorer — summary cards, a status
// distribution strip, one card per database, and a read-only detail drawer.
//
// It also calls IrisApi.getNamespaces() (the same existing, already-verified
// read-only endpoint the Namespaces view itself uses) purely to compute the
// drawer's "Namespace Usage" section — which namespaces reference a given
// database via their own real Globals/Routines/SysGlobals/SysRoutines/
// Library/TempGlobals fields. This is a real, derivable relationship from
// data this project already fetches elsewhere, not an invented one and not
// an extra "expensive" call: it is the exact same GET namespaces.js already
// makes. A failure to load it never blocks or errors the primary database
// list — the drawer just falls back to an honest "unavailable" state for
// that one supplementary section (see renderNamespaceUsage()).
//
// The detail drawer also exposes one read-only action, database.info
// ("View Info"): on click, it calls IrisApi.getDatabaseInfo() (GET
// /api/iris/databases/info?dir=<Directory>, backend/app/routes/iris.py's
// get_database_info) and renders whatever real storage facts IRIS returns
// (block size, allocated size, available space, host disk free space,
// mount/full/encrypted/mirrored status — see INFO_FIELDS below). Unlike
// database.create, this is READ-ONLY — it changes nothing, so it needs no
// confirmation step and is not staged through a wizard; see
// handleViewInfoClick().
//
// The drawer also exposes a second read-only action, database.integrity_check
// ("Run Integrity Check"): on click, it calls
// IrisApi.checkDatabaseIntegrity() (GET /api/iris/databases/integrity-check
// ?dir=<Directory>, backend/app/routes/iris.py's
// get_database_integrity_check) and renders IRIS's own raw async-task
// envelope (State, Console, Failure Reason, Result, Time*) exactly as
// returned — see renderIntegrityCheckResult(). Unlike database.info,
// this operation's `Result` shape has never been observed against a real
// IRIS instance (a real integrity check is a resource-intensive scan of
// live data, not a quick metadata read, and was out of scope to actually
// execute during this implementation — see backend/app/models/iris.py's
// DatabaseIntegrityCheckResult docstring), so `Result` is rendered via
// formatUnknownValue() (verbatim JSON text) rather than named fields —
// nothing here guesses a schema. Also read-only, also no confirmation
// step; see handleRunIntegrityCheckClick().
//
// The drawer also exposes a MUTATING action, database.mount ("Check Mount"
// -> explicit confirmation -> "Confirm & Mount"), which calls
// IrisApi.mountDatabase() (POST /api/iris/databases/mount,
// backend/app/routes/databases.py). "Check Mount" is a dry-run preview
// (the handler only reads POST /v2/database-dir/info's Mounted flag); the
// real request is sent only from submitMount(), reachable only via the
// Confirm & Mount button after an acknowledged, validated preview. As with
// database.create, the backend alone authorizes — see handleMountCheckClick().
//
// This view also exposes a second mutating capability, database.create,
// via the "New Database" wizard drawer, which calls IrisApi.createDatabase()
// (POST /api/iris/databases, backend/app/routes/databases.py). That is the
// ONLY mutating HTTP call this module ever makes, and it is reachable ONLY
// through the wizard's own explicit Confirm & Create button — see
// submitCreate() below. This view never constructs its own authorization/
// confirmation logic for it: the wizard only stages the operator's choices
// (Configure -> Review -> explicit confirmation) and forwards them to the
// existing authorization/execution/verification framework, which alone
// decides whether the request is allowed to proceed. The wizard follows the
// exact same Configure -> Review (dry-run preview) -> explicit confirmation
// -> execute -> result pattern as namespaces.js's "New Namespace" wizard —
// see that file's module docstring for the full rationale (in particular,
// why the Review step's dry-run preview call sends confirmed=true).
//
// Fields shown are exactly the ones backend/app/models/iris.py's
// DatabaseEntry actually defines (Name, Directory, Server, ClusterMountMode,
// MountRequired, MountAtStartup, StreamLocation, Status) — nothing invented,
// and the drawer shows ALL of them, not a subset. See
// docs/api-capability-matrix.md for how that shape was originally verified
// against a real IRIS instance. DatabaseEntry itself has no storage size,
// free space, health, performance, or trend field, so none is shown from
// it — but the drawer's separate "Storage Info" section (see
// handleViewInfoClick()/INFO_FIELDS below) DOES show real storage facts,
// sourced from a different, dedicated endpoint (database.info,
// GET /api/iris/databases/info?dir=<Directory>), fetched only when the
// operator clicks "View Info" — never fabricated, and never fetched
// automatically for every card up front.
//
// The wizard's own fields (Directory, Resource Name, Size, Global Journal
// State, Encryption) are exactly the ones
// backend/app/execution/database_create_handler.py's DatabaseCreateParameters
// accepts — verified by reading that handler directly, not guessed. There
// is no "Name" field anywhere in this wizard: IRIS's own POST
// /v2/database-dir request schema has no such field (see that handler's
// module docstring) — a database is identified by Directory. verify()
// confirms creation via GET /v2/database-dir?dir=<Directory> (the same
// endpoint family, keyed by that same Directory) — its response has no
// Name field either, so the Result step's Verification Detail never shows
// one; it reports the real Directory, ResourceName, ReadOnly, and
// GlobalJournalState IRIS returned instead.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { countBy, renderStackedBar, topCategories } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

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
};

// The "New Database" wizard — a second, separate drawer from the
// read-only detail drawer above (dom.*), so viewing an existing database's
// fields and creating a new one never share, and can never accidentally
// clobber, the same DOM state. Structure mirrors namespaces.js's createDom
// exactly.
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

// The fields the operator configured and reviewed — set only by
// handleCreateNext(), read by renderReviewPreview()/submitCreate(), the
// same "choose -> confirm -> execute" staging namespaces.js's wizard uses.
// `confirmed` is always sent as `true` from submitCreate() alone, reachable
// only via the Confirm & Create button's own click handler — never on
// drawer open, never on a field change, never from the Review step's own
// (non-mutating, dryRun=true) preview call.
let pendingCreateFields = null;

// Whether the Review step's own dry-run call came back as a validated,
// creatable request — the Confirm & Create button stays disabled unless
// this AND the acknowledgment checkbox are both true (see
// updateConfirmButtonEnabled()), so the operator can never confirm past a
// request the backend's own validation has already rejected.
let reviewIsValid = false;

// This project's own defensive, CLIENT-SIDE mirror of
// DatabaseCreateParameters' Directory validation (backend/app/execution/
// database_create_handler.py) — used only to fail obviously-invalid input
// fast, before spending a round trip on it. It is not this app's
// authorization logic and does not replace it: every Review step still
// re-validates for real against live IRIS data via a dry-run call below,
// and the backend re-validates again, independently, on the real
// (non-dry-run) request — see CLAUDE.md's "Do not duplicate backend
// authorization logic in JavaScript".
const DIRECTORY_PATTERN = /^\/[^\0]{0,499}$/;

/** Mirrors database_create_handler.py's _normalize_directory(): every real
 * Directory value GET /api/iris/databases has ever returned ends with a
 * trailing slash (see docs/api-capability-matrix.md) — normalized here so
 * a caller-supplied Directory differing only by a missing/extra trailing
 * slash still compares equal to a real existing one. Deliberately NOT
 * case-folded — Directory is a Linux filesystem path and is genuinely
 * case-sensitive. */
function normalizeDirectory(directory) {
  return `${directory.replace(/\/+$/, "")}/`;
}

/** Mirrors database_create_handler.py's _derive_expected_name(): this
 * project's OWN defensive heuristic — NOT a documented IRIS rule —
 * inferred from every existing real database (each one's Name matches its
 * Directory's final path segment, uppercased). Used only for pre-creation
 * collision defense below, never asserted as fact after creation. Nothing
 * in this wizard ever displays a database's real IRIS-assigned Name at
 * all — not even after successful creation — since neither
 * POST /v2/database-dir nor the GET /v2/database-dir?dir=<Directory> call
 * verify() uses to confirm creation returns one; see this file's module
 * docstring. */
function deriveExpectedName(directory) {
  const segments = directory.split("/").filter(Boolean);
  if (segments.length === 0) return null;
  return segments[segments.length - 1].toUpperCase();
}

// The full list from the last successful fetch — the drawer looks a
// database back up here by name when a card is clicked (event delegation),
// rather than re-fetching or capturing per-card closures.
let allDatabases = [];

// The full namespace list from the last successful (best-effort) fetch —
// used only to compute "Namespace Usage" in the drawer. `null` specifically
// means "could not be loaded this time" (a distinct state from "loaded and
// empty"), so renderNamespaceUsage() can show an honest "unavailable"
// message instead of a false "no namespaces reference this database".
let allNamespaces = null;

// The Directory of whichever database the detail drawer currently shows —
// set by openDrawer(), read by handleViewInfoClick() so the "View Info"
// button knows which real database to query. Never guessed/derived: it is
// exactly the same Directory value already displayed in DRAWER_FIELDS.
let currentDrawerDirectory = null;

// [drawer label, DatabaseEntry field, value kind] — every field the drawer
// shows, in the same order the backend model declares them.
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

// [drawer label, DatabaseInfoResult field, value kind] — every field
// backend/app/models/iris.py's DatabaseInfoResult actually defines, in the
// same order that model declares them. Nothing here is a computed/derived
// metric — each row is exactly one field IRIS itself returned (see
// app/routes/iris.py's get_database_info) for the "View Info" action.
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

// [namespace field, human role label] — every real NamespaceEntry field
// that names a database, used by findReferencingNamespaces() below. Same
// six fields namespaces.js's own drawer already lists (see its
// DRAWER_FIELDS), just read in the other direction (by database, not by
// namespace).
const NAMESPACE_DB_ROLE_FIELDS = [
  ["Globals", "Globals"],
  ["Routines", "Routines"],
  ["SysGlobals", "System Globals"],
  ["SysRoutines", "System Routines"],
  ["Library", "Library"],
  ["TempGlobals", "Temp Globals"],
];

/** A real Status-value distribution over the same `databases` array
 * renderDatabaseCards() below already renders as cards — no extra fetch,
 * no invented category. Hidden entirely when there's nothing to show.
 * Unchanged from the previous table-based design other than where it's
 * mounted in the page (see index.html) — the same shared `.view-overview`
 * component Processes/Web Apps/Tasks/Operations/Investigation also use. */
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
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js/system.js/namespaces.js.
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

/** For a value whose shape this app deliberately does NOT know ahead of
 * time (e.g. database.integrity_check's own `Result`, which
 * backend/app/models/iris.py's DatabaseIntegrityCheckResult intentionally
 * leaves untyped — see that model's docstring) — same fallback pattern
 * security.js's own formatValue() already uses for exactly this
 * situation: render objects/arrays as real, verbatim JSON text rather
 * than guessing named fields to pull out of them. */
function formatUnknownValue(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

/** Classifies a real Status string (e.g. "Mounted/RW", "Mounted/R") into
 * one of this app's existing status-badge color variants — purely a
 * presentation choice over the real, verbatim string (which is always
 * shown as the badge's own text; see makeStatusBadge()), never a fabricated
 * label. A status that doesn't start with "Mounted" at all (never observed
 * live, but not assumed impossible) reads as an error state. */
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

/** Classifies a real IRIS async-task State string ("Finished", "Failed",
 * "Canceled", or an in-progress state like "Running"/"Queued") into one
 * of this app's existing status-badge color variants — the same purely
 * presentational approach statusBadgeVariant() above uses for database
 * Status strings; the badge's own text is always the real, verbatim
 * State value (see the "Integrity Check" section's state badge). */
function taskStateBadgeVariant(state) {
  if (typeof state !== "string" || state.length === 0) return "status-badge--neutral";
  if (state === "Finished") return "status-badge--ok";
  if (state === "Failed" || state === "Canceled") return "status-badge--error";
  return "status-badge--warning";
}

/** A small pill naming one real value — the same generic .db-chip
 * component namespaces.js already uses for database names, reused here
 * (without its color dot, which only makes sense when chips are being
 * cross-referenced against a shared color map, as namespaces.js's are) for
 * mount-flag chips on a card and namespace-name chips in the drawer. */
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
    // Reuses the exact same card component namespaces.js's Namespace
    // Explorer already uses — same visual system, not a second one.
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

    // Only the notable (true) mount flags — MountAtStartup is the common
    // case and less interesting to call out on a compact card; all three
    // booleans are always shown in full in the drawer (see DRAWER_FIELDS).
    // The chip row is appended only when there's at least one to show, so
    // a database with no notable flags doesn't leave an empty gap.
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

/** Every namespace whose Globals/Routines/SysGlobals/SysRoutines/Library/
 * TempGlobals field equals this database's real Name — the same kind of
 * derived, real relationship namespaces.js's own Database Topology section
 * already computes, just grouped by database instead of by namespace.
 * Returns `null` when the namespace list itself could not be loaded (a
 * distinct, honest "unknown" state from "loaded and genuinely empty") —
 * see renderNamespaceUsage(). */
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

/** Clears the "Storage Info" section back to its initial, not-yet-loaded
 * state — called every time the drawer opens for a (possibly different)
 * database, so a previous database's storage facts can never be shown
 * against the wrong one. */
function resetDrawerInfo() {
  dom.drawerInfoLoading.hidden = true;
  dom.drawerInfoError.hidden = true;
  dom.drawerInfoFields.hidden = true;
  dom.drawerInfoFields.replaceChildren();
  dom.drawerInfoButton.disabled = false;
}

/** Renders every real field backend/app/models/iris.py's DatabaseInfoResult
 * defines (see INFO_FIELDS) — never a computed/derived/fabricated metric,
 * only what IRIS's own POST /v2/database-dir/info actually returned for
 * this request. */
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
 * The ONLY place in this file that calls IrisApi.getDatabaseInfo() —
 * reachable only via the drawer's own "View Info" button. Read-only (GET
 * /api/iris/databases/info?dir=<Directory>, backed by IRIS's async-task
 * POST /v2/database-dir/info) — never mutates IRIS, so this needs no
 * confirmation step, unlike the "New Database" wizard's Confirm & Create.
 */
async function handleViewInfoClick() {
  if (!currentDrawerDirectory) return;

  dom.drawerInfoButton.disabled = true;
  dom.drawerInfoError.hidden = true;
  dom.drawerInfoFields.hidden = true;
  dom.drawerInfoLoading.hidden = false;

  try {
    const response = await IrisApi.getDatabaseInfo(currentDrawerDirectory);
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

/** Clears the "Integrity Check" section back to its initial, not-yet-run
 * state — called every time the drawer opens for a (possibly different)
 * database, same reasoning as resetDrawerInfo() above. */
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

/** Renders IRIS's own raw async-task envelope exactly as
 * IrisApi.checkDatabaseIntegrity() returned it — nothing here is parsed,
 * summarized, or invented:
 *  - State is promoted into the section's own status badge (next to the
 *    "Run Integrity Check" button) so it stays visible at a glance,
 *    rather than buried as just another row among the rest.
 *  - Console is rendered separately, in full, in a compact scrollable
 *    monospace panel (see the .integrity-console CSS rule and the <pre>
 *    element itself) — every line IRIS returned, verbatim, joined by
 *    real newlines; never truncated, reworded, or filtered. Hidden
 *    entirely when Console is genuinely empty (nothing to show), rather
 *    than showing an empty box.
 *  - Failure Reason, Result, and the three Time fields remain in the
 *    section's existing info-list. `Result` is shown via
 *    formatUnknownValue() (see that function's docstring for why: this
 *    operation's Result shape has never been observed against a real
 *    IRIS instance, so nothing here assumes a particular structure for
 *    it — the real, verbatim value is always shown, never a guessed
 *    field pulled out of it). */
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
 * The ONLY place in this file that calls IrisApi.checkDatabaseIntegrity()
 * — reachable only via the drawer's own "Run Integrity Check" button.
 * Read-only (GET /api/iris/databases/integrity-check?dir=<Directory>,
 * backed by IRIS's async-task POST /v2/database-dir/integrity-check) —
 * verifies existing data, never mutates IRIS, so this needs no
 * confirmation step, unlike the "New Database" wizard's Confirm & Create.
 */
async function handleRunIntegrityCheckClick() {
  if (!currentDrawerDirectory) return;

  dom.drawerIntegrityButton.disabled = true;
  dom.drawerIntegrityError.hidden = true;
  dom.drawerIntegrityFields.hidden = true;
  // Clear any previous run's badge/console too — otherwise a second click
  // that fails would leave the FIRST run's "Finished" badge and console
  // output visible, misleadingly paired with the new error banner.
  dom.drawerIntegrityStateBadge.hidden = true;
  dom.drawerIntegrityConsoleLabel.hidden = true;
  dom.drawerIntegrityConsole.hidden = true;
  dom.drawerIntegrityConsole.textContent = "";
  dom.drawerIntegrityLoading.hidden = false;

  try {
    const task = await IrisApi.checkDatabaseIntegrity(currentDrawerDirectory);
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

// The fields the operator previewed via "Check Mount" — set only by a
// successful dry-run in handleMountCheckClick(), cleared on any change
// (drawer reopen, Read-only toggle), read by submitMount(). Confirm & Mount
// stays disabled unless this is set AND the acknowledgment box is checked.
let pendingMountFields = null;

function updateMountConfirmEnabled() {
  dom.drawerMountConfirmButton.disabled = !(pendingMountFields && dom.drawerMountAckCheckbox.checked);
}

/** Invalidates any previous preview — the operator must Check Mount again
 * before a (possibly different) request can be confirmed. */
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
 * Read-only preview: IrisApi.mountDatabase(fields, true, true) — the
 * executor's dry-run branch is only reached with confirmed=true (see
 * namespaces.js's module docstring), and DatabaseMountHandler.dry_run()
 * never sends the mount request. A rejection (e.g. "already mounted") is
 * shown verbatim and no confirm control is offered.
 */
async function handleMountCheckClick() {
  const directory = currentDrawerDirectory;
  if (!directory) return;

  const fields = { Directory: directory, ReadOnly: dom.drawerMountReadOnly.checked };
  clearMountPreview();
  dom.drawerMountError.hidden = true;
  dom.drawerMountResult.hidden = true;
  dom.drawerMountCheckButton.disabled = true;
  dom.drawerMountLoadingText.textContent = "Checking mount state…";
  dom.drawerMountLoading.hidden = false;

  try {
    const preview = await IrisApi.mountDatabase(fields, true, true);
    if (currentDrawerDirectory !== directory) return; // drawer moved to another database
    const handlerResult = preview && preview.handler_result;
    if (preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
      pendingMountFields = fields;
      dom.drawerMountPreviewText.textContent = handlerResult.detail;
      dom.drawerMountConfirm.hidden = false;
      updateMountConfirmEnabled();
    } else {
      showMountError(
        (handlerResult && handlerResult.detail) ||
          preview.detail ||
          "This mount request could not be validated against IRIS.",
      );
    }
  } catch (err) {
    showMountError(
      err instanceof ApiError
        ? "Could not reach the Command Center backend to check this database's mount state."
        : "An unexpected error occurred while checking this database's mount state.",
    );
  } finally {
    dom.drawerMountLoading.hidden = true;
    dom.drawerMountCheckButton.disabled = false;
  }
}

/** Status, detail, execution detail and verification exactly as the
 * backend returned them — same audit-friendly rendering as
 * renderCreateResult(). */
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

/**
 * The ONLY place in this file that sends a real (non-dry-run) mount
 * request — reachable only via Confirm & Mount, which is enabled only
 * after a successful Check Mount preview and the acknowledgment checkbox.
 */
async function submitMount() {
  const fields = pendingMountFields;
  if (!fields) return;

  clearMountPreview();
  dom.drawerMountCheckButton.disabled = true;
  dom.drawerMountLoadingText.textContent = "Mounting database…";
  dom.drawerMountLoading.hidden = false;

  try {
    const result = await IrisApi.mountDatabase(fields, true, false);
    renderMountResult(result);
    if (result.status === "success") {
      // Re-read the real database list rather than patching local state.
      await loadDatabases();
    }
  } catch (err) {
    renderMountResult({
      status: "request_failed",
      detail:
        err instanceof ApiError
          ? "Could not reach the Command Center backend to mount this database."
          : "An unexpected error occurred while mounting this database.",
    });
  } finally {
    dom.drawerMountLoading.hidden = true;
    dom.drawerMountCheckButton.disabled = false;
  }
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

  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawerClose.focus();
}

function closeDrawer() {
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
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

/** Best-effort, supplementary fetch for the drawer's Namespace Usage
 * section only — see this module's docstring. Never throws: any failure
 * just leaves `allNamespaces` as `null`, which renderNamespaceUsage()
 * shows as an honest "unavailable" state rather than a false empty one. */
async function loadNamespacesForUsage() {
  try {
    const response = await IrisApi.getNamespaces();
    allNamespaces = response && Array.isArray(response.result) ? response.result : null;
  } catch {
    allNamespaces = null;
  }
}

/**
 * Fetches GET /api/iris/databases (the source of truth for this view) and
 * renders it, plus the best-effort namespaces fetch used only for the
 * drawer's Namespace Usage section. No mutating request exists anywhere in
 * this file.
 */
export async function loadDatabases() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getDatabases();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
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
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js/namespaces.js.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  await loadNamespacesForUsage();

  renderDatabases(databases);
  setLoading(false);
}

// --- "New Database" wizard: Configure -> Review (dry-run preview) ->
// explicit confirmation -> create -> result --- (structure mirrors
// namespaces.js's own wizard section)

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

/** Obvious-error, client-side-only checks — required Directory, its
 * format, and (using the database list this view already has loaded —
 * "existing database data", never an extra fetch) a directory/derived-name
 * collision with an already-existing database. Mirrors
 * database_create_handler.py's own _validate() logic exactly (same regex,
 * same normalization, same heuristic) so obviously-invalid input fails
 * fast — the Review step's dry-run call and the backend's own validation
 * remain the real authority; this never replaces them. */
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

/** Renders the Review step: a "Create Database" summary containing
 * exactly the fields that will be sent (requirement: "exactly what will
 * change"), plus whatever the dry-run preview call found. When the
 * backend's own dry-run validation rejects the request, its exact detail
 * text is shown and the Confirm & Create button is kept disabled — the
 * operator cannot confirm past a request the backend has already told us
 * would fail. */
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

/** The "choose values" step — deliberately NOT the confirmation itself.
 * Submitting the form only reads/validates the fields and moves to the
 * Review step, where it issues a real, non-mutating dry-run call
 * (IrisApi.createDatabase(fields, true, true) — `confirmed: true` is
 * required to reach the executor's dry-run branch at all, see
 * namespaces.js's module docstring) for a server-validated preview.
 * Nothing here, or in that dry-run call, can mutate IRIS — see
 * DatabaseCreateHandler.dry_run(), which never calls post(). */
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

/** An audit-friendly record of exactly what the backend returned — status,
 * directory, detail, execution detail, and (when present) verification
 * status/detail — never re-worded, parsed, or summarized away, the same
 * discipline namespaces.js's renderCreateResult() already follows.
 * `result.verification.status`/`.detail` are always displayed verbatim,
 * as plain text, with no assumption about which IRIS endpoint verify()
 * used to produce them (database_create_handler.py's verify() calls GET
 * /v2/database-dir?dir=<Directory>, never GET /v2/databases — see that
 * handler's module docstring for why) — this function makes none of its
 * own, so a future change to verify()'s underlying endpoint or exact
 * detail wording needs no corresponding frontend change. On failure, the
 * "Edit and Retry" button is shown (never an automatic retry) and the
 * Step 1 field values are left exactly as entered, since
 * resetCreateWizard() only runs on drawer open. */
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
 * The ONLY place in this file that calls IrisApi.createDatabase with a
 * real (non-dry-run) request — reachable ONLY via the Confirm & Create
 * button's click handler below, never on drawer open, never on a field
 * change, never from the Review step's own preview call. `confirmed` is
 * always `true` and `dryRun` is always `false` here because this function
 * only runs after the operator reached Review via handleCreateNext(), saw
 * a validated preview, checked the acknowledgment box, and clicked
 * Confirm.
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
      // Refresh the whole Database Explorer so the new database appears in
      // the summary cards, status distribution, and card grid — the same
      // real GET /api/iris/databases every other refresh already uses, not
      // a locally-patched-in guess at what IRIS now has.
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

export function initDatabasesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadDatabases();
  });
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });

  // Event delegation: one listener for every current and future database
  // card, rather than attaching/detaching a listener per card on every
  // refresh — the same pattern namespaces.js's card grid already uses.
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
  dom.drawerMountReadOnly.addEventListener("change", clearMountPreview);
  dom.drawerMountAckCheckbox.addEventListener("change", updateMountConfirmEnabled);
  dom.drawerMountConfirmButton.addEventListener("click", () => {
    submitMount();
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
