// Ask IRIS (frontend/js/ask-iris.js), tested without a browser like
// tests/test_explain_screen.mjs: a minimal stand-in DOM and a fake fetch()
// that records every request.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_ask_iris.mjs

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { before, beforeEach, test } from "node:test";

const PRIMARY = "primary";
const IRIS2 = "iris-2b1365d07d62";

const elements = new Map();
const documentListeners = {};

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", className: "", type: "", value: "",
    disabled: false, children: [], listeners: {}, focused: false, scrollTop: 0 };
  const self = new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "append") return (...nodes) => { props.children.push(...nodes); };
      if (key === "replaceChildren") return (...nodes) => { props.children = [...nodes]; };
      if (key === "addEventListener") return (type, fn) => { (props.listeners[type] ||= []).push(fn); };
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
const fire = (node, type, event = {}) => node.listeners[type].forEach((fn) => fn({ preventDefault() {}, ...event }));
const click = (node, target) => fire(node, "click", { target: { closest: () => target } });
const settle = () => new Promise((resolve) => setImmediate(resolve));

// A [data-ask-iris] entry button, clicked through the page-wide listener.
function clickEntry(context, screen) {
  const button = stub();
  button.dataset.askIris = context;
  if (screen) button.dataset.askIrisScreen = screen;
  documentListeners.click.forEach((fn) => fn({ target: { closest: (sel) => (sel === "[data-ask-iris]" ? button : null) } }));
}

// --- fake backend: the instance list, the selector's /info check, and /copilot/ask ---

let requests = [];
let askReply;  // () => { status, body } or a promise of one
const navigations = [];

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  requests.push({ method: init.method || "GET", path: parsed.pathname, instance: parsed.searchParams.get("instance"),
    body: init.body ? JSON.parse(init.body) : null });
  if (parsed.pathname === "/api/iris/copilot/ask") {
    const { status = 200, body } = await askReply();
    return { ok: status === 200, status, json: async () => body };
  }
  const body = parsed.pathname === "/api/iris/instances"
    ? { instances: [
      { id: PRIMARY, name: "Primary", base_url: "http://iris:52773", active: true, primary: true },
      { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", active: true, primary: false },
    ] }
    : { status: { errors: [] }, result: { serverVersion: "IRIS 2026.2", apiVersion: 2, product: "iris" } };
  return { ok: true, status: 200, json: async () => body };
}

const processAnswer = {
  answer: "IRIS reports 42 processes in 3 states. States are IRIS's own process state codes, shown as reported.",
  intent: "read_only_query",
  observations: ["State RUNW: 12", "State EVTW: 12", "State HANG: 2"],
  proposed_action: null,
  requires_confirmation: false,
};

let context;
let askIris;

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createTextNode: (value) => { const node = stub(); node.textContent = value; return node; },
    addEventListener(type, fn) { (documentListeners[type] ||= []).push(fn); },
    dispatchEvent: () => true,
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  globalThis.window = globalThis;
  const storage = new Map();
  globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)) };
  globalThis.fetch = fakeFetch;
  context = await import("../frontend/js/instance-context.js");
  const nav = await import("../frontend/js/nav.js");
  nav.initNavigation((view) => navigations.push(view));
  askIris = await import("../frontend/js/ask-iris.js");
  askIris.initAskIris();
});

beforeEach(async () => {
  await context.refreshInstanceContext();
  context.selectInstanceContext(PRIMARY);
  navigations.length = 0;
  askReply = () => ({ body: processAnswer });
  for (const node of elements.values()) {
    node.textContent = "";
    node.hidden = false;
  }
  element("ask-iris-drawer").hidden = true;
  requests = [];
});

const drawer = () => element("ask-iris-drawer");
const result = () => element("ask-iris-result");
const prompts = () => element("ask-iris-prompts").children;
const askRequests = () => requests.filter((r) => r.path.startsWith("/api/iris/copilot"));
const steps = () => find(result(), "ask-iris__step").map((node) => node.dataset.view);

