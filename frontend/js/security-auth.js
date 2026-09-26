// Security page, Authentication tab: summary cards, web authentication
// settings, services, superservers and class access, with service and
// superserver details in the shared drawer (security-access.js).
//
// Uses getSecurityServices / getSecurityServiceDetail, getSecurityWebAuth
// (SMTPUsername and TwoFactorFrom are withheld by the backend),
// getSecuritySuperservers (already merged with details) and
// getSecurityClassAccess.
//
// Loads the first time the tab is shown, then on Refresh or when the page
// is reopened.

import { IrisApi, ApiError } from "./api.js";
import { openSecurityDrawer, registerSecurityDrawerRenderer, securityUi as ui } from "./security-access.js";

const PLACEHOLDER = "—";
const $ = (id) => document.getElementById(id);

const dom = {
  refreshButton: $("security-refresh-button"),
  tabs: $("security-access-tabs"),
  panel: $("security-panel-authentication"),
  errorBanner: $("security-auth-error-banner"),
  errorBannerText: $("security-auth-error-banner-text"),
  loading: $("security-auth-loading"),
  content: $("security-auth-content"),
  summaryGrid: $("security-auth-summary-grid"),
  webAuthUnavailable: $("security-web-auth-unavailable"),
  webAuthMethods: $("security-web-auth-methods"),
  webAuthSettings: $("security-web-auth-settings"),
  services: {
    form: $("security-services-filter-form"),
    search: $("security-services-search"),
    status: $("security-services-status"),
    method: $("security-services-method"),
    clear: $("security-services-clear"),
    count: $("security-services-count"),
    empty: $("security-services-empty"),
    wrapper: $("security-services-table-wrapper"),
    body: $("security-services-table-body"),
  },
  superserversEmpty: $("security-superservers-empty"),
  superserversWrapper: $("security-superservers-table-wrapper"),
  superserversBody: $("security-superservers-table-body"),
  classAccess: {
    form: $("security-class-access-filter-form"),
    search: $("security-class-access-search"),
    count: $("security-class-access-count"),
    empty: $("security-class-access-empty"),
    wrapper: $("security-class-access-table-wrapper"),
    body: $("security-class-access-table-body"),
  },
};

// Web authentication switches. The tooltip shows the IRIS field name.
const WEB_AUTH_METHODS = [
  ["AutheUnauthenticated", "Unauthenticated"],
  ["AutheCache", "Instance authentication"],
  ["AutheOS", "Operating system"],
  ["AutheOSDelegated", "OS-based delegated"],
  ["AutheOSLDAP", "OS-based LDAP"],
  ["AutheKB", "Kerberos"],
  ["AutheLDAP", "LDAP"],
  ["AutheLDAPCache", "LDAP cached credentials"],
  ["AutheDelegated", "Delegated"],
  ["AutheAlwaysTryDelegated", "Always try delegated"],
  ["AutheOAuth2", "OAuth 2.0"],
  ["AutheLoginToken", "Login token"],
  ["AutheTwoFactorSMS", "Two-factor: SMS"],
  ["AutheTwoFactorPW", "Two-factor: time-based one-time password"],
];

// AutheEnabled bits for services.
const SERVICE_AUTHE_BITS = [
  [0, "AutheK5CCache"],
  [1, "AutheK5Prompt"],
  [2, "AutheK5API"],
  [3, "AutheK5KeyTab"],
  [4, "AutheOS"],
  [5, "AuthePassword"],
  [6, "AutheUnauthenticated"],
  [7, "AutheKB"],
  [8, "AutheKBEncryption"],
  [9, "AutheKBIntegrity"],
  [10, "AutheSystem"],
  [11, "AutheLDAP"],
  [13, "AutheDelegated"],
  [14, "AutheLoginToken"],
  [20, "TwoFactorSMS"],
  [21, "TwoFactorPW"],
  [25, "MutualTLS"],
];

