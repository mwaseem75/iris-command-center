// Instances screen, Edit Instance (frontend/js/instances.js), tested without a
// browser like tests/test_fleet_overview.mjs: a minimal stand-in DOM, a fake
// fetch() that records every request and answers like the backend, and the
// real instances.js.
//
// The bug: with nothing changed, Test Connection stopped at "Nothing has
// changed." without asking the backend, so Update Instance never became
// enabled and no PUT was ever sent.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_instances_edit.mjs

import assert from "node:assert/strict";
import { before, beforeEach, test } from "node:test";

const IRIS2 = "iris-2b1365d07d62";
const elements = new Map();

function stub(id = null) {
  const props = { id, hidden: false, dataset: {}, textContent: "", title: "", className: "", type: "", value: "",
    placeholder: "", checked: false, style: { setProperty() {} }, attributes: {}, disabled: false, children: [], listeners: {} };
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

let requests = [];
let registry = [];

function instancesBody() {
  return { instances: registry };
}

function operationResult(dryRun, detail) {
  return {
    operation_name: "instance.update", status: dryRun ? "dry_run" : "success", detail: "",
    handler_result: { outcome: "success", detail, data: {} },
  };
}

async function fakeFetch(url, init = {}) {
  const parsed = new URL(url);
  const method = init.method || "GET";
  const body = init.body ? JSON.parse(init.body) : undefined;
  requests.push({ method, path: parsed.pathname, body });
  if (method === "PUT" && parsed.pathname === `/api/iris/instances/${IRIS2}`) {
    const { confirmed, dry_run: dryRun, ...changes } = body;
    const changed = Object.keys(changes).sort();
    if (!dryRun && changes.name) registry = registry.map((i) => (i.id === IRIS2 ? { ...i, name: changes.name } : i));
    return { ok: true, status: 200, json: async () => operationResult(dryRun,
      dryRun ? `Dry run: would change ${changed.join(", ") || "nothing"}. Nothing was saved.` : "Instance 'IRIS-2' updated.") };
  }
  if (parsed.pathname === "/api/iris/instances") return { ok: true, status: 200, json: async () => instancesBody() };
  return { ok: true, status: 200, json: async () => ({ status: { errors: [] }, result: {} }) };
}

let instances;
const flush = async () => { for (let i = 0; i < 20; i++) await new Promise((r) => setTimeout(r, 0)); };

before(async () => {
  globalThis.document = {
    hidden: false, getElementById: element, createElement: () => stub(), createElementNS: () => stub(),
    createTextNode: () => stub(), addEventListener() {}, dispatchEvent: () => true,
    querySelectorAll: () => [], querySelector: () => null,
  };
  globalThis.window = globalThis;
  globalThis.Node = Function;
  const storage = new Map();
  globalThis.localStorage = { getItem: (k) => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, String(v)) };
  globalThis.fetch = fakeFetch;
  instances = await import("../frontend/js/instances.js");
  instances.initInstancesControls();
});

beforeEach(async () => {
  registry = [
    { id: "primary", name: "Primary", base_url: "http://iris:52773", username: "_SYSTEM", namespace: "USER",
      active: true, primary: true, has_credential: true, last_check: null },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", username: "_SYSTEM", namespace: "USER",
      active: true, primary: false, has_credential: true, last_check: { status: "compatible", checked_at: "2026-10-01T20:12:30Z" } },
  ];
  await instances.loadInstances();
  requests = [];
});

function openEdit() {
  const [click] = element("instances-table-body").listeners.click;
  click({ target: { closest: () => ({ disabled: false, dataset: { action: "edit", instanceId: IRIS2 } }) } });
}

async function testConnection() {
  await element("instance-form").listeners.submit[0]({ preventDefault() {} });
}

async function confirmAndUpdate() {
  element("instance-form-ack-checkbox").checked = true;
  element("instance-form-ack-checkbox").listeners.change[0]();
  assert.equal(element("instance-form-submit-button").disabled, false, "Update Instance is enabled after a successful test");
  element("instance-form-submit-button").listeners.click[0]();
  await flush();
}

const puts = () => requests.filter((r) => r.method === "PUT");

test("Edit with nothing changed: Test asks the backend (dry run), then Update sends the update", async () => {
  openEdit();
  assert.equal(element("instance-form-name").value, "IRIS-2");
  assert.equal(element("instance-form-submit-button").textContent, "Update Instance");
  await testConnection();
  assert.equal(element("instance-form-error").hidden, true, element("instance-form-error-text").textContent);
  assert.deepEqual(puts().map((r) => [r.path, r.body]), [[`/api/iris/instances/${IRIS2}`, { confirmed: true, dry_run: true }]]);
  assert.equal(element("instance-form-ack").hidden, false, "the confirmation checkbox is offered");

  requests = [];
  await confirmAndUpdate();
  assert.deepEqual(puts().map((r) => r.body), [{ confirmed: true, dry_run: false }]);
  assert.equal(element("instance-form-result").hidden, false, "the result is shown");
  assert.ok(requests.some((r) => r.method === "GET" && r.path === "/api/iris/instances"), "the list is reloaded");
  assert.equal(element("instance-form-submit-button").hidden, true, "done: Update is replaced by Close");
});

