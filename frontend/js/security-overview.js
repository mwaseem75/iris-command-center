// Security page, Security Overview: inventory cards and findings across the
// tabs, so they show without opening each tab. Read-only.
//
// Reads the selected instance through existing routes: services
// (GET /api/iris/security/services), X.509 credentials with their
// certificate dates (…/x509/overview), Wallet collections (…/wallet/overview,
// names and secret metadata only) and the audit status
// (…/security/audit/enabled). The OAuth 2.0 overview is the one security.js
// already reads for the page (setOAuthOverview); it isn't requested twice.
//
// Findings are only what that data states: certificates past or near
// ValidityNotAfter (validityOf, the Certificates tab's own rule), enabled
// services that accept Unauthenticated, and auditing turned off. Each one
// opens the tab or page where it's shown in full.

import { IrisApi } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";
import { navigateTo } from "./nav.js";
import { validityOf } from "./security-x509.js";

const $ = (id) => document.getElementById(id);

const dom = {
  cards: $("security-overview-cards"),
  list: $("security-overview-findings"),
  count: $("security-overview-count"),
};

let loadSeq = 0;
let latest = { services: undefined, certificates: undefined, wallet: undefined, auditEnabled: undefined, oauth: undefined };

function openTab(tab) {
  $(`security-tab-${tab}`)?.click();
  $("security-access-tabs")?.scrollIntoView({ behavior: "smooth", block: "start" });
}

const TABS = {
  x509: () => openTab("x509"),
  authentication: () => openTab("authentication"),
  wallet: () => openTab("wallet"),
  oauth: () => openTab("oauth"),
  investigation: () => navigateTo("investigation"),
};

function plural(count, one, many) {
  return `${count} ${count === 1 ? one : many}`;
}

function names(list) {
  const shown = list.slice(0, 3).join(", ");
  return list.length > 3 ? `${shown} and ${list.length - 3} more` : shown;
}

/**
 * Findings from what IRIS reports (each input null if it couldn't be read):
 * { items: [{ badge, badgeClass, title, text, action: [label, target] }], unavailable: [...] }.
 */
export function securityFindings({ services, certificates, auditEnabled }, now = new Date()) {
  const items = [];
  const unavailable = [];

  if (!Array.isArray(certificates)) {
    unavailable.push("the X.509 credentials");
  } else {
    const byValidity = (status) => certificates.filter((c) => validityOf(c.Certificate || null, now) === status).map((c) => c.Alias);
    const expired = byValidity("Expired");
    const expiring = byValidity("Expiring");
    const notYet = byValidity("Not yet valid");
    if (expired.length) {
      items.push({ badge: "Expired", badgeClass: "status-badge--error",
        title: `${plural(expired.length, "certificate has", "certificates have")} expired`,
        text: `${names(expired)}. Past ValidityNotAfter.`, action: ["View Certificates →", "x509"] });
    }
    if (expiring.length) {
      items.push({ badge: "Expiring", badgeClass: "status-badge--warning",
        title: `${plural(expiring.length, "certificate expires", "certificates expire")} within 30 days`,
        text: names(expiring), action: ["View Certificates →", "x509"] });
    }
    if (notYet.length) {
      items.push({ badge: "Not yet valid", badgeClass: "status-badge--warning",
        title: `${plural(notYet.length, "certificate is", "certificates are")} not yet valid`,
        text: `${names(notYet)}. Before ValidityNotBefore.`, action: ["View Certificates →", "x509"] });
    }
  }

  if (!Array.isArray(services)) {
    unavailable.push("the services");
  } else {
    const open = services.filter((s) => s.Enabled === true && Array.isArray(s.AuthenticationMethods)
      && s.AuthenticationMethods.includes("Unauthenticated")).map((s) => s.Name);
    if (open.length) {
      items.push({ badge: "Unauthenticated", badgeClass: "status-badge--warning",
        title: `${plural(open.length, "enabled service accepts", "enabled services accept")} unauthenticated access`,
        text: `${names(open)}. "Unauthenticated" is one of its allowed authentication methods.`,
        action: ["View Authentication →", "authentication"] });
    }
  }

  if (auditEnabled === false) {
    items.push({ badge: "Disabled", badgeClass: "status-badge--error", title: "Security auditing is disabled",
      text: "IRIS reports auditing as off, so audit events aren't recorded.", action: ["View Investigation →", "investigation"] });
  } else if (auditEnabled !== true) {
    unavailable.push("the audit status");
  }
  return { items, unavailable };
}

function statusItem(badge, badgeClass, text, level) {
  const item = document.createElement("li");
  item.className = "dash-alert-list__item";
  item.dataset.level = level;
  const badgeEl = document.createElement("span");
  badgeEl.className = `status-badge ${badgeClass}`;
  badgeEl.textContent = badge;
  const textEl = document.createElement("span");
  textEl.className = "dash-alert-list__text";
  textEl.textContent = text;
  item.append(badgeEl, textEl);
  return item;
}

function findingItem({ badge, badgeClass, title, text, action: [label, target] }) {
  const item = document.createElement("li");
  item.className = "dash-issue dash-attention__item";
  const badgeEl = document.createElement("span");
  badgeEl.className = `status-badge ${badgeClass}`;
  badgeEl.textContent = badge;
  const body = document.createElement("div");
  body.className = "dash-issue__body";
  const heading = document.createElement("p");
  heading.className = "dash-issue__title";
  heading.textContent = title;
  const detail = document.createElement("p");
  detail.className = "dash-issue__text";
  detail.textContent = text;
  body.append(heading, detail);
  const open = document.createElement("button");
  open.className = "dash-panel__link dash-issue__action";
  open.type = "button";
  open.textContent = label;
  open.addEventListener("click", () => TABS[target]());
  item.append(badgeEl, body, open);
  return item;
}

