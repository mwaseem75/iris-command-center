import { IrisApi, ApiError } from "./api.js";
import { getInstanceContext, onInstanceContextChange } from "./instance-context.js";

const $ = (id) => document.getElementById(id);

const dom = {
  refresh: $("health-center-refresh-button"),
  error: $("health-center-error"),
  errorText: $("health-center-error-text"),
  loading: $("health-center-loading"),
  content: $("health-center-content"),
  generated: $("health-center-generated"),
  activityTime: $("health-center-activity-time"),
  activityMetrics: $("health-center-activity-metrics"),
  activityUnavailable: $("health-center-activity-unavailable"),
  coverageRing: $("health-center-coverage-ring"),
  coverageFraction: $("health-center-coverage-fraction"),
  coverage: $("health-center-coverage"),
  assessedScore: $("health-center-assessed-score"),
  status: $("health-center-status"),
  summary: $("health-center-summary"),
  instance: $("health-center-instance"),
  categories: $("health-center-categories"),
  apis: $("health-center-apis"),
  findingsSection: $("health-center-findings-section"),
  findings: $("health-center-findings"),
  findingsEmpty: $("health-center-findings-empty"),
  recommendationsSection: $("health-center-recommendations-section"),
  recommendations: $("health-center-recommendations"),
  unavailableSection: $("health-center-unavailable-section"),
  unavailable: $("health-center-unavailable"),
  view: $("view-health-center"),
  titleScope: $("health-center-title-scope"),
  context: $("health-center-context"),
  contextName: $("health-center-context-name"),
  contextMeta: $("health-center-context-meta"),
  loadingText: $("health-center-loading-text"),
};

// Bumped on every load, so a slower response for an earlier context is ignored.
let loadToken = 0;
let contextKey = null;

const STATUS_BADGES = {
  healthy: "status-badge--ok",
  warning: "status-badge--warning",
  critical: "status-badge--error",
  partial: "status-badge--warning",
  unavailable: "status-badge--neutral",
  not_assessed: "status-badge--neutral",
  low: "status-badge--neutral",
  medium: "status-badge--warning",
  high: "status-badge--error",
};

const CATEGORY_ICONS = {
  performance: "▥",
  tasks: "↻",
  databases: "▤",
  security: "◈",
  "web-applications": "⌘",
  system: "⚙",
};

const CATEGORY_NAMES = {
  tasks: "Tasks & Schedules",
  system: "System & OS",
};

const EVIDENCE_LABELS = {
  GlobalRefsPerSecond: "Global references / sec",
  CacheEfficiency: "Cache efficiency",
  GlobalRefs: "Global references",
  DiskReads: "Disk reads",
  DiskWrites: "Disk writes",
  LogicalRequests: "Logical requests",
  task_manager_not_running: "Task manager",
  database_dismounted: "Database mounts",
  database_full: "Database capacity",
  web_app_namespace_missing: "Web application namespace",
  journal_purge_archived_off: "Journal archive purge",
  system_monitor_not_running: "System monitor",
  audit_status: "Audit status",
  Enabled: "Audit enabled",
  Full: "IRIS full flag",
  "Size, MaxSize": "Database size / maximum size",
};

const API_SOURCES = [
  { method: "GET", path: "/info", purpose: "IRIS version, product and namespace list", categories: [], info: true },
  { method: "GET", path: "/v2/databases", purpose: "Database names and mount configuration", categories: ["databases"] },
  { method: "GET", path: "/v2/database-dirs", purpose: "Database directory mount and storage status", categories: ["databases"] },
  {
    method: "POST",
    path: "/v2/database-dir/info",
    purpose: "Reads each mounted database's Full flag through the existing async task",
    categories: ["databases"],
    conditional: true,
  },
  { method: "GET", path: "/v2/task/manager", purpose: "Task Manager state", categories: ["tasks"] },
  { method: "GET", path: "/v2/web-apps", purpose: "Enabled web application configuration", categories: ["web-applications"] },
  {
    method: "GET",
    path: "/v2/namespaces",
    purpose: "Namespace checks for database and web application findings",
    categories: ["databases", "web-applications"],
    conditional: true,
  },
  { method: "GET", path: "/v2/journal/settings", purpose: "Journal archive and purge settings", categories: ["system"] },
  {
    method: "GET",
    path: "/v2/monitor/dashboard/main",
    purpose: "System Monitor check, configured rule signals, and current activity values",
    categories: ["system", "performance"],
  },
  { method: "GET", path: "/v2/processes", purpose: "System Monitor check and current process snapshot", categories: ["system"] },
  { method: "GET", path: "/v2/security/audit/enabled", purpose: "IRIS audit enabled status", categories: ["security"] },
];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusBadge(status) {
  const label = status ? status.replace(/_/g, " ") : "Unknown";
  return el("span", `status-badge ${STATUS_BADGES[status] || "status-badge--neutral"}`, label);
}

