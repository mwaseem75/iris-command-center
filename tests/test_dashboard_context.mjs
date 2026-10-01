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
    classList: classList(), attributes: {}, disabled: false, value: "" };
  return new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "setAttribute") return (name, value) => { props.attributes[name] = String(value); };
      if (key === "getAttribute") return (name) => props.attributes[name] ?? null;
      if (key === "querySelectorAll") return () => [];
      if (key === "closest") return () => null;
      if (key === "contains") return () => false;
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
    case "/api/iris/tasks/overview": return envelope(list(13));
    case "/api/iris/databases/storage": return envelope([]);
    case "/api/iris/monitor/dashboard": return envelope(null); // no counters: panels show "unavailable"
    case "/api/iris/observability/traces": return { traces: [] };
    case "/api/iris/operations": return { operations: [] };
    case "/api/iris/issues": return { issues: [], recommendations: [] };
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
      active: iris2Active, primary: false, has_credential: true, last_check: null,
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
  for (const path of ["/api/iris/issues", "/api/iris/observability/traces", "/api/iris/operations"]) {
    assert.ok(!reads.some((r) => r.path === path), `${path} is Primary-only`);
  }
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

test("All Active Instances: the five counts summed over the active instances, with a note", async () => {
  context.selectInstanceContext(context.ALL_ACTIVE);
  await settle();
  const reads = irisReads();
  const scoped = new Set(reads.map((r) => `${r.path}|${r.instance}`));
  for (const path of ["/api/iris/namespaces", "/api/iris/databases", "/api/iris/processes", "/api/iris/web-apps", "/api/iris/tasks"]) {
    assert.ok(scoped.has(`${path}|null`) && scoped.has(`${path}|${IRIS2}`), path);
  }
  assert.ok(!reads.some((r) => ["/api/iris/monitor/dashboard", "/api/iris/issues", "/api/iris/info"].includes(r.path)));
  assert.equal(text("stat-namespaces"), String(3 + 6));
  assert.equal(text("stat-databases"), String(5 + 10));
  assert.equal(text("stat-processes"), String(7 + 14));
  assert.equal(text("stat-web-apps"), String(11 + 22));
  assert.equal(text("stat-tasks"), String(13 + 26));
  assert.equal(text("dashboard-title-scope"), "(All Active Instances)");
  assert.equal(text("dashboard-fleet-note-text"),
    "Showing combined counts from 2 active instances: Primary (iris:52773), IRIS-2 (iris-2:52773).");
  assert.equal(element("dashboard-main-grid").hidden, true);
  assert.equal(element("stat-alerts-card").hidden, true);
});

test("All Active Instances: an instance that can't be read is named, not counted", async () => {
  failInstance = { id: IRIS2, status: 502 };
  context.selectInstanceContext(context.ALL_ACTIVE);
  await settle();
  assert.equal(text("stat-namespaces"), "3");
  assert.match(text("dashboard-fleet-note-text"), /Not included \(could not be read\): IRIS-2 \(iris-2:52773\)\./);
});

test("no password or Wallet reference is sent or shown", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  context.selectInstanceContext(context.ALL_ACTIVE);
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
