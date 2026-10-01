// Issue Resolver, Operations, Observability and API Explorer follow the
// selected instance (frontend/js/{issue-resolver,operations,observability,
// capabilities}.js), tested without a browser like tests/test_fleet_overview.mjs:
// a minimal stand-in DOM, a fake fetch() that records every request and
// answers per instance like the backend, and the real page modules plus
// instance-context.js.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_instance_pages.mjs

import assert from "node:assert/strict";
import { before, beforeEach, test } from "node:test";

const PRIMARY = "primary";
const IRIS2 = "iris-2b1365d07d62";

const elements = new Map();

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", title: "", className: "", type: "", value: "",
    checked: false, style: { setProperty() {} }, attributes: {}, disabled: false, children: [], listeners: {} };
  const self = new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "append") return (...nodes) => { props.children.push(...nodes); };
      if (key === "replaceChildren") return (...nodes) => { props.children = [...nodes]; };
      if (key === "addEventListener") return (type, fn) => { (props.listeners[type] ||= []).push(fn); };
      if (key === "setAttribute") return (name, value) => { props.attributes[name] = String(value); };
      if (key === "getAttribute") return (name) => props.attributes[name] ?? null;
      if (key === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      if (key === "querySelectorAll") return () => [];
      if (key === "querySelector") return () => null;
      if (key === "closest") return () => null;
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

const classed = (node, name) => [...walk(node)].filter((n) => String(n.className).split(" ").includes(name));

// --- fake backend, per instance ---

let requests = [];
let down = new Set();   // instances whose IRIS reads fail (502)

const DB_ISSUE = (who) => ({ kind: "database_dismounted", issue_id: `database_dismounted:${who}`, database: `${who.toUpperCase()}DB`,
  directory: `/data/${who}/`, status: "Dismounted" });
const MONITOR_ISSUE = { kind: "system_monitor_not_running", issue_id: "system_monitor_not_running" };
const RESOLUTIONS = {
  database_dismounted: { title: "Database dismounted", severity: "high", resolvable: true, operation: "database.mount",
    risk_level: "medium", required_privileges: ["Manage"], description: "", resolution_steps: [], verification: "" },
  system_monitor_not_running: { title: "System Monitor not running", severity: "medium", resolvable: false,
    investigation: { page: "system", description: "Check the System Monitor." }, description: "", resolution_steps: [] },
};

const TRACES = [
  { trace_id: "t-primary", operation_name: "journal.update_purge_archived", status: "success", instance_id: "primary",
    start_time: "2026-10-01T10:00:02Z", end_time: "2026-10-01T10:00:03Z", duration_ms: 900, spans: [] },
  { trace_id: "t-iris2", operation_name: "database.mount", status: "success", instance_id: IRIS2,
    start_time: "2026-10-01T10:00:01Z", end_time: "2026-10-01T10:00:02Z", duration_ms: 800, spans: [] },
  { trace_id: "t-legacy", operation_name: "database.dismount", status: "success",
    start_time: "2026-10-01T10:00:00Z", end_time: "2026-10-01T10:00:01Z", duration_ms: 700, spans: [] },
];

const IRIS2_CHECK = {
  checked_at: "2026-10-01T08:42:25Z", status: "compatible", product: "IRIS", server_version: "IRIS for UNIX 2026.2 (Build 221U)",
  api_version: 2, endpoints_ok: ["/v2/namespaces"], endpoints_missing: ["/v2/databases"], mgmnt_api_available: true,
};
let primaryCheck = null;
let iris2Check = IRIS2_CHECK;
let registryFails = false;

function instancesBody() {
  return { instances: [
    { id: PRIMARY, name: "Primary", base_url: "http://iris:52773", active: true, primary: true, last_check: primaryCheck },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", active: true, primary: false, last_check: iris2Check },
  ] };
}

function envelope(result) {
  return { status: { errors: [] }, result };
}

function answer(method, path, instance) {
  const who = instance || PRIMARY;
  if (method === "POST" && path === "/api/iris/journal/purge-archived") {
    return { operation_name: "journal.update_purge_archived", status: "success", detail: "PurgeArchived is now on." };
  }
  switch (path) {
    case "/api/iris/instances": return instancesBody();
    case "/api/iris/info": return envelope({ serverVersion: "IRIS 2026.2", apiVersion: 2, product: "iris" });
    case "/api/iris/issues": return { issues: who === PRIMARY ? [DB_ISSUE("primary")] : [DB_ISSUE("iris2"), MONITOR_ISSUE],
      resolutions: RESOLUTIONS, correlations: [], issue_checks_unavailable: [] };
    case "/api/iris/issue-rules": return { signals: [], operators: [], pages: [], rules: [], max_rules: 5, persisted_to_iris: false };
    case "/api/iris/observability/traces": return { traces: TRACES };
    case "/api/iris/operations": return { operations: [{ name: "journal.update_purge_archived", description: "", kind: "update",
      required_privileges: ["Manage"], risk_level: "medium", confirmation_required: true }] };
    case "/api/iris/journal/settings": return envelope({ PurgeArchived: who === PRIMARY });
    case "/api/iris/capabilities": return { capabilities: [
      { capability: "List namespaces", endpoint: "/api/admin/v2/namespaces", method: "GET", required_privilege: "%Admin_Manage:U",
        iris_version: "2026.2", verification_status: "Verified", notes: "", available: true },
      { capability: "List databases", endpoint: "/api/admin/v2/databases", method: "GET", required_privilege: "%Admin_Manage:U",
        iris_version: "2026.2", verification_status: "Verified", notes: "", available: true },
      { capability: "Log in", endpoint: "/api/admin/login", method: "POST", required_privilege: "None",
        iris_version: "2026.2", verification_status: "Verified", notes: "", available: false },
    ] };
    default: return envelope([]);
  }
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  const instance = parsed.searchParams.get("instance");
  const method = init.method || "GET";
  requests.push({ method, path: parsed.pathname, instance, body: init.body });
  if (parsed.pathname === "/api/iris/instances" && registryFails) {
    return { ok: false, status: 503, json: async () => ({ detail: "unavailable" }) };
  }
  if (instance && down.has(instance) && parsed.pathname !== "/api/iris/instances") {
    return { ok: false, status: 502, json: async () => ({ detail: "Could not connect to IRIS" }) };
  }
  return { ok: true, status: 200, json: async () => answer(method, parsed.pathname, instance) };
}

let context;
let issues;
let operations;
let observability;
let capabilities;
const navigations = [];

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createElementNS: () => stub(),
    createTextNode: (value) => { const node = stub(); node.textContent = value; return node; },
    createDocumentFragment: () => stub(),
    addEventListener() {},
    dispatchEvent: () => true,
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  globalThis.window = globalThis;
  globalThis.CSS = { escape: (value) => value };
  globalThis.Node = Function;  // the stand-in elements are function proxies, so \`x instanceof Node\` holds for them
  const storage = new Map();
  globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)) };
  globalThis.fetch = fakeFetch;
  context = await import("../frontend/js/instance-context.js");
  const nav = await import("../frontend/js/nav.js");
  nav.initNavigation((view) => navigations.push(view));
  issues = await import("../frontend/js/issue-resolver.js");
  operations = await import("../frontend/js/operations.js");
  observability = await import("../frontend/js/observability.js");
  capabilities = await import("../frontend/js/capabilities.js");
  issues.initIssueResolverControls({
    onOpenDatabases: () => navigations.push("databases"), onOpenWebApps: () => navigations.push("web-apps"),
    onOpenOperations: () => navigations.push("operations"), onInvestigate: (page) => navigations.push(page),
  });
  operations.initOperationsControls();
  observability.initObservabilityControls({});
  capabilities.initCapabilitiesControls();
});

