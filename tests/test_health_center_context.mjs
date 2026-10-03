// Instance-aware Health Center (frontend/js/health-center.js), tested without
// a browser like tests/test_dashboard_context.mjs: a minimal stand-in DOM, a
// fake fetch() that records requests and answers like the backend, and the
// real health-center.js and instance-context.js modules.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_health_center_context.mjs

import assert from "node:assert/strict";
import { before, beforeEach, test } from "node:test";

const PRIMARY = "primary";
const IRIS2 = "iris-2b1365d07d62";
const SECRET = "Pw-HEALTH-CANARY-not-real";

const elements = new Map();

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", title: "", className: "", style: { setProperty() {} },
    attributes: {}, disabled: false, children: [] };
  return new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "setAttribute") return (name, value) => { props.attributes[name] = String(value); };
      if (key === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      if (key === "querySelectorAll") return () => [];
      if (key === "append") return (...nodes) => { props.children.push(...nodes); };
      if (key === "replaceChildren") return (...nodes) => { props.children = [...nodes]; };
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

let requests = [];
let instances = [];
let fail = null;  // { id, status }
let gate = null;  // a promise that holds back IRIS-2 answers
let reportOverride = null;  // the /health answer for a test, if set

function report(who) {
  return { generated_at: "2026-10-01T10:00:00Z", status: "healthy", overall_score: who === PRIMARY ? 100 : 95,
    score_method: "", penalty_weights: {}, categories: [], findings: [], recommendations: [], unavailable_sources: [] };
}

function answer(path, instance) {
  const who = instance || PRIMARY;
  const n = who === PRIMARY ? 1 : 2;
  const list = (k) => ({ status: { errors: [] }, result: Array.from({ length: n * k }, (_, i) => ({ Name: `${who}-${i}` })) });
  switch (path) {
    case "/api/iris/instances": return { instances };
    case "/api/iris/health": return reportOverride ?? report(who);
    case "/api/iris/info": return { status: { errors: [] }, result: { apiVersion: 2, serverVersion: `IRIS 2026.2 (${who})`, product: "iris", systemMode: "", namespaces: [] } };
    case "/api/iris/monitor/dashboard": return { status: { errors: [] }, result: null };
    case "/api/iris/processes": return list(7);
    case "/api/iris/namespaces": return list(3);
    case "/api/iris/databases": return list(5);
    case "/api/iris/web-apps": return list(11);
    case "/api/iris/tasks": return list(13);
    default: return { status: { errors: [] }, result: [] };
  }
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  const instance = parsed.searchParams.get("instance");
  requests.push({ path: parsed.pathname, instance, init });
  if (gate && instance === IRIS2) await gate;
  if (fail && instance === fail.id) return { ok: false, status: fail.status, json: async () => ({}) };
  return { ok: true, status: 200, json: async () => answer(parsed.pathname, instance) };
}

function registry({ iris2Active = true } = {}) {
  return [
    { id: PRIMARY, name: "Primary", base_url: "http://iris:52773", active: true, primary: true },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", active: iris2Active, primary: false,
      last_check: { status: "compatible" }, password: SECRET, credential_ref: `CommandCenter.${IRIS2}` },
  ];
}

let health;
let context;

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createElementNS: () => stub(),
    createTextNode: (value) => { const node = stub(); node.textContent = String(value); return node; },
    addEventListener() {},
    dispatchEvent: () => true,
    querySelectorAll: () => [],
  };
  globalThis.window = globalThis;
  const storage = new Map();
  globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)) };
  globalThis.fetch = fakeFetch;
  instances = registry();
  context = await import("../frontend/js/instance-context.js");
  health = await import("../frontend/js/health-center.js");
  health.initHealthCenterControls();
  await context.refreshInstanceContext();
});

beforeEach(async () => {
  fail = null;
  reportOverride = null;
  gate = null;
  instances = registry();
  await context.refreshInstanceContext();
  context.selectInstanceContext(PRIMARY);
  await settle();
  requests = [];
});