// SSLSupportLevel: 0 = None, 1 = Accept, 2 = Require.
const TLS_LEVELS = { 0: ["None", "status-badge--warning"], 1: ["Accept", "status-badge--neutral"], 2: ["Require", "status-badge--ok"] };

const SUPERSERVER_PROTOCOLS = [
  ["EnableClients", "Clients"],
  ["EnableCSP", "CSP / Web Gateway"],
  ["EnableECP", "ECP"],
  ["EnableMirror", "Mirror"],
  ["EnableSharding", "Sharding"],
  ["EnableDataCheck", "DataCheck"],
  ["EnableShadows", "Shadows"],
  ["EnableCacheDirect", "Cache Direct"],
  ["EnableNodeJS", "Node.js"],
  ["EnableSNMP", "SNMP"],
  ["EnableWebLink", "WebLink"],
];

let services = null; // null = not loaded or failed
let webAuth = null;
let superservers = null;
let classAccess = null;
let loaded = false;
let loadSeq = 0;
let summaryActions = [];

// --- helpers ---

function badgeList(items) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  if (items.length === 0) {
    cell.textContent = PLACEHOLDER;
    return cell;
  }
  items.forEach(([text, variant], i) => {
    if (i > 0) cell.append(" ");
    cell.append(ui.makeBadge(text, variant));
  });
  return cell;
}

function methodVariant(method) {
  return method === "Unauthenticated" ? "status-badge--warning" : "status-badge--neutral";
}

function enabledBadge(enabled) {
  return enabled ? ui.makeBadge("Enabled", "status-badge--ok") : ui.makeBadge("Disabled", "status-badge--neutral");
}

function tlsBadge(level) {
  const [text, variant] = TLS_LEVELS[level] || [`Level ${level}`, "status-badge--neutral"];
  return ui.makeBadge(text, variant);
}

function formatAllowedConnections(list) {
  // Empty means no restrictions.
  return Array.isArray(list) && list.length > 0 ? list.join(", ") : "Unrestricted";
}

function decodeServiceBits(value) {
  if (typeof value !== "number") return PLACEHOLDER;
  const names = SERVICE_AUTHE_BITS.filter(([bit]) => Math.floor(value / 2 ** bit) % 2 === 1).map(([, n]) => n);
  let known = 0;
  for (const [bit] of SERVICE_AUTHE_BITS) known += 2 ** bit;
  if (value - (value & known) !== 0 || value > 2 ** 31) names.push("other bits");
  return `${names.length ? names.join(", ") : "None"} (${value})`;
}

function superserverKey(server) {
  return `${server.BindAddress}:${server.Port}`;
}

function onOffItem(label, field, on, { warnWhenOn = false } = {}) {
  const item = document.createElement("li");
  item.className = "privilege-list__item";
  const name = document.createElement("span");
  name.className = "privilege-list__name";
  name.textContent = label;
  name.title = field;
  const value = ui.makeBadge(on ? "On" : "Off", on ? (warnWhenOn ? "status-badge--warning" : "status-badge--ok") : "status-badge--neutral");
  item.append(name, value);
  return item;
}

// --- summary cards ---

