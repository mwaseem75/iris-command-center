// AI Assistant page. Read-only Copilot answers use the backend's bounded
// context and deterministic intent; local handlers remain as safe fallbacks.
//
// 1. Change requests (set, enable, mount, run, delete, purge...) are caught
//    here first and answered with a pointer to the right page. Nothing is
//    sent, and this page never runs a change.
// 2. The backend classifier routes supported read-only questions to Copilot.
// 3. Resolution/unknown requests retain the existing local and legacy paths.
//
// All DOM is built with createElement/textContent, no innerHTML.

import { ApiError, IrisApi } from "./api.js";
import { selectedInstanceId } from "./instance-context.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—";
const MAX_ROWS = 10;

const dom = {
  messages: document.getElementById("ai-chat-messages"),
  composer: document.getElementById("ai-chat-composer"),
  input: document.getElementById("ai-chat-input"),
  sendButton: document.getElementById("ai-chat-send-button"),
  refreshButton: document.getElementById("ai-refresh-button"),
  view: document.getElementById("view-ai-assistant"),
  ctxDot: document.getElementById("ai-context-dot"),
  ctxStatus: document.getElementById("ai-context-status"),
  ctxUser: document.getElementById("ai-context-user"),
  ctxVersion: document.getElementById("ai-context-version"),
  ctxBuild: document.getElementById("ai-context-build"),
  ctxNamespaces: document.getElementById("ai-context-namespaces"),
  ctxDatabases: document.getElementById("ai-context-databases"),
  ctxDatabasesMeta: document.getElementById("ai-context-databases-meta"),
  ctxProcesses: document.getElementById("ai-context-processes"),
  ctxWebApps: document.getElementById("ai-context-webapps"),
  ctxWebAppsMeta: document.getElementById("ai-context-webapps-meta"),
  ctxTasks: document.getElementById("ai-context-tasks"),
};

// Messages in this session (the DOM mirrors it).
const history = [];
let sending = false;
let onOpenTrace = null;

// --- small helpers ---

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function result(body) {
  return body && body.result !== undefined ? body.result : null;
}

function asList(body) {
  const value = result(body);
  return Array.isArray(value) ? value : [];
}

function fmtNumber(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString() : PLACEHOLDER;
}

function fmtMB(mb) {
  if (typeof mb !== "number") return PLACEHOLDER;
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${fmtNumber(mb)} MB`;
}

function fmtBytes(bytes) {
  if (typeof bytes !== "number" || !Number.isFinite(bytes)) return PLACEHOLDER;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit ? value.toFixed(1) : value} ${units[unit]}`;
}

function fmtDuration(ms) {
  if (typeof ms !== "number") return PLACEHOLDER;
  return ms < 1000 ? `${ms.toFixed(2)} ms` : `${(ms / 1000).toFixed(2)} s`;
}

function fmtTime(date) {
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function fmtIsoLocal(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso || PLACEHOLDER) : date.toLocaleString();
}

function parseVersion(serverVersion) {
  if (typeof serverVersion !== "string") return { release: null, build: null };
  const release = /\b(\d{4}\.\d+(?:\.\d+)?)\b/.exec(serverVersion);
  const build = /\(Build ([^)]+)\)/.exec(serverVersion);
  return { release: release ? release[1] : null, build: build ? build[1] : null };
}

