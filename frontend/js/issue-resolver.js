// Issue Resolver page: active issues from GET /api/iris/issues, each
// explained with its entry from the Issue Resolution Catalog (the
// response's `resolutions`, keyed by issue kind).
//
// The page itself never changes IRIS: each issue is resolved on the page
// that owns its resource (see RESOURCES): Resolve Issues on the Databases
// page, or the web application's Enabled State on the Web Apps page. The one exception is the Demo Issue panel,
// which runs the existing IPM Issue Resolution Rehearsal in two explicit
// steps (POST /api/iris/demo/rehearsal, scenarios "issue_create" and
// "issue_resolve"), each only after an explicit acknowledgement and Confirm,
// and shows their real step results as one lifecycle:
// Create -> Detect -> Explain -> Resolve -> Verify -> Restore -> Observe.
//
// Instance-aware (instance selector): the issues are checked on the selected
// instance (GET /api/iris/issues?instance=<id>; the Primary without it). Every
// change runs on the Primary only, so with another instance selected the
// Resolve actions, custom rule changes and the Demo Issue are shown disabled
// and marked Primary only, and resolution history (which lists those fixes)
// isn't shown.

import { ApiError, IrisApi } from "./api.js";
import { getInstanceContext, selectedInstanceId } from "./instance-context.js";

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
  kpiResolvable: document.getElementById("issue-resolver-kpi-resolvable"),
  kpiDetection: document.getElementById("issue-resolver-kpi-detection"),
  updated: document.getElementById("issue-resolver-updated"),
  tabs: document.querySelectorAll(".ir-tabs__tab[data-ir-target]"),
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
  drawerHint: document.getElementById("issue-resolver-drawer-hint"),
  rulesAdd: document.getElementById("issue-resolver-rules-add"),
  rulesStorage: document.getElementById("issue-resolver-rules-storage"),
  rulesError: document.getElementById("issue-resolver-rules-error"),
  rulesErrorText: document.getElementById("issue-resolver-rules-error-text"),
  ruleForm: document.getElementById("issue-resolver-rule-form"),
  ruleName: document.getElementById("issue-resolver-rule-name"),
  ruleTitle: document.getElementById("issue-resolver-rule-title"),
  ruleSeverity: document.getElementById("issue-resolver-rule-severity"),
  ruleSignal: document.getElementById("issue-resolver-rule-signal"),
  ruleOperator: document.getElementById("issue-resolver-rule-operator"),
  ruleValue: document.getElementById("issue-resolver-rule-value"),
  rulePage: document.getElementById("issue-resolver-rule-page"),
  ruleGuidance: document.getElementById("issue-resolver-rule-guidance"),
  ruleSubmit: document.getElementById("issue-resolver-rule-submit"),
  ruleCancel: document.getElementById("issue-resolver-rule-cancel"),
  rulesWrapper: document.getElementById("issue-resolver-rules-wrapper"),
  rulesBody: document.getElementById("issue-resolver-rules-body"),
  rulesEmpty: document.getElementById("issue-resolver-rules-empty"),
  rehearsalStart: document.getElementById("issue-resolver-rehearsal-start"),
  rehearsalPrimaryNote: document.getElementById("issue-resolver-rehearsal-primary-note"),
  rulesPrimaryNote: document.getElementById("issue-resolver-rules-primary-note"),
  demoResolve: document.getElementById("issue-resolver-demo-resolve"),
  rehearsalWarning: document.getElementById("issue-resolver-rehearsal-warning"),
  rehearsalAckText: document.getElementById("issue-resolver-rehearsal-ack-text"),
  rehearsalRunningText: document.getElementById("issue-resolver-rehearsal-running-text"),
  rehearsalConfirm: document.getElementById("issue-resolver-rehearsal-confirm"),
  rehearsalAck: document.getElementById("issue-resolver-rehearsal-ack"),
  rehearsalRun: document.getElementById("issue-resolver-rehearsal-run"),
  rehearsalCancel: document.getElementById("issue-resolver-rehearsal-cancel"),
  lifecycle: document.getElementById("issue-resolver-lifecycle"),
  rehearsalRunning: document.getElementById("issue-resolver-rehearsal-running"),
  rehearsalError: document.getElementById("issue-resolver-rehearsal-error"),
  rehearsalErrorText: document.getElementById("issue-resolver-rehearsal-error-text"),
  rehearsalSummary: document.getElementById("issue-resolver-rehearsal-summary"),
  rehearsalResults: document.getElementById("issue-resolver-rehearsal-results"),
  rehearsalStages: document.getElementById("issue-resolver-rehearsal-stages"),
  rehearsalEvidence: document.getElementById("issue-resolver-rehearsal-evidence"),
};

// The last response; the drawer reads from it.
let activeIssues = [];
let resolutions = {};
let issueCorrelations = [];
let issueHistoryRequest = 0;
let onOpenDatabases = null;
let onOpenWebApps = null;
let onOpenOperations = null;
let onInvestigate = null;  // app.js: navigateTo(page), for detection-only issues
let drawerIssue = null;  // the issue shown in the drawer
let onOpenTrace = null;
let onRehearsalFinished = null;

// The last run of each demo step: { result, seconds, fixTrace } or null.
// Kept across page reloads of the issue list. fixTrace (Resolve only) is the
// recorded execution trace of the database.mount fix (null if unreadable).
const demoRuns = { create: null, resolve: null };
let lastStep = null;     // "create" or "resolve": the run the summary describes
let pendingStep = null;  // the step the confirmation box is for
let rehearsalRunning = false;

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

