// Security view — page-level load/connection status and the OAuth 2.0 tab:
// this instance as an authorization server, its registered clients, the
// server definitions (external authorization servers) it uses as a client
// and their client configurations, resource servers and their mappings, plus
// "oauth-client", "oauth-definition", "oauth-config" and
// "oauth-resource-server" detail in the page's shared drawer
// (security-access.js).
//
// Read-only and allowlisted. It calls only these GET endpoints (via IrisApi,
// see backend/app/routes/security_access.py) and no mutating one:
//   - getSecurityOAuthOverview — every area in one allowlisted response;
//     loaded when the Security view opens and on Refresh, and the source of
//     the page's connection status,
//   - getSecurityOAuthServerClient / ServerDefinition / ClientConfiguration
//     / ResourceServer — fresh allowlisted detail for the drawer.
// Client secrets, key passwords, tokens and other secret values are never
// requested: the backend's models only name safe fields, and this module
// reads nothing else. `*Credentials` fields name X.509 credentials and link
// to the Certificates drawer — they are aliases, not key material.

import { IrisApi, ApiError } from "./api.js";
import { openSecurityDrawer, registerSecurityDrawerRenderer, securityUi as ui } from "./security-access.js";

const PLACEHOLDER = "—";
const $ = (id) => document.getElementById(id);

const dom = {
  loadingState: $("security-loading-state"),
  errorBanner: $("security-error-banner"),
  errorBannerText: $("security-error-banner-text"),
  refreshButton: $("security-refresh-button"),
  connectionStatus: $("security-connection-status"),
  connectionStatusLabel: $("security-connection-status-label"),
  connectionDetail: $("security-connection-detail"),
  oauthErrorBanner: $("security-oauth-error-banner"),
  oauthErrorBannerText: $("security-oauth-error-banner-text"),
  content: $("security-oauth-content"),
  summaryGrid: $("security-oauth-summary-grid"),
  form: $("security-oauth-filter-form"),
  search: $("security-oauth-search"),
  server: $("security-oauth-server"),
};

// [overview part, empty-state id prefix, noun, row → {kind, name, cells}]
const TABLES = {
  clients: {
    prefix: "security-oauth-clients",
    noun: "registered clients",
    rows: (o) => o.ServerClients,
    toRow: (c) => ({
      kind: "oauth-client",
      name: c.ClientId,
      cells: [c.Name, c.ClientId, c.ClientType, list(c.RedirectURL), c.Description],
      mono: [false, true, false, true, false],
    }),
  },
  definitions: {
    prefix: "security-oauth-definitions",
    noun: "server definitions",
    rows: (o) => o.ServerDefinitions,
    toRow: (d) => ({
      kind: "oauth-definition",
      name: d.ID,
      cells: [d.ID, d.IssuerEndpoint, count(d.ClientCount), count(d.ResourceCount)],
      mono: [true, true, false, false],
    }),
  },
  configs: {
    prefix: "security-oauth-configs",
    noun: "client configurations",
    rows: (o) => clientConfigurations(o),
    toRow: (c) => ({
      kind: "oauth-config",
      name: c.ApplicationName,
      cells: [c.ApplicationName, c.ServerDefinitionId, c.ClientType, c.DefaultScope],
      mono: [true, true, false, true],
    }),
  },
  resourceServers: {
    prefix: "security-oauth-resource-servers",
    noun: "resource servers",
    rows: (o) => o.ResourceServers,
    toRow: (r) => ({
      kind: "oauth-resource-server",
      name: r.Name,
      cells: [r.Name, r.ServerDefinition],
      mono: [true, true],
    }),
  },
  mappings: {
    prefix: "security-oauth-mappings",
    noun: "resource server mappings",
    rows: (o) => o.ResourceMappings,
    toRow: (m) => ({
      kind: "oauth-resource-server",
      name: m.Resource,
      cells: [m.Service, m.Key, m.Resource],
      mono: [true, true, true],
    }),
  },
};

let overview = null; // last allowlisted overview, or null if the load failed
let loadSeq = 0;

// --- helpers ---

