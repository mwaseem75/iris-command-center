// Fleet Overview (frontend/js/fleet.js), tested without a browser like
// tests/test_dashboard_context.mjs: a minimal stand-in DOM, a fake fetch()
// that records every request and answers per instance like the backend, and
// the real fleet.js, nav.js, web-apps.js and instance-context.js modules.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_fleet_overview.mjs

import assert from "node:assert/strict";
import { before, beforeEach, mock, test } from "node:test";

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

function* walk(node) {
  yield node;
  for (const child of node.children) yield* walk(child);
}

let requests = [];
let instances = [];
let failing = new Set();
let healthStillAnswers = false;  // like the backend: /health is 200 "unavailable" when IRIS is down

function envelope(result) {
  return { status: { errors: [] }, result };
}

// Every instance answers with its own, clearly different values (n = 1, 2, 3).
function answer(path, instance) {
  const who = instance || PRIMARY;
  const n = { [PRIMARY]: 1, [IRIS2]: 2, [IRIS3]: 3 }[who];
  switch (path) {
    case "/api/iris/instances": return { instances };
    case "/api/iris/info": return envelope({ serverVersion: `IRIS for UNIX 2026.2 (Build ${n}21U)`, apiVersion: 2, product: "iris" });
    case "/api/iris/processes": return envelope(Array.from({ length: 7 * n }, (_, i) => ({ Pid: i, Namespace: who })));
    case "/api/iris/health": return {
      status: who === PRIMARY ? "healthy" : "partial",
      findings: Array.from({ length: n - 1 }, (_, i) => ({ severity: "high", title: `${who} finding ${i}` })),
    };
    case "/api/iris/monitor/dashboard": return envelope({
      Performance: { GlobalRefsPerSecond: 100 * n, GlobalRefs: 1000000 * n, DiskReads: 1000 * n, DiskWrites: 500 * n,
        CacheEfficiency: 90 + n },
      Status: { UpTime: `${n}d  1h 0${n}m`, LastBackup: "Never", SystemMonitor: true },
      SystemUsage: { DatabaseSpace: "Normal", DatabaseJournal: "Normal", JournalSpace: n === 2 ? "Troubled" : "Normal",
        CSPSessions: 4 * n, Processes: 99 },
      Alerts: { SeriousAlerts: n - 1, ApplicationErrors: 0 },
      Licensing: { LicenseLimit: 5, LicenseUse: 10 * n, LicenseUseHigh: 15 * n },
    });
    default: return envelope([]);
  }
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  const instance = parsed.searchParams.get("instance");
  requests.push({ path: parsed.pathname, instance, init });
  if (instance && failing.has(instance)) {
    if (healthStillAnswers && parsed.pathname === "/api/iris/health") {
      return { ok: true, status: 200, json: async () => ({ status: "unavailable", findings: [] }) };
    }
    return { ok: false, status: 502, json: async () => ({ detail: "Could not connect to IRIS" }) };
  }
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
let webApps;
let navigations = [];

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createElementNS: () => stub(),
    createTextNode: () => stub(),
    addEventListener() {},
    dispatchEvent: () => true,
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  globalThis.window = globalThis;
  const storage = new Map();
  globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)) };
  globalThis.fetch = fakeFetch;
  // The page isn't shown, so loadFleet() doesn't start the 15 s refresh cycle
  // (the polling test shows it).
  element("view-fleet").hidden = true;
  context = await import("../frontend/js/instance-context.js");
  const nav = await import("../frontend/js/nav.js");
  nav.initNavigation((view) => navigations.push(view));
  fleet = await import("../frontend/js/fleet.js");
  webApps = await import("../frontend/js/web-apps.js");
  fleet.initFleetControls();
});

beforeEach(() => {
  requests = [];
  navigations = [];
  failing = new Set();
  healthStillAnswers = false;
  instances = registry();
});

const reads = () => requests.filter((r) => r.path !== "/api/iris/instances");
const sections = () => element("fleet-instances").children;
const section = (id) => sections().find((node) => node.dataset.instanceId === id);
const links = (node) => [...walk(node)].filter((n) => n.dataset && n.dataset.fleetView);
const trendSamples = (id) => {
  const legend = [...walk(section(id))].find((n) => n.className === "dash-trend__legend");
  return legend ? Number(legend.textContent.split(" ")[0]) : 0;
};
const FULL_READS = ["/api/iris/health", "/api/iris/info", "/api/iris/monitor/dashboard", "/api/iris/processes"];