function evidenceLabel(field) {
  return EVIDENCE_LABELS[field] || field.replace(/_/g, " ");
}

function evidenceValue(item) {
  if (item.value_status === "unknown") return "Unknown";
  if (item.value_status === "not_applicable") return "Not applicable";
  if (item.observed_value === null || item.observed_value === undefined) return "Unknown";
  if (item.observed_value === "not reported") return "No issue detected";
  if (typeof item.observed_value === "object") return JSON.stringify(item.observed_value);
  return String(item.observed_value);
}

function renderEvidenceRow(item) {
  const row = el("div", "health-center__evidence-row");
  row.append(el("dt", "", evidenceLabel(item.field)));
  row.append(el("dd", "", evidenceValue(item)));

  const details = el("details", "health-center__technical-details");
  details.append(el("summary", "", "Technical details"));
  details.append(el("p", "", `${item.source} · ${item.condition}`));
  row.append(details);
  return row;
}

function renderEvidence(items, limit = 4) {
  if (!items.length) return null;

  const list = el("dl", "health-center__evidence-list");
  items.slice(0, limit).forEach((item) => list.append(renderEvidenceRow(item)));
  if (items.length > limit) {
    const details = el("details", "health-center__more-evidence");
    details.append(el("summary", "", `View ${items.length - limit} more checks`));
    const extra = el("dl", "health-center__evidence-list");
    items.slice(limit).forEach((item) => extra.append(renderEvidenceRow(item)));
    details.append(extra);
    list.append(details);
  }
  return list;
}

function categorySummary(category, hasPerformanceSnapshot = false) {
  if (category.score === null) {
    if (category.id === "performance" && hasPerformanceSnapshot) {
      return "Informational snapshot available; no performance condition assessed.";
    }
    if (category.status === "not_assessed") return "Not assessed in this health check.";
    if (category.status === "partial") {
      return `${category.checks_completed} of ${category.checks_total} checks completed; assessment is partial.`;
    }
    if (category.status === "unavailable") return "Assessment data is unavailable.";
  }
  if (category.status === "healthy") {
    return `${category.checks_completed} ${category.checks_completed === 1 ? "check" : "checks"} completed; no issues reported.`;
  }
  if (category.status === "critical") {
    return `${category.findings.length} critical ${category.findings.length === 1 ? "finding" : "findings"} reported.`;
  }
  if (category.status === "warning") {
    return `${category.findings.length} ${category.findings.length === 1 ? "finding" : "findings"} need attention.`;
  }
  return `${category.checks_completed} of ${category.checks_total} checks completed.`;
}

function performanceEvidence(performance, fields, condition) {
  const source = "GET /v2/monitor/dashboard/main";
  return fields
    .filter(([field]) => typeof performance?.[field] === "number" && Number.isFinite(performance[field]))
    .map(([field]) => ({
      field,
      observed_value: performance[field],
      value_status: "observed",
      source,
      condition,
    }));
}

