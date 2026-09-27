// Issue Resolver page: active issues from GET /api/iris/issues, each
// explained with its entry from the Issue Resolution Catalog (the
// response's `resolutions`, keyed by issue kind).
//
// Read-only. The page shows the evidence, the recommended solution and the
// workflow, but never runs anything; resolving happens through Resolve
// Issues on the Databases page.

import { IrisApi } from "./api.js";

const PLACEHOLDER = "—";  // shown for empty values

const SEVERITY_ORDER = ["low", "medium", "high", "critical"];
const SEVERITY_BADGES = {
  critical: "status-badge--error",
  high: "status-badge--error",
  medium: "status-badge--warning",
  low: "status-badge--neutral",
};
const RISK_BADGES = {
  high: "status-badge--error",
  medium: "status-badge--warning",
  low: "status-badge--neutral",
  none: "status-badge--ok",
};

const dom = {
  refreshButton: document.getElementById("issue-resolver-refresh-button"),
  loadingState: document.getElementById("issue-resolver-loading-state"),
  errorBanner: document.getElementById("issue-resolver-error-banner"),
  errorBannerText: document.getElementById("issue-resolver-error-banner-text"),
  kpiActive: document.getElementById("issue-resolver-kpi-active"),
  kpiSeverity: document.getElementById("issue-resolver-kpi-severity"),
  kpiCatalog: document.getElementById("issue-resolver-kpi-catalog"),
  list: document.getElementById("issue-resolver-list"),
  empty: document.getElementById("issue-resolver-empty"),
  catalogWrapper: document.getElementById("issue-resolver-catalog-wrapper"),
  catalogBody: document.getElementById("issue-resolver-catalog-body"),
  drawer: document.getElementById("issue-resolver-drawer"),
  drawerBackdrop: document.getElementById("issue-resolver-drawer-backdrop"),
  drawerClose: document.getElementById("issue-resolver-drawer-close"),
  drawerTitle: document.getElementById("issue-resolver-drawer-title"),
  drawerSeverity: document.getElementById("issue-resolver-drawer-severity"),
  drawerBody: document.getElementById("issue-resolver-drawer-body"),
  openDatabasesButton: document.getElementById("issue-resolver-open-databases"),
};

// The last response; the drawer reads from it.
let activeIssues = [];
let resolutions = {};
let onOpenDatabases = null;

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  if (typeof value === "boolean") return value ? "true" : "false";
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function capitalize(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : PLACEHOLDER;
}

// Built with createElement/textContent (no innerHTML).
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function badge(text, variant) {
  return el("span", `status-badge ${variant}`, text);
}

function severityBadge(severity) {
  return badge(capitalize(severity), SEVERITY_BADGES[severity] || "status-badge--neutral");
}

function riskBadge(risk) {
  return badge(`${capitalize(risk)} risk`, RISK_BADGES[risk] || "status-badge--neutral");
}

function privilegeText(resolution) {
  const privileges = resolution.required_privileges || [];
  return privileges.length ? privileges.join(" or ") : PLACEHOLDER;
}

function section(title, ...children) {
  const wrap = el("section", "ns-drawer__section ir-section");
  wrap.append(el("h4", "ns-drawer__section-title", title), ...children);
  return wrap;
}

function infoList(rows) {
  const list = el("dl", "info-list");
  for (const [label, value, { mono = false } = {}] of rows) {
    const row = el("div", "info-list__row");
    const dd = el("dd", mono ? "info-list__value info-list__value--mono" : "info-list__value");
    if (value instanceof Node) dd.append(value);
    else dd.textContent = textOrPlaceholder(value);
    row.append(el("dt", null, label), dd);
    list.append(row);
  }
  return list;
}

function bulletList(items) {
  const list = el("ul", "ir-bullets");
  for (const item of items) list.append(el("li", null, item));
  return list;
}

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disable right away so a double click doesn't fire two requests.
  dom.refreshButton.disabled = isLoading;
  dom.refreshButton.classList.toggle("btn--spinning", isLoading);
}

function setErrorBanner(message) {
  dom.errorBanner.hidden = !message;
  dom.errorBannerText.textContent = message || "";
}

// --- summary and lists ---

