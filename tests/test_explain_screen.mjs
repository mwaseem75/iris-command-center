// Screen Insights (frontend/js/explain-screen.js), tested without a browser
// like tests/test_instance_pages.mjs: a minimal stand-in DOM and a fake
// fetch() that records every request (the briefing must make none).
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_explain_screen.mjs

import assert from "node:assert/strict";
import { before, beforeEach, test } from "node:test";

const PRIMARY = "primary";
const IRIS2 = "iris-2b1365d07d62";
const VIEWS = ["dashboard", "health-center", "fleet", "issue-resolver", "operations", "observability", "security",
  "capabilities", "investigation"];

const elements = new Map();

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", title: "", className: "", type: "", value: "",
    style: { setProperty() {} }, attributes: {}, disabled: false, children: [], listeners: {}, focused: false, scrollTop: 0 };
  const self = new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "append") return (...nodes) => { props.children.push(...nodes); };
      if (key === "replaceChildren") return (...nodes) => { props.children = [...nodes]; };
      if (key === "addEventListener") return (type, fn) => { (props.listeners[type] ||= []).push(fn); };
      if (key === "setAttribute") return (name, value) => { props.attributes[name] = String(value); };
      if (key === "focus") return () => { props.focused = true; };
      if (key === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      if (key === "querySelectorAll") return () => [];
      if (key === "querySelector") return () => null;
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

const find = (node, className) => [...walk(node)].filter((n) => String(n.className).split(" ").includes(className));

// --- fake backend (only the instance list and the selector's /info check) ---

let requests = [];
let fleetCards = [];  // what document.querySelectorAll returns for the Fleet cards
const navigations = [];

function instancesBody() {
  return { instances: [
    { id: PRIMARY, name: "Primary", base_url: "http://iris:52773", active: true, primary: true },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", active: true, primary: false },
  ] };
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  requests.push({ method: init.method || "GET", path: parsed.pathname, instance: parsed.searchParams.get("instance") });
  const body = parsed.pathname === "/api/iris/instances" ? instancesBody()
    : { status: { errors: [] }, result: { serverVersion: "IRIS 2026.2", apiVersion: 2, product: "iris" } };
  return { ok: true, status: 200, json: async () => body };
}

let context;
let explain;

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createTextNode: (value) => { const node = stub(); node.textContent = value; return node; },
    addEventListener() {},
    dispatchEvent: () => true,
    querySelectorAll: (selector) => (selector.includes("#fleet-instances") ? fleetCards : []),
    querySelector: () => null,
  };
  globalThis.window = globalThis;
  const storage = new Map();
  globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)) };
  globalThis.fetch = fakeFetch;
  context = await import("../frontend/js/instance-context.js");
  const nav = await import("../frontend/js/nav.js");
  nav.initNavigation((view) => navigations.push(view));
  explain = await import("../frontend/js/explain-screen.js");
  explain.initExplainScreen(() => "dashboard");
});

beforeEach(async () => {
  await context.refreshInstanceContext();
  context.selectInstanceContext(PRIMARY);
  fleetCards = [];
  navigations.length = 0;
  for (const node of elements.values()) {
    node.textContent = "";
    node.hidden = false;
  }
  requests = [];
});

const body = () => element("explain-screen-body");
const sectionTitles = () => body().children.map((section) => find(section, "explain-card__title")[0]?.textContent
  ?? find(section, "explain-section__title")[0]?.textContent);
const snapshot = () => find(body(), "explain-snapshot")[0];
const tiles = () => Object.fromEntries(find(snapshot(), "explain-tile").map((tile) =>
  [find(tile, "explain-tile__label")[0].textContent, find(tile, "explain-tile__value")[0].textContent]));
const missingNote = () => find(snapshot(), "explain-snapshot__missing")[0]?.textContent;

test("the nine supported screens, and only those, have a complete briefing", () => {
  assert.deepEqual(Object.keys(explain.EXPLANATIONS).sort(), [...VIEWS].sort());
  for (const view of VIEWS) {
    const entry = explain.EXPLANATIONS[view];
    assert.ok(entry.title && entry.overview && entry.source, `${view} has a title, overview and source`);
    assert.ok(entry.snapshot.facts.length > 0, `${view} has snapshot facts`);
    for (const key of ["tells", "next", "safety"]) assert.ok(entry.insights[key], `${view} has the ${key} insight`);
    assert.ok(entry.terms.length > 0 && entry.related.length > 0, `${view} has key terms and related areas`);
    explain.openExplanation(view);
    assert.deepEqual(sectionTitles(), ["Overview", view === "fleet" ? "All active instances" : "Current snapshot",
      "What matters here", "Key terms", "Related areas"]);
    assert.equal(element("explain-screen-title").textContent, `Screen Insights · ${entry.title}`);
    assert.equal(element("explain-screen-drawer").hidden, false);
    assert.deepEqual(find(body(), "explain-insight").map((card) => card.dataset.kind), ["tells", "next", "safety"]);
  }
  assert.deepEqual(requests, [], "opening any briefing makes no request");
});

