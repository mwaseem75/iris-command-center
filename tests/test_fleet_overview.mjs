// Fleet Overview (frontend/js/fleet.js), tested without a browser like
// tests/test_dashboard_context.mjs: a minimal stand-in DOM, a fake fetch()
// that records every request and answers per instance like the backend, and
// the real fleet.js and instance-context.js modules.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_fleet_overview.mjs

import assert from "node:assert/strict";
import { before, beforeEach, test } from "node:test";

const PRIMARY = "primary";
const IRIS2 = "iris-2b1365d07d62";
const IRIS3 = "iris-3c0ffee00001";
const OFF = "iris-0ff0ff0ff0ff";
const SECRET = "Pw-FLEET-CANARY-not-real";

const elements = new Map();

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", title: "", className: "", type: "",
    style: { setProperty() {} }, attributes: {}, disabled: false, children: [], listeners: {} };
  const self = new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "append") return (...nodes) => { props.children.push(...nodes); };
      if (key === "replaceChildren") return (...nodes) => { props.children = [...nodes]; };
      if (key === "addEventListener") return (type, fn) => { (props.listeners[type] ||= []).push(fn); };
      if (key === "setAttribute") return (name, value) => { props.attributes[name] = String(value); };
      if (key === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      if (key === "querySelectorAll") return () => [];
      return () => stub();
    },
    set(_, key, value) {
      props[key] = value;
      return true;
    },
  });
  return self;
}

function element(id) {
  if (!elements.has(id)) elements.set(id, stub(id));
  return elements.get(id);
}

function text(node) {
  return [node.textContent, ...node.children.map(text)].filter(Boolean).join(" ");
}

let requests = [];
let instances = [];
let failing = new Set();
let healthStillAnswers = false;  // like the backend: /health is 200 "unavailable" when IRIS is down

function envelope(result) {
  return { status: { errors: [] }, result };
}

function answer(path, instance) {
  const who = instance || PRIMARY;
  const n = { [PRIMARY]: 1, [IRIS2]: 2, [IRIS3]: 3 }[who];
  const list = (k) => envelope(Array.from({ length: n * k }, (_, i) => ({
    Name: `${who}-${i}`, Status: i === 0 ? "Dismounted" : "Mounted/RW", Enabled: i !== 0, Size: 100,
  })));
  switch (path) {
    case "/api/iris/instances": return { instances };
    case "/api/iris/info": return envelope({ serverVersion: `IRIS for UNIX 2026.2 (Build ${n}21U)`, apiVersion: 2, product: "iris" });
    case "/api/iris/namespaces": return list(3);
    case "/api/iris/databases": return list(2);
    case "/api/iris/processes": return list(7);
    case "/api/iris/web-apps": return list(5);
    case "/api/iris/tasks": return list(4);
    case "/api/iris/databases/storage": return list(2);
    case "/api/iris/health": return {
      status: who === PRIMARY ? "healthy" : "partial",
      findings: Array.from({ length: n - 1 }, (_, i) => ({ severity: i ? "low" : "high", title: `${who} finding ${i}` })),
    };
    case "/api/iris/monitor/dashboard": return envelope({
      Status: { UpTime: `${n}d 1h` }, Licensing: { LicenseUse: 10 * n },
      Performance: { GlobalRefsPerSecond: 100 * n, CacheEfficiency: 12.5 }, SystemUsage: { CSPSessions: n },
    });
    default: return envelope([]);
  }
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  const instance = parsed.searchParams.get("instance");
  requests.push({ path: parsed.pathname, instance, init });
  if (instance && failing.has(instance) && healthStillAnswers && parsed.pathname === "/api/iris/health") {
    return { ok: true, status: 200, json: async () => ({ status: "unavailable", findings: [] }) };
  }
  if (instance && failing.has(instance)) return { ok: false, status: 502, json: async () => ({ detail: "Could not connect to IRIS" }) };
  return { ok: true, status: 200, json: async () => answer(parsed.pathname, instance) };
}