function renderPerformanceSnapshot(performance) {
  const current = performanceEvidence(
    performance,
    [["GlobalRefsPerSecond"], ["CacheEfficiency"]],
    "IRIS-reported dashboard value; no health threshold is applied.",
  );
  const cumulative = performanceEvidence(
    performance,
    [["GlobalRefs"], ["DiskReads"], ["DiskWrites"], ["LogicalRequests"]],
    "Cumulative counter since IRIS startup; not a rate.",
  );
  if (current.length === 0 && cumulative.length === 0) return null;

  const details = el("details", "health-center__technical-details");
  details.append(el("summary", "", "View Performance Snapshot"));
  details.append(el(
    "p",
    "",
    "Observed Dashboard values only. Cumulative counters are totals since startup and are not converted to rates.",
  ));
  if (current.length) {
    details.append(el("strong", "", "Current rate and reported efficiency"));
    details.append(renderEvidence(current));
  }
  if (cumulative.length) {
    details.append(el("strong", "", "Cumulative since startup"));
    details.append(renderEvidence(cumulative));
  }
  return details;
}

function renderCategory(category, monitorPerformance) {
  const card = el("article", "info-card health-center__category");
  card.dataset.status = category.status;
  const snapshot = category.id === "performance"
    ? renderPerformanceSnapshot(monitorPerformance)
    : null;

  const header = el("div", "health-center__category-header");
  const title = el("h4", "health-center__category-title");
  title.append(
    el("span", "health-center__category-icon", CATEGORY_ICONS[category.id] || "•"),
    document.createTextNode(CATEGORY_NAMES[category.id] || category.name),
  );
  header.append(title, statusBadge(category.status));

  card.append(header, el("p", "health-center__category-summary", categorySummary(category, Boolean(snapshot))));
  const evidence = renderEvidence(category.evidence || []);
  if (evidence) card.append(evidence);
  if (snapshot) card.append(snapshot);

  const unavailable = category.unavailable_sources || [];
  if (unavailable.length) {
    const details = el("details", "health-center__technical-details");
    details.append(el("summary", "", `${unavailable.length} unavailable check${unavailable.length === 1 ? "" : "s"}`));
    for (const source of unavailable) {
      const entry = el("p", "");
      entry.append(
        el("strong", "", evidenceLabel(source.check_id)),
        document.createTextNode(` — ${source.reason} (${source.source})`),
      );
      details.append(entry);
    }
    card.append(details);
  }

  return card;
}

function renderSummary(categories) {
  const counts = {
    healthy: categories.filter((item) => item.status === "healthy").length,
    attention: categories.filter((item) => ["warning", "partial"].includes(item.status)).length,
    critical: categories.filter((item) => item.status === "critical").length,
    notAssessed: categories.filter((item) => ["not_assessed", "unavailable"].includes(item.status)).length,
  };
  const items = [
    ["Healthy", counts.healthy, "ok"],
    ["Needs Attention", counts.attention, "warning"],
    ["Critical", counts.critical, "error"],
    ["Not Assessed", counts.notAssessed, "neutral"],
  ];
  dom.summary.replaceChildren(...items.map(([label, count, variant]) => {
    const item = el("div", `health-center__summary-item health-center__summary-item--${variant}`);
    item.append(el("span", "health-center__summary-count", String(count)), el("span", "health-center__summary-label", label));
    return item;
  }));
}

function renderInstance(info) {
  dom.instance.replaceChildren();
  if (!info || !info.result) {
    dom.instance.append(el("p", "health-center__instance-empty", "Instance information could not be loaded."));
    return;
  }

  const result = info.result;
  const values = [
    ["Version", result.serverVersion],
    ["Product", result.product],
    ["API version", result.apiVersion],
    ["System mode", result.systemMode],
    ["Namespaces", Array.isArray(result.namespaces) ? result.namespaces.map((item) => item.name).join(", ") : null],
  ].filter(([, value]) => value !== null && value !== undefined && value !== "");

  for (const [label, value] of values) {
    const row = el("div", "health-center__instance-row");
    row.append(el("dt", "", label), el("dd", "", String(value)));
    dom.instance.append(row);
  }
}

function renderActivityMetric(label, value, detail) {
  const card = el("article", "health-center__activity-metric");
  card.append(
    el("p", "health-center__activity-label", label),
    el("p", "health-center__activity-value", value),
    el("p", "health-center__activity-detail", detail),
  );
  return card;
}

