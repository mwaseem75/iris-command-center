// Security page, Identity & Access: KPI cards, a Privileged Access panel,
// Users / Roles / Resources tabs with search and filters, and a shared
// detail drawer you can walk through (user -> role -> resource, with Back).
// OAuth 2.0 is in security.js.
//
// Reads: getSecurityUsers / getSecurityUserDetail (the backend withholds
// email, phone and comment, and only lists their names in WithheldFields),
// getSecurityRoles / RoleDetail / RoleOwners, getSecurityRoleAccessMap
// (all role grants in one call) and getSecurityResources / ResourceDetail.
// The one change it can make is Login Access in the user drawer
// (user.set_enabled, see below).
//
// IRIS's role list leaves out %SQLTuneTable. The Roles KPI is IRIS's list
// count; roles that exist but aren't listed are shown separately as "Not in
// IRIS list" and aren't counted.

import { IrisApi, ApiError } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";

const PLACEHOLDER = "—";
const SUPER_USER_ROLE = "%All";
const SECURITY_ADMIN_RESOURCE = "%Admin_Secure";

const $ = (id) => document.getElementById(id);

const dom = {
  refreshButton: $("security-refresh-button"),
  errorBanner: $("security-access-error-banner"),
  errorBannerText: $("security-access-error-banner-text"),
  loading: $("security-access-loading"),
  content: $("security-access-content"),
  summaryGrid: $("security-access-summary-grid"),
  privilegedError: $("security-privileged-error"),
  privilegedWrapper: $("security-privileged-table-wrapper"),
  privilegedBody: $("security-privileged-table-body"),
  privilegedDetails: $("security-privileged-details"),
  privilegedToggle: $("security-privileged-toggle"),
  adminSecureList: $("security-admin-secure-list"),
  tabs: $("security-access-tabs"),
  panels: {
    users: $("security-panel-users"),
    roles: $("security-panel-roles"),
    resources: $("security-panel-resources"),
    authentication: $("security-panel-authentication"),
    wallet: $("security-panel-wallet"),
    x509: $("security-panel-x509"),
    oauth: $("security-panel-oauth"),
  },
  users: {
    form: $("security-users-filter-form"),
    search: $("security-users-search"),
    status: $("security-users-status"),
    type: $("security-users-type"),
    clear: $("security-users-clear"),
    count: $("security-users-count"),
    empty: $("security-users-empty"),
    wrapper: $("security-users-table-wrapper"),
    body: $("security-users-table-body"),
  },
  roles: {
    form: $("security-roles-filter-form"),
    search: $("security-roles-search"),
    escalation: $("security-roles-escalation"),
    resource: $("security-roles-resource"),
    clear: $("security-roles-clear"),
    count: $("security-roles-count"),
    unlistedHint: $("security-roles-unlisted-hint"),
    empty: $("security-roles-empty"),
    wrapper: $("security-roles-table-wrapper"),
    body: $("security-roles-table-body"),
  },
  resources: {
    form: $("security-resources-filter-form"),
    search: $("security-resources-search"),
    type: $("security-resources-type"),
    public: $("security-resources-public"),
    clear: $("security-resources-clear"),
    count: $("security-resources-count"),
    empty: $("security-resources-empty"),
    wrapper: $("security-resources-table-wrapper"),
    body: $("security-resources-table-body"),
  },
  drawer: $("security-drawer"),
  drawerBackdrop: $("security-drawer-backdrop"),
  drawerBack: $("security-drawer-back"),
  drawerClose: $("security-drawer-close"),
  drawerTitle: $("security-drawer-title"),
  drawerKind: $("security-drawer-kind-badge"),
  drawerStatus: $("security-drawer-status-badge"),
  drawerHint: $("security-drawer-hint"),
  drawerLoading: $("security-drawer-loading"),
  drawerError: $("security-drawer-error"),
  drawerErrorText: $("security-drawer-error-text"),
  drawerBody: $("security-drawer-body"),
};

// The authentication, wallet, x509 and oauth tabs belong to their own
// modules. Here we just show their panels and fire a "security-tab-shown"
// event on the tab bar.
const TABS = ["users", "roles", "resources", "authentication", "wallet", "x509", "oauth"];

// Resource permission letters (R, W, U).
const PERMISSION_NAMES = { R: "Read", W: "Write", U: "Use" };

// Two-factor bits in a user's AutheEnabled (2**20 SMS, 2**21 TOTP).
const TWO_FACTOR_BITS = [
  [20, "SMS text"],
  [21, "Time-based one-time password"],
];

// Last loaded data. Filtering and the drawer read from these.
let users = [];
let listedRoles = [];  // IRIS's role list as returned
let accessMap = null;  // Map of name -> {Listed, Detail}, or null if it failed
let resources = [];
let superUserOwners = null; // owners of %All, or null if unavailable
let activeTab = "users";
let drawerStack = [];  // [{kind, name}], the drawer's Back history
let drawerSeq = 0;
let loadSeq = 0;

// --- small helpers ---

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatBoolean(value) {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : PLACEHOLDER;
}

/**
 * AdminOption is "0" on User/Role rows and false on escalation rows.
 * "0"/"1" are read as booleans; anything else is shown as-is.
 */
function formatAdminOption(value) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === "0") return "No";
  if (value === "1") return "Yes";
  return textOrPlaceholder(value);
}

function formatPermissions(value) {
  if (typeof value !== "string" || value === "") return PLACEHOLDER;
  const names = [...value].map((letter) => PERMISSION_NAMES[letter] || letter);
  return `${value} — ${names.join(", ")}`;
}

