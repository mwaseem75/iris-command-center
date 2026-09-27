// Issue Resolver page: active issues from GET /api/iris/issues, each
// explained with its entry from the Issue Resolution Catalog (the
// response's `resolutions`, keyed by issue kind).
//
// The page itself never changes IRIS: resolving happens through Resolve
// Issues on the Databases page. The one exception is the Issue Resolution
// Rehearsal panel, which runs the existing IPM rehearsal
// (POST /api/iris/demo/rehearsal, scenario "issue_resolution") only after an
// explicit Confirm & Run, and shows its real step results as a lifecycle:
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
  rehearsalStart: document.getElementById("issue-resolver-rehearsal-start"),
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
};

// The last response; the drawer reads from it.
let activeIssues = [];
let resolutions = {};
let onOpenDatabases = null;
let onOpenTrace = null;
let onRehearsalFinished = null;

// The last rehearsal: { result, seconds } or null. Kept across page reloads
// of the issue list.
let lastRehearsal = null;
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

// --- Issue Resolution Rehearsal ---

const DISMOUNTED = "database_dismounted";

// The lifecycle, and which of the rehearsal's own steps back each stage.
const LIFECYCLE = [
  { key: "create", label: "Create", sub: "Dismount IPM", steps: ["issue.read", "issue.dry_run", "issue.dismount"] },
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

const SUMMARY = {
  completed: ["banner--success", "Rehearsal completed",
    "The issue was created, detected, resolved and verified, and IPM is back to its original state."],
  stopped: ["banner--warning", "Rehearsal stopped", "A step didn't complete. See the step results below."],
  restore_failed: ["banner--error", "IPM could not be restored",
    "IPM may still be dismounted. Mount it from Resolve Issues on the Databases page."],
};

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
        } else if (verify?.status === "success" && steps.get("issue.read")?.status === "success") {
          state = "done";
          detail = `${target} was mounted before the rehearsal and is mounted again, so nothing is left to restore.`;
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
  const result = lastRehearsal?.result || null;
  const stages = lifecycleStages(result).map((stage) =>
    rehearsalRunning ? { ...stage, state: "waiting" } : result ? stage : { ...stage, state: "pending" });
  renderLifecycle(stages);

  dom.rehearsalRunning.hidden = !rehearsalRunning;
  dom.rehearsalStart.disabled = rehearsalRunning;
  dom.rehearsalSummary.hidden = rehearsalRunning || !result;
  dom.rehearsalResults.hidden = rehearsalRunning || !result;
  if (rehearsalRunning || !result) return;

  const [variant, title, text] = SUMMARY[result.status] ||
    ["banner--warning", `Rehearsal ${textOrPlaceholder(result.status)}`, textOrPlaceholder(result.detail)];
  const summary = el("div", `banner ${variant} ir-rehearsal__banner`);
  const body = el("div", "ir-rehearsal__banner-body");
  body.append(el("strong", null, title), el("span", null, text));
  if (lastRehearsal.seconds !== null) {
    body.append(el("span", "ir-rehearsal__time", `Finished in ${lastRehearsal.seconds.toFixed(1)} s`));
  }
  summary.append(body);
  const fixTrace = stepsById(result).get("issue.fix")?.trace_id;
  if (fixTrace && onOpenTrace) summary.append(traceButton(fixTrace, "View in Observability →"));
  dom.rehearsalSummary.replaceChildren(summary);

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

function showRehearsalConfirm(show) {
  dom.rehearsalConfirm.hidden = !show;
  dom.rehearsalAck.checked = false;
  dom.rehearsalRun.disabled = true;
  if (show) dom.rehearsalAck.focus();
}

// Only called from the Confirm & Run button, after the checkbox.
async function runRehearsal() {
  if (rehearsalRunning || !dom.rehearsalAck.checked) return;
  showRehearsalConfirm(false);
  dom.rehearsalError.hidden = true;
  rehearsalRunning = true;
  renderRehearsal();
  const started = performance.now();
  try {
    const result = await IrisApi.runDemoRehearsal(true, "issue_resolution");
    lastRehearsal = { result, seconds: (performance.now() - started) / 1000 };
  } catch (err) {
    dom.rehearsalErrorText.textContent =
      err instanceof ApiError && err.status === 409
        ? "Another rehearsal is already running. Wait for it to finish, then try again."
        : "Could not run the rehearsal. The Command Center backend may be unreachable.";
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
 * Wired by app.js: `onOpenDatabases()` goes to Resolve Issues on the
 * Databases page, `onOpenTrace(id)` opens a trace in Observability, and
 * `onRehearsalFinished()` refreshes the other pages that show traces.
 */
export function initIssueResolverControls({
  onOpenDatabases: openDatabases,
  onOpenTrace: openTrace,
  onRehearsalFinished: finished,
} = {}) {
  onOpenDatabases = typeof openDatabases === "function" ? openDatabases : null;
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;
  onRehearsalFinished = typeof finished === "function" ? finished : null;
  dom.openDatabasesButton.hidden = !onOpenDatabases;

  dom.rehearsalStart.addEventListener("click", () => showRehearsalConfirm(true));
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
    closeDrawer();
    if (onOpenDatabases) onOpenDatabases();
  });
}
