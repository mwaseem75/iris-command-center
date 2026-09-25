// Web Apps view: a read-only Web Apps Explorer — KPI cards, the Enabled/
// Disabled strip, a client-side search/filter toolbar, a compact table,
// and a detail drawer with Configuration and (REST apps only) REST
// Endpoints tabs, plus a read-only Web Sessions section. It calls exactly
// four read-only endpoints:
//   - GET /api/iris/web-apps (the list; IrisApi.getWebApps()),
//   - GET /api/iris/web-apps/detail?name= (one app's full configuration,
//     fetched only when its drawer opens; IrisApi.getWebAppDetail()),
//   - GET /api/iris/web-apps/rest-endpoints?name= (a REST app's route map,
//     fetched only when its REST Endpoints tab is first opened;
//     IrisApi.getWebAppRestEndpoints()), and
//   - GET /api/iris/web-sessions (active sessions, fetched alongside the
//     list; IrisApi.getWebSessions()). The backend strips every session's
//     IRIS ID before responding, and this module never reads or shows one.
// It also offers exactly two MUTATING actions, both through the backend's
// operation framework (dry run, explicit confirmation, execution and
// verification all happen there): web_app.set_enabled (Enabled State
// section, POST /api/iris/web-apps/set-enabled via
// IrisApi.setWebAppEnabled()) and web_app.update_description (Description
// section, POST /api/iris/web-apps/update-description via
// IrisApi.updateWebAppDescription()). There are no other web-app actions
// (other edits/delete), and no session actions.
//
// Every value shown is a field IRIS actually returned: the table uses
// backend/app/models/iris.py's WebAppEntry, the drawer's configuration
// sections use WebAppDetail (all 46 fields, see DETAIL_SECTIONS). The only
// derived value is "Kind": REST when DispatchClass is set, otherwise CSP.
// IRIS's own list `Type` never says "REST" (live values are only "CSP" and
// "System,CSP"), and mainspec_v2.json documents DispatchClass as "For REST
// Web Application only" — so the derivation is labelled as such in the UI
// and the real `Type` is always shown alongside it.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";
import { countBy, renderStackedBar } from "./viz.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("web-apps-loading-state"),
  errorBanner: document.getElementById("web-apps-error-banner"),
  errorBannerText: document.getElementById("web-apps-error-banner-text"),
  refreshButton: document.getElementById("web-apps-refresh-button"),
  backButton: document.getElementById("web-apps-back-button"),
  connectionStatus: document.getElementById("web-apps-connection-status"),
  connectionStatusLabel: document.getElementById("web-apps-connection-status-label"),
  connectionDetail: document.getElementById("web-apps-connection-detail"),
  countLabel: document.getElementById("web-apps-count"),
  content: document.getElementById("web-apps-content"),
  summaryGrid: document.getElementById("web-apps-summary-grid"),
  tableWrapper: document.getElementById("web-apps-table-wrapper"),
  tableBody: document.getElementById("web-apps-table-body"),
  empty: document.getElementById("web-apps-empty"),
  overview: document.getElementById("web-apps-overview"),
  overviewViz: document.getElementById("web-apps-overview-viz"),
  filterForm: document.getElementById("web-apps-filter-form"),
  filterSearch: document.getElementById("web-apps-filter-search"),
  filterKind: document.getElementById("web-apps-filter-kind"),
  filterStatus: document.getElementById("web-apps-filter-status"),
  filterNamespace: document.getElementById("web-apps-filter-namespace"),
  filterAuth: document.getElementById("web-apps-filter-auth"),
  filterClear: document.getElementById("web-apps-filter-clear-button"),
  filterCount: document.getElementById("web-apps-filter-count"),
  filterEmpty: document.getElementById("web-apps-filter-empty"),
  drawerBackdrop: document.getElementById("web-apps-drawer-backdrop"),
  drawer: document.getElementById("web-apps-drawer"),
  drawerTitle: document.getElementById("web-apps-drawer-title"),
  drawerKindBadge: document.getElementById("web-apps-drawer-kind-badge"),
  drawerStatusBadge: document.getElementById("web-apps-drawer-status-badge"),
  drawerSummary: document.getElementById("web-apps-drawer-summary"),
  drawerLoading: document.getElementById("web-apps-drawer-loading"),
  drawerError: document.getElementById("web-apps-drawer-error"),
  drawerErrorText: document.getElementById("web-apps-drawer-error-text"),
  drawerConfig: document.getElementById("web-apps-drawer-config"),
  drawerClose: document.getElementById("web-apps-drawer-close"),
  drawerTabs: document.getElementById("web-apps-drawer-tabs"),
  tabConfig: document.getElementById("web-apps-tab-config"),
  tabRest: document.getElementById("web-apps-tab-rest"),
  panelConfig: document.getElementById("web-apps-panel-config"),
  panelRest: document.getElementById("web-apps-panel-rest"),
  restLoading: document.getElementById("web-apps-rest-loading"),
  restError: document.getElementById("web-apps-rest-error"),
  restErrorText: document.getElementById("web-apps-rest-error-text"),
  restUnavailable: document.getElementById("web-apps-rest-unavailable"),
  restContent: document.getElementById("web-apps-rest-content"),
  restMeta: document.getElementById("web-apps-rest-meta"),
  restListView: document.getElementById("web-apps-rest-list-view"),
  restFilterForm: document.getElementById("web-apps-rest-filter-form"),
  restSearch: document.getElementById("web-apps-rest-search"),
  restMethod: document.getElementById("web-apps-rest-method"),
  restCount: document.getElementById("web-apps-rest-count"),
  restFilterEmpty: document.getElementById("web-apps-rest-filter-empty"),
  restList: document.getElementById("web-apps-rest-list"),
  restDetailView: document.getElementById("web-apps-rest-detail-view"),
  restBack: document.getElementById("web-apps-rest-back"),
  restDetailMethod: document.getElementById("web-apps-rest-detail-method"),
  restDetailPath: document.getElementById("web-apps-rest-detail-path"),
  restDetailFields: document.getElementById("web-apps-rest-detail-fields"),
  restDetailNoParams: document.getElementById("web-apps-rest-detail-no-params"),
  restDetailParamsWrapper: document.getElementById("web-apps-rest-detail-params-wrapper"),
  restDetailParams: document.getElementById("web-apps-rest-detail-params"),
  restDetailDescriptionSection: document.getElementById("web-apps-rest-detail-description-section"),
  restDetailDescription: document.getElementById("web-apps-rest-detail-description"),
  sessionsLoading: document.getElementById("web-sessions-loading"),
  sessionsError: document.getElementById("web-sessions-error"),
  sessionsErrorText: document.getElementById("web-sessions-error-text"),
  sessionsEmpty: document.getElementById("web-sessions-empty"),
  sessionsContent: document.getElementById("web-sessions-content"),
  sessionsSummaryGrid: document.getElementById("web-sessions-summary-grid"),
  sessionsFilterForm: document.getElementById("web-sessions-filter-form"),
  sessionsFilterSearch: document.getElementById("web-sessions-filter-search"),
  sessionsFilterApp: document.getElementById("web-sessions-filter-app"),
  sessionsFilterUser: document.getElementById("web-sessions-filter-user"),
  sessionsFilterClear: document.getElementById("web-sessions-filter-clear-button"),
  sessionsFilterCount: document.getElementById("web-sessions-filter-count"),
  sessionsFilterEmpty: document.getElementById("web-sessions-filter-empty"),
  sessionsTableWrapper: document.getElementById("web-sessions-table-wrapper"),
  sessionsTableBody: document.getElementById("web-sessions-table-body"),
  sessionDrawerBackdrop: document.getElementById("web-sessions-drawer-backdrop"),
  sessionDrawer: document.getElementById("web-sessions-drawer"),
  sessionDrawerTitle: document.getElementById("web-sessions-drawer-title"),
  sessionDrawerAppBadge: document.getElementById("web-sessions-drawer-app-badge"),
  sessionDrawerFields: document.getElementById("web-sessions-drawer-fields"),
  sessionDrawerApp: document.getElementById("web-sessions-drawer-app"),
  sessionDrawerOpenApp: document.getElementById("web-sessions-drawer-open-app"),
  sessionDrawerClose: document.getElementById("web-sessions-drawer-close"),
  enableCheckButton: document.getElementById("web-apps-enable-check-button"),
  enableLoading: document.getElementById("web-apps-enable-loading"),
  enableLoadingText: document.getElementById("web-apps-enable-loading-text"),
  enableError: document.getElementById("web-apps-enable-error"),
  enableErrorText: document.getElementById("web-apps-enable-error-text"),
  enableConfirm: document.getElementById("web-apps-enable-confirm"),
  enablePreviewText: document.getElementById("web-apps-enable-preview-text"),
  enableAckCheckbox: document.getElementById("web-apps-enable-ack-checkbox"),
  enableAckText: document.getElementById("web-apps-enable-ack-text"),
  enableConfirmButton: document.getElementById("web-apps-enable-confirm-button"),
  enableResult: document.getElementById("web-apps-enable-result"),
  descriptionInput: document.getElementById("web-apps-description-input"),
  descriptionCheckButton: document.getElementById("web-apps-description-check-button"),
  descriptionLoading: document.getElementById("web-apps-description-loading"),
  descriptionLoadingText: document.getElementById("web-apps-description-loading-text"),
  descriptionError: document.getElementById("web-apps-description-error"),
  descriptionErrorText: document.getElementById("web-apps-description-error-text"),
  descriptionConfirm: document.getElementById("web-apps-description-confirm"),
  descriptionPreviewText: document.getElementById("web-apps-description-preview-text"),
  descriptionAckCheckbox: document.getElementById("web-apps-description-ack-checkbox"),
  descriptionAckText: document.getElementById("web-apps-description-ack-text"),
  descriptionConfirmButton: document.getElementById("web-apps-description-confirm-button"),
  descriptionResult: document.getElementById("web-apps-description-result"),
};

