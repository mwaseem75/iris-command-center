// Instance-aware Dashboard (frontend/js/dashboard.js), tested without a
// browser: a minimal stand-in DOM, a fake fetch() that records every request
// and answers like the backend, and an in-memory localStorage. The real
// dashboard.js and instance-context.js modules are imported and driven
// through their exported functions (loadDashboard is what Refresh calls).
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_dashboard_context.mjs

import assert from "node:assert/strict";
import { before, beforeEach, test } from "node:test";

const PRIMARY = "primary";
const IRIS2 = "iris-2b1365d07d62";
const SECRET = "Pw-DASHBOARD-CANARY-not-real";

// --- stand-in DOM: elements remember what's set on them and absorb any
// other call (append, setAttribute, addEventListener, ...). ---

const elements = new Map();

function classList() {
  const set = new Set();
  return {
    add: (...c) => c.forEach((x) => set.add(x)),
    remove: (...c) => c.forEach((x) => set.delete(x)),
    toggle: (c, on) => ((on ?? !set.has(c)) ? set.add(c) : set.delete(c)),
    contains: (c) => set.has(c),
  };
}

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", title: "", children: [], style: {},
    classList: classList(), attributes: {}, disabled: false, value: "", listeners: {} };
  return new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "setAttribute") return (name, value) => { props.attributes[name] = String(value); };
      if (key === "getAttribute") return (name) => props.attributes[name] ?? null;
      if (key === "querySelectorAll") return () => [];
      if (key === "closest") return () => null;
      if (key === "contains") return () => false;
      if (key === "append") return (...nodes) => { props.children.push(...nodes); };
      if (key === "replaceChildren") return (...nodes) => { props.children = [...nodes]; };
      if (key === "addEventListener") return (type, fn) => { (props.listeners[type] ||= []).push(fn); };
      return () => stub();
    },
    set(_, key, value) {
      props[key] = value;
      return true;
    },
  });
}

function element(id) {
  if (!elements.has(id)) elements.set(id, stub(id));
  return elements.get(id);
}

// --- fake backend ---

let requests = [];
let instances = [];
let failInstance = null; // { id, status }
let attentionData = {};     // instance id -> { issues, tasks } for Needs Attention (default: nothing to report)

function envelope(result) {
  return { status: { errors: [] }, result };
}

function answer(path, instance) {
  const who = instance || PRIMARY;
  const n = who === PRIMARY ? 1 : 2; // different list sizes per instance
  const list = (k) => Array.from({ length: n * k }, (_, i) => ({ Name: `${who}-${i}`, Status: "Mounted/RW", State: "RUNW", Enabled: true }));
  switch (path) {
    case "/api/iris/instances": return { instances };
    case "/api/iris/info": return envelope({ apiVersion: 2, username: "_SYSTEM", serverVersion: `IRIS 2026.2 (${who})`, product: "iris", namespaces: [], privileges: {} });
    case "/api/iris/namespaces": return envelope(list(3));
    case "/api/iris/databases": return envelope(list(5));
    case "/api/iris/processes": return envelope(list(7));
    case "/api/iris/web-apps": return envelope(list(11));
    case "/api/iris/tasks": return envelope(list(13));
    case "/api/iris/tasks/overview": return envelope(attentionData[who]?.tasks ?? list(13));
    case "/api/iris/databases/storage": return envelope([]);
    case "/api/iris/monitor/dashboard": return envelope(null); // no counters: panels show "unavailable"
    case "/api/iris/observability/traces": return { traces: [] };
    case "/api/iris/operations": return { operations: [] };
    case "/api/iris/issues": return attentionData[who]?.issues ?? { issues: [], recommendations: [] };
    default: return envelope([]);
  }
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  const instance = parsed.searchParams.get("instance");
  requests.push({ path: parsed.pathname, instance, method: init.method || "GET", init });
  if (failInstance && instance === failInstance.id) {
    return { ok: false, status: failInstance.status, json: async () => ({ detail: "x" }) };
  }
  return { ok: true, status: 200, json: async () => answer(parsed.pathname, instance) };
}

