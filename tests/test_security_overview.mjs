// Security Overview (frontend/js/security-overview.js), tested without a
// browser like tests/test_explain_screen.mjs: a minimal stand-in DOM and a
// fake fetch() that records every request and answers per instance.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_security_overview.mjs

import assert from "node:assert/strict";
import { before, beforeEach, test } from "node:test";

const PRIMARY = "primary";
const IRIS2 = "iris-2b1365d07d62";
const SECRET_NAME = "CommandCenter.iris-0123456789ab";

const elements = new Map();

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", title: "", className: "", type: "", value: "",
    style: { setProperty() {} }, attributes: {}, disabled: false, children: [], listeners: {}, clicks: 0 };
  const self = new Proxy(function () {}, {
    get(_, key) {
      if (key in props) return props[key];
      if (key === "then" || typeof key === "symbol") return undefined;
      if (key === "append") return (...nodes) => { props.children.push(...nodes); };
      if (key === "replaceChildren") return (...nodes) => { props.children = [...nodes]; };
      if (key === "addEventListener") return (type, fn) => { (props.listeners[type] ||= []).push(fn); };
      if (key === "setAttribute") return (name, value) => { props.attributes[name] = String(value); };
      if (key === "click") return () => { props.clicks += 1; };
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

const nodeText = (node) => [node.textContent, ...(node.children || []).map(nodeText)].filter(Boolean).join(" ");

// --- fake backend, per instance ---

let requests = [];
let data = {};   // instance -> { services, x509, wallet, audit } (a value of "fail" answers 502)

const service = (name, enabled, methods) => ({ Name: name, Enabled: enabled, AuthenticationMethods: methods });
const credential = (alias, notAfter, notBefore = "2020-01-01 00:00:00") =>
  ({ Alias: alias, HasPrivateKey: true, Certificate: { ValidityNotBefore: notBefore, ValidityNotAfter: notAfter } });

function defaults() {
  return {
    services: [service("%Service_Login", true, ["Password"]), service("%Service_Weblink", false, ["Unauthenticated"])],
    x509: [],
    wallet: [{ Name: "CommandCenter", Secrets: [{ Name: SECRET_NAME, Type: "KeyValue" }] }],
    audit: { Enabled: true },
  };
}

function envelope(result) {
  return { status: { errors: [] }, result };
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  const instance = parsed.searchParams.get("instance");
  requests.push({ method: init.method || "GET", path: parsed.pathname, instance });
  const who = instance || PRIMARY;
  const d = { ...defaults(), ...(data[who] || {}) };
  if (parsed.pathname === "/api/iris/instances") {
    return { ok: true, status: 200, json: async () => ({ instances: [
      { id: PRIMARY, name: "Primary", base_url: "http://iris:52773", active: true, primary: true },
      { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", active: true, primary: false },
    ] }) };
  }
  const key = { "/api/iris/security/services": "services", "/api/iris/security/x509/overview": "x509",
    "/api/iris/security/wallet/overview": "wallet", "/api/iris/security/audit/enabled": "audit" }[parsed.pathname];
  if (key && d[key] === "fail") return { ok: false, status: 502, json: async () => ({ detail: "x" }) };
  const body = key ? envelope(d[key]) : envelope({ serverVersion: "IRIS 2026.2", apiVersion: 2, product: "iris" });
  return { ok: true, status: 200, json: async () => body };
}

let context;
let overview;
const navigations = [];

before(async () => {
  globalThis.document = {
    hidden: false,
    getElementById: element,
    createElement: () => stub(),
    createTextNode: (value) => { const node = stub(); node.textContent = value; return node; },
    addEventListener() {},
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
  overview = await import("../frontend/js/security-overview.js");
});

beforeEach(async () => {
  data = {};
  navigations.length = 0;
  await context.refreshInstanceContext();
  context.selectInstanceContext(PRIMARY);
  requests = [];
});

const findings = () => element("security-overview-findings").children;
const cards = () => Object.fromEntries(element("security-overview-cards").children.map((card) =>
  [card.children[0].textContent, card.children.slice(1).map((c) => c.textContent).join(" | ")]));

// --- the findings themselves ---

const NOW = new Date(2026, 9, 3, 12, 0, 0);   // 3 Oct 2026, local time like IRIS's dates

test("securityFindings: certificate validity, unauthenticated services and auditing, from IRIS's data only", () => {
  const { items, unavailable } = overview.securityFindings({
    certificates: [
      credential("old-ca", "2026-09-01 00:00:00"),
      credential("soon", "2026-10-20 00:00:00"),
      credential("future", "2027-12-31 00:00:00", "2026-12-01 00:00:00"),
      credential("fine", "2027-12-31 00:00:00"),
      { Alias: "no-cert", Certificate: null },
    ],
    services: [service("%Service_Weblink", true, ["Unauthenticated"]), service("%Service_CSP", false, ["Unauthenticated"]),
      service("%Service_Login", true, ["Password"])],
    auditEnabled: false,
  }, NOW);
  assert.deepEqual(unavailable, []);
  assert.deepEqual(items.map((i) => [i.badge, i.title, i.action[1]]), [
    ["Expired", "1 certificate has expired", "x509"],
    ["Expiring", "1 certificate expires within 30 days", "x509"],
    ["Not yet valid", "1 certificate is not yet valid", "x509"],
    ["Unauthenticated", "1 enabled service accepts unauthenticated access", "authentication"],
    ["Disabled", "Security auditing is disabled", "investigation"],
  ]);
  assert.match(items[0].text, /^old-ca\./);
  assert.match(items[3].text, /^%Service_Weblink\./, "a disabled service isn't a finding");
});

test("securityFindings: nothing found, and nothing inferred from data that couldn't be read", () => {
  assert.deepEqual(overview.securityFindings({ certificates: [credential("fine", "2027-12-31 00:00:00")],
    services: [service("%Service_Login", true, ["Password"])], auditEnabled: true }, NOW), { items: [], unavailable: [] });
  const none = overview.securityFindings({ certificates: null, services: null, auditEnabled: null }, NOW);
  assert.deepEqual(none.items, []);
  assert.deepEqual(none.unavailable, ["the X.509 credentials", "the services", "the audit status"]);
  // A certificate whose dates IRIS didn't give (or can't be parsed) is "Unknown", not expired.
  assert.deepEqual(overview.securityFindings({ certificates: [credential("odd", "not a date")], services: [],
    auditEnabled: true }, NOW).items, []);
});

// --- the section on the page ---

test("Primary: inventory cards and a positive empty state; only existing GET routes, read without ?instance=", async () => {
  overview.setOAuthOverview({ ServerConfigured: false, ServerClients: [], ServerDefinitions: [] });
  await overview.loadSecurityOverview();
  assert.deepEqual(requests.map((r) => `${r.method} ${r.path} ${r.instance}`).sort(), [
    "GET /api/iris/security/audit/enabled null", "GET /api/iris/security/services null",
    "GET /api/iris/security/wallet/overview null", "GET /api/iris/security/x509/overview null",
  ]);
  assert.deepEqual(cards(), {
    Services: "1 | enabled of 2",
    Certificates: "0 | X.509 credentials",
    Wallet: "1 | collection · 1 secret (names only)",
    "OAuth 2.0 Server": "No | 0 clients · 0 server definitions",
  });
  assert.equal(findings().length, 1);
  assert.match(nodeText(findings()[0]), /^OK No findings: no expired or expiring certificates/);
  assert.equal(element("security-overview-count").textContent, "");
  const shown = [...elements.values()].map(nodeText).join("\n");
  assert.ok(!shown.includes(SECRET_NAME), "Wallet secret names aren't shown, only counted");
});

test("IRIS-2: its own data; findings open the existing tab or page; nothing is changed", async () => {
  data[IRIS2] = {
    services: [service("%Service_Weblink", true, ["Unauthenticated", "Password"])],
    audit: { Enabled: false },
    x509: [credential("expired-ca", "2020-01-01 00:00:00")],
  };
  assert.equal(context.selectInstanceContext(IRIS2), true);
  requests = [];
  await overview.loadSecurityOverview();
  assert.ok(requests.every((r) => r.instance === IRIS2 && r.method === "GET"), JSON.stringify(requests));
  const rows = findings().map(nodeText);
  assert.equal(rows.length, 3);
  assert.match(rows[0], /^Expired 1 certificate has expired expired-ca\. Past ValidityNotAfter\. View Certificates →$/);
  assert.match(rows[1], /^Unauthenticated 1 enabled service accepts unauthenticated access %Service_Weblink\./);
  assert.match(rows[2], /^Disabled Security auditing is disabled .* View Investigation →$/);
  assert.equal(element("security-overview-count").textContent, "3 findings");

  requests = [];
  findings()[0].children[2].listeners.click[0]();
  findings()[1].children[2].listeners.click[0]();
  findings()[2].children[2].listeners.click[0]();
  assert.equal(element("security-tab-x509").clicks, 1);
  assert.equal(element("security-tab-authentication").clicks, 1);
  assert.deepEqual(navigations, ["investigation"]);
  assert.deepEqual(requests, [], "the links only open existing tabs and pages");
});

test("a source that couldn't be read is said, not shown as all clear; OAuth failure shows Unavailable", async () => {
  data[PRIMARY] = { x509: "fail" };
  overview.setOAuthOverview(null);
  await overview.loadSecurityOverview();
  const rows = findings().map(nodeText);
  assert.deepEqual(rows, ["Unavailable Couldn't read the X.509 credentials right now. Try Refresh."]);
  assert.equal(cards().Certificates, "Unavailable");
  assert.equal(cards()["OAuth 2.0 Server"], "Unavailable");
});
