// Screen Insights ("Explain This Screen" internally): a short operational
// briefing on the open page, with a snapshot of values that page already
// shows. It's built in the browser from the current view and makes no
// requests.
//
// One button, moved into the open page's header by app.js (next to the
// instance selector, like placeInstanceSelector does), opens one shared
// side panel (`.ns-drawer`, so detail-workspace.js gives it the modal
// behaviour). Only the pages in EXPLANATIONS have it.

import { getInstanceContext } from "./instance-context.js";
import { navigateTo } from "./nav.js";

const NOT_LOADED = "Not loaded yet. Use Refresh.";

// For each page:
// - overview, source: what it is and where its data comes from;
// - snapshot: facts as [label, element id | function, options]; `note` and
//   `updated` are element ids whose text is shown as is;
// - insights: what it tells you, where to look next, changes & safety;
// - terms: [term, definition]; related: other pages (view ids).
export const EXPLANATIONS = {
  dashboard: {
    title: "Dashboard",
    overview: "A live view of the selected instance: inventory counts, IRIS's own alert and license counters, " +
      "resource charts and recent activity.",
    source: "GET /api/iris/monitor/dashboard and the list routes",
    snapshot: {
      facts: [
        ["Namespaces", "stat-namespaces"],
        ["Databases", "stat-databases"],
        ["Processes", "stat-processes"],
        ["Web apps", "stat-web-apps"],
        ["Tasks", "stat-tasks"],
        ["License", "stat-license"],
        ["IRIS Alerts", "stat-alerts"],
      ],
      note: "dashboard-live-label",
    },
    insights: {
      tells: "Counts come from the list routes; alerts and license use from IRIS's own monitor. The charts are " +
        "sampled while this page is open; nothing historical is stored.",
      next: "If a number looks unexpected, check Health Center for the overall assessment or Issue Resolver for " +
        "detected problems. Recent operations open in Observability.",
      safety: "Read-only. On another instance, Issues & Recommendations, Recent Operations and Demo Activity are " +
        "hidden: they cover the Primary only.",
    },
    terms: [
      ["KPI cards", "Counts from the Namespaces, Databases, Processes, Web Apps and Tasks lists."],
      ["IRIS Alerts", "IRIS's serious-alert count, from its monitor."],
      ["License", "License use reported by IRIS's monitor."],
      ["Resource charts", "Sampled by this page while it's open; no history is stored."],
    ],
    related: ["health-center", "issue-resolver", "operations", "observability"],
  },
  "health-center": {
    title: "Health Center",
    overview: "An overall health status built from the Issue Resolver's checks, assessed per category: " +
      "Performance, Tasks, Databases, Security, Web Applications and System.",
    source: "GET /api/iris/health",
    snapshot: {
      facts: [
        ["Status", "health-center-status"],
        ["Coverage", "health-center-coverage"],
      ],
    },
    insights: {
      tells: "Each fully assessed category starts at 100 and loses points per finding; the overall score is the " +
        "mean of the scored categories. Findings reuse the Issue Resolver's checks.",
      next: "Open a finding for its evidence and recommendation, then resolve or investigate it on the page that " +
        "owns it (Issue Resolver for supported fixes).",
      safety: "Read-only. Fixes run through the Issue Resolver's flow, with authorization and your explicit confirmation.",
    },
    terms: [
      ["Partial", "Some checks couldn't run."],
      ["Not assessed", "No defensible basis for a score. Security shows the audit status for information only."],
      ["Score", "100 minus penalties per finding: critical 40, high 25, medium 10, low 5."],
      ["Performance Snapshot", "Separates current rates from cumulative counters since startup."],
    ],
    related: ["issue-resolver", "dashboard", "investigation"],
  },
  fleet: {
    title: "Fleet Overview",
    allInstances: true,
    overview: "Every active instance side by side, each read on its own. Nothing is added up across instances.",
    source: "Each instance's own read routes (?instance=<id>)",
    snapshot: {
      facts: [
        ["Active instances", "fleet-count"],
        ["Unavailable", () => {
          const cards = [...document.querySelectorAll("#fleet-instances article[data-instance-id]")];
          return cards.length ? String(cards.filter((card) => card.dataset.state === "unavailable").length) : null;
        }, { warnAbove: 0 }],
      ],
      updated: "fleet-updated",
    },
    insights: {
      tells: "One card per active instance: health, runtime and resource counts. Its charts are sampled while this " +
        "page is open (every 15 s, with a full read every 60 s).",
      next: "View Details, or a metric's link, selects that instance and opens the matching page.",
      safety: "Read-only (GET only). An unreachable instance never falls back to another instance; inactive " +
        "instances aren't shown.",
    },
    terms: [
      ["Unavailable", "The instance couldn't be read; its values show \"—\", never 0."],
      ["Issues", "The Issue Resolver's active issues for that instance."],
      ["Live charts", "Sampled only while this page is open; no history is stored."],
    ],
    related: ["instances", "dashboard", "health-center"],
  },
  "issue-resolver": {
    title: "Issue Resolver",
    overview: "Issues detected from live IRIS data, and how each one is resolved or investigated.",
    source: "GET /api/iris/issues",
    snapshot: {
      facts: [
        ["Active issues", "issue-resolver-kpi-active"],
        ["Resolvable", "issue-resolver-kpi-resolvable"],
        ["Detection-only", "issue-resolver-kpi-detection"],
        ["Highest severity", "issue-resolver-kpi-severity"],
      ],
      updated: "issue-resolver-updated",
    },
    insights: {
      tells: "Resolvable issues have a registered fix; detection-only issues point to a page to investigate. " +
        "Readiness says whether a resolution check can be run.",
      next: "Open an issue for its evidence and Fix Preview, then go to the page that resolves it. Custom Issue " +
        "Rules add your own detection-only checks.",
      safety: "Nothing changes IRIS from this page. A fix needs the required %Admin_* privilege and your explicit " +
        "confirmation, and is verified and traced. Fixes, rules and the demo run on the Primary only.",
    },
    terms: [
      ["Resolvable", "Has a registered operation: dismounted database, web app with a missing namespace, archived " +
        "journal files not purged."],
      ["Detection-only", "No operation; points to System, Tasks, Databases or Security."],
      ["Fix Preview", "Current → Proposed, operation, authorization requirement, confirmation and verification, " +
        "before anything runs."],
      ["Demo Activity", "Creates a real, reversible demo issue, only after confirmation."],
    ],
    related: ["operations", "health-center", "observability"],
  },
  operations: {
    title: "Operations",
    overview: "The Supported Actions catalog: the changes Command Center can make, with each one's risk and " +
      "required privilege from the operation registry.",
    source: "GET /api/iris/operations",
    snapshot: {
      facts: [
        ["Supported actions", "operations-count"],
      ],
    },
    insights: {
      tells: "Every change follows Review → Confirm & Execute → backend authorization → execution → verification. " +
        "The journal PurgeArchived change runs on this page; the others run on their own pages.",
      next: "Review an operation here, or open the page that runs it: Databases, Namespaces, Web Apps, Security " +
        "(login access) or Tasks (Run Now).",
      safety: "Only Confirm & Execute changes IRIS. The backend checks your privilege (%Admin_Journal or " +
        "%Admin_Manage for the journal setting) and verifies the result. Changes run on the Primary only.",
    },
    terms: [
      ["Risk", "From the operation registry: low, medium or high."],
      ["Required privilege", "Any one of the listed %Admin_* privileges, checked by the backend."],
      ["Verification", "The backend re-reads IRIS after the change."],
    ],
    related: ["issue-resolver", "observability", "journal"],
  },
  observability: {
    title: "Observability",
    overview: "The traces of the operations Command Center ran, including Copilot plans and executions and dry runs.",
    source: "GET /api/iris/observability/traces",
    snapshot: {
      facts: [
        ["Traces", "observability-stat-total"],
        ["Successful", "observability-stat-success"],
        ["Dry runs", "observability-stat-dryrun"],
        ["Other", "observability-stat-other"],
      ],
    },
    insights: {
      tells: "Each trace records the authorization, confirmation, execution and verification results, with each " +
        "step's status and duration.",
      next: "Filter or search (in the browser), open a trace's waterfall, or investigate IRIS audit records around its time.",
      safety: "Read-only. Traces never contain credentials. On another instance it shows that instance's traces.",
    },
    terms: [
      ["Trace", "One operation attempt, from authorization to verification."],
      ["Span", "One step of a trace, with status ok, error or skipped."],
      ["Dry run", "Checked, not executed."],
    ],
    related: ["investigation", "operations", "issue-resolver"],
  },
  security: {
    title: "Security",
    overview: "The instance's security configuration: users, roles, resources, authentication, Wallet, " +
      "certificates and OAuth 2.0.",
    source: "The /api/iris/security routes",
    snapshot: {
      facts: [
        ["Users", "security-users-count"],
        ["Roles", "security-roles-count"],
        ["Resources", "security-resources-count"],
      ],
    },
    insights: {
      tells: "Roles grant privileges on resources. Only safe fields are returned: no passwords, secrets or tokens. " +
        "Wallet and Certificates show metadata only.",
      next: "Browse the tabs and open details in the drawer. Investigation shows the audit trail for the same instance.",
      safety: "The only change here is a user's Login Access: checked first (a dry run), then run after your " +
        "confirmation if you hold %Admin_Secure, and verified. Primary only.",
    },
    terms: [
      ["Role", "A set of privileges on resources, granted to users."],
      ["Resource", "What a privilege applies to, such as a database or an %Admin_* resource."],
      ["Login Access", "Whether the user can log in (user.set_enabled)."],
    ],
    related: ["investigation", "capabilities"],
  },
  capabilities: {
    title: "API Capability Explorer",
    overview: "Command Center's registry of the IRIS API endpoints it uses, with method, required privilege and " +
      "verification status.",
    source: "GET /api/iris/capabilities",
    snapshot: {
      facts: [
        ["Capabilities", "capabilities-count"],
      ],
      note: "capabilities-instance-summary",
    },
    insights: {
      tells: "Verified means checked against IRIS 2026.2. For the selected instance, its last compatibility check " +
        "marks each endpoint Answered, Missing or Not checked.",
      next: "Search and filter the list, or open Instances to run a compatibility check again.",
      safety: "Read-only. Nothing is inferred beyond the last compatibility check.",
    },
    terms: [
      ["Answered", "The endpoint responded in the last check."],
      ["Missing", "The endpoint didn't respond in the last check."],
      ["Not checked", "The last check doesn't cover this endpoint."],
    ],
    related: ["instances", "observability"],
  },
  investigation: {
    title: "Investigation",
    overview: "IRIS's own security audit records for the selected instance.",
    source: "GET /api/iris/security/audit/enabled and /api/iris/security/audit/records",
    snapshot: {
      facts: [
        ["Events", "investigation-kpi-events"],
        ["Users", "investigation-kpi-users"],
        ["Related traces", "investigation-kpi-related"],
        ["Records", "investigation-count"],
      ],
      note: "investigation-audit-enabled",
    },
    insights: {
      tells: "Audit records and Command Center traces share no id, so they're linked by time: traces within ±30 s of an event.",
      next: "Filter by time and event, open an event's details, or jump to traces near its time in Observability.",
      safety: "Read-only. The Message Log tab is the Primary's messages.log, read through its own connection.",
    },
    terms: [
      ["Event", "One IRIS audit record."],
      ["Related traces", "Command Center traces that started within ±30 s of an event."],
      ["Message Log", "IRIS's messages.log on the Primary."],
    ],
    related: ["observability", "security"],
  },
};