function registry({ iris2Active = true } = {}) {
  return [
    { id: PRIMARY, name: "Primary", base_url: "http://iris:52773", username: "_SYSTEM", namespace: "USER",
      active: true, primary: true, has_credential: true, last_check: null },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", username: "_SYSTEM", namespace: "USER",
      active: iris2Active, primary: false, has_credential: true, last_check: { status: "compatible" },
      password: SECRET, credential_ref: `CommandCenter.${IRIS2}` },
  ];
}

const storage = new Map();
let dashboard;
let context;

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createElementNS: () => stub(),
    createTextNode: () => stub(),
    addEventListener: () => {},
    dispatchEvent: () => true,
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  globalThis.window = globalThis;
  globalThis.localStorage = {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
  };
  globalThis.fetch = fakeFetch;
  const realSetTimeout = globalThis.setTimeout;
  // The Dashboard polls every 15 s; don't let that keep the test process alive.
  globalThis.setTimeout = (fn, ms, ...args) => {
    const handle = realSetTimeout(fn, ms, ...args);
    handle.unref?.();
    return handle;
  };

  instances = registry();
  context = await import("../frontend/js/instance-context.js");
  dashboard = await import("../frontend/js/dashboard.js");
  dashboard.initDashboardControls();
  await context.refreshInstanceContext();
});

beforeEach(async () => {
  failInstance = null;
  attentionData = {};
  instances = registry();
  await context.refreshInstanceContext();
  context.selectInstanceContext(PRIMARY);
  await settle();
  requests = [];
});

// Let the async refresh (and any follow-up reload) finish.
async function settle() {
  for (let i = 0; i < 20; i += 1) await new Promise((resolve) => setImmediate(resolve));
}

const irisReads = () => requests.filter((r) => r.path !== "/api/iris/instances");
const text = (id) => element(id).textContent;

test("Primary: the existing Dashboard requests, without ?instance=", async () => {
  await dashboard.loadDashboard();
  const reads = irisReads();
  assert.ok(reads.length > 0);
  assert.ok(reads.every((r) => r.instance === null), JSON.stringify(reads));
  for (const path of ["/api/iris/info", "/api/iris/issues", "/api/iris/observability/traces", "/api/iris/operations"]) {
    assert.ok(reads.some((r) => r.path === path), path);
  }
  assert.equal(text("stat-namespaces"), "3");
  assert.equal(text("dashboard-title-scope"), "· Primary");
  assert.equal(element("dashboard-issues-panel").hidden, false);
});

test("IRIS-2 selected: every IRIS read targets IRIS-2, Primary-only panels are hidden", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  const reads = irisReads();
  assert.ok(reads.length > 0);
  assert.ok(reads.every((r) => r.instance === IRIS2), JSON.stringify(reads.map((r) => [r.path, r.instance])));
  for (const path of ["/api/iris/observability/traces", "/api/iris/operations"]) {
    assert.ok(!reads.some((r) => r.path === path), `${path} is Primary-only`);
  }
  // Needs Attention reads IRIS-2's own issues; the Issues & Recommendations panel stays Primary-only.
  assert.ok(reads.some((r) => r.path === "/api/iris/issues" && r.instance === IRIS2));
  assert.equal(text("stat-namespaces"), "6");
  assert.equal(text("stat-processes"), "14");
  assert.equal(text("dashboard-title-scope"), "· IRIS-2");
  assert.match(text("dashboard-context"), /^IRIS-2 \(iris-2:52773\) · IRIS 2026\.2 \(iris-2b1365d07d62\) · API v2$/);
  assert.equal(element("dashboard-issues-panel").hidden, true);
  assert.equal(element("dashboard-activity-panel").hidden, true);
  assert.equal(element("dashboard-demo-activity-button").hidden, true);
  assert.equal(element("stat-grid").dataset.scope, "other");
});

test("switching instances reloads the Dashboard for the new one", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  assert.ok(irisReads().length > 0 && irisReads().every((r) => r.instance === IRIS2));
  requests = [];
  context.selectInstanceContext(PRIMARY);
  await settle();
  assert.ok(irisReads().length > 0 && irisReads().every((r) => r.instance === null));
  assert.equal(text("stat-namespaces"), "3");
});