// The registry holds the names IRIS's /info reports ("Journal"); shown as the
// full privilege name (%Admin_Journal).
function privilegeText(resolution) {
  const privileges = resolution.required_privileges || [];
  return privileges.length ? privileges.map((name) => `%Admin_${name}`).join(" or ") : PLACEHOLDER;
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

// --- resources: what each issue kind is about and where it's resolved ---

const RESOURCES = {
  database_dismounted: {
    name: (issue) => issue.database,
    detail: (issue) => issue.directory,
    status: (issue) => issue.status,
    rows: (issue) => [
      ["Affected database", issue.database],
      ["Directory", issue.directory, { mono: true }],
      ["IRIS status", issue.status],
    ],
    // For the Fix Preview: [what changes, current value, proposed value].
    change: (issue) => ["Status", issue.status, "Mounted"],
    page: "databases",
    action: "Go to Resolve Issues →",
    hint: "Read-only. Resolving runs through Resolve Issues on the Databases page.",
  },
  web_app_namespace_missing: {
    name: (issue) => issue.web_app,
    detail: (issue) => `namespace ${textOrPlaceholder(issue.namespace)} (missing)`,
    status: (issue) => (issue.enabled ? "Enabled" : "Disabled"),
    rows: (issue) => [
      ["Affected web application", issue.web_app, { mono: true }],
      ["Namespace", issue.namespace, { mono: true }],
      ["Enabled", issue.enabled],
      ["Type", issue.app_type],
    ],
    change: (issue) => ["Enabled", issue.enabled, issue.parameters?.Enabled],
    page: "web-apps",
    action: "Resolve in Web Apps →",
    hint: "Read-only. Resolving runs through the web application's Enabled State on the Web Apps page.",
  },
  journal_purge_archived_off: {
    name: () => "Journal settings",
    detail: (issue) => `ArchiveName ${textOrPlaceholder(issue.archive_name)}`,
    status: (issue) => (issue.purge_archived ? "PurgeArchived on" : "PurgeArchived off"),
    rows: (issue) => [
      ["Resource", "Journal settings"],
      ["ArchiveName", issue.archive_name, { mono: true }],
      ["PurgeArchived", issue.purge_archived],
    ],
    change: (issue) => ["PurgeArchived", issue.purge_archived, issue.parameters?.PurgeArchived],
    page: "operations",
    action: "Resolve in Operations →",
    hint: "Read-only. Resolving runs through Update Journal Settings on the Operations page.",
  },
  // Detection-only kinds: no operation. The page to investigate on comes from
  // the catalog entry's `investigation`, not from here.
  system_monitor_not_running: {
    name: () => "System Monitor",
    detail: (issue) => `instance up ${textOrPlaceholder(issue.up_time)}`,
    status: () => "Not running",
    rows: (issue) => [
      ["Resource", "IRIS System Monitor"],
      ["SystemMonitor", issue.system_monitor],
      ["Instance uptime", issue.up_time],
    ],
  },
  task_manager_not_running: {
    name: () => "Task Manager",
    detail: (issue) => `status ${textOrPlaceholder(issue.status)}`,
    status: (issue) => textOrPlaceholder(issue.status),
    rows: (issue) => [
      ["Resource", "IRIS Task Manager"],
      ["Status", issue.status],
    ],
  },
  database_full: {
    name: (issue) => issue.database || issue.directory,
    detail: (issue) => `${textOrPlaceholder(issue.directory)} · ${textOrPlaceholder(issue.size)} MB of ${textOrPlaceholder(issue.max_size)}`,
    status: (issue) => (issue.full ? "Full" : "At maximum size"),
    rows: (issue) => [
      ["Affected database", issue.database],
      ["Directory", issue.directory, { mono: true }],
      ["Size (MB)", issue.size],
      ["Maximum size (MB)", issue.max_size],
      ["IRIS reports Full", issue.full],
      ["Why", (issue.reasons || []).map((r) => (r === "iris_reports_full" ? "IRIS reports Full" : "Maximum size reached")).join(", ")],
    ],
  },
};

const PAGE_LABELS = {
  dashboard: "Dashboard", system: "System", processes: "Processes", databases: "Databases",
  "web-apps": "Web Apps", tasks: "Tasks", security: "Security", journal: "Journal",
  observability: "Observability", investigation: "Investigation",
};

// A catalog entry with no operation: it says where to investigate instead.
function isDetectionOnly(resolution) {
  return Boolean(resolution && resolution.resolvable === false && resolution.investigation);
}

function pageLabel(page) {
  return PAGE_LABELS[page] || page;
}

function investigateAction(resolution) {
  return `Investigate in ${pageLabel(resolution.investigation.page)} →`;
}

// The Investigation section: where to look and what to check. Nothing runs.
function investigationSection(resolution) {
  return section(
    "Investigation",
    el("p", "ir-solution", resolution.recommended_solution),
    infoList([
      ["Resolution", "Detection-only: the Command Center has no operation for this."],
      ["Where", `${pageLabel(resolution.investigation.page)} page`],
      ["What to check", resolution.investigation.description],
    ]),
  );
}

// An issue kind without an entry is shown by its kind, with no resolve action.
const UNKNOWN_RESOURCE = {
  name: (issue) => issue.kind,
  detail: () => PLACEHOLDER,
  status: () => PLACEHOLDER,
  rows: () => [],
  page: null,
  action: "",
  hint: "Read-only.",
};

// A Custom Issue Rule's issue (kind "custom:<name>"): shown by its rule.
const CUSTOM_RULE_RESOURCE = {
  name: (issue) => `Rule ${textOrPlaceholder(issue.rule)}`,
  detail: (issue) => `${textOrPlaceholder(issue.signal_label)} is ${textOrPlaceholder(issue.value)}`,
  status: () => "Custom rule",
  rows: (issue) => [
    ["Rule", issue.rule, { mono: true }],
    ["Signal", issue.signal_label],
    ["Condition", `${textOrPlaceholder(issue.signal_label)} ${textOrPlaceholder(issue.operator)} ${textOrPlaceholder(issue.threshold)}`],
    ["Live value", issue.value],
  ],
};

function isCustomKind(kind) {
  return typeof kind === "string" && kind.startsWith("custom:");
}

function resourceOf(issue) {
  if (isCustomKind(issue?.kind)) return CUSTOM_RULE_RESOURCE;
  return RESOURCES[issue?.kind] || UNKNOWN_RESOURCE;
}

// The instance the page shows. Changes only run on the Primary.
function viewedInstance() {
  const instance = getInstanceContext().instance;
  return { primary: !instance || instance.primary, name: instance ? instance.name : "Primary" };
}

const PRIMARY_ONLY_FIX = "Resolve on Primary only";
const PRIMARY_ONLY_FIX_TITLE = "Fixes run on the Primary instance only. Select Primary to resolve this issue there.";

// A resolvable issue on another instance can't be fixed from here.
function fixBlocked(resolution) {
  return !isDetectionOnly(resolution) && !viewedInstance().primary;
}

// The app.js callback that opens the page where this issue is resolved.
function resolveHandler(issue) {
  const resolution = resolutions[issue?.kind];
  if (isDetectionOnly(resolution)) {
    return onInvestigate ? () => onInvestigate(resolution.investigation.page) : null;
  }
  const page = resourceOf(issue).page;
  if (page === "databases") return onOpenDatabases;
  if (page === "web-apps") return onOpenWebApps;
  if (page === "operations") return onOpenOperations;
  return null;
}

// --- summary and lists ---

function renderKpis() {
  dom.kpiActive.textContent = String(activeIssues.length);
  const detectionOnly = activeIssues.filter((issue) => isDetectionOnly(resolutions[issue.kind])).length;
  const resolvable = activeIssues.filter((issue) => resolutions[issue.kind]?.resolvable === true).length;
  dom.kpiResolvable.textContent = String(resolvable);
  dom.kpiDetection.textContent = String(detectionOnly);
  dom.kpiCatalog.textContent = String(Object.keys(resolutions).length);
  const severities = activeIssues
    .map((issue) => resolutions[issue.kind]?.severity)
    .filter((s) => SEVERITY_ORDER.includes(s));
  const highest = severities.sort((a, b) => SEVERITY_ORDER.indexOf(b) - SEVERITY_ORDER.indexOf(a))[0];
  dom.kpiSeverity.textContent = highest ? capitalize(highest) : "None";
}

// Resolvable (a registered operation fixes it) or Detection-only (investigate).
function typeBadge(resolution) {
  if (isDetectionOnly(resolution)) return badge("Detection-only", "ir-badge--detection");
  if (resolution) return badge("Resolvable", "status-badge--accent");
  return badge("Unknown", "status-badge--neutral");
}

function readinessBadge(readiness) {
  const labels = {
    ready_to_check: ["Ready to check", "status-badge--ok"],
    blocked: ["Blocked", "status-badge--error"],
    investigation_required: ["Investigation required", "status-badge--warning"],
    insufficient_evidence: ["Insufficient evidence", "status-badge--warning"],
  };
  const known = typeof readiness === "string" && Object.prototype.hasOwnProperty.call(labels, readiness);
  const [label, variant] = known
    ? labels[readiness]
    : ["Readiness unavailable", "status-badge--neutral"];
  return badge(label, variant);
}

function issueIdValue(issueId) {
  const wrap = el("span", "obs-traceid");
  wrap.append(el("code", "ir-mono", textOrPlaceholder(issueId)));
  if (navigator.clipboard && typeof issueId === "string" && issueId) {
    const copy = el("button", "obs-icon-btn", "Copy");
    copy.type = "button";
    copy.title = "Copy the full issue ID";
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(issueId);
        copy.textContent = "Copied";
      } catch {
        copy.textContent = "Copy failed";
      }
      setTimeout(() => {
        copy.textContent = "Copy";
      }, 1500);
    });
    wrap.append(copy);
  }
  return wrap;
}

