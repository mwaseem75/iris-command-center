// Security page, Wallet tab: collections, their edit/use resources, and
// the names and types of their secrets, with details in the shared drawer.
//
// Uses getSecurityWalletOverview, getSecurityWalletCollectionDetail(name)
// and getSecurityWalletSecrets(collection). Secret values are never
// requested (IRIS has no API for that anyway).
//
// Loads the first time the tab is shown, then on Refresh or when the page
// is reopened.

import { IrisApi, ApiError } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";
import { openSecurityDrawer, registerSecurityDrawerRenderer, securityUi as ui } from "./security-access.js";

const PLACEHOLDER = "—";
// IRIS's default maxRows for both list endpoints.
const IRIS_DEFAULT_MAX_ROWS = 1000;
const $ = (id) => document.getElementById(id);

const dom = {
  refreshButton: $("security-refresh-button"),
  tabs: $("security-access-tabs"),
  errorBanner: $("security-wallet-error-banner"),
  errorBannerText: $("security-wallet-error-banner-text"),
  loading: $("security-wallet-loading"),
  content: $("security-wallet-content"),
  summaryGrid: $("security-wallet-summary-grid"),
  none: $("security-wallet-none"),
  sections: $("security-wallet-sections"),
  collections: {
    form: $("security-wallet-collections-filter-form"),
    search: $("security-wallet-collections-search"),
    count: $("security-wallet-collections-count"),
    empty: $("security-wallet-collections-empty"),
    wrapper: $("security-wallet-collections-table-wrapper"),
    body: $("security-wallet-collections-table-body"),
  },
  secrets: {
    form: $("security-wallet-secrets-filter-form"),
    search: $("security-wallet-secrets-search"),
    collection: $("security-wallet-secrets-collection"),
    type: $("security-wallet-secrets-type"),
    clear: $("security-wallet-secrets-clear"),
    count: $("security-wallet-secrets-count"),
    empty: $("security-wallet-secrets-empty"),
    wrapper: $("security-wallet-secrets-table-wrapper"),
    body: $("security-wallet-secrets-table-body"),
  },
};

let collections = null; // overview entries, or null if the load failed
let loaded = false;
let loadSeq = 0;

// --- helpers ---

/**
 * EditResource / UseResource are "resource:permission" strings. With no
 * permission it means WRITE (edit) or READ (use).
 */
function parseResource(value, defaultPermission) {
  if (typeof value !== "string" || value === "") return null;
  const index = value.lastIndexOf(":");
  if (index <= 0) return { resource: value, permission: null, defaultPermission };
  return { resource: value.slice(0, index), permission: value.slice(index + 1), defaultPermission };
}

function describePermission(parsed) {
  if (!parsed) return PLACEHOLDER;
  return parsed.permission || `not specified (IRIS default ${parsed.defaultPermission})`;
}

/**
 * Drawer key for a secret: collection and name joined by a newline (which
 * can't appear in either name).
 */
function secretKey(collection, name) {
  return `${collection}\n${name}`;
}

function allSecrets() {
  if (!collections) return [];
  return collections.flatMap((c) =>
    Array.isArray(c.Secrets) ? c.Secrets.map((s) => ({ collection: c.Name, name: s.Name, type: s.Type })) : [],
  );
}

function secretsCountText(collection) {
  return Array.isArray(collection.Secrets) ? String(collection.Secrets.length) : "Unavailable";
}

function makeResourceCell(value, defaultPermission) {
  const parsed = parseResource(value, defaultPermission);
  const cell = ui.makeCell(parsed ? parsed.resource : "Not reported", { mono: Boolean(parsed) });
  cell.title = parsed ? `${value} — permission: ${describePermission(parsed)}` : "IRIS did not report this field";
  return cell;
}

// --- summary cards ---

function renderSummary() {
  const readable = collections.filter((c) => Array.isArray(c.Secrets));
  const unavailable = collections.length - readable.length;
  const secrets = allSecrets();
  const types = ui.uniqueSorted(secrets.map((s) => s.type));
  const cards = [
    ["Collections", collections.length, null, "var(--color-accent)"],
    [
      "Secrets",
      secrets.length,
      unavailable > 0 ? `unavailable for ${unavailable} collection${unavailable === 1 ? "" : "s"}` : "names and types only",
      "var(--color-chart-2)",
    ],
    ["Secret Types", types.length, types.length ? types.join(", ") : null, "var(--color-chart-6)"],
    ["Empty Collections", readable.filter((c) => c.Secrets.length === 0).length, null, "var(--color-chart-neutral)"],
  ];
  dom.summaryGrid.replaceChildren(
    ...cards.map(([label, value, meta, accent]) => {
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
      if (meta) {
        const metaEl = document.createElement("p");
        metaEl.className = "stat-card__meta";
        metaEl.textContent = meta;
        card.append(metaEl);
      }
      return card;
    }),
  );
}

// --- tables ---