test("Refresh (loadDashboard) reads the selected instance", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  requests = [];
  await dashboard.loadDashboard();
  const reads = irisReads();
  assert.ok(reads.some((r) => r.path === "/api/iris/info"));
  assert.ok(reads.every((r) => r.instance === IRIS2));
});

test("an unavailable selected instance shows its own error and never falls back to the Primary", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  for (const [status, expected] of [[502, /Could not load data from IRIS-2 \(iris-2:52773\)/], [409, /IRIS-2 is inactive/], [404, /no longer registered/]]) {
    failInstance = { id: IRIS2, status };
    requests = [];
    await dashboard.loadDashboard();
    assert.match(text("error-banner-text"), expected);
    assert.equal(element("error-banner").hidden, false);
    assert.ok(irisReads().every((r) => r.instance === IRIS2), "no Primary read in IRIS-2 context");
    assert.ok(!text("error-banner-text").includes("HTTP"), "no raw backend text");
  }
});

test("an inactive instance can't become the Dashboard's context", async () => {
  instances = registry({ iris2Active: false });
  await context.refreshInstanceContext();
  assert.equal(context.selectInstanceContext(IRIS2), false);
  await settle();
  assert.ok(irisReads().every((r) => r.instance !== IRIS2));
});

test("no password or Wallet reference is sent or shown", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  context.selectInstanceContext(PRIMARY);
  await settle();
  for (const r of requests) {
    assert.ok(r.init.body === undefined, `${r.path} sends no body`);
    assert.ok(!JSON.stringify(r.init.headers || {}).toLowerCase().includes("authorization"));
  }
  const shown = [...elements.values()].map((el) => `${el.textContent}|${el.title}`).join("\n");
  const sent = requests.map((r) => `${r.path}?${r.instance}`).join("\n");
  for (const output of [shown, sent]) {
    assert.ok(!output.includes(SECRET) && !output.includes("CommandCenter.") && !output.includes("credential_ref"));
  }
});

// --- Needs Attention ---

const nodeText = (node) => [node.textContent, ...(node.children || []).map(nodeText)].filter(Boolean).join(" ");
const attentionRows = () => element("dashboard-attention-list").children.map(nodeText);

const CATALOG = {
  database_dismounted: { title: "Dismounted database", severity: "high", resolvable: true },
  journal_purge_archived_off: { title: "Archived journal files are not purged", severity: "low", resolvable: true },
  system_monitor_not_running: { title: "System Monitor not running", severity: "medium", resolvable: false },
};
const DISMOUNTED = { kind: "database_dismounted", database: "IPM", directory: "/usr/irissys/mgr/ipm/", status: "Dismounted" };
const JOURNAL = { kind: "journal_purge_archived_off", archive_name: "journal-archive", purge_archived: false };
// Info as IRIS reports it: Error is the last result's text, Status its code (negative codes are failures).
const task = (name, state, status = "1", error = "Success") =>
  ({ Id: 1, Name: name, State: state, Info: { Status: status, Error: error, Suspended: state === "Suspended" } });

test("attentionItems: detected issues by catalog severity, then task errors and suspended tasks", () => {
  const { items, unavailable } = dashboard.attentionItems(
    { issues: [JOURNAL, DISMOUNTED], resolutions: CATALOG },
    [task("Purge Journal", "Not Running"), task("Integrity Check", "Suspended", "1", ""),
      task("Backup", "Not Running", "-2", "ERROR #5001: disk full")],
  );
  assert.deepEqual(unavailable, []);
  assert.deepEqual(items.map((i) => [i.badge, i.title, i.text, i.action[1]]), [
    ["High", "Dismounted database: IPM", "/usr/irissys/mgr/ipm/ · Dismounted", "issue-resolver"],
    ["Error", "1 task reported an error on the last run", "Backup", "tasks"],
    ["Suspended", "1 suspended task", "Integrity Check. Suspended tasks don't run until they're resumed.", "tasks"],
    ["Low", "Archived journal files are not purged: Journal settings", "ArchiveName journal-archive · PurgeArchived off", "issue-resolver"],
  ]);
});