function text(value) {
  return ui.textOrPlaceholder(value);
}

function list(value) {
  return Array.isArray(value) && value.length > 0 ? value.join(", ") : PLACEHOLDER;
}

function count(value) {
  return typeof value === "number" ? String(value) : PLACEHOLDER;
}

function seconds(value) {
  return typeof value === "number" ? `${value} s` : PLACEHOLDER;
}

/** Client configurations across all server definitions, each tagged with
 * its definition's ID. Null if the definitions list itself failed. */
function clientConfigurations(o) {
  if (!Array.isArray(o.ServerDefinitions)) return null;
  return o.ServerDefinitions.flatMap((d) =>
    Array.isArray(d.ClientConfigurations)
      ? d.ClientConfigurations.map((c) => ({ ...c, ServerDefinitionId: d.ID }))
      : [],
  );
}

/** A chip linking to another drawer entity, or placeholder text. */
function link(kind, name) {
  return typeof name === "string" && name !== "" ? ui.makeLinkChips(kind, [name]) : PLACEHOLDER;
}

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern used in the other
  // views. Every Security module listens to this same button.
  dom.refreshButton.disabled = isLoading;
  dom.refreshButton.classList.toggle("btn--spinning", isLoading);
}

function setConnectionState(state, label, detail) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
  dom.connectionDetail.textContent = detail || "";
}

function setBanner(banner, textEl, message) {
  banner.hidden = !message;
  textEl.textContent = message || "";
}

// --- summary + authorization server ---

function renderSummary() {
  const configs = clientConfigurations(overview);
  const size = (value) => (Array.isArray(value) ? value.length : null);
  const serverValue =
    overview.ServerConfigured === true ? "Configured" : overview.ServerConfigured === false ? "Not configured" : null;
  const cards = [
    ["Authorization Server", serverValue, overview.ServerConfigured ? "var(--color-chart-3)" : "var(--color-chart-neutral)"],
    ["Registered Clients", size(overview.ServerClients), "var(--color-accent)"],
    ["Server Definitions", size(overview.ServerDefinitions), "var(--color-chart-2)"],
    ["Client Configurations", size(configs), "var(--color-chart-6)"],
    ["Resource Servers", size(overview.ResourceServers), "var(--color-chart-4)"],
    ["Resource Mappings", size(overview.ResourceMappings), "var(--color-chart-neutral)"],
  ];
  dom.summaryGrid.replaceChildren(
    ...cards.map(([label, value, accent]) => {
      const card = document.createElement("article");
      card.className = "stat-card";
      card.style.setProperty("--stat-card-accent", accent);
      const labelEl = document.createElement("h3");
      labelEl.className = "stat-card__label";
      labelEl.textContent = label;
      const valueEl = document.createElement("p");
      const unavailable = value === null;
      valueEl.className = unavailable
        ? "stat-card__value stat-card__value--unavailable"
        : typeof value === "number"
          ? "stat-card__value"
          : "stat-card__value stat-card__value--mono";
      valueEl.textContent = unavailable ? "Unavailable" : String(value);
      card.append(labelEl, valueEl);
      return card;
    }),
  );
}