function renderSummary() {
  const enabled = services ? services.filter((s) => s.Enabled) : null;
  const withMethod = (method, list) => (list ? list.filter((s) => s.AuthenticationMethods.includes(method)).length : null);
  const unauthEnabled = withMethod("Unauthenticated", enabled);
  const unauthAll = withMethod("Unauthenticated", services);
  const defaultServer = superservers ? superservers.find((s) => s.SystemDefault) || superservers[0] : null;

  const cards = [
    {
      label: "Enabled Services",
      value: enabled ? enabled.length : null,
      meta: services ? `of ${services.length} services` : null,
      accent: "var(--color-chart-3)",
      action: () => filterServices({ status: "enabled", method: "" }),
    },
    {
      label: "Unauthenticated Services",
      value: unauthEnabled,
      meta: unauthAll !== null ? `enabled · ${unauthAll - unauthEnabled} more disabled` : null,
      accent: unauthEnabled ? "var(--color-warning)" : "var(--color-chart-neutral)",
      action: () => filterServices({ status: "enabled", method: "Unauthenticated" }),
    },
    {
      label: "OS-Auth Services",
      value: withMethod("Operating System", enabled),
      meta: enabled ? "enabled, allow Operating System" : null,
      accent: "var(--color-chart-2)",
      action: () => filterServices({ status: "enabled", method: "Operating System" }),
    },
    {
      label: "Two-Factor Services",
      value: services ? services.filter((s) => s.TwoFactorEnabled).length : null,
      meta: services ? "TwoFactorEnabled" : null,
      accent: "var(--color-chart-6)",
    },
    {
      label: "Web Unauthenticated",
      value: webAuth ? (webAuth.AutheUnauthenticated ? "Allowed" : "Off") : null,
      meta: webAuth ? "system-wide AutheUnauthenticated" : null,
      accent: webAuth && webAuth.AutheUnauthenticated ? "var(--color-warning)" : "var(--color-chart-3)",
    },
    {
      label: "Superserver Client TLS",
      value: defaultServer && defaultServer.Detail ? (TLS_LEVELS[defaultServer.Detail.SSLSupportLevel] || [`Level ${defaultServer.Detail.SSLSupportLevel}`])[0] : null,
      meta: defaultServer ? `${superserverKey(defaultServer)}${superservers.length > 1 ? ` · ${superservers.length} superservers` : ""}` : null,
      accent: defaultServer && defaultServer.Detail && defaultServer.Detail.SSLSupportLevel === 2 ? "var(--color-chart-3)" : "var(--color-warning)",
    },
    {
      label: "Class-Access Entries",
      value: classAccess ? classAccess.length : null,
      meta: classAccess ? `${classAccess.filter((e) => e.AllowAccess).length} allow · ${classAccess.filter((e) => e.System).length} system` : null,
      accent: "var(--color-accent)",
    },
  ];

  summaryActions = cards.map((card) => card.action || null);
  dom.summaryGrid.replaceChildren(
    ...cards.map((card, index) => {
      const el = document.createElement("article");
      el.className = card.action ? "stat-card stat-card--interactive" : "stat-card";
      el.style.setProperty("--stat-card-accent", card.accent);
      if (card.action) {
        el.setAttribute("role", "button");
        el.setAttribute("tabindex", "0");
        el.dataset.cardIndex = String(index);
        el.title = `Filter services: ${card.label}`;
      }
      const label = document.createElement("h3");
      label.className = "stat-card__label";
      label.textContent = card.label;
      const value = document.createElement("p");
      const unavailable = card.value === null || card.value === undefined;
      value.className = unavailable
        ? "stat-card__value stat-card__value--unavailable"
        : typeof card.value === "number"
          ? "stat-card__value"
          : "stat-card__value stat-card__value--mono";
      value.textContent = unavailable ? "Unavailable" : String(card.value);
      el.append(label, value);
      if (card.meta && !unavailable) {
        const meta = document.createElement("p");
        meta.className = "stat-card__meta";
        meta.textContent = card.meta;
        el.append(meta);
      }
      return el;
    }),
  );
}

