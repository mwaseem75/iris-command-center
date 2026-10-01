// Global instance context (frontend/js/instance-context.js), tested without a
// browser: the store is driven with a fake GET /api/iris/instances loader and
// an in-memory localStorage stand-in.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_instance_context.mjs

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ALL_ACTIVE,
  PRIMARY_ID,
  connectionLabel,
  createInstanceContext,
  resolveSelection,
} from "../frontend/js/instance-context.js";

const IRIS2 = "iris-2b1365d07d62";
const IRIS3 = "iris-3c0ffee00001";
const SECRET = "Pw-CONTEXT-CANARY-not-real";

// Shaped like the real InstanceView, plus fields that must never get through.
function instances({ iris2Active = true, withIris3 = true } = {}) {
  const list = [
    { id: PRIMARY_ID, name: "Primary", base_url: "http://iris:52773", username: "_SYSTEM", namespace: "USER",
      active: true, primary: true, has_credential: true, last_check: null },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", username: "_SYSTEM", namespace: "USER",
      active: iris2Active, primary: false, has_credential: true, last_check: { status: "compatible" },
      password: SECRET, credential_ref: `CommandCenter.${IRIS2}` },
  ];
  if (withIris3) {
    list.push({ id: IRIS3, name: "IRIS-3", base_url: "http://iris-3:52773", username: "ops", namespace: "USER",
      active: false, primary: false, has_credential: true, last_check: null });
  }
  return { instances: list };
}

function memoryStorage(initial = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key) => (data.has(key) ? data.get(key) : null),
    setItem: (key, value) => data.set(key, String(value)),
  };
}

function makeContext({ body = instances(), storage = memoryStorage(), fail = false } = {}) {
  const dispatched = [];
  const context = createInstanceContext({
    loadInstances: async () => {
      if (fail) throw new Error("backend down");
      return typeof body === "function" ? body() : body;
    },
    storage,
    dispatch: (snapshot) => dispatched.push(snapshot),
  });
  return { context, storage, dispatched };
}

test("loads the instances from the backend list", async () => {
  const { context } = makeContext();
  assert.equal(await context.refresh(), true);
  const snapshot = context.get();
  assert.deepEqual(snapshot.instances.map((i) => i.id), [PRIMARY_ID, IRIS2, IRIS3]);
  assert.deepEqual(snapshot.activeInstances.map((i) => i.id), [PRIMARY_ID, IRIS2]);
  assert.deepEqual(snapshot.instances[1], { id: IRIS2, name: "IRIS-2", primary: false, active: true, connection: "iris-2:52773" });
});

test("the Primary is selected by default and stays selectable", async () => {
  const { context } = makeContext();
  assert.equal(context.get().instanceId, PRIMARY_ID);  // even before loading
  await context.refresh();
  assert.equal(context.get().mode, "instance");
  assert.equal(context.get().instance.name, "Primary");
  assert.equal(context.select(IRIS2), true);
  assert.equal(context.select(PRIMARY_ID), true);
  assert.equal(context.get().instanceId, PRIMARY_ID);
  assert.equal(context.get().instance.connection, "iris:52773");
});

test("IRIS-2 can be selected", async () => {
  const { context, storage } = makeContext();
  await context.refresh();
  assert.equal(context.select(IRIS2), true);
  const snapshot = context.get();
  assert.equal(snapshot.mode, "instance");
  assert.equal(snapshot.instanceId, IRIS2);
  assert.equal(snapshot.instance.name, "IRIS-2");
  assert.equal(snapshot.instance.connection, "iris-2:52773");
  assert.equal(storage.data.get("icc-instance-context"), IRIS2);
});

test("an inactive instance can't be selected", async () => {
  const { context, dispatched } = makeContext();
  await context.refresh();
  const before = dispatched.length;
  assert.equal(context.select(IRIS3), false);
  assert.equal(context.select("iris-doesnotexist"), false);
  assert.equal(context.get().instanceId, PRIMARY_ID);
  assert.equal(dispatched.length, before);
  assert.ok(!context.get().activeInstances.some((i) => i.id === IRIS3));
});