function formatTwoFactor(value) {
  if (typeof value !== "number") return PLACEHOLDER;
  if (value === 0) return "None (0)";
  const names = TWO_FACTOR_BITS.filter(([bit]) => (value & 2 ** bit) !== 0).map(([, name]) => name);
  let known = 0;
  for (const [bit] of TWO_FACTOR_BITS) known += 2 ** bit;
  if ((value & ~known) !== 0) names.push("other bits");
  return `${names.join(", ")} (${value})`;
}

function includesText(value, query) {
  return typeof value === "string" && value.toLowerCase().includes(query);
}

// Everything is built with createElement/textContent (no innerHTML).
function makeCell(text, { mono = false, title = text } = {}) {
  const cell = document.createElement("td");
  cell.className = mono ? "data-table__cell data-table__cell--mono" : "data-table__cell";
  cell.textContent = text;
  cell.title = title;
  return cell;
}

function makeBadge(text, variant) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = text;
  return badge;
}

function makeBadgeCell(...badges) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  cell.append(...badges);
  return cell;
}

function makeNameCell(name, badge) {
  const cell = makeCell(textOrPlaceholder(name), { mono: true });
  if (badge) cell.append(" ", badge);
  return cell;
}

function makeInfoRow(label, field, content, { mono = false } = {}) {
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
  dd.className = mono ? "info-list__value info-list__value--mono" : "info-list__value";
  if (content instanceof Node) dd.append(content);
  else dd.textContent = content;
  row.append(dt, dd);
  return row;
}

function makeSection(title, ...children) {
  const section = document.createElement("div");
  section.className = "ns-drawer__section";
  const heading = document.createElement("h4");
  heading.className = "ns-drawer__section-title";
  heading.textContent = title;
  section.append(heading, ...children);
  return section;
}

function makeInfoList(rows) {
  const list = document.createElement("dl");
  list.className = "info-list";
  list.append(...rows);
  return list;
}

function makeNote(text) {
  const note = document.createElement("p");
  note.className = "ns-hint";
  note.textContent = text;
  return note;
}

/** Chips that open another item in the drawer (e.g. a user's roles). */
function makeLinkChips(kind, names, labelFor = (name) => name) {
  if (!Array.isArray(names) || names.length === 0) return document.createTextNode("None");
  const list = document.createElement("ul");
  list.className = "tag-list";
  for (const name of names) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tag-list__item tag-list__item--link";
    button.dataset.openKind = kind;
    button.dataset.openName = name;
    button.textContent = labelFor(name);
    item.append(button);
    list.append(item);
  }
  return list;
}

/**
 * Small table whose rows open another item in the drawer.
 * `rows` is [{kind, name, label?, cells: [text, ...]}]; the first column
 * shows `label` if given, otherwise `name`.
 */
function makeLinkTable(headers, rows) {
  const wrapper = document.createElement("div");
  wrapper.className = "table-wrapper";
  const table = document.createElement("table");
  table.className = "data-table data-table--compact";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const header of headers) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = header;
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.className = "data-table__row--clickable";
    tr.tabIndex = 0;
    tr.dataset.openKind = row.kind;
    tr.dataset.openName = row.name;
    const label = row.label ?? row.name;
    tr.setAttribute("aria-label", `View ${row.kind} ${label}`);
    tr.append(makeCell(label, { mono: true }), ...row.cells.map((text) => makeCell(text)));
    body.append(tr);
  }
  table.append(head, body);
  wrapper.append(table);
  return wrapper;
}

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

function uniqueSorted(values) {
  return [...new Set(values.filter((v) => typeof v === "string" && v !== ""))].sort();
}

// --- views over the access map ---

function roleDetail(name) {
  const entry = accessMap && accessMap.get(name);
  return entry ? entry.Detail : null;
}

/** Roles missing from IRIS's list that the access map says exist. */
function unlistedRoleNames() {
  if (!accessMap) return [];
  return [...accessMap.entries()].filter(([, entry]) => !entry.Listed).map(([name]) => name);
}

/** [{role, permissions}] for every role whose detail grants `resource`. */
function rolesGranting(resource) {
  if (!accessMap) return null;
  const grants = [];
  for (const [role, entry] of accessMap.entries()) {
    const grant = entry.Detail && entry.Detail.Resources.find((r) => r.Name === resource);
    if (grant) grants.push({ role, permissions: grant.Permissions });
  }
  return grants;
}

/** All rows for the Roles table: IRIS's list, then the unlisted ones. */
function roleRows() {
  const rows = listedRoles.map((role) => ({ ...role, Listed: true, Detail: roleDetail(role.Name) }));
  for (const name of unlistedRoleNames()) {
    const detail = roleDetail(name);
    rows.push({
      Name: name,
      Description: detail ? detail.Description : "",
      CreatedBy: null,  // only IRIS's list has CreatedBy
      EscalationOnly: detail ? detail.EscalationOnly : null,
      Listed: false,
      Detail: detail,
    });
  }
  return rows;
}

// --- KPI cards ---

function superUserHolderCounts() {
  if (!Array.isArray(superUserOwners)) return null;
  const direct = new Set(superUserOwners.filter((o) => o.Type === "User").map((o) => o.Name));
  const escalation = new Set(superUserOwners.filter((o) => o.Type === "User (escalation)").map((o) => o.Name));
  const roles = new Set(superUserOwners.filter((o) => o.Type === "Role").map((o) => o.Name));
  return { users: new Set([...direct, ...escalation]).size, direct: direct.size, escalation: escalation.size, roles: roles.size };
}