// [label, WebAppEntry field, value kind] — the list-endpoint facts shown at
// the top of the drawer immediately, before the detail request finishes.
const SUMMARY_FIELDS = [
  ["Namespace", "Namespace", "text"],
  ["Type", "Type", "text"],
  ["Namespace Default", "NamespaceDefault", "bool"],
  ["System App", "IsSystemApp", "bool"],
  ["Auth Methods", "AuthenticationMethods", "list"],
  ["Resource", "Resource", "mono"],
  ["Dispatch Class", "DispatchClass", "mono"],
];

// [section title, [[label, WebAppDetail field, value kind], ...]] — every
// one of the 46 fields WebAppDetail defines appears exactly once, grouped
// by what an administrator is looking for. Units ("s") follow the spec's
// own descriptions ("in seconds") for each timeout field.
const DETAIL_SECTIONS = [
  ["General", [
    ["Description", "Description", "text"],
    ["Namespace", "NameSpace", "text"],
    ["Enabled", "Enabled", "bool"],
    ["Namespace Default App", "IsNameSpaceDefault", "bool"],
    ["Authentication Group", "GroupById", "mono"],
  ]],
  ["Dispatch & Routing", [
    ["Dispatch Class", "DispatchClass", "mono"],
    ["Physical Path", "Path", "mono"],
    ["Recurse Subdirectories", "Recurse", "bool"],
    ["Package", "Package", "mono"],
    ["Default Superclass", "SuperClass", "mono"],
    ["Event Class", "EventClass", "mono"],
    ["Permitted Classes", "PermittedClasses", "mono"],
    ["Redirect Empty Path", "RedirectEmptyPath", "bool"],
    ["Lock CSP Name", "LockCSPName", "bool"],
  ]],
  ["Authentication & Access", [
    ["Allowed Methods", "AutheEnabled", "authe"],
    ["Resource", "Resource", "mono"],
    ["Application Roles", "MatchRoles", "roles"],
    ["Two-Factor", "TwoFactorEnabled", "bool"],
    ["Login CSRF Token", "CSRFToken", "bool"],
    ["Login Page", "LoginPage", "mono"],
    ["Change Password Page", "ChangePasswordPage", "mono"],
  ]],
  ["JWT", [
    ["JWT Authentication", "JWTAuthEnabled", "bool"],
    ["Access Token Timeout", "JWTAccessTokenTimeout", "seconds"],
    ["Refresh Token Timeout", "JWTRefreshTokenTimeout", "seconds"],
  ]],
  ["CORS", [
    ["Allowed Origins", "CorsAllowlist", "list"],
    ["Allow Credentials", "CorsCredentialsAllowed", "bool"],
    ["Allowed Headers", "CorsHeadersList", "list"],
  ]],
  ["Sessions & Cookies", [
    ["Session Timeout", "Timeout", "seconds"],
    ["Use Cookies", "UseCookies", "text"],
    ["Cookie Path", "CookiePath", "mono"],
    ["Session Cookie SameSite", "SessionScope", "text"],
    ["User Cookie SameSite", "UserCookieScope", "text"],
  ]],
  ["Static Files & Pages", [
    ["Serve Files", "ServeFiles", "text"],
    ["Static File Cache", "ServeFilesTimeout", "seconds"],
    ["Auto Compile", "AutoCompile", "bool"],
    ["Error Page", "ErrorPage", "mono"],
  ]],
  ["Features", [
    ["CSP/Zen Pages", "CSPZENEnabled", "bool"],
    ["Inbound Web Services", "InbndWebServicesEnabled", "bool"],
    ["Analytics (DeepSee)", "DeepSeeEnabled", "bool"],
    ["iKnow", "iKnowEnabled", "bool"],
    ["OpenTelemetry Tracing", "TraceEnabled", "bool"],
  ]],
  ["Python (WSGI/ASGI)", [
    ["Interface Type", "WSGIType", "text"],
    ["App Name", "WSGIAppName", "mono"],
    ["App Location", "WSGIAppLocation", "mono"],
    ["Callable", "WSGICallable", "mono"],
    ["Debug Mode", "WSGIDebug", "bool"],
  ]],
];

// AutheEnabled bit numbers exactly as mainspec_v2.json documents them
// ("these bits correspond to the same bit numbers in the Security.System
// class"). Cross-checked live: 32 ⇔ ["Password"], 64 ⇔ ["Unauthenticated"],
// 96 ⇔ both, matching the list endpoint's AuthenticationMethods for every app.
const AUTHE_BITS = [
  [2, "Kerberos (K5API)"],
  [5, "Password"],
  [6, "Unauthenticated"],
  [11, "LDAP"],
  [13, "Delegated"],
  [14, "Login Token"],
  [20, "Two-Factor SMS"],
  [21, "Two-Factor TOTP"],
];

// KPI cards: [label, filter it applies (or null for Total), predicate].
// Every count is computed from the fetched list — nothing invented.
const SUMMARY_CARDS = [
  ["Total", null, () => true],
  ["REST", { select: "filterKind", value: "REST" }, (app) => kindOf(app) === "REST"],
  ["CSP", { select: "filterKind", value: "CSP" }, (app) => kindOf(app) === "CSP"],
  ["Enabled", { select: "filterStatus", value: "enabled" }, (app) => app.Enabled === true],
  ["Disabled", { select: "filterStatus", value: "disabled" }, (app) => app.Enabled === false],
  [
    "Unauthenticated",
    { select: "filterAuth", value: "Unauthenticated" },
    (app) => authMethodsOf(app).includes("Unauthenticated"),
  ],
];
const CARD_COLORS = [
  "var(--color-accent)",
  "var(--color-chart-2)",
  "var(--color-chart-6)",
  "var(--color-chart-3)",
  "var(--color-chart-neutral)",
  "var(--color-chart-4)",
];

// Real WebAppEntry fields the free-text search matches against.
const SEARCH_FIELDS = ["Name", "Namespace", "Type", "Resource", "DispatchClass"];

// The full list from the last successful fetch — filtering and the drawer
// summary both read from this; neither triggers a re-fetch.
let allWebApps = [];

// Name of the app whose drawer is open, and a counter so a slow detail
// response for a previously opened app can never overwrite a newer one.
let currentDrawerName = null;
let detailRequestSeq = 0;

// REST Endpoints tab state. Route maps are cached per app name until the
// next list Refresh (each fetch costs IRIS a few seconds); a cached entry
// is either { routeMap } or { unavailable: message }. `restRequestSeq`
// guards against a slow response for a previously viewed app.
let activeDrawerTab = "config";
let restCache = new Map();
let restRequestSeq = 0;
let currentRouteMap = null;
let currentEndpointIndex = null;