async function askPrompt(label) {
  const chip = prompts().find((node) => node.dataset.prompt === label);
  assert.ok(chip, `the "${label}" prompt is offered`);
  click(element("ask-iris-prompts"), chip);
  await settle();
}

// --- the context table ---

test("each context has a title, prompts, a source, its page and next steps that are real pages", () => {
  assert.deepEqual(Object.keys(askIris.CONTEXTS), ["processes", "databases", "web-apps", "tasks", "issues"]);
  const html = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
  for (const [key, entry] of Object.entries(askIris.CONTEXTS)) {
    assert.ok(entry.title && entry.source && entry.prompts.length >= 3, `${key} is complete`);
    for (const view of [entry.page, ...entry.steps]) {
      assert.match(html, new RegExp(`data-view="${view}"`), `${key}: ${view} is an existing page`);
    }
  }
  for (const word of ["size", "storage", "utilization"]) {
    assert.ok(!JSON.stringify(askIris.CONTEXTS).toLowerCase().includes(word), `no prompt about ${word}`);
  }
  assert.equal(askIris.CONTEXTS.issues.primaryOnly, true);
});

// --- Processes (unchanged behaviour) ---

test("Ask IRIS opens from the Processes header with the instance, screen and suggested prompts", () => {
  clickEntry("processes");

  assert.equal(drawer().hidden, false);
  assert.equal(element("ask-iris-title").textContent, "Ask IRIS · Processes");
  assert.equal(element("ask-iris-instance").textContent, "Primary");
  assert.equal(element("ask-iris-screen").textContent, "Processes");
  assert.equal(element("ask-iris-read-at").textContent, "Not read yet");
  assert.deepEqual(prompts().map((node) => node.dataset.prompt), askIris.CONTEXTS.processes.prompts);
  assert.deepEqual(requests, [], "opening the panel asks nothing yet");
});

test("a question goes to the existing Copilot for the selected instance; answer and evidence are shown apart", async () => {
  assert.equal(context.selectInstanceContext(IRIS2), true);
  askIris.openAskIris("processes");
  await askPrompt("Show processes by state");

  assert.deepEqual(askRequests(), [{ method: "POST", path: "/api/iris/copilot/ask", instance: IRIS2,
    body: { message: "Show processes by state" } }]);
  const [answer, evidence] = result().children;
  assert.match(text(answer), /^Answer Show processes by state IRIS reports 42 processes in 3 states\./);
  assert.deepEqual(find(evidence, "ask-iris__observations")[0].children.map((li) => li.textContent),
    processAnswer.observations);
  const meta = find(evidence, "ask-iris__meta")[0].children.map(text);
  assert.equal(meta[0], "Source GET /v2/processes");
  assert.equal(meta[1], "Instance IRIS-2 (iris-2:52773)");
  assert.match(meta[2], /^Read at \S/);
  assert.deepEqual(steps(), ["investigation", "processes", "issue-resolver"]);
});

test("a custom question is sent as typed", async () => {
  askIris.openAskIris("processes");
  element("ask-iris-input").value = "  How many processes are in USER?  ";
  fire(element("ask-iris-form"), "submit");
  await settle();

  assert.equal(askRequests()[0].body.message, "How many processes are in USER?");
  assert.equal(element("ask-iris-input").value, "");
});

test("the process drawer opens Ask IRIS for that PID and asks about it", async () => {
  askIris.openAskIris("processes", { pid: 2468 });
  await settle();

  assert.equal(prompts()[0].dataset.prompt, "Explain PID 2468");
  assert.equal(askRequests()[0].body.message, "Explain PID 2468");
});