function renderSummary() {
  const unlisted = unlistedRoleNames();
  const holders = superUserHolderCounts();
  const cards = [
    { label: "Users", value: users.length, accent: "var(--color-accent)", action: () => showFilteredTab("users", { status: "" }) },
    { label: "Enabled Users", value: users.filter((u) => u.Enabled === true).length, accent: "var(--color-chart-3)",
      action: () => showFilteredTab("users", { status: "enabled" }) },
    { label: "Disabled Users", value: users.filter((u) => u.Enabled === false).length, accent: "var(--color-chart-neutral)",
      action: () => showFilteredTab("users", { status: "disabled" }) },
    { label: "Roles", value: listedRoles.length, accent: "var(--color-chart-2)",
      meta: unlisted.length > 0 ? `+${unlisted.length} not in IRIS's role list` : null,
      title: "Count of IRIS's own role list (GET /v2/security/roles)", action: () => showFilteredTab("roles", {}) },
    { label: "Resources", value: resources.length, accent: "var(--color-chart-6)", action: () => showFilteredTab("resources", { public: "" }) },
    { label: "Public Resources", value: resources.filter((r) => r.PublicPermission !== "").length, accent: "var(--color-chart-4)",
      title: "Resources with a non-empty PublicPermission", action: () => showFilteredTab("resources", { public: "public" }) },
    { label: "%All Holders", value: holders ? holders.users : "Unavailable", accent: "var(--color-warning)",
      meta: holders ? `${holders.direct} direct · ${holders.escalation} via escalation` : null,
      title: "Distinct users IRIS reports as holding %All (role/owners)",
      action: () => {
        setPrivilegedExpanded(true);
        document.getElementById("security-privileged-section").scrollIntoView({ behavior: "smooth", block: "start" });
      } },
  ];

  dom.summaryGrid.replaceChildren(
    ...cards.map((card, index) => {
      const el = document.createElement("article");
      el.className = "stat-card stat-card--interactive";
      el.style.setProperty("--stat-card-accent", card.accent);
      el.setAttribute("role", "button");
      el.setAttribute("tabindex", "0");
      el.dataset.cardIndex = String(index);
      if (card.title) el.title = card.title;
      const label = document.createElement("h3");
      label.className = "stat-card__label";
      label.textContent = card.label;
      const value = document.createElement("p");
      value.className = typeof card.value === "number" ? "stat-card__value" : "stat-card__value stat-card__value--unavailable";
      value.textContent = String(card.value);
      el.append(label, value);
      if (card.meta) {
        const meta = document.createElement("p");
        meta.className = "stat-card__meta";
        meta.textContent = card.meta;
        el.append(meta);
      }
      return el;
    }),
  );
  summaryActions = cards.map((card) => card.action);
}

let summaryActions = [];