test("All Active Instances can be selected", async () => {
  const { context, storage } = makeContext();
  await context.refresh();
  assert.equal(context.select(ALL_ACTIVE), true);
  const snapshot = context.get();
  assert.equal(snapshot.mode, "all");
  assert.equal(snapshot.instanceId, null);
  assert.equal(snapshot.instance, null);
  assert.deepEqual(snapshot.activeInstances.map((i) => i.id), [PRIMARY_ID, IRIS2]);
  assert.equal(storage.data.get("icc-instance-context"), ALL_ACTIVE);
});

test("the selection survives a reload (same storage, new context)", async () => {
  const storage = memoryStorage();
  const first = makeContext({ storage });
  await first.context.refresh();
  first.context.select(IRIS2);

  const reloaded = makeContext({ storage });
  await reloaded.context.refresh();
  assert.equal(reloaded.context.get().instanceId, IRIS2);

  reloaded.context.select(ALL_ACTIVE);
  const again = makeContext({ storage });
  await again.context.refresh();
  assert.equal(again.context.get().mode, "all");
});

test("a saved instance that is gone or inactive falls back to the Primary", async () => {
  for (const saved of ["iris-deleted000000", IRIS3]) {
    const { context } = makeContext({ storage: memoryStorage({ "icc-instance-context": saved }) });
    await context.refresh();
    assert.equal(context.get().instanceId, PRIMARY_ID, saved);
  }
  // Saved IRIS-2, but it has been deactivated since.
  const { context } = makeContext({
    storage: memoryStorage({ "icc-instance-context": IRIS2 }),
    body: instances({ iris2Active: false }),
  });
  await context.refresh();
  assert.equal(context.get().instanceId, PRIMARY_ID);
});

test("a backend failure keeps the Primary", async () => {
  const { context } = makeContext({ fail: true, storage: memoryStorage({ "icc-instance-context": IRIS2 }) });
  assert.equal(await context.refresh(), false);
  assert.equal(context.get().instanceId, PRIMARY_ID);
  assert.equal(context.get().instance.primary, true);
});

test("changes are emitted to subscribers and dispatched, once per real change", async () => {
  const { context, dispatched } = makeContext();
  const seen = [];
  const unsubscribe = context.subscribe((snapshot) => seen.push(snapshot.mode === "all" ? "all" : snapshot.instanceId));
  await context.refresh();
  context.select(IRIS2);
  context.select(IRIS2);  // no change: no event
  context.select(ALL_ACTIVE);
  await context.refresh();  // same list: no event
  assert.deepEqual(seen, [PRIMARY_ID, IRIS2, "all"]);
  assert.equal(dispatched.length, 3);
  assert.ok(Object.isFrozen(dispatched[0]) && Object.isFrozen(dispatched[0].instances[0]));
  unsubscribe();
  context.select(PRIMARY_ID);
  assert.equal(seen.length, 3);
  assert.equal(dispatched.length, 4);
});

test("an updated list (e.g. from the Instances screen) moves an inactive selection back to the Primary", async () => {
  const { context } = makeContext();
  await context.refresh();
  context.select(IRIS2);
  context.setInstances(instances({ iris2Active: false }).instances);
  assert.equal(context.get().instanceId, PRIMARY_ID);
});

test("no password or Wallet reference reaches the context or storage", async () => {
  const { context, storage, dispatched } = makeContext();
  await context.refresh();
  context.select(IRIS2);
  for (const text of [JSON.stringify(context.get()), JSON.stringify(dispatched), JSON.stringify([...storage.data])]) {
    assert.ok(!text.includes(SECRET));
    assert.ok(!text.includes("credential_ref") && !text.includes("CommandCenter."));
    assert.ok(!text.includes("password") && !text.includes("username"));
  }
});

test("helpers", () => {
  assert.equal(connectionLabel("http://iris-2:52773"), "iris-2:52773");
  assert.equal(connectionLabel("not a url"), "");
  const entries = [{ id: PRIMARY_ID, active: true }, { id: IRIS2, active: true }, { id: IRIS3, active: false }];
  assert.equal(resolveSelection(entries, IRIS2), IRIS2);
  assert.equal(resolveSelection(entries, IRIS3), PRIMARY_ID);
  assert.equal(resolveSelection(entries, ALL_ACTIVE), ALL_ACTIVE);
  assert.equal(resolveSelection(entries, null), PRIMARY_ID);
});