test("Edit a name: Test and Update send only the changed name; the reloaded list has it", async () => {
  openEdit();
  element("instance-form-name").value = "IRIS-2 renamed";
  await testConnection();
  assert.deepEqual(puts().map((r) => r.body), [{ name: "IRIS-2 renamed", confirmed: true, dry_run: true }]);
  requests = [];
  await confirmAndUpdate();
  assert.deepEqual(puts().map((r) => r.body), [{ name: "IRIS-2 renamed", confirmed: true, dry_run: false }]);
  assert.equal(registry.find((i) => i.id === IRIS2).name, "IRIS-2 renamed");
});

test("A typed password is sent only to the backend, as part of the update", async () => {
  openEdit();
  element("instance-form-password").value = "Pw-EDIT-CANARY-not-real";
  await testConnection();
  assert.deepEqual(puts().map((r) => r.body), [{ password: "Pw-EDIT-CANARY-not-real", confirmed: true, dry_run: true }]);
  requests = [];
  await confirmAndUpdate();
  assert.deepEqual(puts().map((r) => r.body), [{ password: "Pw-EDIT-CANARY-not-real", confirmed: true, dry_run: false }]);
  assert.equal(element("instance-form-password").value, "", "the password is cleared once the update is done");
});

test("Clicking Update Instance after changing the name submits the update (no separate Test Connection needed)", async () => {
  openEdit();
  element("instance-form-name").value = "IRIS-2 renamed";
  // A disabled button never receives a real click: Update Instance must be clickable.
  assert.equal(element("instance-form-submit-button").disabled, false, "Update Instance is clickable in the Edit dialog");
  const clickUpdate = async () => { element("instance-form-submit-button").listeners.click[0](); await flush(); };

  await clickUpdate();   // 1st click: the dry run, then the confirmation is asked for
  assert.deepEqual(puts().map((r) => r.body), [{ name: "IRIS-2 renamed", confirmed: true, dry_run: true }]);
  assert.equal(element("instance-form-ack").hidden, false, "the confirmation checkbox is shown");
  assert.equal(element("instance-form-error").hidden, true, element("instance-form-error-text").textContent);

  requests = [];
  await clickUpdate();   // clicked again without confirming: nothing is sent
  assert.deepEqual(puts(), []);

  element("instance-form-ack-checkbox").checked = true;
  element("instance-form-ack-checkbox").listeners.change[0]();
  await clickUpdate();   // confirmed: the update is sent
  assert.deepEqual(puts().map((r) => r.body), [{ name: "IRIS-2 renamed", confirmed: true, dry_run: false }]);
  assert.equal(registry.find((i) => i.id === IRIS2).name, "IRIS-2 renamed");
  assert.equal(element("instance-form-result").hidden, false, "the result is shown");
});

// --- the Docker-managed iris-2 instance, and checks when the screen opens ---

const OVH = "iris-971d39974df0";

function* walk(node) {
  yield node;
  for (const child of node.children || []) yield* walk(child);
}

function rowButtons(instanceId) {
  const row = element("instances-table-body").children.find((r) => r.dataset.instanceId === instanceId);
  return Object.fromEntries([...walk(row)].filter((n) => n.dataset && n.dataset.action).map((b) => [b.dataset.action, b]));
}

test("Docker-managed IRIS-2: Edit and Delete unavailable, Check and Deactivate kept; Primary and IRIS-2 are checked when the screen opens", async () => {
  registry = [
    { ...registry[0], last_check: null },
    { ...registry[1], docker_managed: true },
    { id: OVH, name: "OVH", base_url: "https://ovh.example", username: "_SYSTEM", namespace: "USER",
      active: true, primary: false, has_credential: true, docker_managed: false, last_check: null },
  ];
  await instances.loadInstances({ checkSystem: true });
  await flush();
  // The existing check, for the Primary and the Docker-managed instance only.
  assert.deepEqual(requests.filter((r) => r.method === "POST").map((r) => r.path).sort(),
    [`/api/iris/instances/${IRIS2}/check`, "/api/iris/instances/primary/check"]);
  assert.ok(requests.filter((r) => r.method === "GET" && r.path === "/api/iris/instances").length >= 2, "the table is reloaded with the results");

  const iris2 = rowButtons(IRIS2);
  assert.equal(iris2.edit.disabled, true);
  assert.equal(iris2.delete.disabled, true);
  assert.match(iris2.edit.title, /Docker Compose/);
  assert.equal(iris2.check.disabled, false);
  assert.equal(iris2.deactivate.disabled, false);
  const ovh = rowButtons(OVH);
  assert.equal(ovh.edit.disabled, false);
  assert.equal(ovh.delete.disabled, false);

  // Even a click that got through opens nothing for IRIS-2.
  const [click] = element("instances-table-body").listeners.click;
  element("instance-form-drawer").hidden = true;
  element("instance-confirm-drawer").hidden = true;
  click({ target: { closest: () => ({ disabled: false, dataset: { action: "edit", instanceId: IRIS2 } }) } });
  click({ target: { closest: () => ({ disabled: false, dataset: { action: "delete", instanceId: IRIS2 } }) } });
  assert.equal(element("instance-form-drawer").hidden, true);
  assert.equal(element("instance-confirm-drawer").hidden, true);
  // OVH still opens.
  click({ target: { closest: () => ({ disabled: false, dataset: { action: "edit", instanceId: OVH } }) } });
  assert.equal(element("instance-form-drawer").hidden, false);
  assert.equal(element("instance-form-name").value, "OVH");
});

test("Reloading the table after a change does not re-run the checks", async () => {
  requests = [];
  await instances.loadInstances();
  await flush();
  assert.ok(!requests.some((r) => r.method === "POST"));
});
