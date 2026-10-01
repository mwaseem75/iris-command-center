// Security page, Certificates tab: X.509 credentials and their certificate
// details, with more in the shared drawer.
//
// Uses getSecurityX509Overview, getSecurityX509CredentialDetail(alias) and
// getSecurityX509Certificate(alias). No key material is requested; only the
// HasPrivateKey flag.
//
// Validity comes from ValidityNotBefore/ValidityNotAfter ("YYYY-MM-DD
// HH:MM:SS", no timezone, so read as local time). Missing or unparseable
// dates show "Unknown".
//
// Loads the first time the tab is shown, then on Refresh or when the page
// is reopened.

import { IrisApi } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";
import { openSecurityDrawer, registerSecurityDrawerRenderer, securityUi as ui } from "./security-access.js";

const PLACEHOLDER = "—";
const EXPIRING_WITHIN_DAYS = 30;
const DAY_MS = 24 * 60 * 60 * 1000;
const IRIS_DATETIME = /^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2})(?::(\d{2}))?$/;
const $ = (id) => document.getElementById(id);

const dom = {
  refreshButton: $("security-refresh-button"),
  tabs: $("security-access-tabs"),
  errorBanner: $("security-x509-error-banner"),
  errorBannerText: $("security-x509-error-banner-text"),
  loading: $("security-x509-loading"),
  content: $("security-x509-content"),
  summaryGrid: $("security-x509-summary-grid"),
  none: $("security-x509-none"),
  sections: $("security-x509-sections"),
  form: $("security-x509-filter-form"),
  search: $("security-x509-search"),
  status: $("security-x509-status"),
  key: $("security-x509-key"),
  clear: $("security-x509-clear"),
  count: $("security-x509-count"),
  empty: $("security-x509-empty"),
  wrapper: $("security-x509-table-wrapper"),
  body: $("security-x509-table-body"),
};

const VALIDITY_BADGES = {
  Valid: "status-badge--ok",
  Expiring: "status-badge--warning",
  Expired: "status-badge--error",
  "Not yet valid": "status-badge--warning",
  Unknown: "status-badge--neutral",
};

let credentials = null; // overview entries, or null if the load failed
let loaded = false;
let loadSeq = 0;
let summaryActions = [];

// --- helpers ---

function parseIrisDate(value) {
  const match = typeof value === "string" ? IRIS_DATETIME.exec(value) : null;
  if (!match) return null;
  const [, y, mo, d, h, mi, s] = match;
  const date = new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi), Number(s || 0));
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Validity status from the certificate's dates. */
function validityOf(certificate, now = new Date()) {
  if (!certificate) return "Unknown";
  const notAfter = parseIrisDate(certificate.ValidityNotAfter);
  if (!notAfter) return "Unknown";
  const notBefore = parseIrisDate(certificate.ValidityNotBefore);
  if (notBefore && now < notBefore) return "Not yet valid";
  if (now > notAfter) return "Expired";
  if (notAfter - now <= EXPIRING_WITHIN_DAYS * DAY_MS) return "Expiring";
  return "Valid";
}

function daysUntil(value) {
  const date = parseIrisDate(value);
  return date ? Math.floor((date - new Date()) / DAY_MS) : null;
}

function formatPrivateKey(value) {
  if (value === true) return "Present";
  if (value === false) return "Not present";
  return PLACEHOLDER;
}

function formatOwners(owners) {
  // An empty OwnerList means any user can use the credentials.
  if (!Array.isArray(owners)) return "Not reported";
  return owners.length === 0 ? "Any user" : owners.join(", ");
}

function certificateOf(credential) {
  return credential.Certificate || null;
}

// --- summary cards ---

