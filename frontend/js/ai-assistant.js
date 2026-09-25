// AI Assistant view: a deterministic (no LLM) assistant over live,
// read-only IRIS data.
//
//   1. Mutation guard, first: any request to change something (set, enable,
//      mount, run, delete, purge-archived changes, ...) is answered HERE
//      with a pointer to the Operations flow and is never sent anywhere —
//      this view never executes, confirms or requests a mutation.
//   2. Known read-only intents are answered from existing read-only GET
//      APIs (IrisApi.get*), as a short sentence built from the returned
//      data plus a structured card/table of that same data.
//   3. Anything else falls back to the existing backend assistant
//      (IrisApi.queryAssistant, GET /api/iris/assistant/query).
//
// Nothing is invented: every number, name and status shown comes from the
// API response it is rendered from. All DOM is built with createElement +
// textContent, never innerHTML.

import { ApiError, IrisApi } from "./api.js";
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

// Conversation history for this page session (the DOM mirrors it).
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

// --- structured card builders (all fed only with API data) ---

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

// --- mutation guard ---

const MUTATION_VERB =
  /\b(set|change|update|modify|edit|enable|disable|turn on|turn off|switch on|switch off|create|add|new|delete|drop|remove|mount|dismount|unmount|kill|terminate|stop|start|restart|run|execute|suspend|resume|confirm|rename|grant|revoke|purge)\b/;

// Where each kind of change is made through the authorization/confirmation
// framework: [pattern, page label, view].
const MUTATION_TARGETS = [
  [/journal|purge ?archived|purgearchived/, "Operations — Update Journal Settings", "operations"],
  [/namespace/, "Namespaces (New Namespace)", "namespaces"],
  [/database|mount/, "Databases", "databases"],
  [/web ?app|application/, "Web Applications", "web-apps"],
  [/user|login|account/, "Security (users)", "security"],
  [/task/, "Tasks (Run Task Now)", "tasks"],
];

function isMutationRequest(text) {
  // Any mention of changing the journal purge setting is always a
  // mutation request here — the assistant never forwards it.
  if (/purge ?archived|purgearchived|purge_archived/.test(text) && /\b(set|change|update|enable|disable|turn|switch|confirm|true|false|on|off)\b/.test(text)) {
    return true;
  }
  if (/purge ?archived|purgearchived|purge_archived/.test(text)) return false; // a question about the setting
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
  const info = result(await IrisApi.getInfo());
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

// IRIS's own System Dashboard indicators (the same set the Dashboard shows).
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
  const monitor = result(await IrisApi.getMonitorDashboard());
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
  const info = result(await IrisApi.getInfo());
  const names = (info.namespaces || []).map((n) => (n && n.name) || PLACEHOLDER);
  return {
    text: `There ${names.length === 1 ? "is" : "are"} ${names.length} namespace${names.length === 1 ? "" : "s"} visible to this session.`,
    card: card("Namespaces", chipList(names)),
    actions: [openButton("Open Namespaces", "namespaces")],
  };
}

async function answerProcesses(text) {
  const processes = asList(await IrisApi.getProcesses());
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
  const [dbResult, storageResult] = await Promise.allSettled([IrisApi.getDatabases(), IrisApi.getDatabaseStorage()]);
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
  const apps = asList(await IrisApi.getWebApps());
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
  const tasks = asList(await IrisApi.getTaskOverview());
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
  const info = result(await IrisApi.getInfo());
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
  const settings = result(await IrisApi.getJournalSettings());
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

const HELP_TEXT =
  "I can answer from live, read-only data about: system status and version, health indicators, namespaces, " +
  "processes (count, top by CPU time, by namespace), databases (status, largest), web applications (all, disabled), " +
  "tasks (all, suspended), your session privileges, recent operations and failures, and journal settings.";

// Ordered, deterministic keyword routing (most specific first).
const INTENTS = [
  [/journal|purge[ _]?archived/, answerJournal],
  [/recent operation|operations|operation attempt|trace|observability|\bfail|failed/, answerTraces],
  [/privilege|permission|my access|security|\broles?\b/, answerPrivileges],
  [/process/, answerProcesses],
  [/database|storage|largest|disk/, answerDatabases],
  [/web ?app|web application|applications/, answerWebApps],
  [/\btasks?\b|schedule/, answerTasks],
  [/namespace/, answerNamespaces],
  [/health|healthy|alert|monitor|backup/, answerHealth],
  [/system|status|version|info|connected|who am i/, answerSystem],
];

async function answer(message) {
  const text = message.toLowerCase();
  if (isMutationRequest(text)) return answerMutation(text);
  if (/\b(help|what can you)\b/.test(text)) return { text: HELP_TEXT };
  const intent = INTENTS.find(([pattern]) => pattern.test(text));
  if (intent) return intent[1](text);
  // Fallback: the existing backend assistant. Mutation requests were
  // stopped above; as a hard guard, nothing mentioning purge is ever
  // forwarded, so the backend's journal operation path is unreachable here.
  if (/purge/.test(text)) return answerMutation(text);
  const response = await IrisApi.queryAssistant(message);
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
  // Disabled synchronously, before any await, so a second rapid Send (or
  // Quick Action) click is a no-op.
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

// --- connection / system context bar (live data) ---

function setText(node, value) {
  node.textContent = value === null || value === undefined || value === "" ? PLACEHOLDER : String(value);
}

export async function loadAssistantContext() {
  dom.refreshButton.disabled = true;
  dom.refreshButton.classList.add("btn--spinning");
  const [info, databases, storage, processes, webApps, tasks] = await Promise.allSettled([
    IrisApi.getInfo(),
    IrisApi.getDatabases(),
    IrisApi.getDatabaseStorage(),
    IrisApi.getProcesses(),
    IrisApi.getWebApps(),
    IrisApi.getTaskOverview(),
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
  // Quick Actions, Suggested Questions and chips all use the same flow.
  dom.view.addEventListener("click", (event) => {
    const button = event.target.closest("[data-prompt]");
    if (button && dom.view.contains(button)) sendMessage(button.dataset.prompt || button.textContent);
  });
  dom.refreshButton.addEventListener("click", () => {
    loadAssistantContext();
  });
}