function filterServices({ status, method }) {
  dom.services.status.value = status;
  if (method === "" || [...dom.services.method.options].some((o) => o.value === method)) {
    dom.services.method.value = method;
  }
  renderServicesTable();
  dom.services.form.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- web authentication ---

function renderWebAuth() {
  dom.webAuthUnavailable.hidden = webAuth !== null;
  if (!webAuth) {
    dom.webAuthMethods.replaceChildren();
    dom.webAuthSettings.replaceChildren();
    return;
  }
  dom.webAuthMethods.replaceChildren(
    ...WEB_AUTH_METHODS.map(([field, label]) =>
      onOffItem(label, field, webAuth[field] === true, { warnWhenOn: field === "AutheUnauthenticated" }),
    ),
  );
  const withheld = Array.isArray(webAuth.WithheldFields) ? webAuth.WithheldFields : [];
  const seconds = (value) => (typeof value === "number" ? `${value} s` : PLACEHOLDER);
  dom.webAuthSettings.replaceChildren(
    ui.makeInfoRow("Login Cookie Timeout", "LoginCookieTimeout", seconds(webAuth.LoginCookieTimeout), { mono: true }),
    ui.makeInfoRow("Two-Factor Timeout", "TwoFactorTimeout", seconds(webAuth.TwoFactorTimeout), { mono: true }),
    ui.makeInfoRow(
      "Two-Factor Sender",
      "TwoFactorFrom",
      withheld.includes("TwoFactorFrom") ? "Withheld by Command Center" : PLACEHOLDER,
    ),
    ui.makeInfoRow("SMTP Server", "SMTPServer", ui.textOrPlaceholder(webAuth.SMTPServer), { mono: true }),
    ui.makeInfoRow(
      "SMTP Username",
      "SMTPUsername",
      withheld.includes("SMTPUsername") ? "Withheld by Command Center" : PLACEHOLDER,
    ),
    ui.makeInfoRow("JWT Issuer", "JWTIssuer", ui.textOrPlaceholder(webAuth.JWTIssuer), { mono: true }),
    ui.makeInfoRow("JWT Signing Algorithm", "JWTSigAlg", ui.textOrPlaceholder(webAuth.JWTSigAlg), { mono: true }),
  );
}

// --- services ---

function renderServicesTable() {
  const c = dom.services;
  if (!services) {
    c.body.replaceChildren();
    c.wrapper.hidden = true;
    c.empty.hidden = false;
    c.empty.textContent = "Could not load services from IRIS.";
    c.count.textContent = "";
    return;
  }
  const query = c.search.value.trim().toLowerCase();
  const visible = services.filter((service) => {
    if (c.status.value === "enabled" && !service.Enabled) return false;
    if (c.status.value === "disabled" && service.Enabled) return false;
    if (c.method.value && !service.AuthenticationMethods.includes(c.method.value)) return false;
    if (!query) return true;
    return ui.includesText(service.Name, query) || ui.includesText(service.Description, query);
  });

  c.body.replaceChildren(
    ...visible.map((service) => {
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = "service";
      row.dataset.openName = service.Name;
      row.setAttribute("aria-label", `View service ${service.Name}`);
      const status = ui.makeBadgeCell(enabledBadge(service.Enabled));
      row.append(
        ui.makeCell(service.Name, { mono: true, title: service.Description }),
        status,
        badgeList(service.AuthenticationMethods.map((m) => [m, methodVariant(m)])),
        ui.makeCell(ui.textOrPlaceholder(service.Public)),
        ui.makeCell(ui.formatBoolean(service.TwoFactorEnabled)),
        ui.makeCell(formatAllowedConnections(service.AllowedConnections)),
      );
      return row;
    }),
  );

  const filtered = query !== "" || c.status.value !== "" || c.method.value !== "";
  c.wrapper.hidden = visible.length === 0;
  c.empty.hidden = visible.length !== 0;
  c.empty.textContent = services.length === 0 ? "IRIS reports no services." : "No services match the current filters.";
  c.clear.disabled = !filtered;
  c.count.textContent = filtered ? `Showing ${visible.length} of ${services.length}` : `Showing all ${services.length}`;
}

// --- superservers ---

function renderSuperservers() {
  dom.superserversBody.replaceChildren();
  if (!superservers || superservers.length === 0) {
    dom.superserversWrapper.hidden = true;
    dom.superserversEmpty.hidden = false;
    dom.superserversEmpty.textContent = superservers
      ? "IRIS reports no superservers."
      : "Could not load superservers from IRIS.";
    return;
  }
  dom.superserversEmpty.hidden = true;
  dom.superserversWrapper.hidden = false;
  for (const server of superservers) {
    const detail = server.Detail;
    const row = document.createElement("tr");
    row.className = "data-table__row--clickable";
    row.tabIndex = 0;
    row.dataset.openKind = "superserver";
    row.dataset.openName = superserverKey(server);
    row.setAttribute("aria-label", `View superserver ${superserverKey(server)}`);
    const status = ui.makeBadgeCell(enabledBadge(server.Enabled));
    if (server.SystemDefault) status.append(" ", ui.makeBadge("System default", "status-badge--accent"));
    const protocols = detail ? SUPERSERVER_PROTOCOLS.filter(([field]) => detail[field] === true).length : null;
    row.append(
      ui.makeCell(ui.textOrPlaceholder(server.BindAddress), { mono: true }),
      ui.makeCell(String(server.Port), { mono: true }),
      status,
      detail ? ui.makeBadgeCell(tlsBadge(detail.SSLSupportLevel)) : ui.makeCell(PLACEHOLDER, { title: "Detail unavailable" }),
      ui.makeCell(detail ? ui.textOrPlaceholder(detail.SSLConfig) : PLACEHOLDER, { mono: true }),
      ui.makeCell(protocols === null ? PLACEHOLDER : `${protocols} of ${SUPERSERVER_PROTOCOLS.length}`),
    );
    dom.superserversBody.append(row);
  }
}

// --- class access ---

function renderClassAccess() {
  const c = dom.classAccess;
  c.body.replaceChildren();
  if (!classAccess || classAccess.length === 0) {
    c.wrapper.hidden = true;
    c.empty.hidden = false;
    c.form.hidden = !classAccess;
    c.count.textContent = "";
    c.empty.textContent = classAccess
      ? "IRIS reports no application class-access entries."
      : "Could not load application class access from IRIS.";
    return;
  }
  c.form.hidden = false;
  const query = c.search.value.trim().toLowerCase();
  const visible = classAccess.filter(
    (entry) => !query || ui.includesText(entry.Name, query) || ui.includesText(entry.Class, query),
  );
  for (const entry of visible) {
    const row = document.createElement("tr");
    row.append(
      ui.makeCell(ui.textOrPlaceholder(entry.Name), { mono: true }),
      ui.makeCell(ui.textOrPlaceholder(entry.Class), { mono: true }),
      ui.makeCell(ui.textOrPlaceholder(entry.AllowType)),
      ui.makeBadgeCell(entry.AllowAccess ? ui.makeBadge("Allowed", "status-badge--ok") : ui.makeBadge("Denied", "status-badge--error")),
      ui.makeCell(ui.formatBoolean(entry.System)),
    );
    c.body.append(row);
  }
  c.wrapper.hidden = visible.length === 0;
  c.empty.hidden = visible.length !== 0;
  c.empty.textContent = "No class-access entries match the search.";
  c.count.textContent = query ? `Showing ${visible.length} of ${classAccess.length}` : `Showing all ${classAccess.length}`;
}

// --- drawer renderers (shown in security-access.js's shared drawer) ---

async function renderServiceDrawer(name, isCurrent) {
  const listEntry = services && services.find((s) => s.Name === name);
  ui.setDrawerHeader("Service", name, listEntry ? (listEntry.Enabled ? ["Enabled", "status-badge--ok"] : ["Disabled", "status-badge--neutral"]) : null);
  ui.drawerHint.textContent = "Read-only. Methods from IRIS's service list; the bitmask from the service's own detail.";

  const response = await IrisApi.getSecurityServiceDetail(name);
  if (!isCurrent()) return;
  const detail = response && response.result;
  if (!detail || typeof detail !== "object") throw new Error("unexpected shape");

  const rows = [ui.makeInfoRow("Description", "Description", ui.textOrPlaceholder(detail.Description))];
  if (listEntry && listEntry.Description !== detail.Description) {
    rows.push(ui.makeInfoRow("List Description", "Description (list)", ui.textOrPlaceholder(listEntry.Description)));
  }
  rows.push(
    ui.makeInfoRow("Enabled", "Enabled", ui.formatBoolean(detail.Enabled)),
    ui.makeInfoRow("Public", "Public", ui.textOrPlaceholder(listEntry && listEntry.Public)),
    ui.makeInfoRow("HttpOnly Cookies", "HttpOnlyCookies", ui.formatBoolean(listEntry && listEntry.HttpOnlyCookies)),
    ui.makeInfoRow("Two-Factor Enabled", "TwoFactorEnabled", ui.formatBoolean(listEntry && listEntry.TwoFactorEnabled)),
  );

  const methods = listEntry ? listEntry.AuthenticationMethods : [];
  ui.drawerBody.replaceChildren(
    ui.makeSection("Service", ui.makeInfoList(rows)),
    ui.makeSection(
      "Authentication",
      ui.makeInfoList([
        ui.makeInfoRow("Methods", "AuthenticationMethods", methods.length ? methods.join(", ") : "None listed"),
        ui.makeInfoRow("Enabled Bits", "AutheEnabled", decodeServiceBits(detail.AutheEnabled), { mono: true }),
      ]),
      ui.makeNote("The list's methods and the detail's bitmask are shown as IRIS reports each; the list does not name every bit (e.g. AutheSystem)."),
    ),
    ui.makeSection(
      "Connections",
      ui.makeInfoList([
        ui.makeInfoRow("Allowed Connections", "AllowedConnections", formatAllowedConnections(listEntry && listEntry.AllowedConnections)),
        ui.makeInfoRow("Client Systems", "ClientSystems", formatAllowedConnections(detail.ClientSystems)),
      ]),
    ),
  );
}

async function renderSuperserverDrawer(key, isCurrent) {
  const server = superservers && superservers.find((s) => superserverKey(s) === key);
  if (!isCurrent()) return;
  if (!server) throw new ApiError("Superserver not found", { status: 404 });
  ui.setDrawerHeader("Superserver", key, server.Enabled ? ["Enabled", "status-badge--ok"] : ["Disabled", "status-badge--neutral"]);
  ui.drawerHint.textContent = "Read-only. From IRIS's superserver list and detail.";
  const detail = server.Detail;
  const overview = [
    ui.makeInfoRow("Bind Address", "BindAddress", ui.textOrPlaceholder(server.BindAddress), { mono: true }),
    ui.makeInfoRow("Port", "Port", String(server.Port), { mono: true }),
    ui.makeInfoRow("System Default", "SystemDefault", ui.formatBoolean(server.SystemDefault)),
  ];
  if (!detail) {
    ui.drawerBody.replaceChildren(
      ui.makeSection("Superserver", ui.makeInfoList(overview)),
      ui.makeNote("IRIS did not return this superserver's detail."),
    );
    return;
  }
  const [tlsText] = TLS_LEVELS[detail.SSLSupportLevel] || [`Level ${detail.SSLSupportLevel}`];
  overview.unshift(ui.makeInfoRow("Description", "Description", ui.textOrPlaceholder(detail.Description)));
  const protocolList = document.createElement("ul");
  protocolList.className = "privilege-list";
  protocolList.append(...SUPERSERVER_PROTOCOLS.map(([field, label]) => onOffItem(label, field, detail[field] === true)));
  ui.drawerBody.replaceChildren(
    ui.makeSection("Superserver", ui.makeInfoList(overview)),
    ui.makeSection(
      "Client TLS",
      ui.makeInfoList([
        ui.makeInfoRow("TLS for Client Connections", "SSLSupportLevel", `${tlsText} (${detail.SSLSupportLevel})`, { mono: true }),
        ui.makeInfoRow("SSL Configuration", "SSLConfig", ui.textOrPlaceholder(detail.SSLConfig), { mono: true }),
      ]),
    ),
    ui.makeSection("Protocols", protocolList),
  );
}

// --- load ---

function listOrNull(settled) {
  return settled.status === "fulfilled" && settled.value && Array.isArray(settled.value.result)
    ? settled.value.result
    : null;
}

async function loadSecurityAuth() {
  const seq = ++loadSeq;
  dom.loading.hidden = false;
  dom.errorBanner.hidden = true;

  const [servicesResult, webAuthResult, superserversResult, classAccessResult] = await Promise.allSettled([
    IrisApi.getSecurityServices(),
    IrisApi.getSecurityWebAuth(),
    IrisApi.getSecuritySuperservers(),
    IrisApi.getSecurityClassAccess(),
  ]);
  if (seq !== loadSeq) return;

  services = listOrNull(servicesResult);
  webAuth =
    webAuthResult.status === "fulfilled" && webAuthResult.value && webAuthResult.value.result && typeof webAuthResult.value.result === "object"
      ? webAuthResult.value.result
      : null;
  superservers = listOrNull(superserversResult);
  classAccess = listOrNull(classAccessResult);
  loaded = true;

  const failed = [
    [services, "services"],
    [webAuth, "web authentication"],
    [superservers, "superservers"],
    [classAccess, "class access"],
  ].filter(([value]) => value === null).map(([, label]) => label);
  const superserverWarnings =
    superserversResult.status === "fulfilled" && Array.isArray(superserversResult.value.status?.errors)
      ? superserversResult.value.status.errors.length
      : 0;
  const messages = [];
  if (failed.length === 4) {
    messages.push("Could not load authentication settings. The Command Center backend may be unreachable.");
  } else if (failed.length > 0) {
    messages.push(`Could not load ${failed.join(", ")}. The rest is shown below.`);
  }
  if (superserverWarnings > 0) messages.push("IRIS did not return detail for every superserver.");
  dom.errorBanner.hidden = messages.length === 0;
  dom.errorBannerText.textContent = messages.join(" ");

  dom.content.hidden = failed.length === 4;
  if (services) {
    ui.populateSelect(dom.services.method, "Any method", ui.uniqueSorted(services.flatMap((s) => s.AuthenticationMethods)));
  }
  renderSummary();
  renderWebAuth();
  renderServicesTable();
  renderSuperservers();
  renderClassAccess();
  dom.loading.hidden = true;
}

/**
 * Called when the Security page is reopened. Only refreshes if this tab
 * was already loaded; otherwise it loads when first shown.
 */
export function refreshSecurityAuthIfLoaded() {
  if (loaded) loadSecurityAuth();
}

function onActivate(event) {
  if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
  const target = event.target.closest("[data-open-kind]");
  if (!target) return;
  if (event.type === "keydown") event.preventDefault();
  openSecurityDrawer(target.dataset.openKind, target.dataset.openName);
}

export function initSecurityAuthControls() {
  registerSecurityDrawerRenderer("service", renderServiceDrawer);
  registerSecurityDrawerRenderer("superserver", renderSuperserverDrawer);

  dom.tabs.addEventListener("security-tab-shown", (event) => {
    if (event.detail.tab === "authentication" && !loaded) loadSecurityAuth();
  });
  dom.refreshButton.addEventListener("click", () => {
    if (loaded) loadSecurityAuth();
  });

  dom.summaryGrid.addEventListener("click", (event) => {
    const card = event.target.closest(".stat-card[data-card-index]");
    if (card) summaryActions[Number(card.dataset.cardIndex)]?.();
  });
  dom.summaryGrid.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".stat-card[data-card-index]");
    if (!card) return;
    event.preventDefault();
    summaryActions[Number(card.dataset.cardIndex)]?.();
  });

  // Filters the last loaded data locally, no request.
  const c = dom.services;
  c.form.addEventListener("submit", (event) => event.preventDefault());
  c.search.addEventListener("input", renderServicesTable);
  c.status.addEventListener("change", renderServicesTable);
  c.method.addEventListener("change", renderServicesTable);
  c.clear.addEventListener("click", () => {
    c.search.value = "";
    c.status.value = "";
    c.method.value = "";
    renderServicesTable();
  });
  dom.classAccess.form.addEventListener("submit", (event) => event.preventDefault());
  dom.classAccess.search.addEventListener("input", renderClassAccess);

  for (const type of ["click", "keydown"]) {
    c.body.addEventListener(type, onActivate);
    dom.superserversBody.addEventListener(type, onActivate);
  }
}