test("the snapshot shows the values the page already displays", () => {
  for (const [id, value] of [["stat-namespaces", "3"], ["stat-databases", "10"], ["stat-processes", "55"],
    ["stat-web-apps", "23"], ["stat-tasks", "16"], ["stat-license", " 13% "], ["stat-alerts", "0"],
    ["dashboard-live-label", "Live · every 15 s · updated 2:20:27 AM"]]) {
    element(id).textContent = value;
  }
  explain.openExplanation("dashboard");
  assert.deepEqual(tiles(), { Namespaces: "3", Databases: "10", Processes: "55", "Web apps": "23", Tasks: "16",
    License: "13%", "IRIS Alerts": "0" });
  assert.equal(find(snapshot(), "explain-snapshot__note")[0].textContent, "Live · every 15 s · updated 2:20:27 AM");
  assert.equal(find(snapshot(), "explain-snapshot__instance")[0].textContent, "Primary · iris:52773");
  assert.equal(missingNote(), undefined, "everything has loaded");
  assert.equal(element("explain-screen-context").textContent, "Showing the Primary instance.");
  assert.deepEqual(requests, []);
});

test("a value that hasn't loaded (empty, the — placeholder, or hidden) says so instead of guessing", () => {
  element("issue-resolver-kpi-active").textContent = "—";
  element("issue-resolver-kpi-resolvable").textContent = "2";
  element("issue-resolver-kpi-detection").textContent = "1";
  element("issue-resolver-kpi-detection").hidden = true;
  element("issue-resolver-kpi-severity").textContent = "Low";
  explain.openExplanation("issue-resolver");
  assert.deepEqual(tiles(), { "Active issues": "—", Resolvable: "2", "Detection-only": "—", "Highest severity": "Low" });
  assert.deepEqual(find(snapshot(), "explain-tile").map((tile) => tile.dataset.state ?? "ok"),
    ["missing", "ok", "missing", "ok"]);
  assert.equal(missingNote(), "Not loaded yet. Use Refresh.");
  assert.equal(find(snapshot(), "explain-snapshot__updated").length, 0, "no Updated line until the page shows one");
});

test("IRIS-2 selected: the briefing names it and says changes run on the Primary only", () => {
  assert.equal(context.selectInstanceContext(IRIS2), true);
  requests = [];
  explain.openExplanation("operations");
  assert.equal(element("explain-screen-context").textContent,
    "Showing IRIS-2 (iris-2:52773). Changes run on the Primary instance only.");
  assert.equal(find(snapshot(), "explain-snapshot__instance")[0].textContent, "IRIS-2 · iris-2:52773");
  assert.match(text(body()), /Changes run on the Primary only\./);
  assert.deepEqual(requests, []);
});

test("Fleet Overview uses its own all-instances context, even with IRIS-2 selected", () => {
  assert.equal(context.selectInstanceContext(IRIS2), true);
  element("fleet-count").textContent = "3 / 3";
  element("fleet-updated").textContent = "10/2/2026, 2:43:46 AM";
  fleetCards = [{ dataset: { state: "ok" } }, { dataset: { state: "ok" } }, { dataset: { state: "unavailable" } }];
  explain.openExplanation("fleet");
  assert.equal(element("explain-screen-context").textContent,
    "Covers every active instance; this page has no instance selector.");
  assert.equal(find(snapshot(), "explain-snapshot__instance").length, 0, "no single instance is named");
  assert.deepEqual(tiles(), { "Active instances": "3 / 3", Unavailable: "1" });
  assert.equal(find(snapshot(), "explain-tile")[1].dataset.tone, "warning", "unavailable instances stand out");
  assert.equal(find(snapshot(), "explain-snapshot__updated")[0].textContent, "Updated 10/2/2026, 2:43:46 AM");
  fleetCards = [];
  explain.openExplanation("fleet");
  assert.equal(tiles().Unavailable, "—");
  assert.equal(missingNote(), "Not loaded yet. Use Refresh.");
});

test("Related areas close the panel and open the page through the normal navigation", () => {
  explain.openExplanation("dashboard");
  const chips = find(body(), "explain-chip");
  assert.deepEqual(chips.map((chip) => chip.dataset.view), ["health-center", "issue-resolver", "operations", "observability"]);
  requests = [];
  chips[1].listeners.click[0]();
  assert.equal(element("explain-screen-drawer").hidden, true);
  assert.equal(element("explain-screen-backdrop").hidden, true);
  assert.deepEqual(navigations, ["issue-resolver"]);
  assert.deepEqual(requests, [], "the chip itself sends nothing; the page it opens loads as usual");
});

test("the panel always opens at the top", () => {
  element("explain-screen-drawer").scrollTop = 640;
  explain.openExplanation("health-center");
  assert.equal(element("explain-screen-drawer").scrollTop, 0);
});

test("other screens get no button and no briefing", () => {
  explain.placeExplainButton("tasks");
  assert.equal(element("explain-screen-button").hidden, true);
  element("explain-screen-drawer").hidden = true;
  explain.openExplanation("tasks");
  assert.equal(element("explain-screen-drawer").hidden, true);
});

test("the button opens the open page's briefing; close and the backdrop close it", () => {
  element("explain-screen-button").listeners.click[0]();
  assert.equal(element("explain-screen-drawer").hidden, false);
  assert.equal(element("explain-screen-title").textContent, "Screen Insights · Dashboard");
  element("explain-screen-close").listeners.click[0]();
  assert.equal(element("explain-screen-drawer").hidden, true);
  assert.equal(element("explain-screen-backdrop").hidden, true);
  element("explain-screen-button").listeners.click[0]();
  element("explain-screen-backdrop").listeners.click[0]();
  assert.equal(element("explain-screen-drawer").hidden, true);
  assert.deepEqual(requests, []);
});