function renderServer() {
  if (overview.ServerConfigured === false) {
    dom.server.replaceChildren(
      ui.makeNote("IRIS reports that this instance is not configured as an OAuth 2.0 authorization server."),
    );
    return;
  }
  if (overview.ServerConfigured !== true || !overview.Server) {
    dom.server.replaceChildren(ui.makeNote("Could not load the authorization server configuration from IRIS."));
    return;
  }
  const s = overview.Server;
  const scopes = Array.isArray(s.SupportedScopes)
    ? s.SupportedScopes.map((scope) => (scope.Description ? `${text(scope.Scope)} (${scope.Description})` : text(scope.Scope)))
    : null;
  const metadata = s.Metadata || {};
  dom.server.replaceChildren(
    ui.makeInfoList([
      ui.makeInfoRow("Issuer Endpoint", "IssuerEndpoint", text(s.IssuerEndpoint), { mono: true }),
      ui.makeInfoRow("Description", "Description", text(s.Description)),
      ui.makeInfoRow("Supported Scopes", "SupportedScopes", scopes && scopes.length ? scopes.join(", ") : PLACEHOLDER),
      ui.makeInfoRow("Default Scope", "DefaultScope", text(s.DefaultScope), { mono: true }),
      ui.makeInfoRow("Access Token Lifetime", "AccessTokenInterval", seconds(s.AccessTokenInterval), { mono: true }),
      ui.makeInfoRow("Authorization Code Lifetime", "AuthorizationCodeInterval", seconds(s.AuthorizationCodeInterval), { mono: true }),
      ui.makeInfoRow("Refresh Token Lifetime", "RefreshTokenInterval", seconds(s.RefreshTokenInterval), { mono: true }),
      ui.makeInfoRow("Session Lifetime", "SessionInterval", seconds(s.SessionInterval), { mono: true }),
      ui.makeInfoRow("Client Secret Lifetime", "ClientSecretInterval", seconds(s.ClientSecretInterval), { mono: true }),
      ui.makeInfoRow("Return Refresh Token", "ReturnRefreshToken", text(s.ReturnRefreshToken)),
      ui.makeInfoRow("PKCE For Public Clients", "ForcePKCEForPublicClients", ui.formatBoolean(s.ForcePKCEForPublicClients)),
      ui.makeInfoRow("PKCE For Confidential Clients", "ForcePKCEForConfidentialClients", ui.formatBoolean(s.ForcePKCEForConfidentialClients)),
      ui.makeInfoRow("Public Client Refresh", "AllowPublicClientRefresh", ui.formatBoolean(s.AllowPublicClientRefresh)),
      ui.makeInfoRow("Allow Unsupported Scope", "AllowUnsupportedScope", ui.formatBoolean(s.AllowUnsupportedScope)),
      ui.makeInfoRow("Audience Required", "AudRequired", ui.formatBoolean(s.AudRequired)),
      ui.makeInfoRow("User Sessions", "SupportSession", ui.formatBoolean(s.SupportSession)),
      ui.makeInfoRow("Signing Algorithm", "SigningAlgorithm", text(s.SigningAlgorithm), { mono: true }),
      ui.makeInfoRow("Encryption Algorithm", "EncryptionAlgorithm", text(s.EncryptionAlgorithm), { mono: true }),
      ui.makeInfoRow("Key Algorithm", "KeyAlgorithm", text(s.KeyAlgorithm), { mono: true }),
      ui.makeInfoRow("Server Credentials", "ServerCredentials", link("x509", s.ServerCredentials)),
      ui.makeInfoRow("SSL Configuration", "SSLConfiguration", text(s.SSLConfiguration), { mono: true }),
      ui.makeInfoRow("Customization Namespace", "CustomizationNamespace", text(s.CustomizationNamespace)),
      ui.makeInfoRow(
        "Customization Roles",
        "CustomizationRoles",
        Array.isArray(s.CustomizationRoles) && s.CustomizationRoles.length ? ui.makeLinkChips("role", s.CustomizationRoles) : PLACEHOLDER,
      ),
      ui.makeInfoRow("Authenticate Class", "AuthenticateClass", text(s.AuthenticateClass), { mono: true }),
      ui.makeInfoRow("Validate User Class", "ValidateUserClass", text(s.ValidateUserClass), { mono: true }),
      ui.makeInfoRow("Session Class", "SessionClass", text(s.SessionClass), { mono: true }),
      ui.makeInfoRow("Generate Token Class", "GenerateTokenClass", text(s.GenerateTokenClass), { mono: true }),
      ui.makeInfoRow("Revoke Token Class", "RevokeTokenClass", text(s.RevokeTokenClass), { mono: true }),
    ]),
    ui.makeSection("Discovery Metadata", metadataList(metadata)),
  );
}