// Web Sessions state. `allSessions` is null when the last sessions fetch
// failed (a distinct "unknown" state from a real empty list). Sessions are
// identified in the UI only by their position in the last fetched list —
// never by IRIS's session ID, which the backend withholds.
let allSessions = null;
let sessionsLoadSeq = 0;
let currentSessionIndex = null;

// [label, WebSessionEntry field, value kind] — every field the backend
// returns for a session (all of GET /v2/web-sessions except ID).
const SESSION_FIELDS = [
  ["Username", "Username", "text"],
  ["Application", "Application", "mono"],
  ["Timeout", "Timeout", "mono"],
  ["License ID", "LicenseId", "mono"],
  ["Process ID", "SesProcessId", "mono"],
  ["Preserve", "Preserve", "mono"],
  ["Allow End Session", "AllowEndSession", "bool"],
];

function kindOf(app) {
  return typeof app.DispatchClass === "string" && app.DispatchClass !== "" ? "REST" : "CSP";
}

function authMethodsOf(app) {
  return Array.isArray(app.AuthenticationMethods) ? app.AuthenticationMethods : [];
}

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in dashboard.js/system.js/processes.js/databases.js.
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

function formatList(value) {
  return Array.isArray(value) && value.length > 0 ? value.join(", ") : PLACEHOLDER;
}

function formatSeconds(value) {
  return typeof value === "number" ? `${value} s` : PLACEHOLDER;
}

/** Decodes the real AutheEnabled bitmask into the spec's documented names,
 * always followed by the raw value; an undocumented set bit is shown as
 * "bit N" rather than guessed. */
function formatAutheEnabled(value) {
  if (typeof value !== "number") return PLACEHOLDER;
  const names = AUTHE_BITS.filter(([bit]) => (value & (1 << bit)) !== 0).map(([, name]) => name);
  let known = 0;
  for (const [bit] of AUTHE_BITS) known |= 1 << bit;
  for (let bit = 0; bit < 31; bit += 1) {
    if ((value & (1 << bit)) !== 0 && (known & (1 << bit)) === 0) names.push(`bit ${bit}`);
  }
  return `${names.length > 0 ? names.join(", ") : "None"} (${value})`;
}

/** MatchRoles pairs as "MatchRole → TargetRoles"; an empty MatchRole means
 * the target roles are always granted (per the spec's own description). */
function formatMatchRoles(value) {
  if (!Array.isArray(value) || value.length === 0) return PLACEHOLDER;
  return value
    .map((pair) => {
      const targets = formatList(pair && pair.TargetRoles);
      return pair && pair.MatchRole ? `${pair.MatchRole} → ${targets}` : `Always → ${targets}`;
    })
    .join("; ");
}

function formatValue(value, kind) {
  switch (kind) {
    case "bool": return formatBoolean(value);
    case "list": return formatList(value);
    case "seconds": return formatSeconds(value);
    case "authe": return formatAutheEnabled(value);
    case "roles": return formatMatchRoles(value);
    default: return textOrPlaceholder(value);
  }
}

function makeBadge(text, variant) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = text;
  return badge;
}

function kindBadgeVariant(kind) {
  return kind === "REST" ? "status-badge--accent" : "status-badge--neutral";
}

function statusBadge(enabled) {
  if (typeof enabled !== "boolean") return ["Unknown", "status-badge--neutral"];
  return enabled ? ["Enabled", "status-badge--ok"] : ["Disabled", "status-badge--neutral"];
}

// Table rows/drawer rows are always built via document.createElement +
// .textContent — never innerHTML — so a name/class/path containing
// HTML-special characters can never be interpreted as markup.
function makeCell(text, { mono = false } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function makeBadgeCell(badge, title) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  if (title) cell.title = title;
  cell.append(badge);
  return cell;
}

function makeInfoRow(label, field, text, kind) {
  const row = document.createElement("div");
  row.className = "info-list__row";

  const dt = document.createElement("dt");
  dt.textContent = label;
  if (field) {
    const fieldName = document.createElement("span");
    fieldName.className = "info-list__field";
    fieldName.textContent = field;
    dt.append(fieldName);
  }

  const dd = document.createElement("dd");
  dd.className = kind === "mono" ? "info-list__value info-list__value--mono" : "info-list__value";
  dd.textContent = text;

  row.append(dt, dd);
  return row;
}

/** A real Enabled/Disabled split over the fetched list. Hidden entirely
 * when there's nothing to show. */
function renderOverview(webApps) {
  dom.overview.hidden = false;
  const entries = countBy(webApps, (app) => (app.Enabled ? "Enabled" : "Disabled"));
  renderStackedBar(dom.overviewViz, entries);
}

function renderSummary(webApps) {
  dom.summaryGrid.replaceChildren();
  SUMMARY_CARDS.forEach(([label, filter, predicate], i) => {
    const card = document.createElement("article");
    card.className = "stat-card stat-card--interactive";
    card.style.setProperty("--stat-card-accent", CARD_COLORS[i % CARD_COLORS.length]);
    card.setAttribute("role", "button");
    card.setAttribute("tabindex", "0");
    card.dataset.cardIndex = String(i);
    card.title = filter ? `Filter to ${label}` : "Clear card filters";

    const labelEl = document.createElement("h3");
    labelEl.className = "stat-card__label";
    labelEl.textContent = label;

    const valueEl = document.createElement("p");
    valueEl.className = "stat-card__value";
    valueEl.textContent = String(webApps.filter(predicate).length);

    card.append(labelEl, valueEl);
    dom.summaryGrid.append(card);
  });
  syncSummaryActiveState();
}

function syncSummaryActiveState() {
  const cardFiltersClear =
    dom.filterKind.value === "" && dom.filterStatus.value === "" && dom.filterAuth.value === "";
  for (const card of dom.summaryGrid.querySelectorAll(".stat-card")) {
    const [, filter] = SUMMARY_CARDS[Number(card.dataset.cardIndex)];
    const isActive = filter ? dom[filter.select].value === filter.value : cardFiltersClear;
    card.classList.toggle("stat-card--active", isActive);
    card.setAttribute("aria-pressed", String(isActive));
  }
}

function applyCardFilter(index) {
  const [, filter] = SUMMARY_CARDS[index];
  if (!filter) {
    dom.filterKind.value = "";
    dom.filterStatus.value = "";
    dom.filterAuth.value = "";
  } else {
    const select = dom[filter.select];
    // Clicking the already-active card clears that filter.
    select.value = select.value === filter.value ? "" : filter.value;
  }
  renderTable();
}

/** Rebuilds a <select>'s options from real values, keeping the current
 * selection if that value still exists after a refresh. */
function populateSelect(select, allLabel, values) {
  const previous = select.value;
  const allOption = document.createElement("option");
  allOption.value = "";
  allOption.textContent = allLabel;
  select.replaceChildren(allOption);
  for (const value of values) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.append(option);
  }
  select.value = values.includes(previous) ? previous : "";
}

function populateFilters() {
  const namespaces = [...new Set(allWebApps.map((app) => app.Namespace).filter(Boolean))].sort();
  populateSelect(dom.filterNamespace, "All namespaces", namespaces);
  const methods = [...new Set(allWebApps.flatMap(authMethodsOf))].sort();
  populateSelect(dom.filterAuth, "All methods", methods);
}

function matchesFilters(app, query) {
  if (dom.filterKind.value && kindOf(app) !== dom.filterKind.value) return false;
  if (dom.filterStatus.value === "enabled" && app.Enabled !== true) return false;
  if (dom.filterStatus.value === "disabled" && app.Enabled !== false) return false;
  if (dom.filterNamespace.value && app.Namespace !== dom.filterNamespace.value) return false;
  if (dom.filterAuth.value && !authMethodsOf(app).includes(dom.filterAuth.value)) return false;
  if (!query) return true;
  return SEARCH_FIELDS.some((field) => {
    const value = app[field];
    return typeof value === "string" && value.toLowerCase().includes(query);
  });
}