// The card: severity edge | what & where | type, severity, action | status | chevron.
function renderIssueCard(issue, index) {
  const resolution = resolutions[issue.kind];
  const card = el("article", "ir-issue");
  card.dataset.index = String(index);
  card.dataset.severity = resolution?.severity || "unknown";
  card.tabIndex = 0;
  card.setAttribute("role", "button");
  const res = resourceOf(issue);
  card.setAttribute("aria-label", `View resolution for ${textOrPlaceholder(res.name(issue))}`);

  const icon = el("span", "ir-issue__icon", "⚠");
  icon.setAttribute("aria-hidden", "true");

  const main = el("div", "ir-issue__main");
  const resource = el("p", "ir-issue__resource");
  resource.append(el("strong", null, textOrPlaceholder(res.name(issue))), document.createTextNode(" · "),
    el("span", "ir-mono", textOrPlaceholder(res.detail(issue))));
  main.append(el("span", "ir-issue__title", resolution ? resolution.title : textOrPlaceholder(issue.kind)), resource);
  if (Array.isArray(issue.affected_namespaces) && issue.affected_namespaces.length) {
    main.append(el("p", "ir-issue__privilege",
      `Affects namespaces: ${issue.affected_namespaces.map((a) => a.namespace).join(", ")}`));
  }

  const plan = el("div", "ir-issue__plan");
  const badges = el("div", "ir-issue__badges");
  badges.append(typeBadge(resolution),
    resolution ? severityBadge(resolution.severity) : badge("Unknown", "status-badge--neutral"),
    readinessBadge(issue.readiness));
  plan.append(badges);
  if (resolution && !isDetectionOnly(resolution)) {
    const meta = el("div", "ir-issue__meta");
    meta.append(
      el("span", "db-chip ir-mono", resolution.operation),
      el("span", "ir-issue__privilege", `Requires ${privilegeText(resolution)}`),
      riskBadge(resolution.risk_level),
    );
    plan.append(meta);
  } else if (!resolution) {
    plan.append(el("span", "ir-issue__privilege", "No catalog entry for this issue type."));
  }
  // The same action as the drawer's button: open the page where it's resolved or investigated.
  if (resolveHandler(issue)) {
    const action = el("button", "ir-issue__action",
      isDetectionOnly(resolution) ? investigateAction(resolution) : res.action);
    action.type = "button";
    if (fixBlocked(resolution)) {
      action.disabled = true;
      action.textContent = PRIMARY_ONLY_FIX;
      action.title = PRIMARY_ONLY_FIX_TITLE;
    }
    plan.append(action);
  }

  const status = el("div", "ir-issue__status");
  status.append(el("span", "ir-issue__detected", "Detected"),
    el("span", "ir-issue__privilege", textOrPlaceholder(res.status(issue))));

  const chevron = el("span", "ir-issue__chevron", "›");
  chevron.setAttribute("aria-hidden", "true");
  card.append(icon, main, plan, status, chevron);
  return card;
}

// A card's action button opens the resolve/investigate page instead of the drawer.
function runCardAction(event) {
  const button = event.target.closest(".ir-issue__action");
  if (!button) return false;
  if (button.disabled) return true;
  const card = button.closest(".ir-issue");
  const issue = activeIssues[Number(card?.dataset.index)];
  const open = resolveHandler(issue);
  if (open) open(issue);
  return true;
}

function renderIssues() {
  dom.list.replaceChildren(...activeIssues.map(renderIssueCard));
  dom.empty.hidden = activeIssues.length !== 0;
}

function firstSentence(text) {
  const value = String(text || "");
  const end = value.search(/[.!?](\s|$)/);
  return end === -1 ? value : value.slice(0, end + 1);
}

// Resolvable: the operation that fixes it. Detection-only: where to look.
function catalogAction(entry) {
  if (isDetectionOnly(entry)) return `Investigate in ${pageLabel(entry.investigation.page)}`;
  return entry.operation ? `Resolve with ${entry.operation}` : PLACEHOLDER;
}

function renderCatalog() {
  const entries = Object.values(resolutions);
  dom.catalogBody.replaceChildren();
  dom.catalogWrapper.hidden = entries.length === 0;
  for (const entry of entries) {
    const row = el("tr", "data-table__row--clickable");
    row.dataset.issueType = entry.issue_type;
    row.tabIndex = 0;
    row.setAttribute("aria-label", `View the catalog definition of ${textOrPlaceholder(entry.title)}`);
    const cell = (content, mono = false) => {
      const td = el("td", mono ? "data-table__cell data-table__cell--mono" : "data-table__cell");
      if (content instanceof Node) td.append(content);
      else td.textContent = textOrPlaceholder(content);
      return td;
    };
    const cellWrap = (text) => {
      const td = cell(text);
      td.classList.add("ir-cell--wrap");
      return td;
    };
    // Only a detected entry is flagged here; the definition shows "Not currently detected".
    const detected = detectedCount(entry.issue_type);
    const title = el("span", "ir-catalog__title");
    title.append(el("span", "ir-catalog__name", textOrPlaceholder(entry.title)));
    if (detected) title.append(detectionBadge(detected));
    if (isCustomKind(entry.issue_type)) title.append(badge("Custom rule", "status-badge--neutral"));
    const action = el("span", "ir-catalog__action");
    const chevron = el("span", "ir-issue__chevron", "›");
    chevron.setAttribute("aria-hidden", "true");
    action.append(el("span", null, catalogAction(entry)), chevron);
    row.append(
      cell(title),
      cellWrap(firstSentence(entry.explanation)),
      cell(typeBadge(entry)),
      cell(severityBadge(entry.severity)),
      cell(action),
    );
    dom.catalogBody.append(row);
  }
}

// --- detail panel ---

function liveValue(issue, field) {
  return field ? issue[field] : undefined;
}

// `issue` is null for the catalog view: no Live value column.
function evidenceTable(issue, resolution) {
  const table = el("table", "data-table data-table--compact");
  const head = el("tr");
  for (const title of ["Check", "Source", ...(issue ? ["Live value"] : [])]) {
    const th = el("th", null, title);
    th.setAttribute("scope", "col");
    head.append(th);
  }
  const thead = el("thead");
  thead.append(head);
  const tbody = el("tbody");
  for (const evidence of resolution.detection_evidence) {
    const row = el("tr");
    row.append(
      el("td", "data-table__cell", evidence.condition),
      el("td", "data-table__cell data-table__cell--mono", `${evidence.source} · ${evidence.field}`),
    );
    if (issue) {
      row.append(el("td", "data-table__cell data-table__cell--mono", textOrPlaceholder(liveValue(issue, evidence.issue_field))));
    }
    tbody.append(row);
  }
  table.append(thead, tbody);
  const wrapper = el("div", "table-wrapper");
  wrapper.append(table);
  return wrapper;
}

// Namespaces that use the database for Globals or Routines (null means
// they couldn't be read).
function affectedNamespaces(issue, resolution) {
  const wrap = el("div");
  const impact = (resolution.impact_evidence || []).find((e) => e.issue_field === "affected_namespaces");
  if (impact) wrap.append(el("p", "ir-why__text", `${impact.condition} (${impact.source} · ${impact.field})`));
  const affected = issue.affected_namespaces;
  if (!Array.isArray(affected)) {
    wrap.append(el("p", "empty-state", "Couldn't read which namespaces use this database."));
    return wrap;
  }
  if (affected.length === 0) {
    wrap.append(el("p", "empty-state", `No namespace uses ${textOrPlaceholder(issue.database)} for Globals or Routines.`));
    return wrap;
  }
  wrap.append(infoList(affected.map((a) => [a.namespace, a.uses.join(", ")])));
  return wrap;
}

function parameterRows(issue, resolution) {
  return resolution.parameters.map((binding) => {
    const value = binding.from_issue_field
      ? (issue ? issue[binding.from_issue_field] : "(from the detected issue)")
      : binding.value;
    const source = binding.from_issue_field ? `from the issue's ${binding.from_issue_field}` : "fixed";
    return [binding.name, `${textOrPlaceholder(value)}  (${source})`, { mono: true }];
  });
}