test("Primary + IRIS-2: each instance is read on its own, only with GETs, never ?instance=all", async () => {
  await fleet.loadFleet();
  const byInstance = (id) => reads().filter((r) => r.instance === id).map((r) => r.path).sort();
  assert.deepEqual(byInstance(null), FULL_READS);   // the Primary, without ?instance=
  assert.deepEqual(byInstance(IRIS2), FULL_READS);
  assert.ok(reads().every((r) => r.instance === null || r.instance === IRIS2));
  assert.ok(!requests.some((r) => r.instance === "all"));
  for (const r of requests) {
    assert.ok(!r.init.method || r.init.method === "GET", `${r.path} is a GET`);
    assert.equal(r.init.body, undefined);
  }
});

test("each instance has its own section with only its own values; nothing is combined", async () => {
  await fleet.loadFleet();
  assert.deepEqual(sections().map((node) => node.dataset.instanceId), [PRIMARY, IRIS2]);
  assert.equal(element("fleet-count").textContent, "2 / 2");

  const primary = text(section(PRIMARY));
  assert.match(primary, /^⬢ Primary ★ Primary iris:52773 Status Connected IRIS 2026\.2 \(121U\) Uptime 1d 1h 01m /);
  assert.match(primary, /Database Normal Journal Normal Alerts 0 Health: Healthy · 0 findings/);
  assert.match(primary, /Processes View → 7 Global References \/ sec View → 100 \/s Web Sessions View → 4 License Usage View → 10% peak 15%/);
  assert.match(primary, /Cache Efficiency 91 Global References Since Startup 1M Disk Reads Since Startup 1K Disk Writes Since Startup 500/);

  const iris2 = text(section(IRIS2));
  assert.match(iris2, /^⬢ IRIS-2 iris-2:52773 Status Connected IRIS 2026\.2 \(221U\) Uptime 2d 1h 02m /);
  assert.match(iris2, /Database Normal Journal Troubled Alerts 1 Health: Partial · 1 finding/);
  assert.match(iris2, /Processes View → 14 Global References \/ sec View → 200 \/s Web Sessions View → 8 License Usage View → 20% peak 30%/);
  assert.match(iris2, /Cache Efficiency 92 Global References Since Startup 2M Disk Reads Since Startup 2K Disk Writes Since Startup 1K/);

  // No Primary value in IRIS-2's section, and the other way round.
  assert.ok(!iris2.includes("121U") && !iris2.includes("★") && !primary.includes("221U") && !primary.includes("Troubled"));
  // No fleet totals anywhere (7 + 14 processes, 100 + 200 refs/s).
  const page = sections().map(text).join(" ");
  assert.ok(!/\b21\b/.test(page) && !page.includes("300 /s"));
});

test("three instances: three sections, in registry order", async () => {
  instances = registry({ withIris3: true });
  await fleet.loadFleet();
  assert.deepEqual(sections().map((node) => node.dataset.instanceId), [PRIMARY, IRIS2, IRIS3]);
  assert.match(text(section(IRIS3)), /^⬢ IRIS-3 iris-3:52773 Status Connected IRIS 2026\.2 \(321U\)/);
  assert.equal(element("fleet-count").textContent, "3 / 3");
});

test("one instance unavailable: only its section says so; the others load and nothing falls back to the Primary", async () => {
  instances = registry({ withIris3: true });
  failing = new Set([IRIS2]);
  await fleet.loadFleet();
  const iris2 = section(IRIS2);
  assert.equal(iris2.dataset.state, "unavailable");
  assert.match(text(iris2), /^⬢ IRIS-2 iris-2:52773 Status Unavailable — Uptime — Database — Journal — Alerts — No health report View Details → IRIS-2 could not be read \(HTTP 502\)\. The other instances are not affected\.$/);
  assert.equal(section(PRIMARY).dataset.state, "ok");
  assert.match(text(section(PRIMARY)), /Processes View → 7 /);
  assert.equal(section(IRIS3).dataset.state, "ok");
  assert.match(text(section(IRIS3)), /Processes View → 21 /);
  assert.equal(reads().filter((r) => r.instance === null).length, 4);  // the Primary's own four reads only
});

test("an instance whose only answer is a 200 'unavailable' health report is unavailable", async () => {
  failing = new Set([IRIS2]);
  healthStillAnswers = true;
  await fleet.loadFleet();
  assert.equal(section(IRIS2).dataset.state, "unavailable");
  assert.match(text(section(IRIS2)), /Status Unavailable .* No health report /);
  assert.equal(section(PRIMARY).dataset.state, "ok");
});

test("inactive instances are never read or shown; the note says how many", async () => {
  instances = registry({ withInactive: true });
  await fleet.loadFleet();
  assert.ok(!requests.some((r) => r.instance === OFF));
  assert.deepEqual(sections().map((node) => node.dataset.instanceId), [PRIMARY, IRIS2]);
  assert.equal(element("fleet-count").textContent, "2 / 3");
  assert.equal(element("fleet-note").hidden, false);
  assert.match(element("fleet-note").textContent, /^1 inactive instance is not shown/);
});