function renderCollectionsTable() {
  const c = dom.collections;
  const query = c.search.value.trim().toLowerCase();
  const visible = collections.filter(
    (entry) =>
      !query ||
      ui.includesText(entry.Name, query) ||
      ui.includesText(entry.EditResource, query) ||
      ui.includesText(entry.UseResource, query),
  );
  c.body.replaceChildren(
    ...visible.map((entry) => {
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = "wallet-collection";
      row.dataset.openName = entry.Name;
      row.setAttribute("aria-label", `View wallet collection ${entry.Name}`);
      row.append(
        ui.makeCell(entry.Name, { mono: true }),
        makeResourceCell(entry.EditResource, "WRITE"),
        makeResourceCell(entry.UseResource, "READ"),
        ui.makeCell(secretsCountText(entry)),
      );
      return row;
    }),
  );
  c.wrapper.hidden = visible.length === 0;
  c.empty.hidden = visible.length !== 0;
  c.count.textContent = query ? `Showing ${visible.length} of ${collections.length}` : `Showing all ${collections.length}`;
}

function renderSecretsTable() {
  const c = dom.secrets;
  const secrets = allSecrets();
  const query = c.search.value.trim().toLowerCase();
  const visible = secrets.filter((secret) => {
    if (c.collection.value && secret.collection !== c.collection.value) return false;
    if (c.type.value && secret.type !== c.type.value) return false;
    return !query || ui.includesText(secret.name, query);
  });
  c.body.replaceChildren(
    ...visible.map((secret) => {
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = "wallet-secret";
      row.dataset.openName = secretKey(secret.collection, secret.name);
      row.setAttribute("aria-label", `View wallet secret ${secret.name}`);
      row.append(
        ui.makeCell(secret.name, { mono: true }),
        ui.makeCell(ui.textOrPlaceholder(secret.type), { mono: true }),
        ui.makeCell(secret.collection, { mono: true }),
      );
      return row;
    }),
  );

  const filtered = query !== "" || c.collection.value !== "" || c.type.value !== "";
  c.wrapper.hidden = visible.length === 0;
  c.empty.hidden = visible.length !== 0;
  c.empty.textContent =
    secrets.length === 0
      ? "IRIS reports no secrets in any readable collection."
      : "No secrets match the current filters.";
  c.clear.disabled = !filtered;
  c.count.textContent = filtered ? `Showing ${visible.length} of ${secrets.length}` : `Showing all ${secrets.length}`;
}

// --- drawer renderers (shown in security-access.js's shared drawer) ---

function resourceRow(label, field, value, defaultPermission) {
  const parsed = parseResource(value, defaultPermission);
  const content = parsed ? ui.makeLinkChips("resource", [parsed.resource]) : "Not reported";
  const rows = [ui.makeInfoRow(label, field, content)];
  rows.push(ui.makeInfoRow(`${label} Permission`, null, describePermission(parsed), { mono: Boolean(parsed && parsed.permission) }));
  return rows;
}

async function renderCollectionDrawer(name, isCurrent) {
  ui.setDrawerHeader("Wallet Collection", name, null);
  ui.drawerHint.textContent = "Read-only. Secret names and types only — values are never requested.";

  const [detailResult, secretsResult] = await Promise.allSettled([
    IrisApi.getSecurityWalletCollectionDetail(name, selectedInstanceId()),
    IrisApi.getSecurityWalletSecrets(name, selectedInstanceId()),
  ]);
  if (!isCurrent()) return;
  if (detailResult.status === "rejected") throw detailResult.reason;
  const detail = detailResult.value && detailResult.value.result;
  if (!detail || typeof detail !== "object") throw new Error("unexpected shape");

  let secretsSection;
  const secrets = secretsResult.status === "fulfilled" ? secretsResult.value && secretsResult.value.result : null;
  if (!Array.isArray(secrets)) {
    secretsSection = ui.makeNote("Could not load this collection's secret list from IRIS.");
  } else if (secrets.length === 0) {
    secretsSection = ui.makeNote("IRIS reports no secrets in this collection.");
  } else {
    secretsSection = ui.makeLinkTable(
      ["Secret Name", "Type"],
      secrets.map((secret) => ({
        kind: "wallet-secret",
        name: secretKey(name, secret.Name),
        label: secret.Name,
        cells: [ui.textOrPlaceholder(secret.Type)],
      })),
    );
  }

  ui.drawerBody.replaceChildren(
    ui.makeSection(
      "Access",
      ui.makeInfoList([
        ...resourceRow("Edit Resource", "EditResource", detail.EditResource, "WRITE"),
        ...resourceRow("Use Resource", "UseResource", detail.UseResource, "READ"),
      ]),
      ui.makeNote("Edit: needed to add, remove or edit secrets. Use: needed to use secrets in this collection (IRIS's own definitions)."),
    ),
    ui.makeSection(`Secrets${Array.isArray(secrets) ? ` (${secrets.length})` : ""}`, secretsSection),
  );
}