// What the fix would change, from the detected issue and its catalog entry.
// Read-only: nothing is authorized or run from here.
function fixPreview(issue, resolution) {
  const [field, current, proposed] = resourceOf(issue).change(issue);
  const rows = [
    ["Current → Proposed", `${field}: ${textOrPlaceholder(current)} → ${textOrPlaceholder(proposed)}`, { mono: true }],
    ["Operation", resolution.operation, { mono: true }],
    ["Authorization requirement",
      `${privilegeText(resolution)} (any one), checked by the backend when the operation runs`],
    ["Confirmation", resolution.confirmation_required ? "Required" : "Not required"],
    ["Verified by", bulletList(resolution.verification_rules.map((rule) => `${rule.condition} (${rule.source})`))],
  ];
  if (fixBlocked(resolution)) rows.push(["Runs on", "The Primary instance only. Select Primary to resolve this issue."]);
  return section("Fix Preview", infoList(rows),
    el("p", "ir-why__text", "The current value is the state detected when this page was loaded."));
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

function relatedFindingsSection(issue) {
  if (typeof issue.issue_id !== "string" || !Array.isArray(issueCorrelations)) return null;

  const related = new Map();
  for (const correlation of issueCorrelations) {
    if (!correlation || typeof correlation !== "object") continue;
    const relatedId = correlation.issue_id_a === issue.issue_id
      ? correlation.issue_id_b
      : correlation.issue_id_b === issue.issue_id
        ? correlation.issue_id_a
        : null;
    if (typeof relatedId !== "string" || !relatedId || relatedId === issue.issue_id) continue;

    const item = related.get(relatedId) || { kinds: new Set(), reasons: new Set() };
    if (typeof correlation.kind === "string" && correlation.kind) item.kinds.add(correlation.kind);
    if (typeof correlation.reason === "string" && correlation.reason) item.reasons.add(correlation.reason);
    related.set(relatedId, item);
  }
  if (!related.size) return null;

  const list = el("div", "info-list");
  for (const [relatedId, relationship] of related) {
    const relatedIssueIndex = activeIssues.findIndex((item) => item.issue_id === relatedId);
    const relatedIssue = relatedIssueIndex >= 0 ? activeIssues[relatedIssueIndex] : null;
    const relatedResolution = relatedIssue ? resolutions[relatedIssue.kind] : null;
    const displayName = relatedIssue?.resource?.display_name
      || relatedResolution?.title
      || relatedIssue?.kind
      || `Issue ${relatedId}`;
    const details = el("div");
    if (relatedIssueIndex >= 0) {
      const link = el("button", "ir-issue__action", displayName);
      link.type = "button";
      link.addEventListener("click", () => openDrawer(relatedIssueIndex));
      details.append(link);
    } else {
      details.append(el("strong", null, displayName));
    }
    if (relatedIssue) {
      details.append(el("p", "ir-why__text", relatedIssue.kind));
    }
    for (const reason of relationship.reasons) {
      details.append(el("p", "ir-why__text", reason));
    }
    list.append(
      infoList([
        [
          [...relationship.kinds].map((kind) => kind.replace(/_/g, " ")).join(", ") || "Related",
          details,
        ],
      ]),
    );
  }
  return section("Related Findings", list);
}

function lifecycleEvidenceText(label, values) {
  if (!values || typeof values !== "object") return null;
  const details = Object.entries(values)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => `${key.replace(/_/g, " ")}: ${textOrPlaceholder(value)}`)
    .join(", ");
  return details ? `${label}: ${details}` : null;
}

function resolutionHistorySection(entries) {
  if (!Array.isArray(entries) || !entries.length) return null;

  const historyItems = entries.map((entry) => {
    const timestamp = entry.timestamp
      ? new Date(entry.timestamp).toLocaleString()
      : PLACEHOLDER;
    const resultStatus = [
      entry.result?.operation_status,
      entry.result?.execution_status,
    ].filter((status) => typeof status === "string" && status).join(" / ") || "Unavailable";
    const verificationStatus = entry.verification?.status || "Unavailable";
    const actionParameters = Object.entries(entry.action?.parameters || {})
      .filter(([, value]) => value !== null && value !== undefined && value !== "");
    const evidence = [
      lifecycleEvidenceText("BEFORE", entry.before?.state),
      entry.action && (entry.action.operation_name || actionParameters.length)
        ? `ACTION: ${textOrPlaceholder(entry.action.operation_name)}`
          + (actionParameters.length
            ? ` (${actionParameters.map(([key, value]) => `${key}=${textOrPlaceholder(value)}`).join(", ")})`
            : "")
        : null,
      lifecycleEvidenceText("AFTER", entry.after),
      entry.verification?.status
        ? `VERIFICATION: ${verificationStatus}`
        : null,
    ].filter(Boolean);
    const item = el("div", "ir-history__entry");
    item.append(
      infoList([
        ["Timestamp", timestamp],
        ["Operation", entry.operation_name],
        ["Result", resultStatus],
        ["Verification", verificationStatus],
      ]),
      ...(evidence.length ? [el("p", "ir-why__text", evidence.join(" → "))] : []),
    );
    return item;
  });
  return section("Resolution History", ...historyItems);
}

async function loadIssueResolutionHistory(issue, requestId) {
  if (typeof issue.issue_id !== "string" || !issue.issue_id) return;
  try {
    const response = await IrisApi.getIssueResolutionHistory(issue.issue_id);
    if (requestId !== issueHistoryRequest || drawerIssue !== issue || dom.drawer.hidden) return;
    const history = resolutionHistorySection(response?.history);
    if (history) dom.drawerBody.append(history);
  } catch {
    if (requestId !== issueHistoryRequest || drawerIssue !== issue || dom.drawer.hidden) return;
    dom.drawerBody.append(section("Resolution History", el("p", "empty-state", "Resolution history is unavailable.")));
  }
}