/** The allowlisted server discovery metadata (endpoints and capabilities). */
function metadataList(metadata) {
  const rows = [
    ["Issuer", "issuer"],
    ["Authorization Endpoint", "authorization_endpoint"],
    ["Token Endpoint", "token_endpoint"],
    ["UserInfo Endpoint", "userinfo_endpoint"],
    ["Revocation Endpoint", "revocation_endpoint"],
    ["Introspection Endpoint", "introspection_endpoint"],
    ["JWKS URI", "jwks_uri"],
    ["Registration Endpoint", "registration_endpoint"],
    ["End Session Endpoint", "end_session_endpoint"],
    ["Scopes Supported", "scopes_supported"],
    ["Grant Types Supported", "grant_types_supported"],
    ["Response Types Supported", "response_types_supported"],
    ["PKCE Methods Supported", "code_challenge_methods_supported"],
    ["Token Auth Methods Supported", "token_endpoint_auth_methods_supported"],
    ["ID Token Signing Algorithms", "id_token_signing_alg_values_supported"],
  ].filter(([, field]) => metadata && metadata[field] !== null && metadata[field] !== undefined);
  if (rows.length === 0) return ui.makeNote("IRIS reports no discovery metadata.");
  return ui.makeInfoList(
    rows.map(([label, field]) =>
      ui.makeInfoRow(label, field, Array.isArray(metadata[field]) ? list(metadata[field]) : text(metadata[field]), { mono: true }),
    ),
  );
}

// --- tables ---

function renderTables() {
  const query = dom.search.value.trim().toLowerCase();
  for (const table of Object.values(TABLES)) {
    const body = $(`${table.prefix}-table-body`);
    const wrapper = $(`${table.prefix}-table-wrapper`);
    const empty = $(`${table.prefix}-empty`);
    const rows = table.rows(overview);
    body.replaceChildren();
    if (!Array.isArray(rows)) {
      wrapper.hidden = true;
      empty.hidden = false;
      empty.textContent = `Could not load ${table.noun} from IRIS.`;
      continue;
    }
    const built = rows.map(table.toRow);
    const visible = built.filter(
      (row) => !query || row.cells.some((cell) => typeof cell === "string" && cell.toLowerCase().includes(query)),
    );
    for (const row of visible) {
      const tr = document.createElement("tr");
      const clickable = typeof row.name === "string" && row.name !== "";
      if (clickable) {
        tr.className = "data-table__row--clickable";
        tr.tabIndex = 0;
        tr.dataset.openKind = row.kind;
        tr.dataset.openName = row.name;
        tr.setAttribute("aria-label", `View ${row.name}`);
      }
      tr.append(...row.cells.map((cell, i) => ui.makeCell(text(cell), { mono: row.mono[i] })));
      body.append(tr);
    }
    wrapper.hidden = visible.length === 0;
    empty.hidden = visible.length !== 0;
    empty.textContent = rows.length === 0 ? `IRIS reports no ${table.noun}.` : `No ${table.noun} match the search.`;
  }
}

// --- drawer renderers (shown in security-access.js's shared drawer) ---

function clientMetadataRows(metadata) {
  if (!metadata) return [ui.makeInfoRow("Metadata", "Metadata", "Not reported")];
  return [
    ui.makeInfoRow("Client Name", "client_name", text(metadata.client_name)),
    ui.makeInfoRow("Application Type", "application_type", text(metadata.application_type)),
    ui.makeInfoRow("Redirect URIs", "redirect_uris", list(metadata.redirect_uris), { mono: true }),
    ui.makeInfoRow("Grant Types", "grant_types", list(metadata.grant_types), { mono: true }),
    ui.makeInfoRow("Response Types", "response_types", list(metadata.response_types), { mono: true }),
    ui.makeInfoRow("Token Endpoint Auth Method", "token_endpoint_auth_method", text(metadata.token_endpoint_auth_method), { mono: true }),
    ui.makeInfoRow("ID Token Signing Algorithm", "id_token_signed_response_alg", text(metadata.id_token_signed_response_alg), { mono: true }),
    ui.makeInfoRow("Client URI", "client_uri", text(metadata.client_uri), { mono: true }),
    ui.makeInfoRow("Default Max Age", "default_max_age", seconds(metadata.default_max_age), { mono: true }),
  ];
}