function showFilteredTab(tab, filters) {
  setTab(tab);
  const controls = dom[tab];
  if (tab === "users" && "status" in filters) controls.status.value = filters.status;
  if (tab === "resources" && "public" in filters) controls.public.value = filters.public;
  renderActiveTable();
  dom.tabs.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- Privileged Access ---

// The holders table and %Admin_Secure list start collapsed to keep the
// page short.
function setPrivilegedExpanded(expanded) {
  dom.privilegedDetails.hidden = !expanded;
  dom.privilegedToggle.setAttribute("aria-expanded", String(expanded));
  dom.privilegedToggle.textContent = expanded ? "Hide details" : "View details →";
}

function renderPrivileged() {
  dom.privilegedBody.replaceChildren();
  if (!Array.isArray(superUserOwners)) {
    dom.privilegedWrapper.hidden = true;
    dom.privilegedError.hidden = false;
    dom.privilegedError.textContent = "Could not load the holders of %All from IRIS.";
  } else if (superUserOwners.length === 0) {
    dom.privilegedWrapper.hidden = true;
    dom.privilegedError.hidden = false;
    dom.privilegedError.textContent = "IRIS reports no holders of %All.";
  } else {
    dom.privilegedError.hidden = true;
    dom.privilegedWrapper.hidden = false;
    for (const owner of superUserOwners) {
      const kind = owner.Type === "Role" ? "role" : "user";
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = kind;
      row.dataset.openName = owner.Name;
      row.setAttribute("aria-label", `View ${kind} ${owner.Name}`);
      const variant = owner.Type === "User (escalation)" ? "status-badge--warning" : "status-badge--neutral";
      row.append(
        makeCell(textOrPlaceholder(owner.Name), { mono: true }),
        makeBadgeCell(makeBadge(textOrPlaceholder(owner.Type), variant)),
        makeCell(formatAdminOption(owner.AdminOption)),
      );
      dom.privilegedBody.append(row);
    }
  }

  const grants = rolesGranting(SECURITY_ADMIN_RESOURCE);
  dom.adminSecureList.replaceChildren(
    makeInfoRow(
      `Roles granting ${SECURITY_ADMIN_RESOURCE}`,
      null,
      grants === null
        ? "Unavailable — role details could not be loaded"
        : makeLinkChips("role", grants.map((g) => g.role), (role) => {
            const grant = grants.find((g) => g.role === role);
            return `${role} (${grant.permissions})`;
          }),
    ),
  );
}

// --- tables ---

function renderUsersTable() {
  const c = dom.users;
  const query = c.search.value.trim().toLowerCase();
  const visible = users.filter((user) => {
    if (c.status.value === "enabled" && user.Enabled !== true) return false;
    if (c.status.value === "disabled" && user.Enabled !== false) return false;
    if (c.type.value && user.Type !== c.type.value) return false;
    if (!query) return true;
    return ["Name", "FullName", "Namespace", "Routine"].some((f) => includesText(user[f], query));
  });

  c.body.replaceChildren(
    ...visible.map((user) => {
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = "user";
      row.dataset.openName = user.Name;
      row.setAttribute("aria-label", `View user ${user.Name}`);
      row.append(
        makeCell(textOrPlaceholder(user.Name), { mono: true }),
        makeCell(textOrPlaceholder(user.FullName)),
        makeBadgeCell(user.Enabled ? makeBadge("Enabled", "status-badge--ok") : makeBadge("Disabled", "status-badge--neutral")),
        makeCell(textOrPlaceholder(user.Type)),
        makeCell(textOrPlaceholder(user.Namespace)),
        makeCell(textOrPlaceholder(user.Routine), { mono: true }),
      );
      return row;
    }),
  );
  finishTable(c, visible.length, users.length, [c.status, c.type], query);
}

function renderRolesTable() {
  const c = dom.roles;
  const query = c.search.value.trim().toLowerCase();
  const all = roleRows();
  const visible = all.filter((role) => {
    if (c.escalation.value === "yes" && role.EscalationOnly !== true) return false;
    if (c.escalation.value === "no" && role.EscalationOnly !== false) return false;
    if (c.resource.value && !(role.Detail && role.Detail.Resources.some((r) => r.Name === c.resource.value))) return false;
    if (!query) return true;
    return includesText(role.Name, query) || includesText(role.Description, query);
  });

  c.body.replaceChildren(
    ...visible.map((role) => {
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = "role";
      row.dataset.openName = role.Name;
      row.setAttribute("aria-label", `View role ${role.Name}`);
      const detail = role.Detail;
      row.append(
        makeNameCell(role.Name, role.Listed ? null : makeBadge("Not in IRIS list", "status-badge--warning")),
        makeCell(textOrPlaceholder(role.Description)),
        makeCell(detail ? String(detail.Resources.length) : PLACEHOLDER, {
          title: detail ? "Resource grants in this role's detail" : "Role detail unavailable",
        }),
        makeCell(detail ? String(detail.GrantedRoles.length) : PLACEHOLDER),
        makeCell(formatBoolean(role.EscalationOnly)),
        role.Listed
          ? makeCell(textOrPlaceholder(role.CreatedBy))
          : makeCell(PLACEHOLDER, { title: "Not reported — only IRIS's role list carries CreatedBy" }),
      );
      return row;
    }),
  );

  const unlisted = unlistedRoleNames();
  c.unlistedHint.hidden = unlisted.length === 0;
  c.unlistedHint.textContent =
    unlisted.length === 0
      ? ""
      : `IRIS's role list (${listedRoles.length} roles) does not include ${unlisted.join(", ")}. ` +
        "Shown here because IRIS returns its role detail; marked \"Not in IRIS list\" and not counted in the Roles card.";
  finishTable(c, visible.length, all.length, [c.escalation, c.resource], query);
}

function renderResourcesTable() {
  const c = dom.resources;
  const query = c.search.value.trim().toLowerCase();
  const visible = resources.filter((resource) => {
    if (c.type.value && resource.ResourceType !== c.type.value) return false;
    if (c.public.value === "public" && resource.PublicPermission === "") return false;
    if (c.public.value === "none" && resource.PublicPermission !== "") return false;
    if (!query) return true;
    return includesText(resource.Name, query) || includesText(resource.Description, query);
  });

  c.body.replaceChildren(
    ...visible.map((resource) => {
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = "resource";
      row.dataset.openName = resource.Name;
      row.setAttribute("aria-label", `View resource ${resource.Name}`);
      const grants = rolesGranting(resource.Name);
      row.append(
        makeCell(textOrPlaceholder(resource.Name), { mono: true }),
        makeCell(textOrPlaceholder(resource.ResourceType)),
        makeCell(textOrPlaceholder(resource.Description)),
        makeCell(textOrPlaceholder(resource.PublicPermission), {
          mono: true,
          title: formatPermissions(resource.PublicPermission),
        }),
        makeCell(grants === null ? PLACEHOLDER : `${grants.length} role${grants.length === 1 ? "" : "s"}`),
        makeCell(formatBoolean(resource.AllowDelete)),
      );
      return row;
    }),
  );
  finishTable(c, visible.length, resources.length, [c.type, c.public], query);
}

function finishTable(c, shown, total, selects, query) {
  const filtered = query !== "" || selects.some((s) => s.value !== "");
  c.wrapper.hidden = shown === 0;
  c.empty.hidden = shown !== 0;
  c.clear.disabled = !filtered;
  c.count.textContent = filtered ? `Showing ${shown} of ${total}` : `Showing all ${total}`;
}

function renderActiveTable() {
  if (activeTab === "users") renderUsersTable();
  else if (activeTab === "roles") renderRolesTable();
  else if (activeTab === "resources") renderResourcesTable();
}

function setTab(tab) {
  activeTab = TABS.includes(tab) ? tab : "users";
  for (const button of dom.tabs.querySelectorAll("[role=tab]")) {
    const selected = button.dataset.tab === activeTab;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  for (const name of TABS) dom.panels[name].hidden = name !== activeTab;
  renderActiveTable();
  dom.tabs.dispatchEvent(new CustomEvent("security-tab-shown", { detail: { tab: activeTab } }));
}

// --- drawer ---

function setDrawerHeader(kind, name, status) {
  dom.drawerTitle.textContent = name;
  dom.drawerKind.textContent = kind;
  dom.drawerStatus.hidden = !status;
  if (status) {
    dom.drawerStatus.className = `status-badge ${status[1]}`;
    dom.drawerStatus.textContent = status[0];
  }
  dom.drawerBack.hidden = drawerStack.length < 2;
}

function showDrawerError(message) {
  dom.drawerErrorText.textContent = message;
  dom.drawerError.hidden = false;
}

function errorMessage(err, what) {
  if (err instanceof ApiError && err.status === 404) return `IRIS reports no ${what} with this name.`;
  if (err instanceof ApiError) return `Could not load this ${what} from IRIS.`;
  return `An unexpected error occurred while loading this ${what}.`;
}

// --- Login Access (user.set_enabled, the only change on this page) ---
//
// Same flow as Enabled State in the Web Apps drawer. "Check" sends a dry
// run (setUserEnabled(fields, true, true); the dry run still needs
// confirmed=true to get past the executor, and never sends the PUT). Only a
// successful preview shows the confirm button, which needs the checkbox
// ticked, and only its click handler sends the real request. The backend
// does all the authorization and protection checks; this just shows what
// it says.

// Last result per user, so it stays visible after the lists reload.
const lastUserResults = new Map();

function makeResultList(result) {
  const rows = [
    ["Status", textOrPlaceholder(result.status)],
    ["Detail", textOrPlaceholder(result.detail)],
  ];
  if (result.handler_result) rows.push(["Execution Detail", textOrPlaceholder(result.handler_result.detail)]);
  if (result.verification) {
    rows.push(["Verification Status", textOrPlaceholder(result.verification.status)]);
    rows.push(["Verification Detail", textOrPlaceholder(result.verification.detail)]);
  }
  return makeInfoList(rows.map(([label, value]) => makeInfoRow(label, null, value)));
}

function makeLoginAccessSection(name, enabled) {
  const section = makeSection("Login Access");
  section.dataset.primaryOnly = "";
  if (typeof enabled !== "boolean") {
    section.append(makeNote("IRIS did not report whether this user is enabled, so it cannot be changed here."));
    return section;
  }
  const target = !enabled;
  const verb = target ? "Enable" : "Disable";
  const seq = drawerSeq;
  const isCurrent = () => seq === drawerSeq;

  const hint = makeNote(
    `${verb}s this user's login through the authorization → confirmation → execution → verification framework. ` +
      "Check is a read-only dry run; nothing is sent to IRIS until you explicitly confirm, and only the Enabled " +
      "setting is ever sent. IRIS's predefined accounts, the Command Center's own account and %All holders are " +
      "refused by the backend.",
  );
  const checkButton = document.createElement("button");
  checkButton.type = "button";
  checkButton.className = "btn";
  checkButton.textContent = `Check ${verb}`;

  const loading = document.createElement("div");
  loading.className = "loading-state";
  loading.hidden = true;
  const spinner = document.createElement("span");
  spinner.className = "spinner";
  spinner.setAttribute("aria-hidden", "true");
  const loadingText = document.createElement("span");
  loading.append(spinner, loadingText);

  const error = document.createElement("div");
  error.className = "banner banner--error";
  error.setAttribute("role", "alert");
  error.hidden = true;

  const confirm = document.createElement("div");
  confirm.hidden = true;
  const preview = document.createElement("div");
  preview.className = "banner banner--warning";
  preview.setAttribute("role", "alert");
  const ackLabel = document.createElement("label");
  ackLabel.className = "ns-form-checkbox";
  const ack = document.createElement("input");
  ack.type = "checkbox";
  const ackText = document.createElement("span");
  ackText.textContent = `I understand this will ${verb.toLowerCase()} login for ${name} on the IRIS instance.`;
  ackLabel.append(ack, ackText);
  const confirmRow = document.createElement("div");
  confirmRow.className = "btn-row";
  const confirmButton = document.createElement("button");
  confirmButton.type = "button";
  confirmButton.className = "btn btn--warning";
  confirmButton.textContent = `Confirm & ${verb}`;
  confirmButton.disabled = true;
  confirmRow.append(confirmButton);
  confirm.append(preview, ackLabel, confirmRow);

  const resultHolder = document.createElement("div");
  const previous = lastUserResults.get(name);
  if (previous) resultHolder.append(makeResultList(previous));

  let pendingFields = null;
  const clearPreview = () => {
    pendingFields = null;
    confirm.hidden = true;
    ack.checked = false;
    confirmButton.disabled = true;
  };
  const showError = (message) => {
    error.textContent = message;
    error.hidden = false;
  };
  const setBusy = (busy, message) => {
    checkButton.disabled = busy;
    loading.hidden = !busy;
    loadingText.textContent = message || "";
  };

  checkButton.addEventListener("click", async () => {
    const fields = { Name: name, Enabled: target };
    clearPreview();
    error.hidden = true;
    setBusy(true, "Checking with IRIS (dry run)…");
    try {
      const result = await IrisApi.setUserEnabled(fields, true, true);
      if (!isCurrent()) return;
      const handlerResult = result && result.handler_result;
      if (result.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
        pendingFields = fields;
        preview.textContent = handlerResult.detail;
        confirm.hidden = false;
      } else {
        // Unauthorized, protected, no change, unknown user... shown as the
        // backend explained it.
        showError((handlerResult && handlerResult.detail) || result.detail || "This change could not be validated against IRIS.");
      }
    } catch (err) {
      if (!isCurrent()) return;
      showError(
        err instanceof ApiError
          ? "Could not reach the Command Center backend to check this change."
          : "An unexpected error occurred while checking this change.",
      );
    } finally {
      if (isCurrent()) setBusy(false);
    }
  });

  ack.addEventListener("change", () => {
    confirmButton.disabled = !(pendingFields && ack.checked);
  });

  // The only place that sends a real change. Only reachable from this button,
  // after a successful preview and the checkbox.
  confirmButton.addEventListener("click", async () => {
    const fields = pendingFields;
    if (!fields) return;
    clearPreview();
    setBusy(true, fields.Enabled ? "Enabling login…" : "Disabling login…");
    let result;
    try {
      result = await IrisApi.setUserEnabled(fields, true, false);
    } catch (err) {
      result = {
        status: "request_failed",
        detail:
          err instanceof ApiError
            ? "Could not reach the Command Center backend to change this user."
            : "An unexpected error occurred while changing this user.",
      };
    }
    lastUserResults.set(fields.Name, result);
    if (!isCurrent()) return;
    setBusy(false);
    resultHolder.replaceChildren(makeResultList(result));
    if (result.status === "success" || result.status === "verification_failed") {
      // Reload the lists instead of patching local state; the drawer re-renders
      // and keeps showing the result.
      await loadSecurityAccess();
    }
  });

  section.append(hint, checkButton, loading, error, confirm, resultHolder);
  return section;
}

async function renderUserDrawer(name, seq) {
  const listEntry = users.find((u) => u.Name === name);
  setDrawerHeader("User", name, listEntry ? (listEntry.Enabled ? ["Enabled", "status-badge--ok"] : ["Disabled", "status-badge--neutral"]) : null);
  dom.drawerHint.textContent = "Personal fields are withheld by the Command Center backend.";

  const response = await IrisApi.getSecurityUserDetail(name, selectedInstanceId());
  if (seq !== drawerSeq) return;
  const user = response && response.result;
  if (!user || typeof user !== "object") throw new Error("unexpected shape");

  const withheld = Array.isArray(user.WithheldFields) ? user.WithheldFields : [];
  if (withheld.length > 0) {
    dom.drawerHint.textContent = `Withheld by the Command Center backend: ${withheld.join(", ")}.`;
  }
  dom.drawerBody.replaceChildren(
    makeSection("Account", makeInfoList([
      makeInfoRow("Full Name", "FullName", textOrPlaceholder(user.FullName)),
      makeInfoRow("Type", "Type", textOrPlaceholder(listEntry && listEntry.Type)),
      makeInfoRow("Enabled", "Enabled", formatBoolean(user.Enabled)),
      makeInfoRow("Account Never Expires", "AccountNeverExpires", formatBoolean(user.AccountNeverExpires)),
      makeInfoRow("Expiration Date", "ExpirationDate", textOrPlaceholder(user.ExpirationDate), { mono: true }),
    ])),
    makeSection("Roles", makeInfoList([
      makeInfoRow("Roles", "Roles", makeLinkChips("role", user.Roles)),
      makeInfoRow("Escalation Roles", "EscalationRoles", makeLinkChips("role", user.EscalationRoles)),
    ])),
    makeSection("Password & Two-Factor", makeInfoList([
      makeInfoRow("Change Password At Next Login", "ChangePassword", formatBoolean(user.ChangePassword)),
      makeInfoRow("Password Never Expires", "PasswordNeverExpires", formatBoolean(user.PasswordNeverExpires)),
      makeInfoRow("Two-Factor Methods", "AutheEnabled", formatTwoFactor(user.AutheEnabled), { mono: true }),
      makeInfoRow("Show TOTP Key At Next Login", "HOTPKeyDisplay", formatBoolean(user.HOTPKeyDisplay)),
    ])),
    makeSection("Startup", makeInfoList([
      makeInfoRow("Namespace", "NameSpace", textOrPlaceholder(user.NameSpace)),
      makeInfoRow("Routine", "Routine", textOrPlaceholder(user.Routine), { mono: true }),
    ])),
    makeLoginAccessSection(name, user.Enabled),
  );
}

async function renderRoleDrawer(name, seq) {
  const listed = listedRoles.find((r) => r.Name === name);
  const mapEntry = accessMap && accessMap.get(name);
  const status = !listed && mapEntry && !mapEntry.Listed ? ["Not in IRIS list", "status-badge--warning"] : null;
  setDrawerHeader("Role", name, status);
  dom.drawerHint.textContent = "Read-only. Grants and holders exactly as IRIS reports them.";

  const [detailResult, ownersResult] = await Promise.allSettled([
    IrisApi.getSecurityRoleDetail(name, selectedInstanceId()),
    IrisApi.getSecurityRoleOwners(name, selectedInstanceId()),
  ]);
  if (seq !== drawerSeq) return;
  if (detailResult.status === "rejected") throw detailResult.reason;
  const role = detailResult.value && detailResult.value.result;
  if (!role || typeof role !== "object") throw new Error("unexpected shape");

  const overview = [
    makeInfoRow("Description", "Description", textOrPlaceholder(role.Description)),
    makeInfoRow("Escalation Only", "EscalationOnly", formatBoolean(role.EscalationOnly)),
    makeInfoRow(
      "Created By",
      "CreatedBy",
      listed ? textOrPlaceholder(listed.CreatedBy) : "Not reported — IRIS's role list does not include this role",
    ),
  ];

  const resourceSection = makeSection(
    "Resources & Permissions",
    role.Resources.length === 0
      ? makeNote("IRIS lists no resource grants for this role.")
      : makeLinkTable(
          ["Resource", "Permissions"],
          role.Resources.map((grant) => ({ kind: "resource", name: grant.Name, cells: [formatPermissions(grant.Permissions)] })),
        ),
  );

  let holders;
  if (ownersResult.status === "rejected") {
    holders = makeNote("Could not load this role's holders from IRIS.");
  } else {
    const owners = Array.isArray(ownersResult.value && ownersResult.value.result) ? ownersResult.value.result : [];
    holders =
      owners.length === 0
        ? makeNote("IRIS reports no holders of this role.")
        : makeLinkTable(
            ["Holder", "Type", "Admin Option"],
            owners.map((owner) => ({
              kind: owner.Type === "Role" ? "role" : "user",
              name: owner.Name,
              cells: [textOrPlaceholder(owner.Type), formatAdminOption(owner.AdminOption)],
            })),
          );
  }

  dom.drawerBody.replaceChildren(
    makeSection("Overview", makeInfoList(overview)),
    makeSection("Granted Roles", makeLinkChips("role", role.GrantedRoles)),
    resourceSection,
    makeSection("Holders", holders),
  );
}

async function renderResourceDrawer(name, seq) {
  const listEntry = resources.find((r) => r.Name === name);
  setDrawerHeader("Resource", name, listEntry ? [listEntry.ResourceType, "status-badge--neutral"] : null);
  dom.drawerHint.textContent = "Read-only. Granting roles come from each role's IRIS detail.";

  const response = await IrisApi.getSecurityResourceDetail(name, selectedInstanceId());
  if (seq !== drawerSeq) return;
  const resource = response && response.result;
  if (!resource || typeof resource !== "object") throw new Error("unexpected shape");

  const grants = rolesGranting(name);
  dom.drawerBody.replaceChildren(
    makeSection("Resource", makeInfoList([
      makeInfoRow("Description", "Description", textOrPlaceholder(resource.Description)),
      makeInfoRow("Type", "ResourceType", textOrPlaceholder(listEntry && listEntry.ResourceType)),
      makeInfoRow("Public Permission", "PublicPermission", formatPermissions(resource.PublicPermission), { mono: true }),
      makeInfoRow("Allow Delete", "AllowDelete", formatBoolean(listEntry && listEntry.AllowDelete)),
    ])),
    makeSection(
      "Granted By Roles",
      grants === null
        ? makeNote("Role details could not be loaded, so granting roles are unknown.")
        : grants.length === 0
          ? makeNote("No role's IRIS detail grants this resource.")
          : makeLinkTable(
              ["Role", "Permissions"],
              grants.map((g) => ({ kind: "role", name: g.role, cells: [formatPermissions(g.permissions)] })),
            ),
    ),
  );
}

async function renderDrawerTop() {
  const top = drawerStack[drawerStack.length - 1];
  if (!top) return;
  const seq = ++drawerSeq;
  dom.drawerBody.replaceChildren();
  dom.drawerError.hidden = true;
  dom.drawerLoading.hidden = false;
  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawer.scrollTop = 0;
  if (wasHidden) dom.drawerClose.focus();

  const renderer =
    { user: renderUserDrawer, role: renderRoleDrawer, resource: renderResourceDrawer }[top.kind] ||
    extraDrawerRenderers.get(top.kind);
  try {
    await renderer(top.name, seq);
  } catch (err) {
    if (seq === drawerSeq) showDrawerError(errorMessage(err, top.kind));
  } finally {
    if (seq === drawerSeq) dom.drawerLoading.hidden = true;
  }
}

function openEntity(kind, name, { push = true } = {}) {
  if (!(["user", "role", "resource"].includes(kind) || extraDrawerRenderers.has(kind)) || !name) return;
  if (!push || dom.drawer.hidden) drawerStack = [];
  drawerStack.push({ kind, name });
  renderDrawerTop();
}

function drawerBack() {
  if (drawerStack.length < 2) return;
  drawerStack.pop();
  renderDrawerTop();
}

function closeDrawer() {
  drawerStack = [];
  drawerSeq += 1;  // ignore any response still in flight
  dom.drawerLoading.hidden = true;
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

// --- load ---

function setLoading(isLoading) {
  dom.loading.hidden = !isLoading;
}

function setErrorBanner(message) {
  dom.errorBanner.hidden = !message;
  dom.errorBannerText.textContent = message || "";
}

function resultList(settled) {
  return settled.status === "fulfilled" && settled.value && Array.isArray(settled.value.result)
    ? settled.value.result
    : null;
}

/**
 * Load users, roles, the access map, resources and the %All holders in
 * parallel. allSettled so one failure doesn't block the rest.
 */
export async function loadSecurityAccess() {
  const seq = ++loadSeq;
  setLoading(true);
  setErrorBanner(null);

  const results = await Promise.allSettled([
    IrisApi.getSecurityUsers(selectedInstanceId()),
    IrisApi.getSecurityRoles(selectedInstanceId()),
    IrisApi.getSecurityRoleAccessMap(selectedInstanceId()),
    IrisApi.getSecurityResources(selectedInstanceId()),
    IrisApi.getSecurityRoleOwners(SUPER_USER_ROLE, selectedInstanceId()),
  ]);
  if (seq !== loadSeq) return;
  const [usersResult, rolesResult, mapResult, resourcesResult, ownersResult] = results;

  const loadedUsers = resultList(usersResult);
  const loadedRoles = resultList(rolesResult);
  const loadedMap = resultList(mapResult);
  const loadedResources = resultList(resourcesResult);
  users = loadedUsers || [];
  listedRoles = loadedRoles || [];
  accessMap = loadedMap ? new Map(loadedMap.map((entry) => [entry.Name, entry])) : null;
  resources = loadedResources || [];
  superUserOwners = resultList(ownersResult);

  const failed = [
    [loadedUsers, "users"],
    [loadedRoles, "roles"],
    [loadedMap, "role details"],
    [loadedResources, "resources"],
    [superUserOwners, "%All holders"],
  ].filter(([value]) => value === null).map(([, label]) => label);
  const mapWarnings =
    mapResult.status === "fulfilled" && mapResult.value.status && Array.isArray(mapResult.value.status.errors)
      ? mapResult.value.status.errors.length
      : 0;

  if (failed.length === results.length) {
    dom.content.hidden = true;
    setErrorBanner("Could not load identity and access data. The Command Center backend may be unreachable.");
    setLoading(false);
    return;
  }
  const messages = [];
  if (failed.length > 0) messages.push(`Could not load ${failed.join(", ")}. The rest is shown below.`);
  if (mapWarnings > 0) messages.push(`IRIS did not return details for ${mapWarnings} role${mapWarnings === 1 ? "" : "s"}.`);
  setErrorBanner(messages.join(" ") || null);

  populateSelect(dom.users.type, "All types", uniqueSorted(users.map((u) => u.Type)));
  populateSelect(dom.resources.type, "All types", uniqueSorted(resources.map((r) => r.ResourceType)));
  const grantedResources = accessMap
    ? uniqueSorted([...accessMap.values()].flatMap((e) => (e.Detail ? e.Detail.Resources.map((r) => r.Name) : [])))
    : [];
  populateSelect(dom.roles.resource, "Any resource", grantedResources);

  dom.content.hidden = false;
  renderSummary();
  renderPrivileged();
  setTab(activeTab);
  setLoading(false);

  // After a refresh, reopen the drawer's current item with fresh data.
  if (!dom.drawer.hidden && drawerStack.length > 0) renderDrawerTop();
}

// --- API for the other Security modules ---
//
// Lets them show their own item kinds (e.g. "service") in this drawer, with
// the same Back history, loading/error states and stale-response check, and
// use the same DOM helpers. A renderer is `async (name, isCurrent) => void`:
// it fills `securityUi.drawerBody` and should stop if `isCurrent()` turns
// false after an await. A thrown ApiError is shown in the drawer.

const extraDrawerRenderers = new Map();

export function registerSecurityDrawerRenderer(kind, renderer) {
  extraDrawerRenderers.set(kind, (name, seq) => renderer(name, () => seq === drawerSeq));
}

export function openSecurityDrawer(kind, name) {
  openEntity(kind, name, { push: false });
}

export const securityUi = {
  drawerBody: dom.drawerBody,
  drawerHint: dom.drawerHint,
  setDrawerHeader,
  textOrPlaceholder,
  formatBoolean,
  includesText,
  makeCell,
  makeBadge,
  makeBadgeCell,
  makeInfoRow,
  makeInfoList,
  makeSection,
  makeNote,
  makeLinkChips,
  makeLinkTable,
  populateSelect,
  uniqueSorted,
};

function onActivate(event, handler) {
  if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
  const target = event.target.closest("[data-open-kind]");
  if (!target) return;
  if (event.type === "keydown") event.preventDefault();
  handler(target.dataset.openKind, target.dataset.openName);
}

export function initSecurityAccessControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadSecurityAccess();
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

  dom.privilegedToggle.addEventListener("click", () => {
    setPrivilegedExpanded(dom.privilegedDetails.hidden);
  });

  dom.tabs.addEventListener("click", (event) => {
    const tab = event.target.closest("[role=tab]");
    if (tab) setTab(tab.dataset.tab);
  });
  dom.tabs.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    setTab(TABS[(TABS.indexOf(activeTab) + step + TABS.length) % TABS.length]);
    dom.tabs.querySelector(`[data-tab="${activeTab}"]`).focus();
  });

  // Filters the last loaded data locally, no request.
  const tables = [
    [dom.users, [dom.users.status, dom.users.type], renderUsersTable],
    [dom.roles, [dom.roles.escalation, dom.roles.resource], renderRolesTable],
    [dom.resources, [dom.resources.type, dom.resources.public], renderResourcesTable],
  ];
  for (const [c, selects, render] of tables) {
    c.form.addEventListener("submit", (event) => event.preventDefault());
    c.search.addEventListener("input", render);
    for (const select of selects) select.addEventListener("change", render);
    c.clear.addEventListener("click", () => {
      c.search.value = "";
      for (const select of selects) select.value = "";
      render();
    });
    for (const type of ["click", "keydown"]) {
      c.body.addEventListener(type, (event) => onActivate(event, (kind, name) => openEntity(kind, name, { push: false })));
    }
  }
  for (const type of ["click", "keydown"]) {
    dom.privilegedBody.addEventListener(type, (event) => onActivate(event, (kind, name) => openEntity(kind, name, { push: false })));
    dom.adminSecureList.addEventListener(type, (event) => onActivate(event, (kind, name) => openEntity(kind, name, { push: false })));
  }
  // Links in the drawer push onto its history so Back works.
  for (const type of ["click", "keydown"]) {
    dom.drawerBody.addEventListener(type, (event) => onActivate(event, (kind, name) => openEntity(kind, name)));
  }

  dom.drawerBack.addEventListener("click", drawerBack);
  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDrawer();
  });
}