const INSIGHTS = [
  ["tells", "What it tells you", "◉"],
  ["next", "Where to look next", "⌕"],
  ["safety", "Changes & safety", "⚠"],
];

const $ = (id) => document.getElementById(id);

const dom = {
  button: $("explain-screen-button"),
  backdrop: $("explain-screen-backdrop"),
  drawer: $("explain-screen-drawer"),
  close: $("explain-screen-close"),
  title: $("explain-screen-title"),
  context: $("explain-screen-context"),
  body: $("explain-screen-body"),
};

let currentView = () => null;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// What the page shows for this fact now, or null if it hasn't loaded
// (empty, still the "—" placeholder, or hidden).
function factValue(source) {
  if (typeof source === "function") return source();
  const node = $(source);
  if (!node || node.hidden) return null;
  const text = node.textContent.replace(/\s+/g, " ").trim();
  return text && text !== "—" ? text : null;
}

function overviewCard(explanation) {
  const card = el("section", "explain-card explain-overview");
  const icon = el("span", "explain-overview__icon", "ⓘ");
  icon.setAttribute("aria-hidden", "true");
  const text = el("div");
  text.append(el("h4", "explain-card__title", "Overview"), el("p", "explain-card__text", explanation.overview),
    el("p", "explain-overview__source", `Source: ${explanation.source}`));
  card.append(icon, text);
  return card;
}