function renderCurrentActivity(monitorResponse, processesResponse, observedAt) {
  const dashboard = monitorResponse?.result;
  const usage = dashboard?.SystemUsage;
  const performance = dashboard?.Performance;
  const processes = Array.isArray(processesResponse?.result) ? processesResponse.result : null;
  const busyProcesses = Array.isArray(usage?.BusyProcesses)
    ? usage.BusyProcesses.filter((item) => typeof item.Process === "number"
      || (typeof item.Process === "string" && item.Process.trim() !== "")).length
    : null;
  const monitorProcess = processes?.find(
    (item) => typeof item.Routine === "string"
      && item.Routine.startsWith("%SYS.Monitor.Control")
      && item.Nspace === "%SYS",
  );
  const number = (value) => typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "Unavailable";
  const metrics = [
    renderActivityMetric(
      "Global references / sec",
      number(performance?.GlobalRefsPerSecond),
      dashboard ? "IRIS-reported current rate" : "Monitor dashboard unavailable",
    ),
    renderActivityMetric(
      "Cache efficiency",
      typeof performance?.CacheEfficiency === "number" && Number.isFinite(performance.CacheEfficiency)
        ? `${performance.CacheEfficiency.toLocaleString()}%`
        : "Unavailable",
      dashboard ? "IRIS-reported value" : "Monitor dashboard unavailable",
    ),
    renderActivityMetric(
      "Process count",
      processes ? number(processes.length) : "Unavailable",
      processes ? "Processes in the current API snapshot" : "Process list unavailable",
    ),
    renderActivityMetric(
      "Busy processes listed",
      busyProcesses === null ? "Unavailable" : number(busyProcesses),
      dashboard ? "Populated entries in the IRIS dashboard list" : "Monitor dashboard unavailable",
    ),
    renderActivityMetric(
      "CSP sessions",
      number(usage?.CSPSessions),
      dashboard ? "IRIS-reported current session count" : "Monitor dashboard unavailable",
    ),
    renderActivityMetric(
      "System Monitor process",
      processes ? (monitorProcess ? "Running" : "Not found") : "Unavailable",
      processes ? "Based on the %SYS.Monitor.Control process in %SYS" : "Process list unavailable",
    ),
  ];
  dom.activityMetrics.replaceChildren(...metrics);
  dom.activityTime.textContent = `As of ${observedAt.toLocaleString()} (responses received)`;

  const unavailable = [];
  if (!dashboard) unavailable.push("monitor dashboard");
  if (!processes) unavailable.push("process list");
  dom.activityUnavailable.textContent = unavailable.length
    ? `Current Activity is incomplete: ${unavailable.join(" and ")} could not be read.`
    : "";
  dom.activityUnavailable.hidden = unavailable.length === 0;
}

function apiUnavailable(api, unavailable) {
  return unavailable.some((item) => item.source.includes(`${api.method} ${api.path}`));
}

function renderApis(report, infoAvailable) {
  const unavailable = report.unavailable_sources || [];
  dom.apis.replaceChildren(...API_SOURCES.map((api) => {
    const row = el("div", "health-center__api-row");
    const endpoint = el("code", "health-center__api-endpoint", `${api.method} ${api.path}`);
    row.append(endpoint, el("p", "health-center__api-purpose", api.purpose));

    if (api.info) {
      row.append(el(
        "span",
        `status-badge ${infoAvailable ? "status-badge--ok" : "status-badge--neutral"}`,
        infoAvailable ? "Responded" : "Unavailable",
      ));
      return row;
    }

    const failed = apiUnavailable(api, unavailable);
    const result = el("div", "health-center__api-results");
    if (api.conditional) result.append(statusBadge("conditional"));
    if (failed) {
      result.append(statusBadge("unavailable"));
    } else {
      for (const id of api.categories) {
        const category = report.categories.find((item) => item.id === id);
        if (category) {
          const badge = statusBadge(category.status);
          badge.textContent = `${CATEGORY_NAMES[category.id] || category.name}: ${category.status.replace(/_/g, " ")}`;
          badge.title = `${category.name} assessment result`;
          result.append(badge);
        }
      }
    }
    row.append(result);
    return row;
  }));
}