function renderKpis() {
  dom.kpiActive.textContent = String(activeIssues.length);
  dom.kpiCatalog.textContent = String(Object.keys(resolutions).length);
  const severities = activeIssues
    .map((issue) => resolutions[issue.kind]?.severity)
    .filter((s) => SEVERITY_ORDER.includes(s));
  const highest = severities.sort((a, b) => SEVERITY_ORDER.indexOf(b) - SEVERITY_ORDER.indexOf(a))[0];
  dom.kpiSeverity.textContent = highest ? capitalize(highest) : "None";
}

function renderIssueCard(issue, index) {
  const resolution = resolutions[issue.kind];
  const card = el("article", "ir-issue");
  card.dataset.index = String(index);
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  card.setAttribute("aria-label", `View resolution for ${textOrPlaceholder(issue.database)}`);

  const head = el("div", "ir-issue__head");
  head.append(
    resolution ? severityBadge(resolution.severity) : badge("Unknown", "status-badge--neutral"),
    el("span", "ir-issue__title", resolution ? resolution.title : textOrPlaceholder(issue.kind)),
    badge(textOrPlaceholder(issue.status), "status-badge--neutral"),
  );

  const resource = el("p", "ir-issue__resource");
  resource.append(el("strong", null, textOrPlaceholder(issue.database)), document.createTextNode(" · "),
    el("span", "ir-mono", textOrPlaceholder(issue.directory)));

  const meta = el("div", "ir-issue__meta");
  if (resolution) {
    meta.append(
      el("span", "db-chip ir-mono", resolution.operation),
      el("span", "ir-issue__privilege", `Requires ${privilegeText(resolution)}`),
      riskBadge(resolution.risk_level),
    );
  } else {
    meta.append(el("span", "ir-issue__privilege", "No catalog entry for this issue type."));
  }

  card.append(head, resource, meta, el("span", "stat-card__link", "View resolution →"));
  return card;
}

function renderIssues() {
  dom.list.replaceChildren(...activeIssues.map(renderIssueCard));
  dom.empty.hidden = activeIssues.length !== 0;
}

function renderCatalog() {
  const entries = Object.values(resolutions);
  dom.catalogBody.replaceChildren();
  dom.catalogWrapper.hidden = entries.length === 0;
  for (const entry of entries) {
    const row = el("tr");
    const cell = (content, mono = false) => {
      const td = el("td", mono ? "data-table__cell data-table__cell--mono" : "data-table__cell");
      if (content instanceof Node) td.append(content);
      else td.textContent = textOrPlaceholder(content);
      return td;
    };
    row.append(
      cell(entry.title),
      cell(severityBadge(entry.severity)),
      cell(entry.recommended_solution),
      cell(entry.operation, true),
      cell(privilegeText(entry)),
      cell(riskBadge(entry.risk_level)),
    );
    dom.catalogBody.append(row);
  }
}

// --- detail panel ---

function liveValue(issue, field) {
  return field ? issue[field] : undefined;
}

function evidenceTable(issue, resolution) {
  const table = el("table", "data-table data-table--compact");
  const head = el("tr");
  for (const title of ["Check", "Source", "Live value"]) {
    const th = el("th", null, title);
    th.setAttribute("scope", "col");
    head.append(th);
  }
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  for (const evidence of resolution.detection_evidence) {
    const row = el("tr");
    const value = liveValue(issue, evidence.issue_field);
    row.append(
      el("td", "data-table__cell", evidence.condition),
      el("td", "data-table__cell data-table__cell--mono", `${evidence.source} · ${evidence.field}`),
      el("td", "data-table__cell data-table__cell--mono", textOrPlaceholder(value)),
    );
    tbody.append(row);
  }
  table.append(thead, tbody);
  const wrapper = el("div", "table-wrapper");
  wrapper.append(table);
  return wrapper;
}

function parameterRows(issue, resolution) {
  return resolution.parameters.map((binding) => {
    const value = binding.from_issue_field ? issue[binding.from_issue_field] : binding.value;
    const source = binding.from_issue_field ? `from the issue's ${binding.from_issue_field}` : "fixed";
    return [binding.name, `${textOrPlaceholder(value)}  (${source})`, { mono: true }];
  });
}

function workflowList(resolution) {
  const list = el("ol", "resolve-steps");
  list.setAttribute("aria-label", "Catalog workflow steps");
  resolution.workflow_steps.forEach((step, index) => {
    const item = el("li", "resolve-step");
    item.dataset.state = "pending";
    const marker = el("span", "resolve-step__marker", String(index + 1));
    marker.setAttribute("aria-hidden", "true");
    const body = el("span", "resolve-step__body");
    body.append(el("span", "resolve-step__label", step.title), el("span", "resolve-step__detail", step.description));
    item.append(marker, body);
    list.append(item);
  });
  return list;
}