async function renderSecretDrawer(key, isCurrent) {
  const split = key.indexOf("\n");
  const collection = split >= 0 ? key.slice(0, split) : "";
  const name = split >= 0 ? key.slice(split + 1) : key;
  if (!isCurrent()) return;
  // Uses the loaded list; IRIS has nothing more than name and type anyway.
  const secret = allSecrets().find((s) => s.collection === collection && s.name === name);
  if (!secret) throw new ApiError("Secret not found in the last loaded list", { status: 404 });
  ui.setDrawerHeader("Wallet Secret", name, null);
  ui.drawerHint.textContent = "Metadata only. The secret's value is never requested, displayed or stored by the Command Center.";
  ui.drawerBody.replaceChildren(
    ui.makeSection(
      "Secret Metadata",
      ui.makeInfoList([
        ui.makeInfoRow("Name", "Name", secret.name, { mono: true }),
        ui.makeInfoRow("Type", "Type", ui.textOrPlaceholder(secret.type), { mono: true }),
        ui.makeInfoRow("Collection", null, ui.makeLinkChips("wallet-collection", [secret.collection])),
      ]),
    ),
  );
}

// --- load ---

async function loadSecurityWallet() {
  const seq = ++loadSeq;
  dom.loading.hidden = false;
  dom.errorBanner.hidden = true;

  let response = null;
  let failed = false;
  try {
    response = await IrisApi.getSecurityWalletOverview(selectedInstanceId());
  } catch {
    failed = true;
  }
  if (seq !== loadSeq) return;
  loaded = true;
  dom.loading.hidden = true;

  const result = response && Array.isArray(response.result) ? response.result : null;
  if (failed || !result) {
    collections = null;
    dom.content.hidden = true;
    dom.errorBanner.hidden = false;
    dom.errorBannerText.textContent = failed
      ? "Could not load wallet collections. The Command Center backend may be unreachable."
      : "IRIS did not return the expected wallet information.";
    return;
  }

  collections = result;
  const messages = [];
  const warnings = response.status && Array.isArray(response.status.errors) ? response.status.errors.length : 0;
  if (warnings > 0) messages.push(`IRIS did not return the secret list for ${warnings} collection${warnings === 1 ? "" : "s"}.`);
  if (collections.length >= IRIS_DEFAULT_MAX_ROWS || collections.some((c) => Array.isArray(c.Secrets) && c.Secrets.length >= IRIS_DEFAULT_MAX_ROWS)) {
    messages.push(`A list reached IRIS's default ${IRIS_DEFAULT_MAX_ROWS}-row limit and may be incomplete.`);
  }
  dom.errorBanner.hidden = messages.length === 0;
  dom.errorBannerText.textContent = messages.join(" ");

  dom.content.hidden = false;
  renderSummary();
  const empty = collections.length === 0;
  dom.none.hidden = !empty;
  dom.sections.hidden = empty;
  if (empty) return;

  ui.populateSelect(dom.secrets.collection, "All collections", ui.uniqueSorted(collections.map((c) => c.Name)));
  ui.populateSelect(dom.secrets.type, "All types", ui.uniqueSorted(allSecrets().map((s) => s.type)));
  renderCollectionsTable();
  renderSecretsTable();
}

/**
 * Called when the Security page is reopened. Only refreshes if this tab
 * was already loaded; otherwise it loads when first shown.
 */
export function refreshSecurityWalletIfLoaded() {
  if (loaded) loadSecurityWallet();
}

function onActivate(event) {
  if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
  const target = event.target.closest("[data-open-kind]");
  if (!target) return;
  if (event.type === "keydown") event.preventDefault();
  openSecurityDrawer(target.dataset.openKind, target.dataset.openName);
}

export function initSecurityWalletControls() {
  registerSecurityDrawerRenderer("wallet-collection", renderCollectionDrawer);
  registerSecurityDrawerRenderer("wallet-secret", renderSecretDrawer);

  dom.tabs.addEventListener("security-tab-shown", (event) => {
    if (event.detail.tab === "wallet" && !loaded) loadSecurityWallet();
  });
  dom.refreshButton.addEventListener("click", () => {
    if (loaded) loadSecurityWallet();
  });

  // Filters the last loaded data locally, no request.
  dom.collections.form.addEventListener("submit", (event) => event.preventDefault());
  dom.collections.search.addEventListener("input", renderCollectionsTable);
  const s = dom.secrets;
  s.form.addEventListener("submit", (event) => event.preventDefault());
  s.search.addEventListener("input", renderSecretsTable);
  s.collection.addEventListener("change", renderSecretsTable);
  s.type.addEventListener("change", renderSecretsTable);
  s.clear.addEventListener("click", () => {
    s.search.value = "";
    s.collection.value = "";
    s.type.value = "";
    renderSecretsTable();
  });

  for (const type of ["click", "keydown"]) {
    dom.collections.body.addEventListener(type, onActivate);
    s.body.addEventListener(type, onActivate);
  }
}