function snapshotCard(explanation) {
  const { facts, note, updated } = explanation.snapshot;
  const card = el("section", "explain-card explain-snapshot");
  const head = el("div", "explain-snapshot__head");
  const who = el("div");
  who.append(el("h4", "explain-card__title", explanation.allInstances ? "All active instances" : "Current snapshot"));
  if (!explanation.allInstances) {
    const instance = getInstanceContext().instance;
    const name = instance ? instance.name : "Primary";
    who.append(el("p", "explain-snapshot__instance",
      instance && instance.connection ? `${name} · ${instance.connection}` : name));
  }
  head.append(who);
  const updatedText = updated ? factValue(updated) : null;
  if (updatedText) head.append(el("p", "explain-snapshot__updated", `Updated ${updatedText}`));
  card.append(head);

  const tiles = el("div", "explain-tiles");
  let missing = false;
  for (const [label, source, { warnAbove } = {}] of facts) {
    const value = factValue(source);
    const tile = el("div", "explain-tile");
    if (value === null) {
      missing = true;
      tile.dataset.state = "missing";
    } else if (warnAbove !== undefined && Number(value) > warnAbove) {
      tile.dataset.tone = "warning";
    }
    // The Dashboard's KPI cards carry an icon; the tile reuses it.
    const pageIcon = typeof source === "string" ? $(source)?.closest(".stat-card")?.querySelector(".dash-kpi__icon") : null;
    if (pageIcon) tile.append(pageIcon.cloneNode(true));
    tile.append(el("span", "explain-tile__value", value ?? "—"), el("span", "explain-tile__label", label));
    tiles.append(tile);
  }
  card.append(tiles);
  const noteText = note ? factValue(note) : null;
  if (noteText) card.append(el("p", "explain-snapshot__note", noteText));
  if (missing) card.append(el("p", "explain-snapshot__missing", NOT_LOADED));
  return card;
}