function renderFinding(finding) {
  const card = el("article", "health-center__finding");
  card.dataset.severity = finding.severity;
  const header = el("div", "health-center__finding-header");
  header.append(el("h4", "health-center__finding-title", finding.title), statusBadge(finding.severity));
  card.append(header, el("p", "health-center__finding-explanation", finding.explanation));
  if (finding.recommendation) {
    const recommendation = el("p", "health-center__finding-recommendation");
    recommendation.append(el("strong", "", "Recommendation: "), document.createTextNode(finding.recommendation));
    card.append(recommendation);
  }
  const evidence = renderEvidence(finding.evidence || [], 4);
  if (evidence) card.append(evidence);

  if (finding.check_id) {
    const details = el("details", "health-center__technical-details");
    details.append(el("summary", "", "Technical check identifier"));
    details.append(el("code", "", finding.check_id));
    card.append(details);
  }
  return card;
}

function renderUnavailable(source) {
  const item = el("article", "health-center__unavailable-item");
  item.append(
    el("h4", "health-center__unavailable-title", evidenceLabel(source.check_id)),
    el("p", "", source.reason),
  );
  const details = el("details", "health-center__technical-details");
  details.append(el("summary", "", "Source details"));
  details.append(el("code", "", source.source));
  details.append(el("p", "", `Check: ${source.check_id}`));
  item.append(details);
  return item;
}

function renderUnavailableSources(report) {
  const items = [...(report.unavailable_sources || [])];
  for (const category of report.categories) {
    if (category.score === null && category.status === "not_assessed") {
      items.push({
        category: category.id,
        check_id: category.id,
        source: "Health Center category assessment",
        reason: category.checks_total === 0
          ? "No checks were available for this category in the current report."
          : "This category did not receive an assessed score.",
      });
    }
    if (category.id === "security" && category.score === null && category.status !== "unavailable") {
      items.push({
        category: category.id,
        check_id: "security_baseline",
        source: "Health Center category assessment",
        reason: "No security baseline is configured; audit status is reported as evidence only.",
      });
    }
  }
  return items;
}

function renderReport(report, infoResult, monitorResponse) {
  const categories = report.categories || [];
  const assessed = categories.filter((category) => category.score !== null).length;
  const total = categories.length;
  const coveragePercent = total ? Math.round((assessed / total) * 100) : 0;

  dom.coverageFraction.textContent = `${assessed}/${total}`;
  dom.coverageRing.style.setProperty("--health-coverage", `${coveragePercent}%`);
  dom.coverageRing.setAttribute("aria-label", `${assessed} of ${total} categories assessed`);
  dom.coverage.textContent = `${assessed} of ${total} categories assessed`;
  dom.assessedScore.hidden = report.overall_score === null;
  dom.assessedScore.textContent = report.overall_score === null
    ? ""
    : `Assessed score: ${report.overall_score}`;
  dom.status.className = `status-badge ${STATUS_BADGES[report.status] || "status-badge--neutral"}`;
  dom.status.textContent = report.status.replace(/_/g, " ");
  dom.generated.textContent = report.generated_at
    ? `Last checked ${new Date(report.generated_at).toLocaleString()}`
    : "Last checked time unavailable";

  renderSummary(categories);
  renderInstance(infoResult);
  dom.categories.replaceChildren(...categories.map(
    (category) => renderCategory(category, monitorResponse?.result?.Performance),
  ));
  renderApis(report, Boolean(infoResult));

  const findings = report.findings || [];
  dom.findings.replaceChildren(...findings.map(renderFinding));
  dom.findingsEmpty.hidden = findings.length !== 0;
  dom.findingsSection.classList.toggle("health-center__findings-section--active", findings.length !== 0);

  const recommendations = report.recommendations || [];
  dom.recommendations.replaceChildren(...recommendations.map((item) => el("li", "", item.text)));
  dom.recommendationsSection.hidden = recommendations.length === 0;

  const unavailable = renderUnavailableSources(report);
  dom.unavailable.replaceChildren(...unavailable.map(renderUnavailable));
  dom.unavailableSection.hidden = unavailable.length === 0;
}