function registry({ withIris3 = false, withInactive = false } = {}) {
  const list = [
    { id: PRIMARY, name: "Primary", base_url: "http://iris:52773", active: true, primary: true, last_check: null },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", active: true, primary: false,
      last_check: { status: "compatible", checked_at: "2026-10-01T08:40:53Z" }, password: SECRET, credential_ref: `CommandCenter.${IRIS2}` },
  ];
  if (withIris3) list.push({ id: IRIS3, name: "IRIS-3", base_url: "http://iris-3:52773", active: true, primary: false, last_check: null });
  if (withInactive) list.push({ id: OFF, name: "Old", base_url: "http://old:52773", active: false, primary: false, last_check: null });
  return list;
}

let fleet;
let context;
const filterButtons = ["active", "all"].map((value) => {
  const button = stub();
  button.dataset.fleetFilter = value;
  return button;
});

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createElementNS: () => stub(),
    createTextNode: () => stub(),
    addEventListener() {},
    dispatchEvent: () => true,
    querySelectorAll: (selector) => (selector === "[data-fleet-filter]" ? filterButtons : []),
    querySelector: () => null,
  };
  globalThis.window = globalThis;
  const storage = new Map();
  globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)) };
  globalThis.fetch = fakeFetch;
  context = await import("../frontend/js/instance-context.js");
  fleet = await import("../frontend/js/fleet.js");
  fleet.initFleetControls();
});

beforeEach(() => {
  requests = [];
  failing = new Set();
  healthStillAnswers = false;
  instances = registry();
});

const reads = () => requests.filter((r) => r.path !== "/api/iris/instances");
const kpi = (i) => text(element("fleet-kpis").children[i].children[1]);  // the card body, without its icon
const rows = () => element("fleet-table-body").children.map(text);

test("Primary + IRIS-2: each instance is read with its own id, never ?instance=all", async () => {
  await fleet.loadFleet();
  const byInstance = (id) => reads().filter((r) => r.instance === id).map((r) => r.path).sort();
  const nine = ["/api/iris/databases", "/api/iris/databases/storage", "/api/iris/health", "/api/iris/info",
    "/api/iris/monitor/dashboard", "/api/iris/namespaces", "/api/iris/processes", "/api/iris/tasks", "/api/iris/web-apps"];
  assert.deepEqual(byInstance(null), nine);   // the Primary, without ?instance=
  assert.deepEqual(byInstance(IRIS2), nine);
  assert.ok(reads().every((r) => r.instance === null || r.instance === IRIS2));
  assert.ok(!requests.some((r) => r.instance === "all"));
});

test("KPIs and the table add up the real per-instance values", async () => {
  await fleet.loadFleet();
  assert.match(kpi(0), /^2 Active Instances of 2 registered · 2 reachable$/);
  assert.match(kpi(1), /^9 Total Namespaces Across 2 instances$/);   // 3 + 6
  assert.match(kpi(2), /^21 Processes/);                             // 7 + 14
  assert.match(kpi(3), /^12 Scheduled Tasks/);                       // 4 + 8
  assert.match(kpi(4), /^1 Health Findings/);                        // 0 + 1
  const [primary, iris2] = rows();
  assert.match(primary, /^Primary ★ Primary · iris:52773 healthy 2026\.2 \(121U\) 3 2 7 5 4 0 1d 1h 10% —/);
  assert.match(iris2, /^IRIS-2 iris-2:52773 partial 2026\.2 \(221U\) 6 4 14 10 8 1 2d 1h 20% /);
  assert.equal(element("fleet-namespaces-chart").children.length, 2);
  assert.match(text(element("fleet-findings-list")), /High IRIS-2 IRIS-2 finding 0|High IRIS-2 iris-2b1365d07d62 finding 0/);
});