function insightsSection(explanation) {
  const wrap = el("section", "explain-section");
  const grid = el("div", "explain-insights");
  for (const [key, title, glyph] of INSIGHTS) {
    const card = el("div", "explain-insight");
    card.dataset.kind = key;
    const head = el("p", "explain-insight__title");
    const icon = el("span", "explain-insight__icon", glyph);
    icon.setAttribute("aria-hidden", "true");
    head.append(icon, document.createTextNode(title));
    card.append(head, el("p", "explain-insight__text", explanation.insights[key]));
    grid.append(card);
  }
  wrap.append(el("h4", "explain-section__title", "What matters here"), grid);
  return wrap;
}

function termsCard(explanation) {
  const card = el("section", "explain-card");
  const list = el("dl", "explain-terms");
  for (const [term, definition] of explanation.terms) list.append(el("dt", null, term), el("dd", null, definition));
  card.append(el("h4", "explain-card__title", "Key terms"), list);
  return card;
}

// Chips that open other pages, labelled and iconed like their nav items.
function relatedCard(explanation) {
  const card = el("section", "explain-card");
  const chips = el("div", "explain-related");
  for (const view of explanation.related) {
    const navItem = document.querySelector(`.nav-item[data-view="${view}"]`);
    const chip = el("button", "explain-chip");
    chip.type = "button";
    chip.dataset.view = view;
    const icon = el("span", "explain-chip__icon", navItem?.querySelector(".nav-item__icon")?.textContent || "");
    icon.setAttribute("aria-hidden", "true");
    const label = navItem?.querySelector("span:not(.nav-item__icon)")?.textContent.trim() || view;
    chip.append(icon, document.createTextNode(label), el("span", "explain-chip__arrow", "›"));
    chip.addEventListener("click", () => {
      closeExplanation();
      navigateTo(view);
    });
    chips.append(chip);
  }
  card.append(el("h4", "explain-card__title", "Related areas"), chips);
  return card;
}

function contextLine(explanation) {
  if (explanation.allInstances) return "Covers every active instance; this page has no instance selector.";
  const instance = getInstanceContext().instance;
  if (!instance || instance.primary) return "Showing the Primary instance.";
  const where = instance.connection ? `${instance.name} (${instance.connection})` : instance.name;
  return `Showing ${where}. Changes run on the Primary instance only.`;
}

/** Opens the briefing for `view` (one of EXPLANATIONS). */
export function openExplanation(view) {
  const explanation = EXPLANATIONS[view];
  if (!explanation) return;
  dom.title.textContent = `Screen Insights · ${explanation.title}`;
  dom.context.textContent = contextLine(explanation);
  dom.body.replaceChildren(
    overviewCard(explanation),
    snapshotCard(explanation),
    insightsSection(explanation),
    termsCard(explanation),
    relatedCard(explanation),
  );
  dom.backdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawer.scrollTop = 0;  // the panel is reused: always start at the top
  dom.close.focus();
}

function closeExplanation() {
  dom.backdrop.hidden = true;
  dom.drawer.hidden = true;
}

/** Puts the button in `view`'s header (after the instance selector when it's there), or hides it. */
export function placeExplainButton(view) {
  closeExplanation();
  const header = EXPLANATIONS[view] ? document.querySelector(`#view-${view} > .view__header`) : null;
  if (!header || !header.firstElementChild) {
    dom.button.hidden = true;
    return;
  }
  const selector = $("instance-selector");
  const after = selector && !selector.hidden && selector.parentElement === header ? selector : header.firstElementChild;
  if (dom.button.previousElementSibling !== after) after.after(dom.button);
  dom.button.hidden = false;
}

/** `getView` returns the open page (app.js's current view). */
export function initExplainScreen(getView) {
  currentView = getView;
  dom.button.addEventListener("click", () => openExplanation(currentView()));
  dom.close.addEventListener("click", closeExplanation);
  dom.backdrop.addEventListener("click", closeExplanation);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeExplanation();
  });
}