function whyThisSolution(issue, resolution) {
  const details = el("details", "db-issue__why ir-why");
  details.open = true;
  details.append(
    el("summary", null, "Why this solution?"),
    ...(issue.explanation ? [el("p", "ir-why__text", issue.explanation)] : []),
    el("p", "ir-why__text", resolution.explanation),
    el("p", "ir-why__label", "Before it runs"),
    bulletList(resolution.prerequisites),
    el("p", "ir-why__label", "How success is verified"),
    bulletList(resolution.verification_rules.map((rule) => `${rule.condition} (${rule.source})`)),
    el("p", "ir-why__label", "Safety restrictions"),
    bulletList(resolution.safety_restrictions),
  );
  return details;
}

function openDrawer(index) {
  const issue = activeIssues[index];
  if (!issue) return;
  const resolution = resolutions[issue.kind];

  dom.drawerTitle.textContent = `${textOrPlaceholder(issue.database)} · ${resolution ? resolution.title : textOrPlaceholder(issue.kind)}`;
  const severity = resolution ? resolution.severity : null;
  dom.drawerSeverity.className = `status-badge ${SEVERITY_BADGES[severity] || "status-badge--neutral"}`;
  dom.drawerSeverity.textContent = severity ? capitalize(severity) : "Unknown";

  const summary = section("Issue", infoList([
    ["Issue type", issue.kind, { mono: true }],
    ["Affected database", issue.database],
    ["Directory", issue.directory, { mono: true }],
    ["IRIS status", issue.status],
  ]));

  if (!resolution) {
    dom.drawerBody.replaceChildren(summary, el("p", "empty-state", "No catalog entry for this issue type."));
  } else {
    dom.drawerBody.replaceChildren(
      summary,
      section("Live evidence", evidenceTable(issue, resolution)),
      section(
        "Recommended solution",
        el("p", "ir-solution", resolution.recommended_solution),
        infoList([["Operation", resolution.operation, { mono: true }], ...parameterRows(issue, resolution)]),
      ),
      section("Privilege and risk", infoList([
        ["Required privilege", privilegeText(resolution)],
        ["Risk", riskBadge(resolution.risk_level)],
        ["Confirmation", resolution.confirmation_required ? "Required" : "Not required"],
      ])),
      section("Workflow", workflowList(resolution)),
      whyThisSolution(issue, resolution),
    );
  }

  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (wasHidden) dom.drawerClose.focus();
}

function closeDrawer() {
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

/** Load GET /api/iris/issues and render the page. */
export async function loadIssueResolver() {
  setLoading(true);
  setErrorBanner(null);
  try {
    const response = await IrisApi.getIssues();
    activeIssues = Array.isArray(response?.issues) ? response.issues : [];
    resolutions = response?.resolutions && typeof response.resolutions === "object" ? response.resolutions : {};
  } catch {
    activeIssues = [];
    resolutions = {};
    setErrorBanner("Could not check for issues right now. The Command Center backend may be unreachable.");
  }
  closeDrawer();
  renderKpis();
  renderIssues();
  renderCatalog();
  setLoading(false);
}

/** `onOpenDatabases()` goes to Resolve Issues on the Databases page (wired by app.js). */
export function initIssueResolverControls({ onOpenDatabases: openDatabases } = {}) {
  onOpenDatabases = typeof openDatabases === "function" ? openDatabases : null;
  dom.openDatabasesButton.hidden = !onOpenDatabases;

  dom.refreshButton.addEventListener("click", () => {
    loadIssueResolver();
  });
  dom.list.addEventListener("click", (event) => {
    const card = event.target.closest(".ir-issue");
    if (card) openDrawer(Number(card.dataset.index));
  });
  dom.list.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const card = event.target.closest(".ir-issue");
    if (!card) return;
    event.preventDefault();
    openDrawer(Number(card.dataset.index));
  });
  dom.drawerClose.addEventListener("click", closeDrawer);
  dom.drawerBackdrop.addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDrawer();
  });
  dom.openDatabasesButton.addEventListener("click", () => {
    closeDrawer();
    if (onOpenDatabases) onOpenDatabases();
  });
}