test("View links select that instance and open the existing page for it", async () => {
  await context.refreshInstanceContext();
  await fleet.loadFleet();
  const expected = [
    ["dashboard", undefined],                     // View Details
    ["databases", undefined],
    ["journal", undefined],
    ["health-center", undefined],                 // Alerts / health
    ["processes", undefined],
    ["dashboard", "dashboard-resources-title"],   // Global References / sec
    ["web-apps", undefined],                      // Web Sessions
    ["dashboard", "stat-license"],                // License Usage
    ["dashboard", "dashboard-resources-title"],   // the trend panel
    ["dashboard", "dashboard-resources-title"],   // Performance Context
  ];
  const [click] = element("fleet-instances").listeners.click;
  for (const id of [IRIS2, PRIMARY]) {
    const found = links(section(id));
    assert.deepEqual(found.map((n) => [n.dataset.fleetView, n.dataset.fleetAnchor]).sort(), [...expected].sort());
    assert.ok(found.every((n) => n.dataset.fleetOpen === id), "every link in a section is for that section's instance");
    assert.deepEqual(found.filter((n) => n.dataset.fleetFocus).map((n) => [n.dataset.fleetView, n.dataset.fleetFocus]),
      [["web-apps", "web-sessions"]]);
    for (const button of found) {
      navigations = [];
      click({ target: { closest: () => button } });
      assert.equal(context.getInstanceContext().instanceId, id);
      assert.deepEqual(navigations, [button.dataset.fleetView]);
    }
  }
});

test("Web Sessions: Web Apps shows its Web Sessions section once that instance's page has loaded", async () => {
  await context.refreshInstanceContext();
  await fleet.loadFleet();
  let scrolls = 0;
  element("web-sessions-section").scrollIntoView = () => { scrolls += 1; };
  const [click] = element("fleet-instances").listeners.click;
  for (const id of [IRIS2, PRIMARY]) {
    const button = links(section(id)).find((n) => n.dataset.fleetFocus === "web-sessions");
    navigations = [];
    scrolls = 0;
    click({ target: { closest: () => button } });
    assert.equal(context.getInstanceContext().instanceId, id);
    assert.deepEqual(navigations, ["web-apps"]);
    assert.equal(scrolls, 0, "Fleet doesn't scroll; the Web Apps page does once it has loaded");
    // app.js runs the Web Apps loader on navigation; run it here.
    requests = [];
    await webApps.loadWebApps();
    assert.equal(scrolls, 1);
    const want = id === PRIMARY ? null : id;
    assert.deepEqual(requests.map((r) => `${r.path} ${r.instance}`).sort(),
      [`/api/iris/web-apps ${want}`, `/api/iris/web-sessions ${want}`]);
    await webApps.loadWebApps();   // a later, ordinary load doesn't scroll again
    assert.equal(scrolls, 1);
  }
});

test("each instance keeps its own trend samples; a failed read adds none", async () => {
  await fleet.loadFleet();
  const before = [trendSamples(PRIMARY), trendSamples(IRIS2)];
  failing = new Set([IRIS2]);
  await fleet.loadFleet();
  assert.equal(trendSamples(PRIMARY), before[0] + 1);
  failing = new Set();
  await fleet.loadFleet();
  assert.equal(trendSamples(IRIS2), before[1] + 1);  // only the two successful reads
  assert.ok([...walk(section(IRIS2))].some((n) => n.className === "dash-trend__body"), "the chart is drawn from two samples on");
  assert.match(text(section(IRIS2)), /Global References \/ Second \(live\) View → Current trend, sampled every 15 s while this page is open\. Not historical data\./);
});

test("while shown, every 15 s it re-reads only each instance's monitor; it stops when the page is left", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    element("view-fleet").hidden = false;
    await fleet.loadFleet();
    requests = [];
    mock.timers.tick(15000);
    for (let i = 0; i < 20; i++) await Promise.resolve();
    assert.deepEqual(reads().map((r) => `${r.path} ${r.instance}`).sort(),
      [`/api/iris/monitor/dashboard ${IRIS2}`, "/api/iris/monitor/dashboard null"]);
    element("view-fleet").hidden = true;
    requests = [];
    mock.timers.tick(15000);
    for (let i = 0; i < 20; i++) await Promise.resolve();
    assert.equal(requests.length, 0);
  } finally {
    element("view-fleet").hidden = true;
    mock.timers.reset();
  }
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