beforeEach(async () => {
  down = new Set();
  registryFails = false;
  primaryCheck = null;
  iris2Check = IRIS2_CHECK;
  navigations.length = 0;
  await context.refreshInstanceContext();
  context.selectInstanceContext(PRIMARY);
  requests = [];
});

async function select(id) {
  assert.equal(context.selectInstanceContext(id), true);
  requests = [];
}

const reads = (path) => requests.filter((r) => r.path === path);

// --- Issue Resolver ---

const issueActions = () => element("issue-resolver-list").children.map((card) => classed(card, "ir-issue__action")[0]);

test("Issue Resolver, Primary: issues read without ?instance=, fixes enabled", async () => {
  await issues.loadIssueResolver();
  assert.deepEqual(reads("/api/iris/issues").map((r) => r.instance), [null]);
  const [fix] = issueActions();
  assert.equal(fix.disabled, false);
  assert.equal(fix.textContent, "Go to Resolve Issues →");
  assert.equal(element("issue-resolver-rules-add").disabled, false);
  assert.equal(element("issue-resolver-rules-primary-note").hidden, true);
  assert.equal(element("issue-resolver-rehearsal-primary-note").hidden, true);
  assert.match(element("issue-resolver-updated").textContent, / · Primary$/);
});

test("Issue Resolver, IRIS-2: its own issues; fixes, rules and the demo are Primary only and disabled", async () => {
  await select(IRIS2);
  await issues.loadIssueResolver();
  assert.deepEqual(reads("/api/iris/issues").map((r) => r.instance), [IRIS2]);
  assert.match(text(element("issue-resolver-list")), /IRIS2DB/);
  assert.doesNotMatch(text(element("issue-resolver-list")), /PRIMARYDB/);
  const [fix, investigate] = issueActions();
  assert.equal(fix.disabled, true);
  assert.equal(fix.textContent, "Resolve on Primary only");
  assert.match(fix.title, /Primary instance only/);
  assert.equal(investigate.disabled, false, "detection-only issues can still be investigated on IRIS-2");
  assert.equal(investigate.textContent, "Investigate in System →");
  assert.equal(element("issue-resolver-rules-add").disabled, true);
  assert.equal(element("issue-resolver-rules-primary-note").hidden, false);
  assert.equal(element("issue-resolver-rehearsal-start").disabled, true);
  assert.equal(element("issue-resolver-rehearsal-primary-note").hidden, false);
  assert.match(element("issue-resolver-updated").textContent, / · IRIS-2$/);
  assert.ok(!requests.some((r) => r.method !== "GET"), "nothing is changed");
});

