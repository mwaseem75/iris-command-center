// Security view — Identity & Access: KPI cards, a Privileged Access panel,
// Users / Roles / Resources tabs with client-side search/filters, and one
// shared detail drawer that can walk user → role → resource (with Back).
// OAuth 2.0 on the same page stays in security.js.
//
// Read-only. It calls only these GET endpoints (all via IrisApi, see
// backend/app/routes/security_access.py) and no mutating one:
//   - getSecurityUsers / getSecurityUserDetail(name) — personal fields
//     (email, phone, free-text comment) are withheld by the backend; only their names arrive,
//     in WithheldFields. IRIS returns no password or hash.
//   - getSecurityRoles, getSecurityRoleDetail(name), getSecurityRoleOwners(name)
//   - getSecurityRoleAccessMap — every role's grants in one response, the
//     source of resource → role lookups and per-role counts.
//   - getSecurityResources / getSecurityResourceDetail(name)
//
// IRIS's role list omits %SQLTuneTable (observed on 2026.2). The Roles KPI
// is IRIS's own list count; roles the access map confirms exist but that
// the list omits are shown separately, marked "Not in IRIS list", and never
// folded into that count.

import { IrisApi, ApiError } from "./api.js";

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
  adminSecureList: $("security-admin-secure-list"),
  tabs: $("security-access-tabs"),
  panels: {
    users: $("security-panel-users"),
    roles: $("security-panel-roles"),
    resources: $("security-panel-resources"),
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

const TABS = ["users", "roles", "resources"];

// Resource permission letters, per mainspec_v2.json ("a string consisting
// only of 'R', 'W', and 'U'").
const PERMISSION_NAMES = { R: "Read", W: "Write", U: "Use" };

// User AutheEnabled bits, per mainspec_v2.json ("Two factor Authentication
// options ... 2**20 - SMS Text authentication, 2**21 - Time-based One-time
// Password").
const TWO_FACTOR_BITS = [
  [20, "SMS text"],
  [21, "Time-based one-time password"],
];

// Data from the last successful load. Filtering and the drawer read from
// these; neither re-fetches the lists.
let users = [];
let listedRoles = []; // IRIS's role list, exactly as returned
let accessMap = null; // Map name → {Listed, Detail}, or null if it failed to load
let resources = [];
let superUserOwners = null; // owners of %All, or null if unavailable
let activeTab = "users";
let drawerStack = []; // [{kind, name}] — the drawer's Back history
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

/** role/owners' AdminOption: documented boolean, observed as "0" (string)
 * on User/Role rows and false on escalation rows. "0"/"1" are read as the
 * boolean strings IRIS uses; anything else is shown raw. */
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

// Every row, cell and drawer value is built with createElement +
// textContent — never innerHTML — so IRIS-supplied names/descriptions can
// never be interpreted as markup.
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

/** Chips that open another entity in the drawer (e.g. a user's roles). */
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

/** A compact table whose rows open another entity in the drawer.
 * `rows` is [{kind, name, cells: [text, ...]}]; the first column is the name. */
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
    tr.setAttribute("aria-label", `View ${row.kind} ${row.name}`);
    tr.append(makeCell(row.name, { mono: true }), ...row.cells.map((text) => makeCell(text)));
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

// --- derived views over the access map (real grants only) ---

function roleDetail(name) {
  const entry = accessMap && accessMap.get(name);
  return entry ? entry.Detail : null;
}

/** Roles not in IRIS's role list that the access map confirms exist. */
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

/** Every role row shown in the Roles table: IRIS's list, then unlisted. */
function roleRows() {
  const rows = listedRoles.map((role) => ({ ...role, Listed: true, Detail: roleDetail(role.Name) }));
  for (const name of unlistedRoleNames()) {
    const detail = roleDetail(name);
    rows.push({
      Name: name,
      Description: detail ? detail.Description : "",
      CreatedBy: null, // not reported: only IRIS's list carries CreatedBy
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
      action: () => document.getElementById("security-privileged-section").scrollIntoView({ behavior: "smooth", block: "start" }) },
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
  else renderResourcesTable();
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

async function renderUserDrawer(name, seq) {
  const listEntry = users.find((u) => u.Name === name);
  setDrawerHeader("User", name, listEntry ? (listEntry.Enabled ? ["Enabled", "status-badge--ok"] : ["Disabled", "status-badge--neutral"]) : null);
  dom.drawerHint.textContent = "Read-only. Personal fields are withheld by the Command Center backend.";

  const response = await IrisApi.getSecurityUserDetail(name);
  if (seq !== drawerSeq) return;
  const user = response && response.result;
  if (!user || typeof user !== "object") throw new Error("unexpected shape");

  const withheld = Array.isArray(user.WithheldFields) ? user.WithheldFields : [];
  if (withheld.length > 0) {
    dom.drawerHint.textContent = `Read-only. Withheld by the Command Center backend: ${withheld.join(", ")}.`;
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
  );
}

async function renderRoleDrawer(name, seq) {
  const listed = listedRoles.find((r) => r.Name === name);
  const mapEntry = accessMap && accessMap.get(name);
  const status = !listed && mapEntry && !mapEntry.Listed ? ["Not in IRIS list", "status-badge--warning"] : null;
  setDrawerHeader("Role", name, status);
  dom.drawerHint.textContent = "Read-only. Grants and holders exactly as IRIS reports them.";

  const [detailResult, ownersResult] = await Promise.allSettled([
    IrisApi.getSecurityRoleDetail(name),
    IrisApi.getSecurityRoleOwners(name),
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

  const response = await IrisApi.getSecurityResourceDetail(name);
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

  const renderer = { user: renderUserDrawer, role: renderRoleDrawer, resource: renderResourceDrawer }[top.kind];
  try {
    await renderer(top.name, seq);
  } catch (err) {
    if (seq === drawerSeq) showDrawerError(errorMessage(err, top.kind));
  } finally {
    if (seq === drawerSeq) dom.drawerLoading.hidden = true;
  }
}

function openEntity(kind, name, { push = true } = {}) {
  if (!["user", "role", "resource"].includes(kind) || !name) return;
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
  drawerSeq += 1; // discard any in-flight response
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
 * Loads users, roles, the role access map, resources and the holders of
 * %All in parallel. Promise.allSettled: one failing call never blocks the
 * others. Only GETs — no mutating request exists in this file.
 */
export async function loadSecurityAccess() {
  const seq = ++loadSeq;
  setLoading(true);
  setErrorBanner(null);

  const results = await Promise.allSettled([
    IrisApi.getSecurityUsers(),
    IrisApi.getSecurityRoles(),
    IrisApi.getSecurityRoleAccessMap(),
    IrisApi.getSecurityResources(),
    IrisApi.getSecurityRoleOwners(SUPER_USER_ROLE),
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

  // Re-open the drawer's current entity with fresh data after a refresh.
  if (!dom.drawer.hidden && drawerStack.length > 0) renderDrawerTop();
}

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

  // Filtering is client-side over the last fetched lists — never a request.
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
  // Links inside the drawer push onto its history, so Back returns.
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