test("three instances: all three are read and charted", async () => {
  instances = registry({ withIris3: true });
  await fleet.loadFleet();
  assert.deepEqual([...new Set(reads().map((r) => r.instance))].sort((a, b) => String(a).localeCompare(String(b))),
    [IRIS2, IRIS3, null].sort((a, b) => String(a).localeCompare(String(b))));
  assert.match(kpi(1), /^18 Total Namespaces Across 3 instances$/);  // 3 + 6 + 9
  assert.equal(element("fleet-namespaces-chart").children.length, 3);
  assert.equal(element("fleet-storage-chart").children.length, 3);
});

test("one instance failing: it shows as unavailable and the others still load", async () => {
  instances = registry({ withIris3: true });
  failing = new Set([IRIS2]);
  await fleet.loadFleet();
  const table = rows();
  assert.match(table[1], /^IRIS-2 iris-2:52773 Unavailable — — — — — — — — — /);
  assert.match(table[2], /^IRIS-3 iris-3:52773 partial/);
  assert.match(kpi(0), /2 reachable$/);
  assert.match(kpi(1), /^12 Total Namespaces Across 2 of 3 instances$/);  // 3 + 9, IRIS-2 not counted
  assert.match(text(element("fleet-health-rings")), /67% 2 \/ 3 Instances Reachable/);
  // Nothing of IRIS-2's was asked of the Primary instead.
  assert.ok(reads().filter((r) => r.instance === null).length === 9);
});

test("an instance whose only answer is a 200 'unavailable' health report is not reachable", async () => {
  instances = registry({ withIris3: true });
  failing = new Set([IRIS2]);
  healthStillAnswers = true;
  await fleet.loadFleet();
  assert.match(rows()[1], /^IRIS-2 iris-2:52773 Unavailable — — — — — — — — — /);
  assert.match(kpi(0), /2 reachable$/);
  assert.match(text(element("fleet-health-rings")), /67% 2 \/ 3 Instances Reachable/);
  assert.match(kpi(4), /^2 Health Findings Across 2 of 3 instances$/);  // IRIS-3's two; IRIS-2's empty list isn't counted
});

test("no active user-defined instances: only the Primary is read", async () => {
  instances = registry().slice(0, 1).concat({ ...registry()[1], active: false });
  await fleet.loadFleet();
  assert.ok(reads().length === 9 && reads().every((r) => r.instance === null));
  assert.match(kpi(0), /^1 Active Instances of 2 registered · 1 reachable$/);
  assert.equal(rows().length, 1);
});

test("inactive instances are never read; 'All Instances' lists them as inactive", async () => {
  instances = registry({ withInactive: true });
  await fleet.loadFleet();
  assert.ok(!reads().some((r) => r.instance === OFF));
  assert.equal(rows().length, 2);
  filterButtons[1].listeners.click[0]();  // All Instances
  assert.equal(rows().length, 3);
  assert.match(rows()[2], /^Old old:52773 Inactive — — /);
  assert.equal(element("fleet-namespaces-chart").children.length, 2);  // charts: active instances only
  filterButtons[0].listeners.click[0]();  // back to Active Only
  assert.equal(rows().length, 2);
});

test("'Open' selects the instance in the global selector", async () => {
  await context.refreshInstanceContext();
  await fleet.loadFleet();
  const [click] = element("fleet-table-body").listeners.click;
  click({ target: { closest: () => ({ dataset: { fleetOpen: IRIS2 } }) } });
  assert.equal(context.getInstanceContext().instanceId, IRIS2);
  click({ target: { closest: () => ({ dataset: { fleetOpen: PRIMARY } }) } });
  assert.equal(context.getInstanceContext().instanceId, PRIMARY);
});

test("no password or Wallet reference is sent or shown", async () => {
  instances = registry({ withIris3: true, withInactive: true });
  await fleet.loadFleet();
  for (const r of requests) {
    assert.equal(r.init.body, undefined);
    assert.ok(!JSON.stringify(r.init.headers || {}).toLowerCase().includes("authorization"));
  }
  const shown = [...elements.values()].map(text).join("\n");
  assert.ok(!shown.includes(SECRET) && !shown.includes("CommandCenter.") && !shown.includes("credential_ref"));
});