test("Issue Resolver, IRIS-2 unreachable: its own error, never the Primary's issues", async () => {
  await select(IRIS2);
  down = new Set([IRIS2]);
  await issues.loadIssueResolver();
  assert.deepEqual(reads("/api/iris/issues").map((r) => r.instance), [IRIS2]);
  assert.equal(element("issue-resolver-list").children.length, 0);
  assert.match(element("issue-resolver-error-banner-text").textContent,
    /^Could not check IRIS-2 for issues right now\. .*no other instance's issues are shown\.$/);
});

// --- Operations ---

const purgeRows = () => element("operations-execute-current-list").children.map(text);

test("Operations, Primary: current value from the Primary; the change can be started; cards say Primary only", async () => {
  await operations.loadOperations();
  const card = text(element("operations-catalog"));
  assert.match(card, /Runs on Primary instance only/);
  operations.resolveJournalIssue(null);
  element("operations-set-true-button").listeners.click?.length;  // wired
  await operations.loadOperations();
  // Open the journal action (the catalog's Open button) and read its value.
  const open = classed(element("operations-catalog"), "ops-card__open")[0];
  open.listeners.click[0]();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(reads("/api/iris/journal/settings").map((r) => r.instance), [null]);
  assert.deepEqual(purgeRows(), ["Current PurgeArchived Value (Primary) Yes"]);
  assert.equal(element("operations-set-true-button").disabled, false);
  assert.equal(element("operations-execute-primary-note").hidden, true);
});

test("Operations, IRIS-2: IRIS-2's value is shown, and its change is marked Primary only and can't be started", async () => {
  await select(IRIS2);
  await operations.loadOperations();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(reads("/api/iris/journal/settings").map((r) => r.instance), [IRIS2]);
  assert.deepEqual(purgeRows(), ["Current PurgeArchived Value (IRIS-2) No"]);
  assert.equal(element("operations-set-true-button").disabled, true);
  assert.equal(element("operations-set-false-button").disabled, true);
  assert.equal(element("operations-execute-primary-note").hidden, false);
  assert.match(element("operations-execute-primary-note").textContent, /^Primary only: .* The value above is IRIS-2's;/);
  // Even if a click got through, nothing is planned or sent.
  element("operations-set-true-button").listeners.click[0]();
  element("operations-confirm-button").listeners.click[0]();
  await new Promise((r) => setTimeout(r, 0));
  assert.ok(!requests.some((r) => r.method === "POST"), "no change is sent while IRIS-2 is selected");
});

test("Operations, IRIS-2 unreachable: 'Could not load', never the Primary's value", async () => {
  await select(IRIS2);
  down = new Set([IRIS2]);
  await operations.loadOperations();
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(reads("/api/iris/journal/settings").map((r) => r.instance), [IRIS2]);
  assert.deepEqual(purgeRows(), ["Current PurgeArchived Value (IRIS-2) Could not load"]);
});

test("Operations, Primary: the confirmed change goes to the Primary's route (no ?instance=) and says where it ran", async () => {
  await operations.loadOperations();
  await new Promise((r) => setTimeout(r, 0));
  element("operations-set-false-button").listeners.click[0]();
  requests = [];
  await element("operations-confirm-button").listeners.click[0]();
  await new Promise((r) => setTimeout(r, 0));
  const posts = requests.filter((r) => r.method === "POST");
  assert.deepEqual(posts.map((r) => [r.path, r.instance]), [["/api/iris/journal/purge-archived", null]]);
  assert.match(text(element("operations-result-list")), /Ran On Primary instance/);
});

// --- Observability ---

// The list's trace buttons (appended through a document fragment).
const traceButtons = () => classed(element("observability-trace-list"), "obs-trace");
const traceIds = () => traceButtons().map((button) => button.dataset.traceId);

test("Observability: each instance's own traces, plus those with no recorded instance (marked, not attributed)", async () => {
  await observability.loadExecutionTraces();
  assert.deepEqual(traceIds(), ["t-primary", "t-legacy"]);
  assert.match(element("observability-count").textContent, /^2 traces for Primary \(1 with no recorded instance\)/);
  const [primaryItem, legacyItem] = traceButtons();
  assert.equal(classed(primaryItem, "obs-trace__tag--muted").length, 0);
  assert.equal(classed(legacyItem, "obs-trace__tag--muted")[0].textContent, "Instance not recorded");
  assert.match(text(element("observability-detail-body")), /Instance Primary/);

  await select(IRIS2);
  await observability.loadExecutionTraces();
  assert.deepEqual(traceIds(), ["t-iris2", "t-legacy"]);
  assert.match(element("observability-count").textContent, /^2 traces for IRIS-2 \(1 with no recorded instance\)/);
  assert.match(text(element("observability-detail-body")), /Instance IRIS-2/);
});

// --- API Explorer ---

// The "On <instance>" column (after Available).
const capabilityRows = () => element("capabilities-table-body").children.map((row) => text(row.children[6]));

test("API Explorer, IRIS-2: its last compatibility check, endpoint by endpoint", async () => {
  await select(IRIS2);
  await capabilities.loadCapabilities();
  assert.ok(!requests.some((r) => r.instance), "no IRIS read: the recorded check is used");
  assert.equal(element("capabilities-instance-column").textContent, "On IRIS-2");
  assert.deepEqual(capabilityRows(), ["Answered", "Missing", "Not checked"]);
  assert.match(element("capabilities-instance-summary").textContent,
    /^IRIS-2's last compatibility check: 1 of 2 required System Administration API endpoints answered, 1 missing\.$/);
  const facts = text(element("capabilities-instance-facts"));
  assert.match(facts, /Check result compatible/);
  assert.match(facts, /Server version IRIS for UNIX 2026\.2 \(Build 221U\)/);
  assert.match(facts, /API version 2/);
  assert.match(facts, /Management API \(\/api\/mgmnt\) Available/);
  assert.match(element("capabilities-summary").textContent, /1 answered on IRIS-2$/);
  // The filter works on the same check.
  element("capabilities-filter-instance").value = "missing";
  element("capabilities-filter-instance").listeners.change[0]();
  assert.deepEqual(capabilityRows(), ["Missing"]);
  element("capabilities-filter-instance").value = "";
  element("capabilities-filter-instance").listeners.change[0]();
});

test("API Explorer, Primary without a recorded check: says so, nothing inferred", async () => {
  await capabilities.loadCapabilities();
  assert.equal(element("capabilities-instance-column").textContent, "On Primary");
  assert.deepEqual(capabilityRows(), ["—", "—", "—"]);
  assert.match(element("capabilities-instance-summary").textContent,
    /^No compatibility check is recorded for Primary since the backend started\. Run Check on the Instances screen/);
  assert.equal(element("capabilities-instance-facts").children.length, 0);
  primaryCheck = { ...IRIS2_CHECK, endpoints_ok: ["/v2/namespaces", "/v2/databases"], endpoints_missing: [] };
  await capabilities.loadCapabilities();
  assert.deepEqual(capabilityRows(), ["Answered", "Answered", "Not checked"]);
});

test("API Explorer: an unavailable registry is reported, not guessed", async () => {
  registryFails = true;
  await capabilities.loadCapabilities();
  assert.equal(element("capabilities-instance-summary").textContent, "Could not load Primary's compatibility information.");
  assert.deepEqual(capabilityRows(), ["—", "—", "—"]);
});

test("API Explorer, all required endpoints answered: 13 of 13, each listed capability Answered", async () => {
  const thirteen = ["/v2/namespaces", "/v2/databases", ...Array.from({ length: 11 }, (_, i) => `/v2/other-${i}`)];
  iris2Check = { ...IRIS2_CHECK, endpoints_ok: thirteen, endpoints_missing: [] };
  await select(IRIS2);
  await capabilities.loadCapabilities();
  assert.equal(element("capabilities-instance-summary").textContent,
    "IRIS-2's last compatibility check: 13 of 13 required System Administration API endpoints answered.");
  assert.deepEqual(capabilityRows(), ["Answered", "Answered", "Not checked"]);
  assert.match(element("capabilities-summary").textContent, /2 answered on IRIS-2$/);
});

test("API Explorer, a check that failed before probing endpoints: says so, no '0 of 0', no per-endpoint verdicts", async () => {
  iris2Check = { checked_at: "2026-10-01T09:00:00Z", status: "unreachable", failure: "unreachable",
    detail: "The instance could not be reached.", endpoints_ok: [], endpoints_missing: [], mgmnt_api_available: null };
  await select(IRIS2);
  await capabilities.loadCapabilities();
  const summary = element("capabilities-instance-summary").textContent;
  assert.equal(summary, "IRIS-2's last compatibility check ended before its API endpoints were checked (result: unreachable). " +
    "The instance could not be reached. Run Check again on the Instances screen.");
  assert.doesNotMatch(summary, /0 of 0/);
  assert.deepEqual(capabilityRows(), ["—", "—", "—"], "no Answered / Missing / Not checked without an endpoint check");
  assert.doesNotMatch(element("capabilities-summary").textContent, /answered on/);
  const facts = text(element("capabilities-instance-facts"));
  assert.match(facts, /Check result unreachable/);
  assert.match(facts, /Detail The instance could not be reached\./);
  // The endpoint filter shows nothing rather than guessing.
  element("capabilities-filter-instance").value = "not_checked";
  element("capabilities-filter-instance").listeners.change[0]();
  assert.deepEqual(capabilityRows(), []);
  element("capabilities-filter-instance").value = "";
  element("capabilities-filter-instance").listeners.change[0]();
});

test("API Explorer, an auth_failed check without a detail still names its result", async () => {
  iris2Check = { checked_at: "2026-10-01T09:00:00Z", status: "auth_failed", endpoints_ok: [], endpoints_missing: [] };
  await select(IRIS2);
  await capabilities.loadCapabilities();
  assert.equal(element("capabilities-instance-summary").textContent,
    "IRIS-2's last compatibility check ended before its API endpoints were checked (result: auth failed). " +
    "Run Check again on the Instances screen.");
});