test("loading is shown while the live read runs; a failed read says which instance and doesn't fall back", async () => {
  assert.equal(context.selectInstanceContext(IRIS2), true);
  let fail;
  askReply = () => new Promise((resolve) => { fail = () => resolve({ status: 502, body: {} }); });
  askIris.openAskIris("processes");
  click(element("ask-iris-prompts"), prompts()[0]);
  await settle();

  assert.equal(element("ask-iris-loading").hidden, false);
  assert.match(element("ask-iris-loading-text").textContent, /^Reading live IRIS data from IRIS-2/);
  assert.equal(element("ask-iris-send").disabled, true);

  fail();
  await settle();
  assert.equal(element("ask-iris-loading").hidden, true);
  assert.equal(element("ask-iris-send").disabled, false);
  assert.equal(element("ask-iris-error").hidden, false);
  assert.match(element("ask-iris-error-text").textContent,
    /^Couldn't read IRIS data from IRIS-2 \(iris-2:52773\)\..*no other instance was used/);
  assert.equal(result().children.length, 0);
  assert.deepEqual(askRequests().map((r) => r.instance), [IRIS2], "asked once, of IRIS-2 only");
});

test("closing the panel drops an answer still on its way", async () => {
  let answer;
  askReply = () => new Promise((resolve) => { answer = () => resolve({ body: processAnswer }); });
  askIris.openAskIris("processes");
  click(element("ask-iris-prompts"), prompts()[0]);
  await settle();
  fire(element("ask-iris-close"), "click");
  answer();
  await settle();

  assert.equal(drawer().hidden, true);
  assert.equal(result().children.length, 0);
  assert.equal(element("ask-iris-send").disabled, false);
});

test("a change request stays read-only: no proposal, no plan, authorize or execute, and links to where changes are made", async () => {
  askReply = () => ({ body: { answer: "I can describe a possible next step, but no operation is executed by this Copilot step.",
    intent: "resolution_request", observations: [], proposed_action: "Mount database IPM", requires_confirmation: true } });
  askIris.openAskIris("databases");
  element("ask-iris-input").value = "Mount database IPM";
  fire(element("ask-iris-form"), "submit");
  await settle();

  const answerText = find(result(), "ask-iris__answer-text").map((node) => node.textContent);
  assert.equal(answerText.length, 1);
  assert.match(answerText[0], /^Ask IRIS is read-only and doesn't make changes\./);
  assert.doesNotMatch(answerText[0], /Mount database IPM|possible next step/i, "the Copilot's proposal isn't shown");
  assert.equal(find(result(), "ask-iris__evidence").length, 0);
  assert.deepEqual(askRequests().map((r) => r.path), ["/api/iris/copilot/ask"]);
  assert.deepEqual(steps(), ["operations", "databases"]);
});

test("next steps only switch pages with navigateTo() and close the panel", async () => {
  askIris.openAskIris("processes");
  await askPrompt("Summarize process activity");
  const investigation = find(result(), "ask-iris__step").find((node) => node.dataset.view === "investigation");
  click(result(), investigation);

  assert.deepEqual(navigations, ["investigation"]);
  assert.equal(drawer().hidden, true);
  assert.deepEqual(askRequests().map((r) => r.path), ["/api/iris/copilot/ask"], "no request beyond the question");
});

// --- the other contexts ---

test("a Dashboard card's 🤖 opens that card's context, for the selected instance", async () => {
  assert.equal(context.selectInstanceContext(IRIS2), true);
  askReply = () => ({ body: { answer: "IRIS reports 10 databases: Mounted/RW 8, Mounted/R 2.", intent: "read_only_query",
    observations: ["Status Mounted/RW: 8", "Status Mounted/R: 2"], proposed_action: null, requires_confirmation: false } });
  clickEntry("databases", "Dashboard");

  assert.equal(element("ask-iris-title").textContent, "Ask IRIS · Databases");
  assert.equal(element("ask-iris-screen").textContent, "Dashboard · Databases");
  assert.equal(element("ask-iris-instance").textContent, "IRIS-2 (iris-2:52773)");
  assert.deepEqual(prompts().map((node) => node.dataset.prompt), askIris.CONTEXTS.databases.prompts);

  await askPrompt("Summarize database status");
  assert.deepEqual(askRequests().map((r) => r.instance), [IRIS2]);
  const meta = find(result(), "ask-iris__meta")[0].children.map(text);
  assert.equal(meta[0], "Source GET /v2/databases, with the Issue Resolver's detection");
  assert.deepEqual(steps(), ["databases", "issue-resolver"]);
  assert.deepEqual(navigations, [], "the 🤖 doesn't navigate");
});

test("web apps and tasks open with their own prompts, source and next steps", async () => {
  for (const [key, prompt, source, expected] of [
    ["web-apps", "Which web apps are disabled?", "GET /v2/web-apps, with the Issue Resolver's detection", ["web-apps", "issue-resolver"]],
    ["tasks", "Which tasks are suspended?", "GET /v2/tasks, with each task's info and details", ["tasks", "issue-resolver"]],
  ]) {
    askReply = () => ({ body: { answer: "An answer.", intent: "read_only_query", observations: ["One fact."],
      proposed_action: null, requires_confirmation: false } });
    requests = [];
    clickEntry(key);
    await askPrompt(prompt);
    assert.equal(find(result(), "ask-iris__meta")[0].children.map(text)[0], `Source ${source}`);
    assert.deepEqual(steps(), expected);
    assert.equal(askRequests()[0].body.message, prompt);
  }
});

test("the issues context is Primary-only and names the Issue Resolver as its source", async () => {
  askReply = () => ({ body: { answer: "The Issue Resolver reports no active issues.", intent: "issue_investigation",
    observations: ["All issue checks ran."], proposed_action: null, requires_confirmation: false } });
  clickEntry("issues", "Dashboard");
  assert.equal(drawer().hidden, false);
  await askPrompt("Which issue checks could not run?");
  assert.equal(find(result(), "ask-iris__meta")[0].children.map(text)[0], "Source Issue Resolver detection (read-only)");
  assert.deepEqual(steps(), ["issue-resolver", "investigation"]);

  fire(element("ask-iris-close"), "click");
  assert.equal(context.selectInstanceContext(IRIS2), true);
  clickEntry("issues", "Dashboard");
  assert.equal(drawer().hidden, true, "not opened for another instance");
});

test("Dashboard 🤖 buttons sit beside their cards, so a card click still opens its page", () => {
  const html = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
  const dashboard = html.slice(html.indexOf('id="view-dashboard"'), html.indexOf('id="view-health-center"'));
  const cards = [...dashboard.matchAll(/data-ask-iris="([a-z-]+)" data-ask-iris-screen="Dashboard"/g)].map((m) => m[1]);
  assert.deepEqual(cards, ["databases", "processes", "web-apps", "tasks", "issues"]);
  for (const slot of dashboard.split('<div class="dash-kpi-slot">').slice(1)) {
    const article = slot.slice(0, slot.indexOf("</article>"));
    assert.doesNotMatch(article, /<button/, "no button inside a card's role=button");
    assert.match(slot.slice(slot.indexOf("</article>")), /^<\/article>\s*<button class="ask-iris-card-button"/);
  }
  for (const page of ["processes", "databases", "web-apps", "tasks"]) {
    assert.match(html, new RegExp(`id="${page}-ask-button" data-ask-iris="${page}"`), `${page} has a page-level button`);
  }
  for (const page of ["security", "investigation", "fleet", "operations", "journal", "namespaces", "system",
    "extensions", "capabilities", "health-center", "issue-resolver"]) {
    const start = html.indexOf(`id="view-${page}"`);
    const section = html.slice(start, html.indexOf("</section>\n\n        <section", start));
    assert.doesNotMatch(section, /data-ask-iris=/, `${page} has no Ask IRIS`);
  }
});