function renderTable() {
  const query = dom.filterSearch.value.trim().toLowerCase();
  const visible = allWebApps.filter((app) => matchesFilters(app, query));

  dom.tableBody.replaceChildren();
  for (const app of visible) {
    const row = document.createElement("tr");
    row.className = "data-table__row--clickable";
    row.dataset.name = app.Name;
    row.tabIndex = 0;
    row.setAttribute("aria-label", `View details for web application ${textOrPlaceholder(app.Name)}`);

    const kind = kindOf(app);
    const [statusText, statusVariant] = statusBadge(app.Enabled);
    row.append(
      makeCell(textOrPlaceholder(app.Name), { mono: true }),
      makeBadgeCell(makeBadge(kind, kindBadgeVariant(kind)), "Derived from Dispatch Class"),
      makeCell(textOrPlaceholder(app.Namespace)),
      makeBadgeCell(makeBadge(statusText, statusVariant)),
      makeCell(formatList(app.AuthenticationMethods)),
      makeCell(textOrPlaceholder(app.Resource), { mono: true }),
      makeCell(textOrPlaceholder(app.DispatchClass), { mono: true }),
      makeCell(textOrPlaceholder(app.Type)),
    );
    dom.tableBody.append(row);
  }

  const filtered =
    query !== "" ||
    [dom.filterKind, dom.filterStatus, dom.filterNamespace, dom.filterAuth].some((s) => s.value !== "");
  dom.tableWrapper.hidden = visible.length === 0;
  dom.filterEmpty.hidden = visible.length !== 0;
  dom.filterClear.disabled = !filtered;
  dom.filterCount.textContent = filtered
    ? `Showing ${visible.length} of ${allWebApps.length}`
    : `Showing all ${allWebApps.length}`;
  syncSummaryActiveState();
}

function renderDrawerSummary(app) {
  const kind = kindOf(app);
  const [statusText, statusVariant] = statusBadge(app.Enabled);
  dom.drawerTitle.textContent = textOrPlaceholder(app.Name);
  dom.drawerKindBadge.className = `status-badge ${kindBadgeVariant(kind)}`;
  dom.drawerKindBadge.textContent = kind;
  dom.drawerStatusBadge.className = `status-badge ${statusVariant}`;
  dom.drawerStatusBadge.textContent = statusText;

  const sessions = sessionsForApp(app);
  dom.drawerSummary.replaceChildren(
    ...SUMMARY_FIELDS.map(([label, field, kindOfValue]) =>
      makeInfoRow(label, null, formatValue(app[field], kindOfValue), kindOfValue),
    ),
    makeInfoRow(
      "Active Sessions",
      null,
      sessions === null ? "Unavailable" : String(sessions.length),
      "text",
    ),
  );
}

function renderDrawerConfig(detail) {
  dom.drawerConfig.replaceChildren();
  for (const [title, fields] of DETAIL_SECTIONS) {
    const section = document.createElement("div");
    section.className = "ns-drawer__section";

    const heading = document.createElement("h4");
    heading.className = "ns-drawer__section-title";
    heading.textContent = title;

    const list = document.createElement("dl");
    list.className = "info-list";
    for (const [label, field, kind] of fields) {
      list.append(makeInfoRow(label, field, formatValue(detail[field], kind), kind));
    }

    section.append(heading, list);
    dom.drawerConfig.append(section);
  }
}

/** Fetches GET /api/iris/web-apps/detail for the open drawer's app. Only
 * the most recent request's result is ever rendered. */
async function loadDrawerDetail(name) {
  const seq = ++detailRequestSeq;
  dom.drawerConfig.replaceChildren();
  dom.drawerError.hidden = true;
  dom.drawerLoading.hidden = false;

  try {
    const response = await IrisApi.getWebAppDetail(name);
    if (seq !== detailRequestSeq) return;
    const detail = response && response.result && typeof response.result === "object" ? response.result : null;
    if (!detail) {
      dom.drawerErrorText.textContent = "IRIS did not return the expected web application configuration.";
      dom.drawerError.hidden = false;
      return;
    }
    renderDrawerConfig(detail);
    const app = allWebApps.find((entry) => entry.Name === name);
    if (app) syncDescriptionFromDetail(app, detail);
  } catch (err) {
    if (seq !== detailRequestSeq) return;
    dom.drawerErrorText.textContent =
      err instanceof ApiError
        ? "Could not load this web application's configuration."
        : "An unexpected error occurred while loading this web application's configuration.";
    dom.drawerError.hidden = false;
  } finally {
    if (seq === detailRequestSeq) dom.drawerLoading.hidden = true;
  }
}

// --- Enabled State (web_app.set_enabled — the drawer's one MUTATING action) ---
//
// Flow, same as the Database drawer's mount: "Check" sends a dry run
// (IrisApi.setWebAppEnabled(fields, true, true) — the executor's dry-run
// branch is only reached with confirmed=true, and the handler's dry_run()
// never sends the PUT). Only a successful preview offers the confirm
// control, which is enabled only after the acknowledgment checkbox; the
// real request is sent only from submitEnable(). The backend alone
// authorizes, hard-denies protected apps, executes and verifies — this code
// never decides any of that itself, it only shows what the backend returned.

// The fields the operator previewed — set only by a successful dry run,
// cleared whenever the drawer's app or its current state changes.
let pendingEnableFields = null;

function enableTargetFor(app) {
  return typeof app.Enabled === "boolean" ? !app.Enabled : null;
}

function updateEnableConfirmEnabled() {
  dom.enableConfirmButton.disabled = !(pendingEnableFields && dom.enableAckCheckbox.checked);
}

function clearEnablePreview() {
  pendingEnableFields = null;
  dom.enableConfirm.hidden = true;
  dom.enableAckCheckbox.checked = false;
  updateEnableConfirmEnabled();
}

function resetEnableControls() {
  clearEnablePreview();
  dom.enableLoading.hidden = true;
  dom.enableError.hidden = true;
  dom.enableResult.hidden = true;
  dom.enableResult.replaceChildren();
  dom.enableCheckButton.disabled = false;
}

/** Labels the controls for the app's real current state (from the list),
 * and drops a preview that no longer matches it. */
function syncEnableControls(app) {
  const target = enableTargetFor(app);
  dom.enableCheckButton.hidden = target === null;
  const verb = target ? "Enable" : "Disable";
  dom.enableCheckButton.textContent = `Check ${verb}`;
  dom.enableConfirmButton.textContent = `Confirm & ${verb}`;
  dom.enableAckText.textContent = `I understand this will ${verb.toLowerCase()} ${app.Name} on the IRIS instance.`;
  if (pendingEnableFields && (pendingEnableFields.Name !== app.Name || pendingEnableFields.Enabled !== target)) {
    clearEnablePreview();
  }
}

function showEnableError(message) {
  dom.enableErrorText.textContent = message;
  dom.enableError.hidden = false;
}

async function handleEnableCheckClick() {
  const app = allWebApps.find((entry) => entry.Name === currentDrawerName);
  const target = app ? enableTargetFor(app) : null;
  if (!app || target === null) return;

  const fields = { Name: app.Name, Enabled: target };
  clearEnablePreview();
  dom.enableError.hidden = true;
  dom.enableResult.hidden = true;
  dom.enableCheckButton.disabled = true;
  dom.enableLoadingText.textContent = "Checking with IRIS (dry run)…";
  dom.enableLoading.hidden = false;

  try {
    const preview = await IrisApi.setWebAppEnabled(fields, true, true);
    if (currentDrawerName !== fields.Name) return; // drawer moved to another app
    const handlerResult = preview && preview.handler_result;
    if (preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
      pendingEnableFields = fields;
      dom.enablePreviewText.textContent = handlerResult.detail;
      dom.enableConfirm.hidden = false;
      updateEnableConfirmEnabled();
    } else {
      // Unauthorized, protected, no-op, unknown app… shown exactly as the
      // backend explained it.
      showEnableError(
        (handlerResult && handlerResult.detail) ||
          preview.detail ||
          "This change could not be validated against IRIS.",
      );
    }
  } catch (err) {
    showEnableError(
      err instanceof ApiError
        ? "Could not reach the Command Center backend to check this change."
        : "An unexpected error occurred while checking this change.",
    );
  } finally {
    dom.enableLoading.hidden = true;
    dom.enableCheckButton.disabled = false;
  }
}