async function settle() {
  for (let i = 0; i < 20; i += 1) await new Promise((resolve) => setImmediate(resolve));
}

const reads = () => requests.filter((r) => r.path !== "/api/iris/instances");
const text = (id) => element(id).textContent;
const shown = (id) => !element(id).hidden;

test("Primary: the existing Health Center reads, without ?instance=", async () => {
  await health.loadHealthCenter();
  assert.deepEqual(reads().map((r) => r.path).sort(),
    ["/api/iris/health", "/api/iris/info", "/api/iris/monitor/dashboard", "/api/iris/processes"]);
  assert.ok(reads().every((r) => r.instance === null));
  assert.equal(text("health-center-title-scope"), "· Primary");
  assert.equal(text("health-center-context-name"), "Primary");
  assert.equal(text("health-center-context-meta"), "iris:52773 · IRIS 2026.2 (primary) · API v2");
  assert.ok(shown("health-center-content") && !shown("health-center-error"));
});

test("IRIS-2 selected: the switch reloads, and every read targets IRIS-2", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  assert.equal(reads().length, 4);
  assert.ok(reads().every((r) => r.instance === IRIS2), JSON.stringify(reads()));
  assert.equal(text("health-center-title-scope"), "· IRIS-2");
  assert.equal(text("health-center-context-meta"), `iris-2:52773 · IRIS 2026.2 (${IRIS2}) · API v2`);
  assert.ok(shown("health-center-content"));
});

test("switching back to the Primary reloads its own data", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  requests = [];
  context.selectInstanceContext(PRIMARY);
  await settle();
  assert.ok(reads().length === 4 && reads().every((r) => r.instance === null));
  assert.equal(text("health-center-context-name"), "Primary");
});

test("manual refresh reads the selected instance", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  requests = [];
  await health.loadHealthCenter();  // what the Run Health Check button calls
  assert.ok(reads().length === 4 && reads().every((r) => r.instance === IRIS2));
});

test("an unreachable IRIS-2 shows its own error and no Primary data", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  fail = { id: IRIS2, status: 502 };
  requests = [];
  await health.loadHealthCenter();
  assert.ok(shown("health-center-error") && !shown("health-center-content"));
  assert.equal(text("health-center-error-text"),
    "Could not run the health check on IRIS-2 (iris-2:52773). The instance may be unreachable or may have rejected its stored credentials.");
  assert.ok(reads().every((r) => r.instance === IRIS2), "no Primary read");

  fail = null;  // it comes back
  await health.loadHealthCenter();
  assert.ok(!shown("health-center-error") && shown("health-center-content"));
});

test("inactive or unregistered IRIS-2 gets its own message", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  for (const [status, expected] of [[409, /^IRIS-2 \(iris-2:52773\) is inactive\./], [404, /is no longer registered\./]]) {
    fail = { id: IRIS2, status };
    await health.loadHealthCenter();
    assert.match(text("health-center-error-text"), expected);
    assert.ok(!text("health-center-error-text").includes("HTTP"));
  }
  // An inactive instance can't be selected in the first place.
  instances = registry({ iris2Active: false });
  await context.refreshInstanceContext();
  assert.equal(context.selectInstanceContext(IRIS2), false);
});

test("a slow IRIS-2 answer after switching back is ignored (no stale data)", async () => {
  let release;
  gate = new Promise((resolve) => { release = resolve; });
  context.selectInstanceContext(IRIS2);
  await settle();
  context.selectInstanceContext(PRIMARY);
  await settle();
  release();
  await settle();
  assert.equal(text("health-center-context-name"), "Primary");
  assert.equal(text("health-center-context-meta"), "iris:52773 · IRIS 2026.2 (primary) · API v2");
});

test("no password or Wallet reference is sent or shown", async () => {
  context.selectInstanceContext(IRIS2);
  await settle();
  context.selectInstanceContext(PRIMARY);
  await settle();
  for (const r of requests) {
    assert.equal(r.init.body, undefined);
    assert.ok(!JSON.stringify(r.init.headers || {}).toLowerCase().includes("authorization"));
  }
  const output = [...elements.values()].map((e) => `${e.textContent}|${e.title}|${JSON.stringify(e.dataset)}`).join("\n")
    + requests.map((r) => r.path + r.instance).join("\n");
  assert.ok(!output.includes(SECRET) && !output.includes("CommandCenter.") && !output.includes("credential_ref"));
});