function countBy(items, keyFn) {
  const counts = new Map();
  for (const item of items) {
    const key = keyFn(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function badge(text, variant) {
  return el("span", `status-badge status-badge--${variant}`, text);
}

// --- cards and tables ---

function kpiRow(items) {
  const row = el("div", "ai-kpis");
  for (const [label, value, meta] of items) {
    const card = el("div", "ai-kpi");
    card.append(el("span", "ai-kpi__value", value), el("span", "ai-kpi__label", label));
    if (meta) card.append(el("span", "ai-kpi__meta", meta));
    row.append(card);
  }
  return row;
}

function table(columns, rows, { onRowClick, rowTitle } = {}) {
  const wrapper = el("div", "table-wrapper ai-table");
  const tableEl = el("table", "data-table data-table--compact");
  const thead = el("thead");
  const head = el("tr");
  for (const column of columns) {
    const th = el("th", "", column);
    th.scope = "col";
    head.append(th);
  }
  thead.append(head);
  const tbody = el("tbody");
  rows.forEach((cells, index) => {
    const tr = el("tr");
    for (const cell of cells) {
      const td = el("td", "data-table__cell");
      if (cell instanceof Node) td.append(cell);
      else {
        td.textContent = cell === null || cell === undefined || cell === "" ? PLACEHOLDER : String(cell);
        td.title = td.textContent;
      }
      tr.append(td);
    }
    if (onRowClick) {
      tr.className = "data-table__row--link";
      tr.tabIndex = 0;
      if (rowTitle) tr.title = rowTitle(index);
      tr.addEventListener("click", () => onRowClick(index));
      tr.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        onRowClick(index);
      });
    }
    tbody.append(tr);
  });
  tableEl.append(thead, tbody);
  wrapper.append(tableEl);
  return wrapper;
}

function barList(entries, total) {
  const list = el("div", "ai-bars");
  for (const [label, count] of entries) {
    const row = el("div", "ai-bars__row");
    const track = el("span", "ai-bars__track");
    const fill = el("span", "ai-bars__fill");
    fill.style.width = `${total ? Math.max(2, (count / total) * 100) : 0}%`;
    track.append(fill);
    row.append(el("span", "ai-bars__label", label), track, el("span", "ai-bars__value", fmtNumber(count)));
    list.append(row);
  }
  return list;
}

function chipList(items, variant) {
  const list = el("div", "ai-chips");
  for (const item of items) list.append(el("span", `ai-chip${variant ? ` ai-chip--${variant}` : ""}`, item));
  return list;
}

function openButton(label, view) {
  const button = el("button", "dash-panel__link ai-open", `${label} →`);
  button.type = "button";
  button.addEventListener("click", () => navigateTo(view));
  return button;
}

function card(title, ...children) {
  const node = el("div", "ai-card");
  if (title) node.append(el("p", "ai-card__title", title));
  for (const child of children) if (child) node.append(child);
  return node;
}

function operationProposalCard(plan) {
  const details = el("dl", "info-list");
  const cardNode = card("IRIS Operation Proposal", details);
  const addDetail = (label, value) => {
    const term = el("dt", "", label);
    const description = el("dd", "", value);
    details.append(term, description);
  };

  addDetail("Operation", plan.operation);
  const target = plan.target;
  if (target && typeof target === "object") {
    addDetail(
      "Target",
      [target.kind, target.identifier].filter((value) => typeof value === "string").join(" — "),
    );
  }
  if (plan.parameters && typeof plan.parameters === "object") {
    for (const [name, value] of Object.entries(plan.parameters)) {
      addDetail("Change", `${name} → ${typeof value === "string" ? value : JSON.stringify(value)}`);
    }
  }
  if (typeof plan.reason === "string" && plan.reason) addDetail("Reason", plan.reason);
  if (typeof plan.requires_confirmation === "boolean") {
    addDetail("Confirmation", plan.requires_confirmation ? "Required" : "Not required");
  }

  if (plan.requires_confirmation !== true) return cardNode;

  const status = el("p", "ai-card__note", "Waiting for your explicit confirmation.");
  status.setAttribute("role", "status");
  const actions = el("div", "ai-message__actions");
  const confirmButton = el("button", "btn btn--warning", "Confirm & Execute");
  const cancelButton = el("button", "btn", "Cancel");
  confirmButton.type = "button";
  cancelButton.type = "button";
  actions.append(confirmButton, cancelButton);
  cardNode.append(status, actions);

  let state = "pending";
  const setProposalNotice = (text) => {
    const messageText = cardNode.closest(".ai-message")?.querySelector(".chat__message-text");
    if (messageText) messageText.textContent = text;
  };
  cancelButton.addEventListener("click", () => {
    if (state !== "pending") return;
    state = "cancelled";
    actions.remove();
    setProposalNotice("This proposal was cancelled. It was not authorized or executed.");
    status.textContent = "Operation cancelled. No changes were made.";
  });
  confirmButton.addEventListener("click", async () => {
    if (state !== "pending") return;
    state = "running";
    confirmButton.disabled = true;
    cancelButton.disabled = true;
    setProposalNotice("Explicit confirmation received. Checking authorization.");
    status.textContent = "Authorizing operation…";

    try {
      const authorization = await IrisApi.authorizeCopilotPlan(plan, true);
      if (!authorization.authorized) {
        const privileges = Array.isArray(authorization.required_privileges)
          ? authorization.required_privileges.filter((item) => typeof item === "string")
          : [];
        status.textContent = [
          "Authorization denied.",
          privileges.length ? `Required privilege: ${privileges.join(" / ")}` : "",
          "No changes were made.",
        ].filter(Boolean).join("\n");
        setProposalNotice("Authorization was denied. No operation was executed.");
        state = "complete";
        return;
      }
      if (authorization.ready_to_execute !== true) {
        status.textContent = `Authorization passed, but the operation is not ready to execute: ${String(authorization.reason || "not ready")}. No changes were made.`;
        setProposalNotice("The operation was not ready to execute. No operation was executed.");
        state = "complete";
        return;
      }

      setProposalNotice("Authorization passed. The operation is being executed and verified.");
      status.textContent = "Authorization passed. Executing and verifying…";
      const execution = await IrisApi.executeCopilotPlan(plan, authorization, true);
      const resultCard = el("div", "ai-card__note");
      const stage = (label, succeeded) =>
        `${label}  ${succeeded === true ? "✓" : succeeded === false ? "✗" : "—"}`;
      resultCard.append(
        el("p", "", stage("Authorization", authorization.authorized)),
        el("p", "", stage("Execution", execution.execution_succeeded)),
        el("p", "", stage("Verification", execution.verification_succeeded)),
        el(
          "p",
          "",
          typeof execution.detail === "string" && execution.detail
            ? execution.detail
            : "The operation result was returned.",
        ),
      );
      status.replaceWith(resultCard);
      setProposalNotice(
        execution.execution_succeeded === true && execution.verification_succeeded === true
          ? "Operation execution and verification succeeded."
          : execution.execution_succeeded === true
            ? "The operation executed, but verification did not succeed."
            : "The operation did not complete successfully.",
      );
      state = "complete";
    } catch {
      setProposalNotice("The operation result could not be confirmed. Check its state before taking further action.");
      status.textContent =
        "The request failed. Check the operation state before taking further action; no automatic retry was made.";
      state = "complete";
    }
  });
  return cardNode;
}

// --- mutation guard ---

const MUTATION_VERB =
  /\b(set|change|update|modify|edit|enable|disable|turn on|turn off|switch on|switch off|create|add|new|delete|drop|remove|mount|dismount|unmount|kill|terminate|stop|start|restart|run|execute|suspend|resume|confirm|rename|grant|revoke|purge)\b/;

// Where each kind of change is done: [pattern, page label, view].
const MUTATION_TARGETS = [
  [/journal|purge ?archived|purgearchived/, "Operations — Update Journal Settings", "operations"],
  [/namespace/, "Namespaces (New Namespace)", "namespaces"],
  [/database|mount/, "Databases", "databases"],
  [/web ?app|application/, "Web Applications", "web-apps"],
  [/user|login|account/, "Security (users)", "security"],
  [/task/, "Tasks (Run Task Now)", "tasks"],
];

function isMutationRequest(text) {
  // Anything about changing the journal purge setting counts as a change
  // request; it's never forwarded.
  if (/purge ?archived|purgearchived|purge_archived/.test(text) && /\b(set|change|update|enable|disable|turn|switch|confirm|true|false|on|off)\b/.test(text)) {
    return true;
  }
  if (/purge ?archived|purgearchived|purge_archived/.test(text)) return false;  // just asking about the setting
  return MUTATION_VERB.test(text);
}

function answerMutation(text) {
  const target = MUTATION_TARGETS.find(([pattern]) => pattern.test(text));
  const actions = [openButton("Open Operations", "operations")];
  if (target && target[2] !== "operations") actions.unshift(openButton(`Open ${target[1]}`, target[2]));
  return {
    text:
      "I'm read-only, so I can't make changes. Changes to IRIS go through the Operations flow, which checks your " +
      "privileges, asks for explicit confirmation and verifies the result" +
      (target ? ` — for this, use ${target[1]}.` : "."),
    actions,
  };
}

// --- read-only intents ---

async function answerSystem() {
  const info = result(await IrisApi.getInfo(selectedInstanceId()));
  const { release, build } = parseVersion(info.serverVersion);
  const privileges = Object.values(info.privileges || {});
  const granted = privileges.filter((p) => p && p.use).length;
  return {
    text:
      `Connected as ${info.username || "an unknown user"} to ${info.product || "IRIS"} ${release || info.serverVersion || ""}` +
      `${build ? ` (Build ${build})` : ""}, Admin API v${info.apiVersion ?? "?"}, with ${(info.namespaces || []).length} namespaces visible.`,
    card: card(
      "System Summary",
      kpiRow([
        ["Version", release || PLACEHOLDER, build ? `Build ${build}` : null],
        ["API Version", info.apiVersion !== undefined ? `v${info.apiVersion}` : PLACEHOLDER],
        ["Namespaces", fmtNumber((info.namespaces || []).length)],
        ["Privileges", `${granted} of ${privileges.length}`, "granted"],
      ]),
    ),
    actions: [openButton("Open System", "system")],
  };
}

// IRIS System Dashboard indicators (same set as the Dashboard).
const HEALTH_INDICATORS = [
  ["Database Space", "SystemUsage", "DatabaseSpace"],
  ["Database Journal", "SystemUsage", "DatabaseJournal"],
  ["Journal Space", "SystemUsage", "JournalSpace"],
  ["Lock Table", "SystemUsage", "LockTable"],
  ["Write Daemon", "SystemUsage", "WriteDaemon"],
  ["ECP Clients", "ECP", "ECPClients"],
  ["ECP Servers", "ECP", "ECPServers"],
  ["Shadow Connections", "ECP", "ShadowConnections"],
  ["Shadows", "ECP", "Shadows"],
];

async function answerHealth() {
  const monitor = result(await IrisApi.getMonitorDashboard(selectedInstanceId()));
  const rows = HEALTH_INDICATORS.map(([label, section, field]) => {
    const value = monitor && monitor[section] ? monitor[section][field] : null;
    return [label, value, typeof value === "string" && value.trim().toLowerCase() === "normal"];
  });
  const normal = rows.filter((r) => r[2]).length;
  const serious = monitor && monitor.Alerts ? monitor.Alerts.SeriousAlerts : null;
  const backup = monitor && monitor.Status ? monitor.Status.LastBackup : null;
  return {
    text:
      `${normal} of ${rows.length} IRIS status indicators report Normal; IRIS reports ${fmtNumber(serious)} serious ` +
      `alert${serious === 1 ? "" : "s"}. Last full backup: ${backup || PLACEHOLDER}.`,
    card: card(
      "Health Indicators",
      table(["Indicator", "Status"], rows.map(([label, value, ok]) => [label, badge(value || PLACEHOLDER, ok ? "ok" : "warning")])),
    ),
    actions: [openButton("Open Dashboard", "dashboard")],
  };
}

async function answerNamespaces() {
  const info = result(await IrisApi.getInfo(selectedInstanceId()));
  const names = (info.namespaces || []).map((n) => (n && n.name) || PLACEHOLDER);
  return {
    text: `There ${names.length === 1 ? "is" : "are"} ${names.length} namespace${names.length === 1 ? "" : "s"} visible to this session.`,
    card: card("Namespaces", chipList(names)),
    actions: [openButton("Open Namespaces", "namespaces")],
  };
}

async function answerProcesses(text) {
  const processes = asList(await IrisApi.getProcesses(selectedInstanceId()));
  const byNamespace = countBy(processes, (p) => p.Nspace || "(none)");
  const byState = countBy(processes, (p) => p.State || "Unknown");
  const actions = [openButton("Open Processes", "processes")];

  if (/\b(top|busiest|cpu|heaviest|most active)\b/.test(text)) {
    const top = [...processes].filter((p) => typeof p.CPUTime === "number").sort((a, b) => b.CPUTime - a.CPUTime).slice(0, 5);
    return {
      text: `Here are the top ${top.length} of ${processes.length} processes by cumulative CPU time, as reported by IRIS.`,
      card: card(
        "Top Processes by CPU Time",
        table(
          ["PID", "Namespace", "Routine", "State", "CPU time", "Commands", "Globals"],
          top.map((p) => [p.Pid, p.Nspace, p.Routine, p.State, fmtNumber(p.CPUTime), fmtNumber(p.Commands), fmtNumber(p.Globals)]),
        ),
      ),
      actions,
    };
  }
  if (/namespace/.test(text)) {
    const [first] = byNamespace;
    return {
      text: first
        ? `${first[0]} has the most processes (${first[1]} of ${processes.length}).`
        : "IRIS reported no processes.",
      card: card("Processes by Namespace", barList(byNamespace, processes.length)),
      actions,
    };
  }
  return {
    text: `There are ${processes.length} processes across ${byNamespace.length} namespaces.`,
    card: card(
      "Process Summary",
      kpiRow([
        ["Processes", fmtNumber(processes.length)],
        ["Namespaces", fmtNumber(byNamespace.length)],
        ...byState.slice(0, 2).map(([state, count]) => [state, fmtNumber(count), "state"]),
      ]),
    ),
    actions,
  };
}

async function answerDatabases(text) {
  const [dbResult, storageResult] = await Promise.allSettled([IrisApi.getDatabases(selectedInstanceId()), IrisApi.getDatabaseStorage(selectedInstanceId())]);
  if (dbResult.status !== "fulfilled") throw dbResult.reason;
  const databases = asList(dbResult.value);
  const storage = storageResult.status === "fulfilled" ? asList(storageResult.value) : [];
  const byDir = new Map(storage.map((s) => [s.Directory, s]));
  const rows = databases.map((db) => {
    const s = byDir.get(db.Directory);
    return { name: db.Name, dir: db.Directory, status: s ? s.Status : db.Status, size: s ? s.Size : null };
  });
  const mounted = rows.filter((r) => typeof r.status === "string" && r.status.toLowerCase().startsWith("mounted")).length;
  const total = rows.reduce((sum, r) => sum + (typeof r.size === "number" ? r.size : 0), 0);
  const largest = /\b(largest|biggest|size|space|storage)\b/.test(text);
  const shown = largest ? [...rows].sort((a, b) => (b.size ?? -1) - (a.size ?? -1)) : rows;
  return {
    text:
      `There are ${rows.length} databases` +
      (storage.length ? `; ${mounted} report a Mounted status, ${fmtMB(total)} allocated in total.` : ".") +
      (largest && shown[0] ? ` The largest is ${shown[0].name} (${fmtMB(shown[0].size)}).` : ""),
    card: card(
      largest ? "Databases by Size" : "Database Status",
      table(
        ["Name", "Status", "Size", "Directory"],
        shown.slice(0, MAX_ROWS).map((r) => [r.name, r.status, fmtMB(r.size), r.dir]),
      ),
      shown.length > MAX_ROWS ? el("p", "ai-card__note", `Showing ${MAX_ROWS} of ${shown.length}.`) : null,
    ),
    actions: [openButton("Open Databases", "databases")],
  };
}

async function answerWebApps(text) {
  const apps = asList(await IrisApi.getWebApps(selectedInstanceId()));
  const enabled = apps.filter((a) => a.Enabled === true).length;
  const onlyDisabled = /\bdisabled\b/.test(text);
  const shown = onlyDisabled ? apps.filter((a) => a.Enabled === false) : apps;
  return {
    text: onlyDisabled
      ? `${shown.length} of ${apps.length} web applications are disabled.`
      : `There are ${apps.length} web applications; ${enabled} enabled and ${apps.length - enabled} disabled.`,
    card: card(
      onlyDisabled ? "Disabled Web Applications" : "Web Applications",
      shown.length
        ? table(
            ["Name", "Namespace", "Enabled", "Type"],
            shown.slice(0, MAX_ROWS).map((a) => [a.Name, a.Namespace, badge(a.Enabled ? "Enabled" : "Disabled", a.Enabled ? "ok" : "neutral"), a.Type]),
          )
        : el("p", "ai-card__note", "None."),
      shown.length > MAX_ROWS ? el("p", "ai-card__note", `Showing ${MAX_ROWS} of ${shown.length}.`) : null,
    ),
    actions: [openButton("Open Web Applications", "web-apps")],
  };
}

async function answerTasks(text) {
  const tasks = asList(await IrisApi.getTaskOverview(selectedInstanceId()));
  const onlySuspended = /\bsuspended\b/.test(text);
  const shown = onlySuspended ? tasks.filter((t) => t.State === "Suspended") : tasks;
  const byState = countBy(tasks, (t) => t.State || "Unknown");
  return {
    text: onlySuspended
      ? `${shown.length} of ${tasks.length} tasks are suspended.`
      : `There are ${tasks.length} tasks defined (${byState.map(([s, n]) => `${n} ${s.toLowerCase()}`).join(", ")}).`,
    card: card(
      onlySuspended ? "Suspended Tasks" : "Tasks",
      shown.length
        ? table(
            ["Name", "Type", "State", "Next scheduled"],
            shown.slice(0, MAX_ROWS).map((t) => [t.Name, t.Type, t.State, t.NextScheduled]),
          )
        : el("p", "ai-card__note", "None."),
      shown.length > MAX_ROWS ? el("p", "ai-card__note", `Showing ${MAX_ROWS} of ${shown.length}.`) : null,
    ),
    actions: [openButton("Open Tasks", "tasks")],
  };
}

async function answerPrivileges() {
  const info = result(await IrisApi.getInfo(selectedInstanceId()));
  const entries = Object.entries(info.privileges || {}).sort(([a], [b]) => a.localeCompare(b));
  const granted = entries.filter(([, flag]) => flag && flag.use).map(([name]) => name);
  const missing = entries.filter(([, flag]) => !(flag && flag.use)).map(([name]) => name);
  return {
    text: `This session (${info.username || "unknown user"}) holds ${granted.length} of ${entries.length} admin privileges.`,
    card: card(
      "Session Privileges",
      chipList(granted, "ok"),
      missing.length ? el("p", "ai-card__note", "Not granted:") : null,
      missing.length ? chipList(missing) : null,
    ),
    actions: [openButton("Open System", "system"), openButton("Open Security", "security")],
  };
}

async function answerTraces(text) {
  const traces = (await IrisApi.getExecutionTraces()).traces || [];
  const failuresOnly = /\bfail|error|denied|unauthori/.test(text);
  const shown = failuresOnly ? traces.filter((t) => t.status !== "success" && t.status !== "dry_run") : traces;
  const recent = shown.slice(0, 5);
  const variant = (status) => (status === "success" ? "ok" : status === "dry_run" ? "neutral" : "error");
  return {
    text: failuresOnly
      ? shown.length
        ? `${shown.length} of ${traces.length} recorded operation attempts did not succeed; the latest are below.`
        : `None of the ${traces.length} recorded operation attempts failed.`
      : traces.length
        ? `Here are the ${recent.length} most recent of ${traces.length} recorded operation attempts. Select one to open its trace.`
        : "No operation attempts have been recorded yet.",
    card: recent.length
      ? card(
          failuresOnly ? "Unsuccessful Operations" : "Recent Operations",
          table(
            ["Operation", "Status", "Duration", "Started"],
            recent.map((t) => [t.operation_name, badge(String(t.status || PLACEHOLDER).replace(/_/g, " "), variant(t.status)), fmtDuration(t.duration_ms), fmtIsoLocal(t.start_time)]),
            onOpenTrace
              ? { onRowClick: (i) => onOpenTrace(recent[i].trace_id), rowTitle: (i) => `Open trace ${recent[i].trace_id} in Observability` }
              : {},
          ),
        )
      : null,
    actions: [openButton("Open Observability", "observability")],
  };
}

async function answerJournal() {
  const settings = result(await IrisApi.getJournalSettings(selectedInstanceId()));
  const fields = [
    ["Purge archived journals", settings.PurgeArchived === true ? "Yes" : settings.PurgeArchived === false ? "No" : PLACEHOLDER],
    ["Current directory", settings.CurrentDirectory],
    ["Alternate directory", settings.AlternateDirectory],
    ["Days before purge", fmtNumber(settings.DaysBeforePurge)],
    ["Backups before purge", fmtNumber(settings.BackupsBeforePurge)],
    ["File size limit (MB)", fmtNumber(settings.FileSizeLimit)],
    ["Compress files", settings.CompressFiles === true ? "Yes" : settings.CompressFiles === false ? "No" : PLACEHOLDER],
  ];
  return {
    text:
      `Journal files are written to ${settings.CurrentDirectory || PLACEHOLDER}; archived journals are ` +
      `${settings.PurgeArchived ? "" : "not "}purged automatically. To change this, use Operations → Update Journal Settings.`,
    card: card("Journal Settings", table(["Setting", "Value"], fields)),
    actions: [openButton("Open Journal", "journal"), openButton("Open Operations", "operations")],
  };
}

// Host values from Embedded Python inside IRIS
// (app/embedded_python/diagnostics.py). Missing fields are null.
async function answerPython() {
  if (selectedInstanceId()) return { text: "Embedded Python diagnostics are available for the Primary instance only." };
  const d = await IrisApi.getPythonDiagnostics();
  const load = Array.isArray(d.load_average) ? d.load_average.map((v) => v.toFixed(2)) : null;
  const memory = d.memory || {};
  const disk = d.manager_disk || {};
  const parts = [
    `Embedded Python ${d.python_version || PLACEHOLDER} is running inside IRIS on ${d.hostname || PLACEHOLDER}.`,
    ` The host has ${fmtNumber(d.cpu_count)} CPUs${load ? ` (load ${load.join(" / ")})` : ""}`,
    `, ${fmtBytes(memory.available_bytes)} of ${fmtBytes(memory.total_bytes)} memory available`,
    ` and ${fmtBytes(disk.free_bytes)} free on the manager directory's disk.`,
  ];
  return {
    text: parts.join(""),
    card: card(
      "Embedded Python Host Diagnostics",
      kpiRow([
        ["Python", d.python_version || PLACEHOLDER, "inside IRIS"],
        ["CPUs", fmtNumber(d.cpu_count), load ? `load ${load[0]}` : null],
        ["Memory Free", fmtBytes(memory.available_bytes), `of ${fmtBytes(memory.total_bytes)}`],
        ["Disk Free", fmtBytes(disk.free_bytes), `of ${fmtBytes(disk.total_bytes)}`],
      ]),
      table(
        ["Diagnostic", "Value"],
        [
          ["Platform", d.platform],
          ["Hostname", d.hostname],
          ["IRIS process ID", d.iris_pid],
          ["Load average (1 / 5 / 15 min)", load ? load.join(" / ") : null],
          ["Manager directory", d.manager_directory],
          ["Manager disk used", fmtBytes(disk.used_bytes)],
          ["Installed Python packages", fmtNumber(d.package_count)],
          ["Collected in", fmtDuration(d.duration_ms)],
        ],
      ),
      d.unavailable && d.unavailable.length
        ? el("p", "ai-card__note", `Not available: ${d.unavailable.join(", ")}.`)
        : null,
    ),
    actions: [openButton("Open System", "system")],
  };
}

// How-to questions ("how do I...", "which privilege...", "...need
// confirmation?") are answered from the knowledge base: stored documents
// ranked by IRIS Vector Search (VECTOR_COSINE). Nothing is generated.
const KNOWLEDGE_QUERY =
  /\bhow (do|can|should) i\b|\bhow to\b|\b(privileges?|permissions?)\b.*\b(needed|required|need|needs|require|requires)\b|\bwhich privileges?\b|\bconfirmation\b|\bendpoints?\b|\bcapabilit|\bknowledge\b|\bdocs?\b|\bdocumentation\b|\bexplain\b/;
const MIN_KNOWLEDGE_SCORE = 0.1;
const SNIPPET_CHARS = 180;

function snippet(text) {
  const value = String(text || "");
  return value.length > SNIPPET_CHARS ? `${value.slice(0, SNIPPET_CHARS - 1)}…` : value;
}

async function answerKnowledge(message, text) {
  let response;
  try {
    response = await IrisApi.searchKnowledge(message);
  } catch (err) {
    if (err instanceof ApiError && err.status === 503) {
      return { text: "Knowledge search isn't enabled on this Command Center (set ENABLE_KNOWLEDGE_SEARCH=true on the backend)." };
    }
    throw err;
  }
  const hits = (response && Array.isArray(response.results) ? response.results : []).filter(
    (h) => typeof h.score === "number" && h.score >= MIN_KNOWLEDGE_SCORE,
  );
  const actions = [];
  const readOnlyNote = isMutationRequest(text)
    ? " I'm read-only — any change goes through the Operations flow (privilege check, explicit confirmation, verification)."
    : "";
  if (isMutationRequest(text)) actions.push(openButton("Open Operations", "operations"));
  if (!hits.length) {
    return { text: `I couldn't find a relevant document in the knowledge base.${readOnlyNote}`, actions };
  }

  const [top] = hits;
  const kind = (source) => (String(source).startsWith("operation:") ? "Operation" : "IRIS API");
  if (!actions.length) {
    actions.push(
      String(top.source).startsWith("operation:")
        ? openButton("Open Operations", "operations")
        : openButton("Open Capabilities", "capabilities"),
    );
  }
  return {
    text: `Best match: ${top.title} (cosine ${top.score.toFixed(3)}). ${top.body}${readOnlyNote}`,
    card: card(
      "Knowledge Base — IRIS Vector Search",
      table(
        ["Document", "Type", "Cosine"],
        hits.map((h) => {
          const cell = el("div");
          cell.append(el("strong", "", h.title), el("p", "ai-card__note", snippet(h.body)));
          return [cell, badge(kind(h.source), kind(h.source) === "Operation" ? "ok" : "neutral"), h.score.toFixed(3)];
        }),
      ),
      el("p", "ai-card__note", "Stored Command Center documents ranked by VECTOR_COSINE inside IRIS — not generated text."),
    ),
    actions,
  };
}

const HELP_TEXT =
  "I can answer from live, read-only data about: system status and version, health indicators, namespaces, " +
  "processes (count, top by CPU time, by namespace), databases (status, largest), web applications (all, disabled), " +
  "tasks (all, suspended), your session privileges, recent operations and failures, journal settings, and " +
  "Embedded Python host diagnostics (CPU, load, memory, disk, Python packages). Ask how-to questions " +
  '(e.g. "Which operations need confirmation?") and I\'ll search the knowledge base with IRIS Vector Search.';

// Keyword routing, most specific first.
const INTENTS = [
  [/journal|purge[ _]?archived/, answerJournal],
  [/recent operation|operations|operation attempt|trace|observability|\bfail|failed/, answerTraces],
  [/privilege|permission|my access|security|\broles?\b/, answerPrivileges],
  [/process/, answerProcesses],
  // Host/Python questions, but not about databases (disk usage belongs
  // to answerDatabases).
  [/^(?!.*database)(?=.*(\bpython\b|\bhost\b|load average|memory|\bram\b|cpu count|\bcores\b|disk usage|disk space|free disk|packages))/, answerPython],
  [/database|storage|largest|disk/, answerDatabases],
  [/web ?app|web application|applications/, answerWebApps],
  [/\btasks?\b|schedule/, answerTasks],
  [/namespace/, answerNamespaces],
  [/health|healthy|alert|monitor|backup/, answerHealth],
  [/system|status|version|info|connected|who am i/, answerSystem],
];

async function answer(message) {
  const text = message.toLowerCase();
  // Knowledge search goes first: it's a read-only GET, and otherwise a
  // question like "how do I dismount..." would hit the change guard.
  // answerKnowledge still points to Operations if the question names a
  // change.
  if (KNOWLEDGE_QUERY.test(text) && !/purge/.test(text)) return answerKnowledge(message, text);
  if (/\b(help|what can you)\b/.test(text)) return { text: HELP_TEXT };

  let classification;
  try {
    classification = await IrisApi.classifyCopilotRequest(message);
  } catch (error) {
    if (isMutationRequest(text)) return answerMutation(text);
    throw error;
  }
  if (classification && classification.intent === "resolution_request") {
    // Copilot changes are planned, authorized and run on the Primary only.
    if (selectedInstanceId()) {
      return { text: "Changes run on the Primary instance only. Switch to Primary in the instance selector above to plan this change." };
    }
    const reasoning = await IrisApi.askCopilot(message, selectedInstanceId());
    const planning = await IrisApi.planCopilotOperation(message, reasoning);
    if (planning && planning.plan) {
      return {
        text: "The backend prepared this operation proposal. It has not been authorized or executed.",
        card: operationProposalCard(planning.plan),
      };
    }
    return answerMutation(text);
  }
  if (isMutationRequest(text)) return answerMutation(text);

  if (classification && ["issue_investigation", "health_status", "read_only_query"].includes(classification.intent)) {
    const response = await IrisApi.askCopilot(message, selectedInstanceId());
    if (response && response.intent === classification.intent && typeof response.answer === "string" && response.answer) {
      const parts = [response.answer];
      if (Array.isArray(response.observations)) {
        const observations = response.observations.filter((item) => typeof item === "string" && item);
        if (observations.length) parts.push(`Observations:\n${observations.map((item) => `• ${item}`).join("\n")}`);
      }
      if (typeof response.proposed_action === "string" && response.proposed_action) {
        parts.push(`Possible next step (proposal only): ${response.proposed_action}`);
      }
      if (response.requires_confirmation === true) {
        parts.push("Confirmation is required for any operation; this response does not authorize or execute it.");
      }
      return { text: parts.join("\n\n") };
    }
    return { text: "I didn't get a usable answer for that. Try one of the suggested questions." };
  }
  if (classification && classification.intent === "resolution_request") {
    return answerMutation(text);
  }

  // Preserve existing local answers for topics outside Copilot's supported
  // intents, then retain its legacy read-only endpoint as the final fallback.
  const intent = INTENTS.find(([pattern]) => pattern.test(text));
  if (intent) return intent[1](text);
  const response = await IrisApi.queryAssistant(message, selectedInstanceId());
  return {
    text:
      response && typeof response.reply === "string" && response.reply
        ? response.reply
        : "I didn't get a usable answer for that. Try one of the suggested questions.",
  };
}

// --- rendering ---

function appendMessage(role, { text, card: cardNode, actions } = {}) {
  const time = new Date();
  history.push({ role, text, time });
  const message = el("div", `chat__message chat__message--${role} ai-message`);
  const head = el("div", "ai-message__head");
  head.append(el("span", "ai-message__who", role === "user" ? "You" : "IRIS Assistant"), el("span", "ai-message__time", fmtTime(time)));
  message.append(head, el("p", "chat__message-text", text));
  if (cardNode) message.append(cardNode);
  if (actions && actions.length) {
    const row = el("div", "ai-message__actions");
    row.append(...actions);
    message.append(row);
  }
  dom.messages.append(message);
  message.scrollIntoView({ block: "nearest" });
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

function setSending(isSending) {
  // Disable right away so a double Send (or Quick Action) click does nothing.
  sending = isSending;
  dom.sendButton.disabled = isSending;
  dom.input.disabled = isSending;
  dom.view.querySelectorAll("[data-prompt]").forEach((button) => {
    button.disabled = isSending;
  });
}

async function sendMessage(raw) {
  const message = (raw || "").trim();
  if (!message || sending) return;
  appendMessage("user", { text: message });
  setSending(true);
  try {
    appendMessage("assistant", await answer(message));
  } catch (err) {
    appendMessage("assistant", {
      text:
        err instanceof ApiError
          ? "I couldn't load that from the Command Center backend just now. Please try again."
          : "Something went wrong while answering that.",
    });
  } finally {
    setSending(false);
    dom.input.focus();
  }
}

// --- connection / system context bar ---

function setText(node, value) {
  node.textContent = value === null || value === undefined || value === "" ? PLACEHOLDER : String(value);
}

export async function loadAssistantContext() {
  dom.refreshButton.disabled = true;
  dom.refreshButton.classList.add("btn--spinning");
  const [info, databases, storage, processes, webApps, tasks] = await Promise.allSettled([
    IrisApi.getInfo(selectedInstanceId()),
    IrisApi.getDatabases(selectedInstanceId()),
    IrisApi.getDatabaseStorage(selectedInstanceId()),
    IrisApi.getProcesses(selectedInstanceId()),
    IrisApi.getWebApps(selectedInstanceId()),
    IrisApi.getTaskOverview(selectedInstanceId()),
  ]);
  const ok = (r) => r.status === "fulfilled";

  if (ok(info)) {
    const i = result(info.value) || {};
    const { release, build } = parseVersion(i.serverVersion);
    dom.ctxDot.dataset.state = "connected";
    setText(dom.ctxStatus, "Connected");
    dom.ctxUser.textContent = i.username ? `as ${i.username}` : "";
    setText(dom.ctxVersion, release || i.serverVersion);
    dom.ctxVersion.title = i.serverVersion || "";
    dom.ctxBuild.textContent = build ? `Build ${build}` : "";
    setText(dom.ctxNamespaces, Array.isArray(i.namespaces) ? i.namespaces.length : null);
  } else {
    dom.ctxDot.dataset.state = "error";
    setText(dom.ctxStatus, "Not connected");
    dom.ctxUser.textContent = "backend unreachable";
    setText(dom.ctxVersion, null);
    dom.ctxBuild.textContent = "";
    setText(dom.ctxNamespaces, null);
  }
  setText(dom.ctxDatabases, ok(databases) ? asList(databases.value).length : null);
  dom.ctxDatabasesMeta.textContent = ok(storage)
    ? `${asList(storage.value).filter((s) => typeof s.Status === "string" && s.Status.toLowerCase().startsWith("mounted")).length} mounted`
    : "";
  setText(dom.ctxProcesses, ok(processes) ? asList(processes.value).length : null);
  const apps = ok(webApps) ? asList(webApps.value) : null;
  setText(dom.ctxWebApps, apps ? apps.length : null);
  dom.ctxWebAppsMeta.textContent = apps ? `${apps.filter((a) => a.Enabled === true).length} enabled` : "";
  setText(dom.ctxTasks, ok(tasks) ? asList(tasks.value).length : null);

  dom.refreshButton.disabled = false;
  dom.refreshButton.classList.remove("btn--spinning");
}

/** `onOpenTrace(traceId)` opens a trace in Observability (wired by app.js). */
/** Ask a question as if the user typed it (used by links from other pages). */
export function askAssistant(text) {
  sendMessage(text);
}

export function initAiAssistantControls({ onOpenTrace: openTrace } = {}) {
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;

  dom.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = dom.input.value;
    dom.input.value = "";
    sendMessage(text);
  });
  // Enter sends; Shift+Enter keeps a new line.
  dom.input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      dom.composer.requestSubmit();
    }
  });
  // Quick Actions, Suggested Questions and chips all go through here.
  dom.view.addEventListener("click", (event) => {
    const button = event.target.closest("[data-prompt]");
    if (button && dom.view.contains(button)) sendMessage(button.dataset.prompt || button.textContent);
  });
  dom.refreshButton.addEventListener("click", () => {
    loadAssistantContext();
  });
}