/** Status, detail, execution detail and verification exactly as the
 * backend returned them — same rendering as the Database drawer's mount. */
function renderEnableResult(result) {
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
  dom.enableResult.replaceChildren(
    ...rows.map(([label, value]) => makeInfoRow(label, null, value, "text")),
  );
  dom.enableResult.hidden = false;
}

/**
 * The ONLY place in this file that sends a real (non-dry-run) change —
 * reachable only via the confirm button, which is enabled only after a
 * successful preview and the acknowledgment checkbox.
 */
async function submitEnable() {
  const fields = pendingEnableFields;
  if (!fields) return;

  clearEnablePreview();
  dom.enableCheckButton.disabled = true;
  dom.enableLoadingText.textContent = fields.Enabled ? "Enabling web application…" : "Disabling web application…";
  dom.enableLoading.hidden = false;

  let result;
  try {
    result = await IrisApi.setWebAppEnabled(fields, true, false);
  } catch (err) {
    result = {
      status: "request_failed",
      detail:
        err instanceof ApiError
          ? "Could not reach the Command Center backend to change this web application."
          : "An unexpected error occurred while changing this web application.",
    };
  }
  dom.enableLoading.hidden = true;
  dom.enableCheckButton.disabled = false;
  if (currentDrawerName === fields.Name) renderEnableResult(result);

  if (result.status === "success" || result.status === "verification_failed") {
    // Re-read the real list rather than patching local state — the drawer
    // re-renders from it (same app, so the result above stays visible).
    await loadWebApps();
  }
}

// --- Description (web_app.update_description — the drawer's second
// MUTATING action) ---
//
// The same flow as Enabled State above: "Check" sends a dry run
// (IrisApi.updateWebAppDescription(fields, true, true) — the handler's
// dry_run() never sends the PUT); only a successful preview offers the
// confirm control, enabled only after the acknowledgment checkbox; the real
// request is sent only from submitDescription(). The backend alone
// authorizes, refuses protected apps, executes and verifies. The input is
// prefilled with the app's real Description from the detail load.

// The fields the operator previewed — set only by a successful dry run,
// cleared whenever the drawer's app or the typed text changes.
let pendingDescriptionFields = null;
// Whether the operator has edited the input since it was last prefilled.
let descriptionEdited = false;

function updateDescriptionConfirmEnabled() {
  dom.descriptionConfirmButton.disabled = !(pendingDescriptionFields && dom.descriptionAckCheckbox.checked);
}

function clearDescriptionPreview() {
  pendingDescriptionFields = null;
  dom.descriptionConfirm.hidden = true;
  dom.descriptionAckCheckbox.checked = false;
  updateDescriptionConfirmEnabled();
}

function resetDescriptionControls() {
  clearDescriptionPreview();
  descriptionEdited = false;
  dom.descriptionInput.value = "";
  dom.descriptionInput.disabled = true;
  dom.descriptionLoading.hidden = true;
  dom.descriptionError.hidden = true;
  dom.descriptionResult.hidden = true;
  dom.descriptionResult.replaceChildren();
  dom.descriptionCheckButton.disabled = true;
}

/** Prefills the input with the app's real Description (from GET
 * /api/iris/web-apps/detail), unless the operator is mid-edit. */
function syncDescriptionFromDetail(app, detail) {
  const current = detail && typeof detail.Description === "string" ? detail.Description : null;
  dom.descriptionInput.disabled = current === null;
  dom.descriptionCheckButton.disabled = current === null;
  if (!descriptionEdited) dom.descriptionInput.value = current ?? "";
  dom.descriptionAckText.textContent = `I understand this will change the Description of ${app.Name} on the IRIS instance.`;
}

function showDescriptionError(message) {
  dom.descriptionErrorText.textContent = message;
  dom.descriptionError.hidden = false;
}

async function handleDescriptionCheckClick() {
  const app = allWebApps.find((entry) => entry.Name === currentDrawerName);
  if (!app) return;

  const fields = { Name: app.Name, Description: dom.descriptionInput.value };
  clearDescriptionPreview();
  dom.descriptionError.hidden = true;
  dom.descriptionResult.hidden = true;
  dom.descriptionCheckButton.disabled = true;
  dom.descriptionLoadingText.textContent = "Checking with IRIS (dry run)…";
  dom.descriptionLoading.hidden = false;

  try {
    const preview = await IrisApi.updateWebAppDescription(fields, true, true);
    if (currentDrawerName !== fields.Name || dom.descriptionInput.value !== fields.Description) return;
    const handlerResult = preview && preview.handler_result;
    if (preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
      pendingDescriptionFields = fields;
      dom.descriptionPreviewText.textContent = handlerResult.detail;
      dom.descriptionConfirm.hidden = false;
      updateDescriptionConfirmEnabled();
    } else {
      // Unauthorized, protected, no-op, too long, unknown app… shown exactly
      // as the backend explained it.
      showDescriptionError(
        (handlerResult && handlerResult.detail) || preview.detail || "This change could not be validated against IRIS.",
      );
    }
  } catch (err) {
    showDescriptionError(
      err instanceof ApiError
        ? "Could not reach the Command Center backend to check this change."
        : "An unexpected error occurred while checking this change.",
    );
  } finally {
    dom.descriptionLoading.hidden = true;
    dom.descriptionCheckButton.disabled = false;
  }
}

function renderDescriptionResult(result) {
  const rows = [
    ["Status", textOrPlaceholder(result.status)],
    ["Detail", textOrPlaceholder(result.detail)],
  ];
  if (result.handler_result) rows.push(["Execution Detail", textOrPlaceholder(result.handler_result.detail)]);
  if (result.verification) {
    rows.push(["Verification Status", textOrPlaceholder(result.verification.status)]);
    rows.push(["Verification Detail", textOrPlaceholder(result.verification.detail)]);
  }
  dom.descriptionResult.replaceChildren(...rows.map(([label, value]) => makeInfoRow(label, null, value, "text")));
  dom.descriptionResult.hidden = false;
}

/**
 * The ONLY place in this file that sends a real Description change —
 * reachable only via the confirm button, which is enabled only after a
 * successful preview of exactly the typed text and the acknowledgment.
 */
async function submitDescription() {
  const fields = pendingDescriptionFields;
  if (!fields) return;

  clearDescriptionPreview();
  dom.descriptionCheckButton.disabled = true;
  dom.descriptionLoadingText.textContent = "Updating description…";
  dom.descriptionLoading.hidden = false;

  let result;
  try {
    result = await IrisApi.updateWebAppDescription(fields, true, false);
  } catch (err) {
    result = {
      status: "request_failed",
      detail:
        err instanceof ApiError
          ? "Could not reach the Command Center backend to change this web application."
          : "An unexpected error occurred while changing this web application.",
    };
  }
  dom.descriptionLoading.hidden = true;
  dom.descriptionCheckButton.disabled = false;
  if (currentDrawerName === fields.Name) renderDescriptionResult(result);

  if (result.status === "success" || result.status === "verification_failed") {
    // Re-read the real data; the drawer re-renders (same app, so the result
    // above stays visible) and the input is refilled from IRIS.
    descriptionEdited = false;
    await loadWebApps();
  }
}

// --- REST Endpoints tab ---