// --- per-check results and the summary ---

const nodeText = (node) => [node.textContent, ...(node.children || []).map(nodeText)].filter(Boolean).join(" ");

const check = (check_id, status, extra = {}) => ({ check_id, status, source: "GET /v2/x", condition: "the condition",
  evidence: [], reason: null, ...extra });
const observed = (field, observed_value) => ({ source: "GET /v2/x", field, observed_value, value_status: "observed",
  condition: "the condition" });
const category = (id, status, checks, findings = [], extra = {}) => ({ id, name: id, status, score: null,
  checks_completed: checks.filter((c) => c.status !== "not_assessed").length, checks_total: checks.length,
  evidence: [], findings, unavailable_sources: [], checks, ...extra });
const finding = (severity) => ({ id: "f", check_id: "x", category: "x", severity, title: "T", explanation: "E",
  evidence: [], recommendation: null, investigation: null });

test("each check shows its outcome and what it observed; the summary counts detected issues separately", async () => {
  reportOverride = { generated_at: "2026-10-03T10:00:00Z", status: "partial", overall_score: 95, score_method: "",
    penalty_weights: {}, findings: [], recommendations: [], unavailable_sources: [], categories: [
      category("tasks", "healthy", [check("task_manager_not_running", "passed", { evidence: [observed("Status", "Running")] })],
        [], { score: 100 }),
      category("system", "warning", [check("system_monitor_not_running", "issue_detected",
        { evidence: [observed("SystemMonitor", false)] })], [finding("medium")], { score: 90 }),
      category("security", "partial", [check("audit_status", "issue_detected", { evidence: [observed("Enabled", false)] })],
        [finding("high")]),
      category("databases", "partial", [
        check("database_dismounted", "passed", { evidence: [observed("Databases checked", 10)] }),
        check("database_full", "not_assessed", { reason: "IRIS data for this check could not be read or evaluated." }),
      ]),
      category("performance", "not_assessed", []),
      category("web-applications", "unavailable", [check("web_app_namespace_missing", "not_assessed", { reason: "no data" })]),
    ] };
  await health.loadHealthCenter();
  await settle();

  const cards = element("health-center-categories").children.map(nodeText);
  assert.match(cards[0], /Task manager ✓ Passed Status: Running Technical details Source: GET \/v2\/x Reports an issue when: the condition/);
  assert.match(cards[2], /1 issue detected · 1 of 1 check completed\./, "an unscored category says its issue first");
  assert.match(cards[2], /Audit status ⚠ Issue detected Audit enabled: false/);
  assert.match(cards[3], /Database mounts ✓ Passed Databases checked: 10/);
  assert.match(cards[3], /Database capacity — Not assessed IRIS data for this check could not be read or evaluated\./);
  assert.doesNotMatch(cards[3], /Database capacity ✓/, "an unavailable check is never shown as passed");

  const summary = element("health-center-summary").children.map(nodeText);
  assert.deepEqual(summary, ["1 Healthy", "2 Needs Attention", "0 Critical", "1 Partially Assessed", "2 Not Assessed"]);
});

test("a critical finding counts as Critical, not Needs Attention", async () => {
  reportOverride = { generated_at: "2026-10-03T10:00:00Z", status: "critical", overall_score: 60, score_method: "",
    penalty_weights: {}, findings: [], recommendations: [], unavailable_sources: [], categories: [
      category("databases", "critical", [check("database_full", "issue_detected")], [finding("critical")], { score: 60 }),
    ] };
  await health.loadHealthCenter();
  await settle();
  assert.deepEqual(element("health-center-summary").children.map(nodeText),
    ["0 Healthy", "0 Needs Attention", "1 Critical", "0 Partially Assessed", "0 Not Assessed"]);
});