function keyOf(ctx) {
  return ctx.instanceId;
}

function describe(instance) {
  return instance.connection ? `${instance.name} (${instance.connection})` : instance.name;
}

function renderContext(ctx, info) {
  dom.titleScope.textContent = `· ${ctx.instance ? ctx.instance.name : ctx.instanceId}`;
  dom.context.hidden = false;
  dom.contextName.textContent = ctx.instance ? ctx.instance.name : ctx.instanceId;
  const meta = [ctx.instance && ctx.instance.connection];
  if (info && info.result) meta.push(info.result.serverVersion, `API v${info.result.apiVersion}`);
  dom.contextMeta.textContent = meta.filter(Boolean).join(" · ");
}

// Errors for an instance other than the Primary, without raw backend text.
function instanceError(ctx, error) {
  const where = ctx.instance ? describe(ctx.instance) : ctx.instanceId;
  const status = error instanceof ApiError ? error.status : undefined;
  if (status === 409) return `${where} is inactive. Activate it on the Instances screen, or choose another instance above.`;
  if (status === 404) return `${where} is no longer registered. Choose another instance above.`;
  if (status === null) return "Could not reach the Command Center backend.";
  return `Could not run the health check on ${where}. The instance may be unreachable or may have rejected its stored credentials.`;
}

export async function loadHealthCenter() {
  const ctx = getInstanceContext();
  const token = ++loadToken;
  contextKey = keyOf(ctx);
  const primary = Boolean(ctx.instance && ctx.instance.primary);
  renderContext(ctx, null);
  dom.loadingText.textContent = `Checking ${ctx.instance ? ctx.instance.name : "IRIS"} health…`;
  dom.loading.hidden = false;
  dom.content.hidden = true;
  dom.error.hidden = true;
  dom.generated.textContent = "";
  dom.refresh.disabled = true;

  try {
    const id = primary ? undefined : ctx.instanceId;
    const [reportResult, infoResult, monitorResult, processesResult] = await Promise.allSettled([
      IrisApi.getHealthReport(id),
      IrisApi.getInfo(id),
      IrisApi.getMonitorDashboard(id),
      IrisApi.getProcesses(id),
    ]);
    if (token !== loadToken) return;
    if (reportResult.status === "rejected") throw reportResult.reason;

    const info = infoResult.status === "fulfilled" ? infoResult.value : null;
    const monitor = monitorResult.status === "fulfilled" ? monitorResult.value : null;
    renderContext(getInstanceContext(), info);
    renderReport(reportResult.value, info, monitor);
    renderCurrentActivity(
      monitor,
      processesResult.status === "fulfilled" ? processesResult.value : null,
      new Date(),
    );
    dom.content.hidden = false;
  } catch (error) {
    if (token !== loadToken) return;
    dom.errorText.textContent = primary
      ? error.message || "Could not load the Health Center report."
      : instanceError(ctx, error);
    dom.error.hidden = false;
  } finally {
    if (token === loadToken) {
      dom.loading.hidden = true;
      dom.refresh.disabled = false;
    }
  }
}

export function initHealthCenterControls() {
  dom.refresh.addEventListener("click", loadHealthCenter);

  // A new instance in the instance selector: reload if the page is open,
  // otherwise just drop the old report (the page reloads when it's opened).
  contextKey = keyOf(getInstanceContext());
  onInstanceContextChange((ctx) => {
    if (keyOf(ctx) === contextKey) return;
    if (!dom.view.hidden) {
      loadHealthCenter();
    } else {
      contextKey = keyOf(ctx);
      loadToken += 1;  // a load still running is ignored
      dom.loading.hidden = true;
      dom.refresh.disabled = false;
      dom.content.hidden = true;
      dom.error.hidden = true;
      renderContext(ctx, null);
    }
  });
}