function trimmedOrNull(value) {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function makeMethodBadge(method) {
  const badge = document.createElement("span");
  badge.className = "method-badge";
  // Colour is keyed by IRIS's own verb, lower-cased (see styles.css).
  badge.dataset.method = String(method || "").toLowerCase();
  badge.textContent = textOrPlaceholder(method);
  return badge;
}

function setDrawerTab(tab) {
  const app = allWebApps.find((entry) => entry.Name === currentDrawerName);
  const restAvailable = Boolean(app) && kindOf(app) === "REST";
  activeDrawerTab = tab === "rest" && restAvailable ? "rest" : "config";
  const isRest = activeDrawerTab === "rest";

  dom.tabConfig.setAttribute("aria-selected", String(!isRest));
  dom.tabRest.setAttribute("aria-selected", String(isRest));
  dom.tabConfig.tabIndex = isRest ? -1 : 0;
  dom.tabRest.tabIndex = isRest ? 0 : -1;
  dom.panelConfig.hidden = isRest;
  dom.panelRest.hidden = !isRest;
  dom.drawer.classList.toggle("ns-drawer--xwide", isRest);

  if (isRest) loadRestEndpoints(currentDrawerName);
}

function resetRestPanel() {
  restRequestSeq += 1; // discard any in-flight route-map response
  currentRouteMap = null;
  currentEndpointIndex = null;
  dom.restLoading.hidden = true;
  dom.restError.hidden = true;
  dom.restUnavailable.hidden = true;
  dom.restContent.hidden = true;
  dom.restList.replaceChildren();
  dom.restSearch.value = "";
  dom.restMethod.value = "";
  showEndpointList();
}

/** Fetches (or reuses) the route map for `name` and renders it. Only the
 * most recent request's result is ever rendered. */
async function loadRestEndpoints(name) {
  const cached = restCache.get(name);
  if (cached) {
    renderRestResult(cached);
    return;
  }
  if (!dom.restLoading.hidden) return; // this app's request is already in flight

  const seq = ++restRequestSeq;
  dom.restError.hidden = true;
  dom.restUnavailable.hidden = true;
  dom.restContent.hidden = true;
  dom.restLoading.hidden = false;

  try {
    const response = await IrisApi.getWebAppRestEndpoints(name);
    if (seq !== restRequestSeq) return;
    const routeMap = response && response.result;
    if (!routeMap || !Array.isArray(routeMap.endpoints)) {
      dom.restErrorText.textContent = "IRIS did not return the expected REST route map.";
      dom.restError.hidden = false;
      return;
    }
    const entry = { routeMap };
    restCache.set(name, entry);
    renderRestResult(entry);
  } catch (err) {
    if (seq !== restRequestSeq) return;
    if (err instanceof ApiError && err.status === 404) {
      // The backend's 404 means IRIS itself has no route map for this app
      // (observed live for /api/interop-editors) — a real, cacheable
      // answer, not a transient failure.
      const entry = {
        unavailable:
          "IRIS's API Management API returned no REST route map for this application, so its endpoints cannot be listed here.",
      };
      restCache.set(name, entry);
      renderRestResult(entry);
      return;
    }
    dom.restErrorText.textContent =
      err instanceof ApiError
        ? "Could not load this application's REST route map."
        : "An unexpected error occurred while loading this application's REST route map.";
    dom.restError.hidden = false;
  } finally {
    if (seq === restRequestSeq) dom.restLoading.hidden = true;
  }
}

function renderRestResult(entry) {
  dom.restLoading.hidden = true;
  dom.restError.hidden = true;
  if (entry.unavailable) {
    currentRouteMap = null;
    dom.restContent.hidden = true;
    dom.restUnavailable.textContent = entry.unavailable;
    dom.restUnavailable.hidden = false;
    return;
  }
  dom.restUnavailable.hidden = true;
  if (currentRouteMap === entry.routeMap) return; // already rendered; keep filters/detail
  currentRouteMap = entry.routeMap;
  currentEndpointIndex = null;

  const routeMap = entry.routeMap;
  dom.restMeta.replaceChildren(
    makeInfoRow("Dispatch Class", null, textOrPlaceholder(routeMap.dispatchClass), "mono"),
    makeInfoRow("Namespace", null, textOrPlaceholder(routeMap.namespace), "text"),
    makeInfoRow("Base Path", null, textOrPlaceholder(routeMap.basePath), "mono"),
    makeInfoRow("Endpoints", null, String(routeMap.endpoints.length), "text"),
    makeInfoRow("Spec Format", null, routeMap.swagger ? `Swagger ${routeMap.swagger}` : PLACEHOLDER, "text"),
  );

  const methods = [...new Set(routeMap.endpoints.map((e) => e.method).filter(Boolean))].sort();
  populateSelect(dom.restMethod, "All methods", methods);
  showEndpointList();
  renderEndpointList();
  dom.restContent.hidden = false;
}

function endpointMatches(endpoint, query, method) {
  if (method && endpoint.method !== method) return false;
  if (!query) return true;
  return [endpoint.path, endpoint.serviceMethod, endpoint.operationId, endpoint.summary]
    .some((value) => typeof value === "string" && value.toLowerCase().includes(query));
}

function renderEndpointList() {
  if (!currentRouteMap) return;
  const query = dom.restSearch.value.trim().toLowerCase();
  const method = dom.restMethod.value;
  const endpoints = currentRouteMap.endpoints;

  dom.restList.replaceChildren();
  let shown = 0;
  endpoints.forEach((endpoint, index) => {
    if (!endpointMatches(endpoint, query, method)) return;
    shown += 1;
    const item = document.createElement("li");
    item.className = "endpoint-list__item";
    item.dataset.index = String(index);
    item.tabIndex = 0;
    item.setAttribute("role", "button");
    item.setAttribute(
      "aria-label",
      `View endpoint ${textOrPlaceholder(endpoint.method)} ${textOrPlaceholder(endpoint.path)}`,
    );

    const path = document.createElement("span");
    path.className = "endpoint-list__path";
    path.textContent = textOrPlaceholder(endpoint.path);
    path.title = path.textContent;

    const service = document.createElement("span");
    service.className = "endpoint-list__service";
    service.textContent = textOrPlaceholder(endpoint.serviceMethod);
    service.title = `Implementing method: ${service.textContent}`;

    item.append(makeMethodBadge(endpoint.method), path, service);
    dom.restList.append(item);
  });

  const filtered = query !== "" || method !== "";
  dom.restList.hidden = shown === 0;
  dom.restFilterEmpty.hidden = shown !== 0;
  dom.restCount.textContent = filtered
    ? `Showing ${shown} of ${endpoints.length}`
    : `Showing all ${endpoints.length}`;
}

function showEndpointList() {
  dom.restDetailView.hidden = true;
  dom.restListView.hidden = false;
}

function formatParameterType(param) {
  if (param.bodySchema) return JSON.stringify(param.bodySchema);
  return textOrPlaceholder(param.type);
}

function showEndpointDetail(index) {
  const endpoint = currentRouteMap && currentRouteMap.endpoints[index];
  if (!endpoint) return;
  currentEndpointIndex = index;

  dom.restDetailMethod.dataset.method = String(endpoint.method || "").toLowerCase();
  dom.restDetailMethod.textContent = textOrPlaceholder(endpoint.method);
  dom.restDetailPath.textContent = textOrPlaceholder(endpoint.path);

  const basePath = currentRouteMap.basePath || "";
  dom.restDetailFields.replaceChildren(
    makeInfoRow("Full Path", null, textOrPlaceholder(`${basePath}${endpoint.path || ""}`), "mono"),
    makeInfoRow("Implementing Method", "x-ISC_ServiceMethod", textOrPlaceholder(endpoint.serviceMethod), "mono"),
    makeInfoRow("Dispatch Class", null, textOrPlaceholder(currentRouteMap.dispatchClass), "mono"),
    makeInfoRow("Operation ID", "operationId", textOrPlaceholder(endpoint.operationId), "mono"),
    makeInfoRow("Summary", "summary", textOrPlaceholder(trimmedOrNull(endpoint.summary)), "text"),
  );

  const params = Array.isArray(endpoint.parameters) ? endpoint.parameters : [];
  dom.restDetailParams.replaceChildren();
  for (const param of params) {
    const row = document.createElement("tr");
    // An unresolvable $ref is shown verbatim, never guessed into a name.
    const nameText = param.ref ? `${param.ref} (unresolved)` : textOrPlaceholder(param.name);
    row.append(
      makeCell(nameText, { mono: true }),
      makeCell(textOrPlaceholder(param.location)),
      makeCell(formatBoolean(param.required)),
      makeCell(formatParameterType(param), { mono: true }),
      makeCell(textOrPlaceholder(param.pattern), { mono: true }),
    );
    dom.restDetailParams.append(row);
  }
  dom.restDetailNoParams.hidden = params.length !== 0;
  dom.restDetailParamsWrapper.hidden = params.length === 0;

  const description = trimmedOrNull(endpoint.description);
  dom.restDetailDescription.textContent = description || "";
  dom.restDetailDescriptionSection.hidden = description === null;

  dom.restListView.hidden = true;
  dom.restDetailView.hidden = false;
  dom.drawer.scrollTop = 0;
  dom.restBack.focus();
}

function backToEndpointList() {
  const index = currentEndpointIndex;
  currentEndpointIndex = null;
  showEndpointList();
  const item = index === null ? null : dom.restList.querySelector(`[data-index="${index}"]`);
  if (item) item.focus();
}

function openDrawer(name) {
  const app = allWebApps.find((entry) => entry.Name === name);
  if (!app) return;
  const isSameApp = currentDrawerName === app.Name;
  currentDrawerName = app.Name;
  renderDrawerSummary(app);

  // The REST Endpoints tab exists only for REST apps (DispatchClass set).
  dom.drawerTabs.hidden = kindOf(app) !== "REST";
  if (!isSameApp) {
    resetRestPanel();
    resetEnableControls();
    resetDescriptionControls();
    activeDrawerTab = "config";
  }
  syncEnableControls(app);

  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (!isSameApp) dom.drawer.scrollTop = 0;
  if (wasHidden) dom.drawerClose.focus();
  setDrawerTab(activeDrawerTab);
  loadDrawerDetail(app.Name);
}

function closeDrawer() {
  currentDrawerName = null;
  detailRequestSeq += 1; // discard any in-flight detail response
  resetRestPanel();
  resetEnableControls();
  resetDescriptionControls();
  activeDrawerTab = "config";
  dom.drawer.classList.remove("ns-drawer--xwide");
  dom.drawerLoading.hidden = true;
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

function renderWebApps(webApps) {
  if (!Array.isArray(webApps) || webApps.length === 0) {
    allWebApps = [];
    dom.overview.hidden = true;
    dom.content.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    dom.tableBody.replaceChildren();
    closeDrawer();
    return;
  }

  allWebApps = webApps;
  // A Refresh re-reads route maps too; an open REST tab re-fetches below.
  restCache = new Map();
  currentRouteMap = null;
  dom.content.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${webApps.length} web app${webApps.length === 1 ? "" : "s"}`;

  populateFilters();
  renderSummary(webApps);
  renderOverview(webApps);
  renderTable();

  // After a refresh, re-open (and re-fetch) the drawer's app with fresh
  // data — or close it honestly if that app no longer exists.
  if (currentDrawerName !== null) {
    if (allWebApps.some((app) => app.Name === currentDrawerName)) openDrawer(currentDrawerName);
    else closeDrawer();
  }
}

// --- Web Sessions (read-only) ---

/** IRIS reports a session's Application with a trailing slash (observed
 * live: "/csp/sys/") while GET /v2/web-apps names have none ("/csp/sys"),
 * so both sides are compared without it. */
function normalizeAppName(name) {
  if (typeof name !== "string") return "";
  return name.length > 1 ? name.replace(/\/+$/, "") : name;
}

/** The configured web app a session belongs to, or null when no app in
 * the last fetched list has that name. */
function webAppForSession(session) {
  const target = normalizeAppName(session.Application);
  if (!target) return null;
  return allWebApps.find((app) => normalizeAppName(app.Name) === target) || null;
}

function sessionsForApp(app) {
  if (!Array.isArray(allSessions)) return null;
  const target = normalizeAppName(app.Name);
  return allSessions.filter((session) => normalizeAppName(session.Application) === target);
}

/** Fetches GET /api/iris/web-sessions. Never throws — returns either
 * { sessions } or { error } so a sessions failure never breaks the app list. */
async function fetchWebSessions() {
  try {
    const response = await IrisApi.getWebSessions();
    if (response && Array.isArray(response.result)) return { sessions: response.result };
    return { error: "IRIS did not return the expected web session information." };
  } catch (err) {
    return {
      error:
        err instanceof ApiError
          ? "Could not load web sessions."
          : "An unexpected error occurred while loading web sessions.",
    };
  }
}

function renderSessionsResult(result) {
  dom.sessionsLoading.hidden = true;
  if (result.error) {
    allSessions = null;
    dom.sessionsErrorText.textContent = result.error;
    dom.sessionsError.hidden = false;
    dom.sessionsContent.hidden = true;
    dom.sessionsEmpty.hidden = true;
    closeSessionDrawer();
  } else {
    allSessions = result.sessions;
    dom.sessionsError.hidden = true;
    dom.sessionsEmpty.hidden = allSessions.length !== 0;
    dom.sessionsContent.hidden = allSessions.length === 0;
    if (allSessions.length > 0) {
      renderSessionsSummary();
      populateSessionFilters();
      renderSessionsTable();
    }
    // A position-identified session can't be matched across a refresh, so
    // an open session drawer is closed rather than showing another session.
    closeSessionDrawer();
  }
  // The open app drawer's "Active Sessions" count depends on this list.
  if (currentDrawerName !== null) {
    const app = allWebApps.find((entry) => entry.Name === currentDrawerName);
    if (app) renderDrawerSummary(app);
  }
}

function makeStatCard(label, value, accent) {
  const card = document.createElement("article");
  card.className = "stat-card";
  card.style.setProperty("--stat-card-accent", accent);
  const labelEl = document.createElement("h3");
  labelEl.className = "stat-card__label";
  labelEl.textContent = label;
  const valueEl = document.createElement("p");
  valueEl.className = "stat-card__value";
  valueEl.textContent = String(value);
  card.append(labelEl, valueEl);
  return card;
}

/** Aggregate counts, each computed from the fetched list — nothing invented. */
function renderSessionsSummary() {
  const distinct = (field) => new Set(allSessions.map((s) => s[field])).size;
  dom.sessionsSummaryGrid.replaceChildren(
    makeStatCard("Sessions", allSessions.length, "var(--color-accent)"),
    makeStatCard("Users", distinct("Username"), "var(--color-chart-2)"),
    makeStatCard("Applications", distinct("Application"), "var(--color-chart-6)"),
    makeStatCard(
      "Preserved",
      allSessions.filter((s) => typeof s.Preserve === "number" && s.Preserve !== 0).length,
      "var(--color-chart-4)",
    ),
  );
}

function populateSessionFilters() {
  const values = (field) =>
    [...new Set(allSessions.map((s) => s[field]).filter((v) => typeof v === "string" && v !== ""))].sort();
  populateSelect(dom.sessionsFilterApp, "All applications", values("Application"));
  populateSelect(dom.sessionsFilterUser, "All users", values("Username"));
}

// Fields the free-text session search matches — never an ID (none exists here).
const SESSION_SEARCH_FIELDS = ["Username", "Application", "LicenseId", "SesProcessId", "Timeout"];

function renderSessionsTable() {
  if (!Array.isArray(allSessions)) return;
  const query = dom.sessionsFilterSearch.value.trim().toLowerCase();
  const appFilter = dom.sessionsFilterApp.value;
  const userFilter = dom.sessionsFilterUser.value;

  dom.sessionsTableBody.replaceChildren();
  let shown = 0;
  allSessions.forEach((session, index) => {
    if (appFilter && session.Application !== appFilter) return;
    if (userFilter && session.Username !== userFilter) return;
    if (
      query &&
      !SESSION_SEARCH_FIELDS.some((field) => String(session[field] ?? "").toLowerCase().includes(query))
    ) {
      return;
    }
    shown += 1;

    const row = document.createElement("tr");
    row.className = "data-table__row--clickable";
    row.dataset.sessionIndex = String(index);
    row.tabIndex = 0;
    row.setAttribute(
      "aria-label",
      `View details for the web session of ${textOrPlaceholder(session.Username)} on ${textOrPlaceholder(session.Application)}`,
    );

    const app = webAppForSession(session);
    row.append(
      makeCell(textOrPlaceholder(session.Username)),
      makeCell(textOrPlaceholder(session.Application), { mono: true }),
      makeCell(app ? app.Name : "Not listed", { mono: Boolean(app) }),
      makeCell(textOrPlaceholder(session.Timeout), { mono: true }),
      makeCell(textOrPlaceholder(session.LicenseId), { mono: true }),
      makeCell(textOrPlaceholder(session.SesProcessId), { mono: true }),
      makeCell(textOrPlaceholder(session.Preserve), { mono: true }),
    );
    dom.sessionsTableBody.append(row);
  });

  const filtered = query !== "" || appFilter !== "" || userFilter !== "";
  dom.sessionsTableWrapper.hidden = shown === 0;
  dom.sessionsFilterEmpty.hidden = shown !== 0;
  dom.sessionsFilterClear.disabled = !filtered;
  dom.sessionsFilterCount.textContent = filtered
    ? `Showing ${shown} of ${allSessions.length}`
    : `Showing all ${allSessions.length}`;
}

function openSessionDrawer(index) {
  const session = Array.isArray(allSessions) ? allSessions[index] : null;
  if (!session) return;
  currentSessionIndex = index;

  dom.sessionDrawerTitle.textContent = session.Username ? session.Username : "(no username)";
  dom.sessionDrawerAppBadge.textContent = textOrPlaceholder(session.Application);
  dom.sessionDrawerFields.replaceChildren(
    ...SESSION_FIELDS.map(([label, field, kind]) =>
      makeInfoRow(label, field, formatValue(session[field], kind), kind),
    ),
  );

  const app = webAppForSession(session);
  if (app) {
    const [statusText] = statusBadge(app.Enabled);
    dom.sessionDrawerApp.replaceChildren(
      makeInfoRow("Name", null, textOrPlaceholder(app.Name), "mono"),
      makeInfoRow("Kind", null, kindOf(app), "text"),
      makeInfoRow("Status", null, statusText, "text"),
      makeInfoRow("Namespace", null, textOrPlaceholder(app.Namespace), "text"),
    );
  } else {
    dom.sessionDrawerApp.replaceChildren(
      makeInfoRow(
        "Name",
        null,
        "No web app with this name in the current web app list",
        "text",
      ),
    );
  }
  dom.sessionDrawerOpenApp.hidden = !app;
  dom.sessionDrawerOpenApp.dataset.appName = app ? app.Name : "";

  const wasHidden = dom.sessionDrawer.hidden;
  dom.sessionDrawerBackdrop.hidden = false;
  dom.sessionDrawer.hidden = false;
  if (wasHidden) dom.sessionDrawerClose.focus();
}

function closeSessionDrawer() {
  currentSessionIndex = null;
  dom.sessionDrawerBackdrop.hidden = true;
  dom.sessionDrawer.hidden = true;
}

/**
 * Fetches GET /api/iris/web-apps and renders it. No mutating request exists
 * anywhere in this file.
 */
export async function loadWebApps() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  // Sessions load in parallel but render after the list, since each is
  // matched to a web app by name. A newer load supersedes an older one.
  const sessionsSeq = ++sessionsLoadSeq;
  dom.sessionsLoading.hidden = false;
  dom.sessionsError.hidden = true;
  const sessionsPromise = fetchWebSessions();

  let response;
  try {
    response = await IrisApi.getWebApps();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load web application information. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading web application information.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderWebApps(null);
    setLoading(false);
    return;
  }

  const webApps = response && Array.isArray(response.result) ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (webApps === null) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected web application information.");
    renderWebApps(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in system.js/processes.js/databases.js.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  renderWebApps(webApps);
  const sessionsResult = await sessionsPromise;
  if (sessionsSeq === sessionsLoadSeq) renderSessionsResult(sessionsResult);
  setLoading(false);
}

export function initWebAppsControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadWebApps();
  });
  dom.backButton.addEventListener("click", () => {
    navigateTo("dashboard");
  });

  // Filtering is purely client-side over the last fetched list — instant,
  // and never a new request.
  dom.filterForm.addEventListener("submit", (event) => event.preventDefault());
  dom.filterSearch.addEventListener("input", renderTable);
  for (const select of [dom.filterKind, dom.filterStatus, dom.filterNamespace, dom.filterAuth]) {
    select.addEventListener("change", renderTable);
  }
  dom.filterClear.addEventListener("click", () => {
    dom.filterSearch.value = "";
    for (const select of [dom.filterKind, dom.filterStatus, dom.filterNamespace, dom.filterAuth]) {
      select.value = "";
    }
    renderTable();
  });

  // Event delegation for KPI cards and table rows — the same pattern
  // processes.js/databases.js/namespaces.js use.
  dom.summaryGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".stat-card");
    if (card) applyCardFilter(Number(card.dataset.cardIndex));
  });
  dom.summaryGrid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".stat-card");
    if (!card) return;
    event.preventDefault();
    applyCardFilter(Number(card.dataset.cardIndex));
  });

  dom.tableBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-name]");
    if (row) openDrawer(row.dataset.name);
  });
  dom.tableBody.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("tr[data-name]");
    if (!row) return;
    event.preventDefault();
    openDrawer(row.dataset.name);
  });

  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!dom.sessionDrawer.hidden) closeSessionDrawer();
    else if (!dom.drawer.hidden) closeDrawer();
  });

  // Drawer tabs (REST apps only), with arrow-key switching per the WAI-ARIA
  // tabs pattern.
  dom.tabConfig.addEventListener("click", () => setDrawerTab("config"));
  dom.tabRest.addEventListener("click", () => setDrawerTab("rest"));
  dom.drawerTabs.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    setDrawerTab(activeDrawerTab === "rest" ? "config" : "rest");
    (activeDrawerTab === "rest" ? dom.tabRest : dom.tabConfig).focus();
  });

  // REST endpoint filtering is client-side over the cached route map.
  dom.restFilterForm.addEventListener("submit", (event) => event.preventDefault());
  dom.restSearch.addEventListener("input", renderEndpointList);
  dom.restMethod.addEventListener("change", renderEndpointList);
  dom.restList.addEventListener("click", (event) => {
    const item = event.target.closest(".endpoint-list__item");
    if (item) showEndpointDetail(Number(item.dataset.index));
  });
  dom.restList.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const item = event.target.closest(".endpoint-list__item");
    if (!item) return;
    event.preventDefault();
    showEndpointDetail(Number(item.dataset.index));
  });
  dom.restBack.addEventListener("click", backToEndpointList);

  // Enabled State (web_app.set_enabled): dry-run check, acknowledgment,
  // then the one real request.
  dom.enableCheckButton.addEventListener("click", () => {
    handleEnableCheckClick();
  });
  dom.enableAckCheckbox.addEventListener("change", updateEnableConfirmEnabled);
  dom.enableConfirmButton.addEventListener("click", () => {
    submitEnable();
  });

  // Description (web_app.update_description): dry-run check of the typed
  // text, acknowledgment, then the one real request. Editing the text
  // discards a preview of different text.
  dom.descriptionInput.addEventListener("input", () => {
    descriptionEdited = true;
    if (pendingDescriptionFields && pendingDescriptionFields.Description !== dom.descriptionInput.value) {
      clearDescriptionPreview();
    }
  });
  dom.descriptionCheckButton.addEventListener("click", () => {
    handleDescriptionCheckClick();
  });
  dom.descriptionAckCheckbox.addEventListener("change", updateDescriptionConfirmEnabled);
  dom.descriptionConfirmButton.addEventListener("click", () => {
    submitDescription();
  });

  // Web Sessions: client-side filtering over the last fetched list, and a
  // read-only detail drawer (no session actions exist anywhere here).
  dom.sessionsFilterForm.addEventListener("submit", (event) => event.preventDefault());
  dom.sessionsFilterSearch.addEventListener("input", renderSessionsTable);
  dom.sessionsFilterApp.addEventListener("change", renderSessionsTable);
  dom.sessionsFilterUser.addEventListener("change", renderSessionsTable);
  dom.sessionsFilterClear.addEventListener("click", () => {
    dom.sessionsFilterSearch.value = "";
    dom.sessionsFilterApp.value = "";
    dom.sessionsFilterUser.value = "";
    renderSessionsTable();
  });
  dom.sessionsTableBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-session-index]");
    if (row) openSessionDrawer(Number(row.dataset.sessionIndex));
  });
  dom.sessionsTableBody.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("tr[data-session-index]");
    if (!row) return;
    event.preventDefault();
    openSessionDrawer(Number(row.dataset.sessionIndex));
  });
  dom.sessionDrawerClose.addEventListener("click", closeSessionDrawer);
  dom.sessionDrawerBackdrop.addEventListener("click", closeSessionDrawer);
  dom.sessionDrawerOpenApp.addEventListener("click", () => {
    const name = dom.sessionDrawerOpenApp.dataset.appName;
    closeSessionDrawer();
    if (name) openDrawer(name);
  });
}