async function fetchResult(call, isCurrent) {
  const response = await call();
  if (!isCurrent()) return null;
  const result = response && response.result;
  if (!result || typeof result !== "object") throw new Error("unexpected shape");
  return result;
}

async function renderClientDrawer(clientId, isCurrent) {
  const listed = overview && Array.isArray(overview.ServerClients) ? overview.ServerClients.find((c) => c.ClientId === clientId) : null;
  ui.setDrawerHeader("OAuth Client", (listed && listed.Name) || clientId, null);
  ui.drawerHint.textContent = "Read-only. Allowlisted fields only — the client secret is never requested.";
  const c = await fetchResult(() => IrisApi.getSecurityOAuthServerClient(clientId), isCurrent);
  if (!c) return;
  ui.drawerBody.replaceChildren(
    ui.makeSection("Client", ui.makeInfoList([
      ui.makeInfoRow("Client ID", "ClientId", text(clientId), { mono: true }),
      ui.makeInfoRow("Name", "Name", text(c.Name)),
      ui.makeInfoRow("Type", "ClientType", text(c.ClientType)),
      ui.makeInfoRow("Description", "Description", text(c.Description)),
      ui.makeInfoRow("Redirect URLs", "RedirectURL", list(c.RedirectURL), { mono: true }),
      ui.makeInfoRow("Launch URL", "LaunchURL", text(c.LaunchURL), { mono: true }),
      ui.makeInfoRow("Default Scope", "DefaultScope", text(c.DefaultScope), { mono: true }),
      ui.makeInfoRow("Client Credentials", "ClientCredentials", link("x509", c.ClientCredentials)),
    ])),
    ui.makeSection("Registration Metadata", ui.makeInfoList(clientMetadataRows(c.Metadata))),
  );
}

async function renderDefinitionDrawer(serverId, isCurrent) {
  ui.setDrawerHeader("Server Definition", serverId, null);
  ui.drawerHint.textContent = "Read-only. An external authorization server this instance uses as a client.";
  const d = await fetchResult(() => IrisApi.getSecurityOAuthServerDefinition(serverId), isCurrent);
  if (!d) return;
  const listed = overview && Array.isArray(overview.ServerDefinitions) ? overview.ServerDefinitions.find((x) => x.ID === serverId) : null;
  const configs = listed && Array.isArray(listed.ClientConfigurations) ? listed.ClientConfigurations : null;
  const resourceServers =
    overview && Array.isArray(overview.ResourceServers) ? overview.ResourceServers.filter((r) => r.ServerDefinition === serverId) : null;
  ui.drawerBody.replaceChildren(
    ui.makeSection("Server Definition", ui.makeInfoList([
      ui.makeInfoRow("Issuer Endpoint", "IssuerEndpoint", text(d.IssuerEndpoint), { mono: true }),
      ui.makeInfoRow("SSL Configuration", "SSLConfiguration", text(d.SSLConfiguration), { mono: true }),
      ui.makeInfoRow("Server Credentials", "ServerCredentials", link("x509", d.ServerCredentials)),
    ])),
    ui.makeSection(
      "Client Configurations",
      configs === null
        ? ui.makeNote("Client configurations for this definition could not be loaded.")
        : configs.length === 0
          ? ui.makeNote("IRIS reports no client configurations for this server definition.")
          : ui.makeLinkTable(["Application", "Type"], configs.filter((c) => c.ApplicationName).map((c) => ({
              kind: "oauth-config", name: c.ApplicationName, cells: [text(c.ClientType)],
            }))),
    ),
    ui.makeSection(
      "Resource Servers",
      resourceServers === null
        ? ui.makeNote("Resource servers could not be loaded.")
        : resourceServers.length === 0
          ? ui.makeNote("No resource server uses this server definition.")
          : ui.makeLinkChips("oauth-resource-server", resourceServers.map((r) => r.Name).filter(Boolean)),
    ),
    ui.makeSection("Discovery Metadata", metadataList(d.Metadata)),
  );
}