function openDrawer(index) {
  const issue = activeIssues[index];
  if (!issue) return;
  const historyRequest = ++issueHistoryRequest;
  const resolution = resolutions[issue.kind];

  const res = resourceOf(issue);
  drawerIssue = issue;
  dom.drawerTitle.textContent = `${textOrPlaceholder(res.name(issue))} · ${resolution ? resolution.title : textOrPlaceholder(issue.kind)}`;
  const detectionOnly = isDetectionOnly(resolution);
  dom.drawerHint.textContent = detectionOnly
    ? `Read-only. Detection-only: investigate it on the ${pageLabel(resolution.investigation.page)} page.`
    : res.hint;
  dom.openDatabasesButton.textContent = detectionOnly ? investigateAction(resolution) : res.action;
  dom.openDatabasesButton.hidden = !resolveHandler(issue);
  dom.openDatabasesButton.disabled = fixBlocked(resolution);
  dom.openDatabasesButton.title = fixBlocked(resolution) ? PRIMARY_ONLY_FIX_TITLE : "";
  if (fixBlocked(resolution)) dom.openDatabasesButton.textContent = PRIMARY_ONLY_FIX;
  const severity = resolution ? resolution.severity : null;
  dom.drawerSeverity.className = `status-badge ${SEVERITY_BADGES[severity] || "status-badge--neutral"}`;
  dom.drawerSeverity.textContent = severity ? capitalize(severity) : "Unknown";

  const summary = section("Issue", infoList([
    ["Issue type", issue.kind, { mono: true }],
    ["Readiness", readinessBadge(issue.readiness)],
    ["Resource", issue.resource?.display_name],
    ["Canonical resource key", issue.resource?.canonical_key, { mono: true }],
    ["Issue ID", issueIdValue(issue.issue_id)],
    ...res.rows(issue),
  ]));
  const relatedFindings = relatedFindingsSection(issue);

  if (!resolution) {
    dom.drawerBody.replaceChildren(
      summary,
      ...(relatedFindings ? [relatedFindings] : []),
      el("p", "empty-state", "No catalog entry for this issue type."),
    );
  } else if (detectionOnly) {
    dom.drawerBody.replaceChildren(
      summary,
      ...(relatedFindings ? [relatedFindings] : []),
      section("Live evidence", evidenceTable(issue, resolution)),
      section("Explanation",
        ...(issue.explanation ? [el("p", "ir-why__text", issue.explanation)] : []),
        el("p", "ir-why__text", resolution.explanation)),
      investigationSection(resolution),
      section("Verification", bulletList(resolution.verification_rules.map((rule) => `${rule.condition} (${rule.source})`))),
    );
  } else {
    dom.drawerBody.replaceChildren(
      summary,
      ...(relatedFindings ? [relatedFindings] : []),
      section("Live evidence", evidenceTable(issue, resolution)),
      ...(res.change ? [fixPreview(issue, resolution)] : []),
      ...("affected_namespaces" in issue ? [section("Affected namespaces", affectedNamespaces(issue, resolution))] : []),
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

  showDrawer();
  const viewed = viewedInstance();
  if (viewed.primary) {
    void loadIssueResolutionHistory(issue, historyRequest);
  } else {
    dom.drawerBody.append(section("Resolution History", el("p", "empty-state",
      `Resolution history lists fixes, which run on the Primary instance only, so it isn't shown for ${viewed.name}.`)));
  }
}

// Opens the (shared, centered) detail workspace.
function showDrawer() {
  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (wasHidden) dom.drawerClose.focus();
}

// --- catalog definitions (read-only, active or not) ---

function detectedCount(issueType) {
  return activeIssues.filter((issue) => issue.kind === issueType).length;
}

function detectionBadge(count) {
  return count
    ? badge(`Detected (${count})`, "status-badge--warning")
    : badge("Not currently detected", "status-badge--neutral");
}

/** The catalog entry for `issueType`, shown in the detail workspace. */
function openCatalogEntry(issueType) {
  const resolution = resolutions[issueType];
  if (!resolution) return;
  const detected = detectedCount(issueType);

  drawerIssue = null;  // no resolve action from a definition
  dom.drawerTitle.textContent = `${textOrPlaceholder(resolution.title)} · Catalog definition`;
  dom.drawerSeverity.className = `status-badge ${SEVERITY_BADGES[resolution.severity] || "status-badge--neutral"}`;
  dom.drawerSeverity.textContent = resolution.severity ? capitalize(resolution.severity) : "Unknown";
  dom.drawerHint.textContent = detected
    ? "Read-only catalog definition. This issue is detected now; open it from Active Issues to resolve it."
    : "Read-only catalog definition. Not currently detected.";
  dom.openDatabasesButton.hidden = true;

  const impact = resolution.impact_evidence || [];
  if (isDetectionOnly(resolution)) {
    dom.drawerBody.replaceChildren(
      section("Issue type", infoList([
        ["Issue type", resolution.issue_type, { mono: true }],
        ["Title", resolution.title],
        ["Severity", severityBadge(resolution.severity)],
        ["Status", detectionBadge(detected)],
      ])),
      section("Detection evidence", evidenceTable(null, resolution)),
      section("Explanation", el("p", "ir-why__text", resolution.explanation)),
      investigationSection(resolution),
      section("Verification", bulletList(resolution.verification_rules.map(
        (rule) => `${rule.condition} (${rule.source}; checked by issue detection)`,
      ))),
    );
    showDrawer();
    return;
  }
  dom.drawerBody.replaceChildren(
    section("Issue type", infoList([
      ["Issue type", resolution.issue_type, { mono: true }],
      ["Title", resolution.title],
      ["Severity", severityBadge(resolution.severity)],
      ["Status", detectionBadge(detected)],
    ])),
    section("Detection evidence", evidenceTable(null, resolution)),
    ...(impact.length
      ? [section("Impact evidence", bulletList(impact.map((e) => `${e.condition} (${e.source} · ${e.field})`)))]
      : []),
    section("Explanation", el("p", "ir-why__text", resolution.explanation)),
    section(
      "Recommended solution",
      el("p", "ir-solution", resolution.recommended_solution),
      infoList([["Operation", resolution.operation, { mono: true }], ...parameterRows(null, resolution)]),
    ),
    section("Privilege and risk", infoList([
      ["Required privilege", privilegeText(resolution)],
      ["Risk", riskBadge(resolution.risk_level)],
      ["Confirmation", resolution.confirmation_required ? "Required" : "Not required"],
    ])),
    section("Prerequisites", bulletList(resolution.prerequisites)),
    section("Safety restrictions", bulletList(resolution.safety_restrictions)),
    section("Workflow", workflowList(resolution)),
    section("Verification", bulletList(resolution.verification_rules.map(
      (rule) => `${rule.condition} (${rule.source}; checked by ${rule.checked_by === "operation" ? "the operation" : "issue detection"})`,
    ))),
  );
  showDrawer();
}

function closeDrawer() {
  issueHistoryRequest += 1;
  dom.drawerBackdrop.hidden = true;
  dom.drawer.hidden = true;
}

// --- Create Demo Issue (the existing IPM Issue Resolution Rehearsal) ---

const DISMOUNTED = "database_dismounted";
const DEMO_SCENARIO = "Dismounted database — IPM";
const DEMO_LABEL = "Intentionally created for demonstration";

// The lifecycle, and which of the rehearsal's own steps back each stage.
const LIFECYCLE = [
  { key: "create", label: "Create", sub: "Dismount IPM",
    steps: ["issue.read", "issue.dry_run", "issue.dismount", "issue.confirm_dismounted"] },
  { key: "detect", label: "Detect", sub: "Find the issue", steps: ["issue.detect"] },
  { key: "explain", label: "Explain", sub: "Show impact", steps: ["issue.detect"] },
  { key: "resolve", label: "Resolve", sub: "database.mount", steps: ["issue.fix"] },
  { key: "verify", label: "Verify", sub: "Confirm the fix", steps: ["issue.verify"] },
  { key: "restore", label: "Restore", sub: "Original state", steps: [] },
  { key: "observe", label: "Observe", sub: "Traces", steps: [] },
];

const STAGE_LABELS = { done: "Completed", failed: "Failed", pending: "Not run", waiting: "Waiting" };
const STAGE_BADGES = {
  done: "status-badge--ok",
  failed: "status-badge--error",
  pending: "status-badge--neutral",
  waiting: "status-badge--neutral",
};

// The two demo steps: the scenario each runs, and its texts.
const DEMO_STEPS = {
  create: {
    scenario: "issue_create",
    confirm: "Confirm & Create Demo Issue",
    warning: "This intentionally creates a real issue: the IPM database on the connected IRIS instance is " +
      "dismounted and stays dismounted until you resolve it.",
    ack: "I understand IPM will be dismounted and stay dismounted until I resolve it.",
    running: "Creating the demo issue… results appear when it finishes (usually a few seconds).",
  },
  resolve: {
    scenario: "issue_resolve",
    confirm: "Confirm & Resolve Demo Issue",
    warning: "This resolves the demo issue through the normal workflow: database.mount mounts IPM again on the " +
      "connected IRIS instance, then the fix is verified.",
    ack: "I understand IPM will be mounted again with database.mount.",
    running: "Resolving the demo issue… results appear when it finishes (usually a few seconds).",
  },
};

const RESTORE_FAILED = ["banner--error", "IPM could not be restored",
  "IPM may still be dismounted. Mount it from Resolve Issues on the Databases page."];
const SUMMARY = {
  create: {
    completed: ["banner--success", "Demo issue created",
      "IPM is dismounted and the issue is now active in Active Issues. Resolve it with Resolve Demo Issue."],
    stopped: ["banner--warning", "Demo issue not created",
      "A step didn't complete, and anything that changed was restored. See the step results below."],
    restore_failed: RESTORE_FAILED,
  },
  resolve: {
    completed: ["banner--success", "Demo issue resolved",
      "The demo issue was detected, resolved and verified, and IPM is back to its original state."],
    stopped: ["banner--warning", "Demo issue not resolved",
      "The fix didn't complete, so the demo issue may still be active. See the step results below."],
    restore_failed: RESTORE_FAILED,
  },
};

// The IPM demo issue is active in the live issue list.
function demoIssueActive() {
  return activeIssues.some((issue) => issue.kind === DISMOUNTED && String(issue.database).toUpperCase() === "IPM");
}

// Both steps' real results as one: the latest run's status and detail, and
// the steps of both runs (their step ids don't overlap).
function combinedDemoResult() {
  const latest = lastStep ? demoRuns[lastStep]?.result : null;
  if (!latest) return null;
  const steps = [demoRuns.create, demoRuns.resolve].flatMap((run) => (Array.isArray(run?.result?.steps) ? run.result.steps : []));
  return { status: latest.status, detail: latest.detail, steps };
}

function stepsById(result) {
  const map = new Map();
  for (const step of Array.isArray(result?.steps) ? result.steps : []) map.set(step.step, step);
  return map;
}

function stageFromSteps(ids, steps) {
  const found = ids.map((id) => steps.get(id)).filter(Boolean);
  if (found.length === 0) return "pending";
  if (found.some((step) => step.status === "failed")) return "failed";
  return found.length === ids.length ? "done" : "pending";
}

// Each stage's state and detail, built only from the rehearsal's real steps
// and the catalog entry.
function lifecycleStages(result) {
  const steps = stepsById(result);
  const entry = resolutions[DISMOUNTED];
  const detect = steps.get("issue.detect");
  const fix = steps.get("issue.fix");
  const verify = steps.get("issue.verify");
  const restoreStep = steps.get("issue.restore");
  const target = detect?.target || fix?.target || "IPM";
  const traces = [...steps.values()].filter((step) => step.trace_id);

  return LIFECYCLE.map((stage) => {
    let state = stageFromSteps(stage.steps, steps);
    let detail = "";
    let traceId = null;
    switch (stage.key) {
      case "create":
        detail = steps.get("issue.dismount")?.detail || steps.get("issue.dry_run")?.detail || steps.get("issue.read")?.detail || "";
        break;
      case "detect":
        detail = detect
          ? `GET /api/iris/issues reports ${entry ? entry.title.toLowerCase() : "an issue"}: ${target}.`
          : "";
        if (detect && detect.status !== "success") detail = detect.detail;
        break;
      case "explain":
        detail = detect ? String(detect.detail || "").replace(/^Command Center Issue:\s*/, "") : "";
        break;
      case "resolve":
        detail = fix ? `${textOrPlaceholder(fix.operation_name)} (${textOrPlaceholder(fix.operation_status)}): ${textOrPlaceholder(fix.detail)}` : "";
        traceId = fix?.trace_id || null;
        break;
      case "verify":
        detail = verify?.detail || "";
        break;
      case "restore":
        if (restoreStep) {
          state = restoreStep.status === "success" ? "done" : "failed";
          detail = restoreStep.detail;
        } else if (result?.status === "restore_failed") {
          state = "failed";
          detail = result.detail;
        } else if (verify?.status === "success") {
          state = "done";
          detail = `${target} is mounted again, as it was before the demo issue was created.`;
        } else if (steps.get("issue.confirm_dismounted")?.status === "success") {
          detail = `${target} stays dismounted until the demo issue is resolved.`;
        }
        break;
      case "observe":
        state = traces.length ? "done" : "pending";
        detail = traces.length
          ? `${traces.length} execution trace${traces.length === 1 ? "" : "s"} recorded; the resolution is labelled Issue Resolver.`
          : "";
        traceId = fix?.trace_id || traces[traces.length - 1]?.trace_id || null;
        break;
      default:
        break;
    }
    return { ...stage, state, detail, traceId, traces: stage.key === "observe" ? traces : [] };
  });
}

// --- Evidence chain: Detection -> Impact -> Resolution -> Verification -> Observability ---
//
// Only data the workflow already produced: the rehearsal's steps (the
// detected issue's explanation, the fix and the verification), the fix's
// execution trace, and the catalog entry.

// The detect step carries the issue's explanation, built by the issues route
// from fixed sentences; pull out the status and the namespace impact.
function parseDetection(detail) {
  const text = String(detail || "");
  const found = text.match(/Database (\S+) \((.+?)\) is reported by IRIS as "([^"]+)"/);
  const impact = text.match(/(No namespace uses it for Globals or Routines\.|Namespaces that depend on it: [^.]+\.|Which namespaces use it couldn't be read\.)/);
  return {
    database: found ? found[1] : null,
    directory: found ? found[2] : null,
    status: found ? found[3] : null,
    impact: impact ? impact[1] : null,
  };
}

function evidenceChain(result, fixTrace) {
  const steps = stepsById(result);
  const entry = resolutions[DISMOUNTED];
  const detect = steps.get("issue.detect");
  const fix = steps.get("issue.fix");
  const verify = steps.get("issue.verify");
  const detection = parseDetection(detect?.detail);
  const readOnly = entry?.parameters?.find((b) => b.name === "ReadOnly");
  const operationRule = entry?.verification_rules?.find((r) => r.checked_by === "operation");
  const directory = fixTrace?.resolution?.resource || detection.directory;
  const verified = fixTrace ? fixTrace.verification_result === "verified" : fix?.status === "success";

  return [
    {
      label: "Detection",
      source: "GET /api/iris/issues · /v2/database-dirs Status",
      value: detection.status
        ? `${detection.database} (${detection.directory}) reported "${detection.status}"`
        : textOrPlaceholder(detect?.detail),
      ok: detect?.status === "success",
    },
    {
      label: "Impact",
      source: "GET /v2/namespaces · Globals, Routines",
      value: detection.impact || PLACEHOLDER,
      ok: detect?.status === "success" && Boolean(detection.impact),
    },
    {
      label: "Resolution",
      source: textOrPlaceholder(fix?.operation_name),
      value: fix
        ? `Directory=${textOrPlaceholder(directory)}, ReadOnly=${textOrPlaceholder(readOnly?.value)} · ${textOrPlaceholder(fix.operation_status)}`
        : PLACEHOLDER,
      ok: fix?.status === "success",
    },
    {
      label: "Verification",
      source: `${operationRule ? operationRule.source : "operation verification"} · GET /api/iris/issues`,
      value: fix
        ? [
          verified ? "Mounted=true (operation verification: verified)" : `Operation verification: ${textOrPlaceholder(fixTrace?.verification_result)}`,
          verify?.status === "success" ? "issue cleared" : textOrPlaceholder(verify?.detail),
        ].join("; ")
        : PLACEHOLDER,
      ok: verified && verify?.status === "success",
    },
    {
      label: "Observability",
      source: "Execution trace",
      value: fixTrace
        ? `${String(fixTrace.trace_id).slice(0, 8)} · ${textOrPlaceholder(fixTrace.status)} · labelled ${textOrPlaceholder(fixTrace.resolution?.issue_title)}`
        : fix?.trace_id ? `${String(fix.trace_id).slice(0, 8)} (details couldn't be loaded)` : PLACEHOLDER,
      ok: Boolean(fixTrace?.resolution),
      traceId: fix?.trace_id || null,
    },
  ];
}

function renderEvidence(result, fixTrace) {
  dom.rehearsalEvidence.replaceChildren();
  for (const item of evidenceChain(result, fixTrace)) {
    const row = el("li", "ir-evidence__row");
    row.dataset.ok = String(item.ok);
    const mark = el("span", "ir-evidence__mark", item.ok ? "✓" : "–");
    mark.setAttribute("aria-label", item.ok ? "evidence present" : "evidence missing");
    const body = el("span", "ir-evidence__body");
    body.append(el("span", "ir-evidence__value", item.value));
    if (item.traceId && onOpenTrace) body.append(traceButton(item.traceId, "Open trace →"));
    row.append(mark, el("span", "ir-evidence__label", item.label), el("span", "ir-evidence__source", item.source), body);
    dom.rehearsalEvidence.append(row);
  }
}

function renderLifecycle(stages) {
  dom.lifecycle.replaceChildren();
  stages.forEach((stage, index) => {
    const item = el("li", "ir-lifecycle__stage");
    item.dataset.state = stage.state;
    const marker = el("span", "ir-lifecycle__marker", stage.state === "done" ? "✓" : stage.state === "failed" ? "!" : String(index + 1));
    marker.setAttribute("aria-hidden", "true");
    item.append(marker, el("span", "ir-lifecycle__label", stage.label), el("span", "ir-lifecycle__sub", stage.sub));
    item.title = `${stage.label}: ${STAGE_LABELS[stage.state]}`;
    dom.lifecycle.append(item);
  });
}

function traceButton(traceId, text) {
  const button = el("button", "dash-panel__link", text);
  button.type = "button";
  button.title = `Open trace ${traceId} in Observability`;
  button.addEventListener("click", () => onOpenTrace && onOpenTrace(traceId));
  return button;
}

function renderRehearsal() {
  const result = combinedDemoResult();
  const last = lastStep ? demoRuns[lastStep] : null;
  const stages = lifecycleStages(result).map((stage) =>
    rehearsalRunning ? { ...stage, state: "waiting" } : result ? stage : { ...stage, state: "pending" });
  renderLifecycle(stages);

  dom.rehearsalRunning.hidden = !rehearsalRunning;
  // Create while there's no active demo issue; Resolve only while there is one.
  const issueActive = demoIssueActive();
  const { primary } = viewedInstance();
  dom.rehearsalStart.disabled = rehearsalRunning || issueActive || !primary;
  dom.rehearsalStart.title = !primary ? "The Demo Issue runs on the Primary instance only."
    : issueActive ? "The IPM demo issue is already active. Resolve it first." : "";
  dom.demoResolve.disabled = rehearsalRunning || !issueActive || !primary;
  dom.rehearsalPrimaryNote.hidden = primary;
  if (!primary && !rehearsalRunning) dom.rehearsalConfirm.hidden = true;
  dom.rehearsalSummary.hidden = rehearsalRunning || !result;
  dom.rehearsalResults.hidden = rehearsalRunning || !result;
  if (rehearsalRunning || !result) return;

  const [variant, title, text] = SUMMARY[lastStep]?.[result.status] ||
    ["banner--warning", `Demo issue ${textOrPlaceholder(result.status)}`, textOrPlaceholder(result.detail)];
  const summary = el("div", `banner ${variant} ir-rehearsal__banner`);
  const body = el("div", "ir-rehearsal__banner-body");
  const heading = el("div", "ir-rehearsal__banner-title");
  heading.append(el("strong", null, title), badge(DEMO_LABEL, "status-badge--warning"));
  body.append(heading, el("span", null, `Scenario: ${DEMO_SCENARIO}.`), el("span", null, text));
  if (last.seconds !== null) {
    body.append(el("span", "ir-rehearsal__time", `Finished in ${last.seconds.toFixed(1)} s`));
  }
  summary.append(body);
  const fixTrace = stepsById(result).get("issue.fix")?.trace_id;
  if (fixTrace && onOpenTrace) summary.append(traceButton(fixTrace, "View in Observability →"));
  dom.rehearsalSummary.replaceChildren(summary);

  renderEvidence(result, demoRuns.resolve?.fixTrace || null);

  dom.rehearsalStages.replaceChildren();
  stages.forEach((stage, index) => {
    const row = el("li", "ir-stage");
    row.dataset.state = stage.state;
    row.append(
      el("span", "ir-stage__number", String(index + 1)),
      el("span", "ir-stage__label", stage.label),
      badge(STAGE_LABELS[stage.state], STAGE_BADGES[stage.state]),
    );
    const detail = el("div", "ir-stage__detail");
    detail.append(el("span", null, stage.detail || "—"));
    if (stage.key === "create" && stage.state !== "pending") {
      detail.append(el("span", "ir-stage__note", `${DEMO_LABEL} (${DEMO_SCENARIO}).`));
    }
    if (stage.key === "explain" && stage.state === "done" && resolutions[DISMOUNTED]) {
      detail.append(el("span", "ir-stage__note", `Catalog: ${resolutions[DISMOUNTED].explanation}`));
    }
    if (stage.key === "observe" && onOpenTrace) {
      const links = el("span", "ir-stage__links");
      for (const step of stage.traces) {
        links.append(traceButton(step.trace_id, `${textOrPlaceholder(step.operation_name)} ${String(step.trace_id).slice(0, 8)} →`));
      }
      if (links.childElementCount) detail.append(links);
    } else if (stage.traceId && onOpenTrace) {
      detail.append(traceButton(stage.traceId, "View trace →"));
    }
    row.append(detail);
    dom.rehearsalStages.append(row);
  });
}

// Opens the confirmation box for one step ("create" or "resolve"), or closes it.
function showRehearsalConfirm(show, step = null) {
  pendingStep = show ? step : null;
  dom.rehearsalConfirm.hidden = !show;
  dom.rehearsalAck.checked = false;
  dom.rehearsalRun.disabled = true;
  if (!show) return;
  const texts = DEMO_STEPS[step];
  dom.rehearsalWarning.textContent = texts.warning;
  dom.rehearsalAckText.textContent = texts.ack;
  dom.rehearsalRun.textContent = texts.confirm;
  dom.rehearsalAck.focus();
}

// The recorded trace of the rehearsal's fix (read-only; null if unavailable).
async function readFixTrace(result) {
  const traceId = stepsById(result).get("issue.fix")?.trace_id;
  if (!traceId) return null;
  try {
    const response = await IrisApi.getExecutionTraces();
    return (response?.traces || []).find((trace) => trace.trace_id === traceId) || null;
  } catch {
    return null;  // the evidence falls back to the step results
  }
}

// Only called from the Confirm button, after the checkbox, for the step the
// confirmation box was opened for.
async function runRehearsal() {
  if (rehearsalRunning || !dom.rehearsalAck.checked || !viewedInstance().primary) return;
  const step = pendingStep;
  if (!DEMO_STEPS[step]) return;
  showRehearsalConfirm(false);
  dom.rehearsalError.hidden = true;
  dom.rehearsalRunningText.textContent = DEMO_STEPS[step].running;
  rehearsalRunning = true;
  renderRehearsal();
  const started = performance.now();
  try {
    const result = await IrisApi.runDemoRehearsal(true, DEMO_STEPS[step].scenario);
    const seconds = (performance.now() - started) / 1000;
    const fixTrace = step === "resolve" ? await readFixTrace(result) : null;
    if (step === "create") demoRuns.resolve = null;  // a new demo cycle
    demoRuns[step] = { result, seconds, fixTrace };
    lastStep = step;
  } catch (err) {
    dom.rehearsalErrorText.textContent =
      err instanceof ApiError && err.status === 409
        ? "Another rehearsal or demo issue is already running. Wait for it to finish, then try again."
        : `Could not ${step} the demo issue. The Command Center backend may be unreachable.`;
    dom.rehearsalError.hidden = false;
  } finally {
    rehearsalRunning = false;
    renderRehearsal();
    // Issues and traces changed; refresh this page and the trace views.
    loadIssueResolver();
    if (onRehearsalFinished) onRehearsalFinished();
  }
}

/** Load GET /api/iris/issues and render the page. */
export async function loadIssueResolver() {
  setLoading(true);
  setErrorBanner(null);
  const viewed = viewedInstance();
  try {
    const response = await IrisApi.getIssues(selectedInstanceId());
    activeIssues = Array.isArray(response?.issues) ? response.issues : [];
    resolutions = response?.resolutions && typeof response.resolutions === "object" ? response.resolutions : {};
    issueCorrelations = Array.isArray(response?.correlations) ? response.correlations : [];
    dom.updated.textContent = `${new Date().toLocaleString()} · ${viewed.name}`;
    const unavailable = Array.isArray(response?.issue_checks_unavailable) ? response.issue_checks_unavailable : [];
    if (unavailable.length) {
      const names = unavailable.map((kind) => resolutions[kind]?.title || kind).join(", ");
      setErrorBanner(`Some issue checks couldn't run because IRIS data couldn't be read: ${names}.`);
    }
  } catch {
    activeIssues = [];
    resolutions = {};
    issueCorrelations = [];
    setErrorBanner(viewed.primary
      ? "Could not check for issues right now. The Command Center backend may be unreachable."
      : `Could not check ${viewed.name} for issues right now. The instance may be unreachable; no other instance's issues are shown.`);
  }
  closeDrawer();
  renderKpis();
  renderIssues();
  renderCatalog();
  renderRehearsal();
  await loadRules();
  setLoading(false);
}

// --- Custom Issue Rules (V1): detection-only rules the user defines ---
//
// The form only offers the backend's fixed vocabulary (signals, operators,
// pages from GET /api/iris/issue-rules); the backend validates every field
// again and checks the Manage privilege. Rules never run anything.

let ruleOptions = null;  // { signals, operators, pages, max_rules, persisted_to_iris }
let customRules = [];
let pendingDeleteRule = null;  // the rule whose inline "Confirm delete" is showing

function setRulesError(message) {
  dom.rulesError.hidden = !message;
  dom.rulesErrorText.textContent = message || "";
}

function fillSelect(select, options) {
  const current = select.value;
  select.replaceChildren(...options.map(([value, label]) => {
    const option = el("option", null, label);
    option.value = value;
    return option;
  }));
  if (options.some(([value]) => value === current)) select.value = current;
}

function ruleSignal(key) {
  return (ruleOptions?.signals || []).find((s) => s.key === key);
}

function ruleCondition(rule) {
  const signal = ruleSignal(rule.signal);
  return `${signal ? signal.label : rule.signal} ${rule.operator} ${rule.value}${signal && signal.unit ? ` ${signal.unit}` : ""}`;
}

async function loadRules() {
  try {
    const response = await IrisApi.getIssueRules();
    ruleOptions = response;
    customRules = Array.isArray(response?.rules) ? response.rules : [];
    fillSelect(dom.ruleSignal, (response.signals || []).map((s) => [s.key, `${s.label} (${s.field})`]));
    fillSelect(dom.ruleOperator, (response.operators || []).map((op) => [op, op]));
    fillSelect(dom.rulePage, (response.pages || []).map((p) => [p.key, p.label]));
    setRulesError(null);
  } catch {
    ruleOptions = null;
    customRules = [];
    setRulesError("Could not load custom issue rules. The Command Center backend may be unreachable.");
  }
  renderRules();
}

function renderRules() {
  const { primary } = viewedInstance();
  dom.rulesAdd.disabled = !primary || !ruleOptions || customRules.length >= (ruleOptions.max_rules || 0);
  dom.rulesPrimaryNote.hidden = primary;
  if (!primary && !dom.ruleForm.hidden) showRuleForm(false);  // no rule changes for another instance
  if (!primary) pendingDeleteRule = null;
  dom.rulesStorage.textContent = !ruleOptions ? "" : `${customRules.length} of ${ruleOptions.max_rules} rules. ` + (
    ruleOptions.persisted_to_iris
      ? "Rules are saved in IRIS (^CommandCenterIssueRule) and survive a backend restart."
      : "Rules are kept in memory only and are lost when the backend restarts (PERSIST_ISSUE_RULES_TO_IRIS is off)."
  );
  dom.rulesWrapper.hidden = customRules.length === 0;
  dom.rulesEmpty.hidden = customRules.length !== 0 || !ruleOptions;
  dom.rulesBody.replaceChildren(...customRules.map((rule) => {
    const row = el("tr");
    row.dataset.rule = rule.name;
    const cell = (content, className = "data-table__cell") => {
      const td = el("td", className);
      if (content instanceof Node) td.append(content);
      else td.textContent = textOrPlaceholder(content);
      return td;
    };
    const signal = ruleSignal(rule.signal);
    const detected = detectedCount(`custom:${rule.name}`) > 0;
    const status = el("span", `ir-rule-status${detected ? " ir-rule-status--detected" : ""}`,
      detected ? "Detected" : "Not detected");
    const actions = el("span", "btn-row");
    if (pendingDeleteRule === rule.name) {
      const yes = el("button", "btn btn--warning", "Confirm delete");
      yes.type = "button";
      yes.dataset.action = "delete-confirm";
      const no = el("button", "btn", "Cancel");
      no.type = "button";
      no.dataset.action = "delete-cancel";
      actions.append(yes, no);
    } else {
      const remove = el("button", "btn ir-danger-btn", "Delete");
      remove.type = "button";
      remove.dataset.action = "delete";
      remove.disabled = !primary;
      if (!primary) remove.title = "Rules can be deleted with the Primary instance selected.";
      remove.setAttribute("aria-label", `Delete rule ${rule.name}`);
      actions.append(remove);
    }
    row.append(
      cell(rule.name, "data-table__cell data-table__cell--mono"),
      cell(rule.title),
      cell(signal ? signal.label : rule.signal),
      cell(`${rule.operator} ${rule.value}${signal && signal.unit ? ` ${signal.unit}` : ""}`, "data-table__cell data-table__cell--mono"),
      cell(badge("Detection-only", "ir-badge--detection")),
      cell(status),
      cell(pageLabel(rule.investigation_page)),
      cell(actions),
    );
    return row;
  }));
}

function showRuleForm(show) {
  dom.ruleForm.hidden = !show;
  dom.rulesAdd.hidden = show;
  if (show) {
    dom.ruleForm.reset();
    dom.ruleName.focus();
  }
}

// Only reached from the form's submit; the backend validates everything again.
async function submitRule(event) {
  event.preventDefault();
  if (!viewedInstance().primary) return;
  if (dom.ruleValue.value.trim() === "" || !Number.isFinite(Number(dom.ruleValue.value))) {
    setRulesError("Value must be a number.");
    return;
  }
  const rule = {
    name: dom.ruleName.value.trim(),
    title: dom.ruleTitle.value.trim(),
    severity: dom.ruleSeverity.value,
    signal: dom.ruleSignal.value,
    operator: dom.ruleOperator.value,
    value: Number(dom.ruleValue.value),
    investigation_page: dom.rulePage.value,
    guidance: dom.ruleGuidance.value.trim(),
  };
  dom.ruleSubmit.disabled = true;
  try {
    const result = await IrisApi.createIssueRule(rule);
    showRuleForm(false);
    setRulesError(result && result.persisted === false && ruleOptions?.persisted_to_iris
      ? "The rule was created but couldn't be saved to IRIS; it will be lost when the backend restarts."
      : null);
    await loadIssueResolver();  // evaluate it with the other checks
  } catch (err) {
    setRulesError(err instanceof ApiError ? err.message : "Could not create the rule.");
  } finally {
    dom.ruleSubmit.disabled = false;
  }
}

// Only reached from a rule's inline "Confirm delete" button.
async function deleteRule(name) {
  pendingDeleteRule = null;
  try {
    await IrisApi.deleteIssueRule(name);
    setRulesError(null);
    await loadIssueResolver();
  } catch (err) {
    setRulesError(err instanceof ApiError ? err.message : "Could not delete the rule.");
    renderRules();
  }
}

function handleRulesClick(event) {
  const button = event.target.closest("button[data-action]");
  const row = event.target.closest("tr[data-rule]");
  if (!button || !row) return;
  const name = row.dataset.rule;
  if (button.dataset.action === "delete") pendingDeleteRule = name;
  else if (button.dataset.action === "delete-cancel") pendingDeleteRule = null;
  else if (button.dataset.action === "delete-confirm" && pendingDeleteRule === name) {
    deleteRule(name);
    return;
  }
  renderRules();
}

/**
 * Wired by app.js: `onOpenDatabases(issue)` goes to Resolve Issues on the
 * Databases page, `onOpenWebApps(issue)` opens the issue's web application
 * on the Web Apps page, `onOpenOperations(issue)` opens the journal action on
 * the Operations page, `onInvestigate(page)` opens the page a detection-only
 * issue is investigated on, `onOpenTrace(id)` opens a trace in Observability,
 * and `onRehearsalFinished()` refreshes the other pages that show traces.
 */
export function initIssueResolverControls({
  onOpenDatabases: openDatabases,
  onOpenWebApps: openWebApps,
  onOpenOperations: openOperations,
  onInvestigate: investigate,
  onOpenTrace: openTrace,
  onRehearsalFinished: finished,
} = {}) {
  onOpenDatabases = typeof openDatabases === "function" ? openDatabases : null;
  onOpenWebApps = typeof openWebApps === "function" ? openWebApps : null;
  onOpenOperations = typeof openOperations === "function" ? openOperations : null;
  onInvestigate = typeof investigate === "function" ? investigate : null;
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;
  onRehearsalFinished = typeof finished === "function" ? finished : null;
  dom.openDatabasesButton.hidden = true;  // set per issue when the drawer opens

  dom.rehearsalStart.addEventListener("click", () => showRehearsalConfirm(true, "create"));
  dom.demoResolve.addEventListener("click", () => showRehearsalConfirm(true, "resolve"));
  dom.rehearsalCancel.addEventListener("click", () => showRehearsalConfirm(false));
  dom.rehearsalAck.addEventListener("change", () => {
    dom.rehearsalRun.disabled = !dom.rehearsalAck.checked;
  });
  dom.rehearsalRun.addEventListener("click", () => {
    runRehearsal();
  });
  renderRehearsal();

  dom.refreshButton.addEventListener("click", () => {
    loadIssueResolver();
  });
  // In-page tabs: jump to a section and mark it current. All sections stay visible.
  dom.tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      dom.tabs.forEach((other) => other.removeAttribute("aria-current"));
      tab.setAttribute("aria-current", "true");
      document.getElementById(tab.dataset.irTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  dom.rulesAdd.addEventListener("click", () => showRuleForm(true));
  dom.ruleCancel.addEventListener("click", () => showRuleForm(false));
  dom.ruleForm.addEventListener("submit", submitRule);
  dom.rulesBody.addEventListener("click", handleRulesClick);
  dom.catalogBody.addEventListener("click", (event) => {
    const row = event.target.closest("tr[data-issue-type]");
    if (row) openCatalogEntry(row.dataset.issueType);
  });
  dom.catalogBody.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest("tr[data-issue-type]");
    if (!row) return;
    event.preventDefault();
    openCatalogEntry(row.dataset.issueType);
  });
  dom.list.addEventListener("click", (event) => {
    if (runCardAction(event)) return;
    const card = event.target.closest(".ir-issue");
    if (card) openDrawer(Number(card.dataset.index));
  });
  dom.list.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    if (event.target.closest(".ir-issue__action")) return;  // the button handles its own keys
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
    const issue = drawerIssue;
    const open = resolveHandler(issue);
    closeDrawer();
    if (open) open(issue);
  });
}
