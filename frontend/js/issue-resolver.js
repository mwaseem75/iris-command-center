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

import { ApiError, IrisApi } from "./api.js";

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
  drawerHint: document.getElementById("issue-resolver-drawer-hint"),
  rehearsalStart: document.getElementById("issue-resolver-rehearsal-start"),
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
let onOpenDatabases = null;
let onOpenWebApps = null;
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
    page: "web-apps",
    action: "Resolve in Web Apps →",
    hint: "Read-only. Resolving runs through the web application's Enabled State on the Web Apps page.",
  },
};

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

function resourceOf(issue) {
  return RESOURCES[issue?.kind] || UNKNOWN_RESOURCE;
}

// The app.js callback that opens the page where this issue is resolved.
function resolveHandler(issue) {
  const page = resourceOf(issue).page;
  if (page === "databases") return onOpenDatabases;
  if (page === "web-apps") return onOpenWebApps;
  return null;
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
  const res = resourceOf(issue);
  card.setAttribute("aria-label", `View resolution for ${textOrPlaceholder(res.name(issue))}`);

  const head = el("div", "ir-issue__head");
  head.append(
    resolution ? severityBadge(resolution.severity) : badge("Unknown", "status-badge--neutral"),
    el("span", "ir-issue__title", resolution ? resolution.title : textOrPlaceholder(issue.kind)),
    badge(textOrPlaceholder(res.status(issue)), "status-badge--neutral"),
  );

  const resource = el("p", "ir-issue__resource");
  resource.append(el("strong", null, textOrPlaceholder(res.name(issue))), document.createTextNode(" · "),
    el("span", "ir-mono", textOrPlaceholder(res.detail(issue))));

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

  card.append(head, resource, meta);
  if (Array.isArray(issue.affected_namespaces) && issue.affected_namespaces.length) {
    card.append(el("p", "ir-issue__privilege",
      `Affects namespaces: ${issue.affected_namespaces.map((a) => a.namespace).join(", ")}`));
  }
  card.append(el("span", "stat-card__link", "View resolution →"));
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

  const res = resourceOf(issue);
  drawerIssue = issue;
  dom.drawerTitle.textContent = `${textOrPlaceholder(res.name(issue))} · ${resolution ? resolution.title : textOrPlaceholder(issue.kind)}`;
  dom.drawerHint.textContent = res.hint;
  dom.openDatabasesButton.textContent = res.action;
  dom.openDatabasesButton.hidden = !resolveHandler(issue);
  const severity = resolution ? resolution.severity : null;
  dom.drawerSeverity.className = `status-badge ${SEVERITY_BADGES[severity] || "status-badge--neutral"}`;
  dom.drawerSeverity.textContent = severity ? capitalize(severity) : "Unknown";

  const summary = section("Issue", infoList([
    ["Issue type", issue.kind, { mono: true }],
    ...res.rows(issue),
  ]));

  if (!resolution) {
    dom.drawerBody.replaceChildren(summary, el("p", "empty-state", "No catalog entry for this issue type."));
  } else {
    dom.drawerBody.replaceChildren(
      summary,
      section("Live evidence", evidenceTable(issue, resolution)),
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

  const wasHidden = dom.drawer.hidden;
  dom.drawerBackdrop.hidden = false;
  dom.drawer.hidden = false;
  if (wasHidden) dom.drawerClose.focus();
}

function closeDrawer() {
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
  dom.rehearsalStart.disabled = rehearsalRunning || issueActive;
  dom.rehearsalStart.title = issueActive ? "The IPM demo issue is already active. Resolve it first." : "";
  dom.demoResolve.disabled = rehearsalRunning || !issueActive;
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
  if (rehearsalRunning || !dom.rehearsalAck.checked) return;
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
  try {
    const response = await IrisApi.getIssues();
    activeIssues = Array.isArray(response?.issues) ? response.issues : [];
    resolutions = response?.resolutions && typeof response.resolutions === "object" ? response.resolutions : {};
    const unavailable = Array.isArray(response?.issue_checks_unavailable) ? response.issue_checks_unavailable : [];
    if (unavailable.length) {
      const names = unavailable.map((kind) => resolutions[kind]?.title || kind).join(", ");
      setErrorBanner(`Some issue checks couldn't run because IRIS data couldn't be read: ${names}.`);
    }
  } catch {
    activeIssues = [];
    resolutions = {};
    setErrorBanner("Could not check for issues right now. The Command Center backend may be unreachable.");
  }
  closeDrawer();
  renderKpis();
  renderIssues();
  renderCatalog();
  renderRehearsal();
  setLoading(false);
}

/**
 * Wired by app.js: `onOpenDatabases(issue)` goes to Resolve Issues on the
 * Databases page, `onOpenWebApps(issue)` opens the issue's web application
 * on the Web Apps page, `onOpenTrace(id)` opens a trace in Observability,
 * and `onRehearsalFinished()` refreshes the other pages that show traces.
 */
export function initIssueResolverControls({
  onOpenDatabases: openDatabases,
  onOpenWebApps: openWebApps,
  onOpenTrace: openTrace,
  onRehearsalFinished: finished,
} = {}) {
  onOpenDatabases = typeof openDatabases === "function" ? openDatabases : null;
  onOpenWebApps = typeof openWebApps === "function" ? openWebApps : null;
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
    const issue = drawerIssue;
    const open = resolveHandler(issue);
    closeDrawer();
    if (open) open(issue);
  });
}