async function renderConfigDrawer(applicationName, isCurrent) {
  ui.setDrawerHeader("Client Configuration", applicationName, null);
  ui.drawerHint.textContent = "Read-only. Allowlisted fields only — the client secret and password are never requested.";
  const c = await fetchResult(() => IrisApi.getSecurityOAuthClientConfiguration(applicationName), isCurrent);
  if (!c) return;
  if (typeof c.Enabled === "boolean") {
    ui.setDrawerHeader("Client Configuration", applicationName, c.Enabled ? ["Enabled", "status-badge--ok"] : ["Disabled", "status-badge--neutral"]);
  }
  ui.drawerBody.replaceChildren(
    ui.makeSection("Client Configuration", ui.makeInfoList([
      ui.makeInfoRow("Server Definition", "OAuth2ServerDefinition", link("oauth-definition", c.OAuth2ServerDefinition)),
      ui.makeInfoRow("Enabled", "Enabled", ui.formatBoolean(c.Enabled)),
      ui.makeInfoRow("Type", "ClientType", text(c.ClientType)),
      ui.makeInfoRow("Description", "Description", text(c.Description)),
      ui.makeInfoRow("Redirection Endpoint", "RedirectionEndpoint", text(c.RedirectionEndpoint), { mono: true }),
      ui.makeInfoRow("Default Scope", "DefaultScope", text(c.DefaultScope), { mono: true }),
      ui.makeInfoRow("JWT Audience", "JWTAudience", text(c.JWTAudience), { mono: true }),
      ui.makeInfoRow("SSL Configuration", "SSLConfiguration", text(c.SSLConfiguration), { mono: true }),
      ui.makeInfoRow("Client Credentials", "ClientCredentials", link("x509", c.ClientCredentials)),
    ])),
    ui.makeSection("Registration Metadata", ui.makeInfoList(clientMetadataRows(c.Metadata))),
  );
}

async function renderResourceServerDrawer(name, isCurrent) {
  ui.setDrawerHeader("Resource Server", name, null);
  ui.drawerHint.textContent = "Read-only. Allowlisted fields only — no client secret is requested.";
  const r = await fetchResult(() => IrisApi.getSecurityOAuthResourceServer(name), isCurrent);
  if (!r) return;
  if (typeof r.Enabled === "boolean") {
    ui.setDrawerHeader("Resource Server", name, r.Enabled ? ["Enabled", "status-badge--ok"] : ["Disabled", "status-badge--neutral"]);
  }
  const listed = overview && Array.isArray(overview.ResourceServers) ? overview.ResourceServers.find((x) => x.Name === name) : null;
  const mappings = overview && Array.isArray(overview.ResourceMappings) ? overview.ResourceMappings.filter((m) => m.Resource === name) : null;
  ui.drawerBody.replaceChildren(
    ui.makeSection("Resource Server", ui.makeInfoList([
      ui.makeInfoRow("Server Definition", "ServerDefinition", link("oauth-definition", listed && listed.ServerDefinition)),
      ui.makeInfoRow("Enabled", "Enabled", ui.formatBoolean(r.Enabled)),
      ui.makeInfoRow("Description", "Description", text(r.Description)),
      ui.makeInfoRow("Issuer Endpoint", "IssuerEndpoint", text(r.IssuerEndpoint), { mono: true }),
      ui.makeInfoRow("Audiences", "Audiences", list(r.Audiences), { mono: true }),
      ui.makeInfoRow("Required Scope", "ScopeRequiredToConnect", text(r.ScopeRequiredToConnect), { mono: true }),
    ])),
    ui.makeSection("Token Validation", ui.makeInfoList([
      ui.makeInfoRow("Access Token Is JWT", "AccessTokenIsJWT", ui.formatBoolean(r.AccessTokenIsJWT)),
      ui.makeInfoRow("Always Call Introspection", "AlwaysCallIntrospection", ui.formatBoolean(r.AlwaysCallIntrospection)),
      ui.makeInfoRow("Introspection Auth Method", "IntrospectionAuthMethod", text(r.IntrospectionAuthMethod), { mono: true }),
      ui.makeInfoRow("Client ID", "ClientId", text(r.ClientId), { mono: true }),
      ui.makeInfoRow("Use OpenID Connect", "UseOIDC", ui.formatBoolean(r.UseOIDC)),
    ])),
    ui.makeSection(
      "Mappings",
      mappings === null
        ? ui.makeNote("Resource server mappings could not be loaded.")
        : mappings.length === 0
          ? ui.makeNote("No mapping routes requests to this resource server.")
          : ui.makeInfoList(mappings.map((m) => ui.makeInfoRow(text(m.Service), null, text(m.Key), { mono: true }))),
    ),
  );
}