function renderSummary() {
  const statusCount = (status) => credentials.filter((c) => validityOf(certificateOf(c)) === status).length;
  const cards = [
    { label: "Credentials", value: credentials.length, accent: "var(--color-accent)", action: () => applyFilter({}) },
    {
      label: "With Private Key",
      value: credentials.filter((c) => c.HasPrivateKey === true).length,
      meta: "HasPrivateKey",
      accent: "var(--color-chart-2)",
      action: () => applyFilter({ key: "yes" }),
    },
    {
      label: "Expired",
      value: statusCount("Expired"),
      accent: statusCount("Expired") ? "var(--color-error)" : "var(--color-chart-neutral)",
      action: () => applyFilter({ status: "Expired" }),
    },
    {
      label: "Expiring",
      value: statusCount("Expiring"),
      meta: `within ${EXPIRING_WITHIN_DAYS} days`,
      accent: statusCount("Expiring") ? "var(--color-warning)" : "var(--color-chart-neutral)",
      action: () => applyFilter({ status: "Expiring" }),
    },
    {
      label: "Available To Any User",
      value: credentials.filter((c) => Array.isArray(c.OwnerList) && c.OwnerList.length === 0).length,
      meta: "empty OwnerList",
      accent: "var(--color-chart-6)",
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
        el.title = `Filter: ${card.label}`;
      }
      const label = document.createElement("h3");
      label.className = "stat-card__label";
      label.textContent = card.label;
      const value = document.createElement("p");
      value.className = "stat-card__value";
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
}

function applyFilter({ status = "", key = "" }) {
  dom.search.value = "";
  dom.status.value = status;
  dom.key.value = key;
  renderTable();
  dom.form.scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- table ---

function renderTable() {
  const query = dom.search.value.trim().toLowerCase();
  const visible = credentials.filter((credential) => {
    const certificate = certificateOf(credential);
    if (dom.status.value && validityOf(certificate) !== dom.status.value) return false;
    if (dom.key.value === "yes" && credential.HasPrivateKey !== true) return false;
    if (dom.key.value === "no" && credential.HasPrivateKey !== false) return false;
    if (!query) return true;
    return (
      ui.includesText(credential.Alias, query) ||
      (certificate &&
        (ui.includesText(certificate.SubjectDN, query) ||
          ui.includesText(certificate.IssuerDN, query) ||
          ui.includesText(certificate.SerialNumber, query))) ||
      (Array.isArray(credential.PeerNames) && credential.PeerNames.some((peer) => ui.includesText(peer, query)))
    );
  });

  dom.body.replaceChildren(
    ...visible.map((credential) => {
      const certificate = certificateOf(credential);
      const validity = validityOf(certificate);
      const row = document.createElement("tr");
      row.className = "data-table__row--clickable";
      row.tabIndex = 0;
      row.dataset.openKind = "x509";
      row.dataset.openName = credential.Alias;
      row.setAttribute("aria-label", `View X.509 credential ${credential.Alias}`);
      row.append(
        ui.makeCell(credential.Alias, { mono: true }),
        ui.makeCell(certificate ? ui.textOrPlaceholder(certificate.SubjectDN) : "Unavailable", { mono: Boolean(certificate) }),
        ui.makeCell(certificate ? ui.textOrPlaceholder(certificate.IssuerDN) : "Unavailable", { mono: Boolean(certificate) }),
        ui.makeCell(certificate ? ui.textOrPlaceholder(certificate.ValidityNotAfter) : PLACEHOLDER, { mono: true }),
        ui.makeBadgeCell(ui.makeBadge(validity, VALIDITY_BADGES[validity])),
        ui.makeCell(formatPrivateKey(credential.HasPrivateKey)),
        ui.makeCell(formatOwners(credential.OwnerList)),
      );
      return row;
    }),
  );

  const filtered = query !== "" || dom.status.value !== "" || dom.key.value !== "";
  dom.wrapper.hidden = visible.length === 0;
  dom.empty.hidden = visible.length !== 0;
  dom.clear.disabled = !filtered;
  dom.count.textContent = filtered ? `Showing ${visible.length} of ${credentials.length}` : `Showing all ${credentials.length}`;
}

// --- drawer renderer (shown in security-access.js's shared drawer) ---

async function renderCredentialDrawer(alias, isCurrent) {
  const listed = credentials && credentials.find((c) => c.Alias === alias);
  ui.setDrawerHeader("X.509 Credential", alias, null);
  ui.drawerHint.textContent = "Read-only. Certificate metadata only — key material and key passwords are never requested.";

  const [detailResult, certificateResult] = await Promise.allSettled([
    IrisApi.getSecurityX509CredentialDetail(alias, selectedInstanceId()),
    IrisApi.getSecurityX509Certificate(alias, selectedInstanceId()),
  ]);
  if (!isCurrent()) return;
  if (detailResult.status === "rejected") throw detailResult.reason;
  const detail = detailResult.value && detailResult.value.result;
  if (!detail || typeof detail !== "object") throw new Error("unexpected shape");
  const certificate =
    certificateResult.status === "fulfilled" && certificateResult.value && typeof certificateResult.value.result === "object"
      ? certificateResult.value.result
      : null;

  const validity = validityOf(certificate);
  ui.setDrawerHeader("X.509 Credential", alias, [validity, VALIDITY_BADGES[validity]]);

  let certificateSection;
  if (!certificate) {
    certificateSection = ui.makeSection("Certificate", ui.makeNote("Could not load this credential's certificate metadata from IRIS."));
  } else {
    const days = daysUntil(certificate.ValidityNotAfter);
    const remaining =
      days === null ? PLACEHOLDER : days >= 0 ? `${days} day${days === 1 ? "" : "s"} remaining` : `expired ${-days} day${days === -1 ? "" : "s"} ago`;
    certificateSection = ui.makeSection(
      "Certificate",
      ui.makeInfoList([
        ui.makeInfoRow("Subject", "SubjectDN", ui.textOrPlaceholder(certificate.SubjectDN), { mono: true }),
        ui.makeInfoRow("Issuer", "IssuerDN", ui.textOrPlaceholder(certificate.IssuerDN), { mono: true }),
        ui.makeInfoRow("Serial Number", "SerialNumber", ui.textOrPlaceholder(certificate.SerialNumber), { mono: true }),
        ui.makeInfoRow("Valid From", "ValidityNotBefore", ui.textOrPlaceholder(certificate.ValidityNotBefore), { mono: true }),
        ui.makeInfoRow("Valid Until", "ValidityNotAfter", ui.textOrPlaceholder(certificate.ValidityNotAfter), { mono: true }),
        ui.makeInfoRow("Validity", null, `${validity}${days === null ? "" : ` (${remaining})`}`),
      ]),
    );
  }

  const hasPrivateKey = certificate && typeof certificate.HasPrivateKey === "boolean" ? certificate.HasPrivateKey : listed && listed.HasPrivateKey;
  const owners = detail.OwnerList;
  const peers = detail.PeerNames;
  ui.drawerBody.replaceChildren(
    certificateSection,
    ui.makeSection(
      "Private Key",
      ui.makeInfoList([ui.makeInfoRow("Private Key", "HasPrivateKey", formatPrivateKey(hasPrivateKey))]),
      ui.makeNote("Only whether a private key is present is shown. The key itself and its password are never requested."),
    ),
    ui.makeSection(
      "Access",
      ui.makeInfoList([
        ui.makeInfoRow(
          "Owners",
          "OwnerList",
          !Array.isArray(owners)
            ? "Not reported"
            : owners.length === 0
              ? "Any user (OwnerList is empty)"
              : ui.makeLinkChips("user", owners),
        ),
        ui.makeInfoRow(
          "Peer Names",
          "PeerNames",
          !Array.isArray(peers) ? "Not reported" : peers.length === 0 ? "None" : peers.join(", "),
          { mono: Array.isArray(peers) && peers.length > 0 },
        ),
      ]),
    ),
    ui.makeSection(
      "Trust",
      ui.makeInfoList([
        ui.makeInfoRow(
          "CA File",
          "CAFile",
          typeof detail.CAFile !== "string"
            ? "Not reported"
            : detail.CAFile === ""
              ? "Not set (IRIS then uses iris.cer in the mgr directory)"
              : detail.CAFile,
          { mono: typeof detail.CAFile === "string" && detail.CAFile !== "" },
        ),
      ]),
    ),
  );
}

// --- load ---

async function loadSecurityX509() {
  const seq = ++loadSeq;
  dom.loading.hidden = false;
  dom.errorBanner.hidden = true;

  let response = null;
  let failed = false;
  try {
    response = await IrisApi.getSecurityX509Overview(selectedInstanceId());
  } catch {
    failed = true;
  }
  if (seq !== loadSeq) return;
  loaded = true;
  dom.loading.hidden = true;

  const result = response && Array.isArray(response.result) ? response.result : null;
  if (failed || !result) {
    credentials = null;
    dom.content.hidden = true;
    dom.errorBanner.hidden = false;
    dom.errorBannerText.textContent = failed
      ? "Could not load X.509 credentials. The Command Center backend may be unreachable."
      : "IRIS did not return the expected X.509 credential information.";
    return;
  }

  credentials = result;
  const warnings = response.status && Array.isArray(response.status.errors) ? response.status.errors.length : 0;
  dom.errorBanner.hidden = warnings === 0;
  dom.errorBannerText.textContent =
    warnings > 0 ? `IRIS did not return certificate metadata for ${warnings} credential${warnings === 1 ? "" : "s"}.` : "";

  dom.content.hidden = false;
  renderSummary();
  const empty = credentials.length === 0;
  dom.none.hidden = !empty;
  dom.sections.hidden = empty;
  if (!empty) renderTable();
}

/**
 * Called when the Security page is reopened. Only refreshes if this tab
 * was already loaded; otherwise it loads when first shown.
 */
export function refreshSecurityX509IfLoaded() {
  if (loaded) loadSecurityX509();
}

function onActivate(event) {
  if (event.type === "keydown" && event.key !== "Enter" && event.key !== " ") return;
  const target = event.target.closest("[data-open-kind]");
  if (!target) return;
  if (event.type === "keydown") event.preventDefault();
  openSecurityDrawer(target.dataset.openKind, target.dataset.openName);
}

export function initSecurityX509Controls() {
  registerSecurityDrawerRenderer("x509", renderCredentialDrawer);

  dom.tabs.addEventListener("security-tab-shown", (event) => {
    if (event.detail.tab === "x509" && !loaded) loadSecurityX509();
  });
  dom.refreshButton.addEventListener("click", () => {
    if (loaded) loadSecurityX509();
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
  dom.form.addEventListener("submit", (event) => event.preventDefault());
  dom.search.addEventListener("input", renderTable);
  dom.status.addEventListener("change", renderTable);
  dom.key.addEventListener("change", renderTable);
  dom.clear.addEventListener("click", () => {
    dom.search.value = "";
    dom.status.value = "";
    dom.key.value = "";
    renderTable();
  });

  for (const type of ["click", "keydown"]) dom.body.addEventListener(type, onActivate);
}