// Inventory: what each area holds, as IRIS reports it (no secret values).
function inventoryCards({ services, certificates, wallet, oauth }) {
  const unavailable = "Unavailable";
  const enabled = Array.isArray(services) ? services.filter((s) => s.Enabled === true).length : null;
  const secrets = Array.isArray(wallet)
    ? wallet.reduce((sum, collection) => sum + (Array.isArray(collection.Secrets) ? collection.Secrets.length : 0), 0) : null;
  const oauthKnown = oauth && typeof oauth === "object";
  return [
    { label: "Services", value: enabled ?? unavailable, accent: "var(--color-accent)",
      meta: Array.isArray(services) ? `enabled of ${services.length}` : null, open: "authentication" },
    { label: "Certificates", value: Array.isArray(certificates) ? certificates.length : unavailable, accent: "var(--color-chart-6)",
      meta: Array.isArray(certificates) ? "X.509 credentials" : null, open: "x509" },
    { label: "Wallet", value: Array.isArray(wallet) ? wallet.length : unavailable, accent: "var(--color-chart-2)",
      meta: secrets !== null ? `${wallet.length === 1 ? "collection" : "collections"} · ${plural(secrets, "secret", "secrets")} (names only)` : null,
      open: "wallet" },
    { label: "OAuth 2.0 Server",
      value: oauth === undefined ? "…" : oauthKnown ? (oauth.ServerConfigured === true ? "Yes" : "No") : unavailable,
      accent: "var(--color-chart-4)",
      meta: oauthKnown ? `${plural(Array.isArray(oauth.ServerClients) ? oauth.ServerClients.length : 0, "client", "clients")} · `
        + `${plural(Array.isArray(oauth.ServerDefinitions) ? oauth.ServerDefinitions.length : 0, "server definition", "server definitions")}` : null,
      open: "oauth" },
  ].map((card) => {
    const el = document.createElement("article");
    el.className = "stat-card stat-card--interactive";
    el.style.setProperty("--stat-card-accent", card.accent);
    el.setAttribute("role", "button");
    el.setAttribute("tabindex", "0");
    el.dataset.open = card.open;
    const label = document.createElement("h3");
    label.className = "stat-card__label";
    label.textContent = card.label;
    const value = document.createElement("p");
    value.className = card.value === unavailable ? "stat-card__value stat-card__value--unavailable" : "stat-card__value";
    value.textContent = String(card.value);
    el.append(label, value);
    if (card.meta) {
      const meta = document.createElement("p");
      meta.className = "stat-card__meta";
      meta.textContent = card.meta;
      el.append(meta);
    }
    el.addEventListener("click", () => TABS[card.open]());
    el.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        TABS[card.open]();
      }
    });
    return el;
  });
}

function render() {
  const { services, certificates, wallet, auditEnabled } = latest;
  if ([services, certificates, wallet, auditEnabled].includes(undefined)) return;  // still loading
  dom.cards.replaceChildren(...inventoryCards(latest));
  const { items, unavailable } = securityFindings({ services, certificates, auditEnabled });
  dom.list.replaceChildren(...items.map(findingItem));
  dom.count.textContent = items.length ? plural(items.length, "finding", "findings") : "";
  if (unavailable.length) {
    dom.list.append(statusItem("Unavailable", "status-badge--warning",
      `Couldn't read ${unavailable.join(", ")} right now. Try Refresh.`, "info"));
  } else if (items.length === 0) {
    dom.list.append(statusItem("OK", "status-badge--ok",
      "No findings: no expired or expiring certificates, no enabled service accepts unauthenticated access, "
        + "and auditing is on.", "ok"));
  }
}

async function result(call) {
  try {
    const response = await call();
    return response && response.result !== undefined ? response.result : null;
  } catch {
    return null;
  }
}

/** The OAuth 2.0 overview security.js loaded for the page (null if it failed). */
export function setOAuthOverview(overview) {
  latest.oauth = overview && typeof overview === "object" ? overview : null;
  if (dom.cards.children.length) dom.cards.replaceChildren(...inventoryCards(latest));
}

export async function loadSecurityOverview() {
  const seq = ++loadSeq;
  const id = selectedInstanceId();
  latest = { ...latest, services: undefined, certificates: undefined, wallet: undefined, auditEnabled: undefined };
  dom.cards.replaceChildren();
  dom.count.textContent = "";
  dom.list.replaceChildren(statusItem("…", "status-badge--neutral", "Checking…", "info"));
  const [services, certificates, wallet, audit] = await Promise.all([
    result(() => IrisApi.getSecurityServices(id)),
    result(() => IrisApi.getSecurityX509Overview(id)),
    result(() => IrisApi.getSecurityWalletOverview(id)),
    result(() => IrisApi.getAuditEnabled(id)),
  ]);
  if (seq !== loadSeq) return;
  latest = {
    ...latest,
    services: Array.isArray(services) ? services : null,
    certificates: Array.isArray(certificates) ? certificates : null,
    wallet: Array.isArray(wallet) ? wallet : null,
    auditEnabled: typeof audit?.Enabled === "boolean" ? audit.Enabled : null,
  };
  render();
}