// --- load ---

/**
 * Loads the allowlisted OAuth 2.0 overview and renders the OAuth tab and the
 * page's connection status. Called when the Security view opens and on
 * Refresh. Only a GET — no mutating request exists anywhere in this file.
 */
export async function loadSecurity() {
  const seq = ++loadSeq;
  setLoading(true);
  setBanner(dom.errorBanner, dom.errorBannerText, null);
  setConnectionState("checking", "Checking connection…", "");

  let response = null;
  try {
    response = await IrisApi.getSecurityOAuthOverview();
  } catch (err) {
    if (seq !== loadSeq) return;
    overview = null;
    dom.content.hidden = true;
    setConnectionState("error", "Could not reach IRIS", "");
    setBanner(
      dom.oauthErrorBanner,
      dom.oauthErrorBannerText,
      err instanceof ApiError
        ? "Could not load OAuth 2.0 configuration. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading OAuth 2.0 configuration.",
    );
    setLoading(false);
    return;
  }
  if (seq !== loadSeq) return;

  const result = response && response.result && typeof response.result === "object" ? response.result : null;
  if (!result) {
    overview = null;
    dom.content.hidden = true;
    setConnectionState("error", "IRIS returned no data", "");
    setBanner(dom.oauthErrorBanner, dom.oauthErrorBannerText, "IRIS did not return the expected OAuth 2.0 information.");
    setLoading(false);
    return;
  }

  overview = result;
  const warnings = response.status && Array.isArray(response.status.errors) ? response.status.errors : [];
  if (warnings.length > 0) {
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    const areas = warnings.map((w) => (w && typeof w.area === "string" ? w.area : null)).filter(Boolean);
    setBanner(
      dom.oauthErrorBanner,
      dom.oauthErrorBannerText,
      `Some OAuth 2.0 information could not be loaded${areas.length ? `: ${areas.join(", ")}` : ""}. The rest is shown below.`,
    );
  } else {
    setConnectionState("connected", "Connected", "");
    setBanner(dom.oauthErrorBanner, dom.oauthErrorBannerText, null);
  }

  dom.content.hidden = false;
  renderSummary();
  renderServer();
  renderTables();
  setLoading(false);
}

function onActivate(event) {
  if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
  const target = event.target.closest("[data-open-kind]");
  if (!target) return;
  if (event.type === "keydown") event.preventDefault();
  openSecurityDrawer(target.dataset.openKind, target.dataset.openName);
}

export function initSecurityControls() {
  registerSecurityDrawerRenderer("oauth-client", renderClientDrawer);
  registerSecurityDrawerRenderer("oauth-definition", renderDefinitionDrawer);
  registerSecurityDrawerRenderer("oauth-config", renderConfigDrawer);
  registerSecurityDrawerRenderer("oauth-resource-server", renderResourceServerDrawer);

  dom.refreshButton.addEventListener("click", () => {
    loadSecurity();
  });

  // Client-side search over the last loaded overview — never a request.
  dom.form.addEventListener("submit", (event) => event.preventDefault());
  dom.search.addEventListener("input", () => {
    if (overview) renderTables();
  });

  for (const table of Object.values(TABLES)) {
    const body = $(`${table.prefix}-table-body`);
    for (const type of ["click", "keydown"]) body.addEventListener(type, onActivate);
  }
  for (const type of ["click", "keydown"]) dom.server.addEventListener(type, onActivate);
}