test("attentionItems: nothing to report, and nothing inferred from data that couldn't be read", () => {
  assert.deepEqual(dashboard.attentionItems({ issues: [], resolutions: CATALOG }, [task("Purge Journal", "Not Running")]),
    { items: [], unavailable: [] });
  const none = dashboard.attentionItems(null, null);
  assert.deepEqual(none.items, []);
  assert.deepEqual(none.unavailable, ["the issue checks", "the task states"]);
  const partial = dashboard.attentionItems(
    { issues: [], resolutions: CATALOG, issue_checks_unavailable: ["system_monitor_not_running"] }, []);
  assert.deepEqual(partial.unavailable, ["some issue checks (System Monitor not running)"]);
  // A last-result text that isn't "Success" is not an error without an error Status code (as on the Tasks page).
  const notFailed = dashboard.attentionItems({ issues: [] }, [
    task("Feature Tracker", "Not Running", "1", "Task Has Expired for 2026-06-28 00:00  Continuing from 2026-10-03"),
    task("Diagnostic Report", "Not Running", "1", ""),
    task("Purge Tasks", "Not Running", "1", "Success"),
  ]);
  assert.deepEqual(notFailed.items, []);
  for (const code of ["-2", "-3", "-4", "-5"]) {
    assert.equal(dashboard.attentionItems({ issues: [] }, [task("Job", "Not Running", code, "x")]).items[0].badge, "Error");
  }
  assert.deepEqual(dashboard.attentionItems({ issues: [] }, [task("Job", "Running", "-1", "")]).items, [], "-1 is running");
  // Long name lists are shortened.
  const many = dashboard.attentionItems({ issues: [] }, ["A", "B", "C", "D", "E"].map((n) => task(n, "Suspended")));
  assert.equal(many.items[0].text, "A, B, C and 2 more. Suspended tasks don't run until they're resumed.");
});

test("Needs Attention, Primary: nothing to report shows a positive empty state", async () => {
  await dashboard.loadDashboard();
  assert.deepEqual(attentionRows(), ["OK Nothing needs attention: no detected issues, suspended tasks or task errors."]);
  assert.equal(text("dashboard-attention-count"), "");
});

test("Needs Attention, IRIS-2: its own issues and task states; links use the normal navigation; nothing is changed", async () => {
  attentionData[IRIS2] = {
    issues: { issues: [DISMOUNTED], resolutions: CATALOG, recommendations: [] },
    tasks: [task("Integrity Check", "Suspended"), task("Purge Tasks", "Not Running")],
  };
  context.selectInstanceContext(IRIS2);
  await settle();
  assert.deepEqual(attentionRows(), [
    "High Dismounted database: IPM /usr/irissys/mgr/ipm/ · Dismounted View Issues →",
    "Suspended 1 suspended task Integrity Check. Suspended tasks don't run until they're resumed. View Tasks →",
  ]);
  assert.equal(text("dashboard-attention-count"), "2 items");
  assert.equal(element("dashboard-issues-panel").hidden, true, "the detailed panel stays Primary-only");
  assert.ok(irisReads().every((r) => r.instance === IRIS2), "nothing falls back to the Primary");
  assert.ok(requests.every((r) => r.method === "GET"), "detection only");

  const nav = await import("../frontend/js/nav.js");
  const opened = [];
  nav.initNavigation((view) => opened.push(view));
  const [issueRow, taskRow] = element("dashboard-attention-list").children;
  requests = [];
  issueRow.children[2].listeners.click[0]();
  taskRow.children[2].listeners.click[0]();
  assert.deepEqual(opened, ["issue-resolver", "tasks"]);
  assert.deepEqual(requests, [], "a link only navigates; the page it opens loads as usual");
});

test("Needs Attention: data that couldn't be read is said, not shown as all clear", async () => {
  attentionData[PRIMARY] = { issues: { detail: "no issues field" }, tasks: [task("Integrity Check", "Suspended")] };
  await dashboard.loadDashboard();
  const rows = attentionRows();
  assert.equal(rows.length, 2);
  assert.match(rows[0], /^Suspended 1 suspended task/);
  assert.equal(rows[1], "Unavailable Couldn't read the issue checks right now. Try Refresh.");
  assert.ok(!rows.some((row) => row.startsWith("OK")));
});
