// Web Apps view: a read-only Web Apps Explorer — KPI cards, the Enabled/
// Disabled strip, a client-side search/filter toolbar, a compact table,
// and a detail drawer. It calls exactly two read-only endpoints:
//   - GET /api/iris/web-apps (the list; IrisApi.getWebApps()), and
//   - GET /api/iris/web-apps/detail?name= (one app's full configuration,
//     fetched only when its drawer opens; IrisApi.getWebAppDetail()).
// No mutating HTTP method is used anywhere in this module, and there are
// deliberately no web-app actions (enable/disable/edit/delete).
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

  dom.drawerSummary.replaceChildren(
    ...SUMMARY_FIELDS.map(([label, field, kindOfValue]) =>
      makeInfoRow(label, null, formatValue(app[field], kindOfValue), kindOfValue),
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

function openDrawer(name) {
  const app = allWebApps.find((entry) => entry.Name === name);
  if (!app) return;
  currentDrawerName = app.Name;
  renderDrawerSummary(app);

  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawer.scrollTop = 0;
  if (wasHidden) dom.drawerClose.focus();
  loadDrawerDetail(app.Name);
}

function closeDrawer() {
  currentDrawerName = null;
  detailRequestSeq += 1; // discard any in-flight detail response
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

/**
 * Fetches GET /api/iris/web-apps and renders it. No mutating request exists
 * anywhere in this file.
 */
export async function loadWebApps() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

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
    if (event.key === "Escape" && !dom.drawer.hidden) closeDrawer();
  });
}
