// Instance context (frontend/js/instance-context.js), tested without a
// browser: the store is driven with a fake GET /api/iris/instances loader, a
// fake reachability check (the app uses GET /api/iris/info?instance=) and an
// in-memory localStorage stand-in.
//
// Run with Node's built-in runner (no npm packages):
//     node --test tests/test_instance_context.mjs

import assert from "node:assert/strict";
import { test } from "node:test";

import * as module from "../frontend/js/instance-context.js";

const { PRIMARY_ID, connectionLabel, createInstanceContext, resolveSelection } = module;

const IRIS2 = "iris-2b1365d07d62";
const IRIS3 = "iris-3c0ffee00001";   // inactive
const IRIS4 = "iris-4dead0000004";   // active, but doesn't answer
const SECRET = "Pw-CONTEXT-CANARY-not-real";

// Shaped like the real InstanceView, plus fields that must never get through.
function instances({ iris2Active = true, iris2Check = "compatible", withOthers = true } = {}) {
  const list = [
    { id: PRIMARY_ID, name: "Primary", base_url: "http://iris:52773", username: "_SYSTEM", namespace: "USER",
      active: true, primary: true, has_credential: true, last_check: null },
    { id: IRIS2, name: "IRIS-2", base_url: "http://iris-2:52773", username: "_SYSTEM", namespace: "USER",
      active: iris2Active, primary: false, has_credential: true, last_check: { status: iris2Check },
      password: SECRET, credential_ref: `CommandCenter.${IRIS2}` },
  ];
  if (withOthers) {
    list.push(
      { id: IRIS3, name: "IRIS-3", base_url: "http://iris-3:52773", username: "ops", namespace: "USER",
        active: false, primary: false, has_credential: true, last_check: { status: "compatible" } },
      { id: IRIS4, name: "IRIS-4", base_url: "http://iris-4:52773", username: "ops", namespace: "USER",
        active: true, primary: false, has_credential: true, last_check: { status: "unreachable" } },
    );
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

// `down` holds the ids that don't answer the reachability check right now.
function makeContext({ body = instances(), storage = memoryStorage(), fail = false, down = new Set([IRIS4]) } = {}) {
  const dispatched = [];
  const checked = [];
  let loads = 0;
  const context = createInstanceContext({
    loadInstances: async () => {
      loads += 1;
      if (fail) throw new Error("backend down");
      return typeof body === "function" ? body() : body;
    },
    checkInstance: async (id) => {
      checked.push(id);
      if (down.has(id)) throw new Error("502");
      return true;
    },
    storage,
    dispatch: (snapshot) => dispatched.push(snapshot),
  });
  return { context, storage, dispatched, checked, down, loads: () => loads };
}

test("loads the instances and marks which are selectable (active and, unless Primary, answering now)", async () => {
  const { context, checked } = makeContext();
  assert.equal(await context.refresh(), true);
  const snapshot = context.get();
  assert.deepEqual(snapshot.instances.map((i) => [i.id, i.selectable]),
    [[PRIMARY_ID, true], [IRIS2, true], [IRIS3, false], [IRIS4, false]]);
  assert.deepEqual(snapshot.instances[1],
    { id: IRIS2, name: "IRIS-2", primary: false, active: true, selectable: true, connection: "iris-2:52773" });
  assert.deepEqual(Object.keys(snapshot).sort(), ["fallbackFrom", "instance", "instanceId", "instances"]);
  // Only the active instances other than the Primary are checked.
  assert.deepEqual(checked.sort(), [IRIS2, IRIS4].sort());
});

test("a saved last_check doesn't make an instance selectable: only a current answer does", async () => {
  const { context } = makeContext({ down: new Set([IRIS2]) });   // IRIS-2's saved check is "compatible"
  await context.refresh();
  assert.equal(context.get().instances[1].selectable, false);
  assert.equal(context.select(IRIS2), false);
});

test("a selected instance that stops answering falls back to the Primary, and the snapshot says so", async () => {
  const { context, down } = makeContext();
  await context.refresh();
  assert.equal(context.select(IRIS2), true);
  assert.equal(context.get().fallbackFrom, null);
  down.add(IRIS2);
  await context.refresh();
  assert.equal(context.get().instanceId, PRIMARY_ID);
  assert.equal(context.get().fallbackFrom, "IRIS-2");
  assert.equal(context.select(IRIS2), false);
  down.delete(IRIS2);
  await context.refresh();
  assert.equal(context.get().instanceId, PRIMARY_ID, "back up: offered again, but not re-selected by itself");
  assert.equal(context.select(IRIS2), true);
  assert.equal(context.get().fallbackFrom, null);
});

test("overlapping refreshes share one load and one round of checks", async () => {
  const { context, checked, loads } = makeContext();
  await Promise.all([context.refresh(), context.refresh(), context.refresh()]);
  assert.equal(loads(), 1);
  assert.equal(checked.length, 2);
  await context.refresh();
  assert.equal(loads(), 2);
});

test("the Primary is selected by default and stays selectable", async () => {
  const { context } = makeContext();
  assert.equal(context.get().instanceId, PRIMARY_ID);  // even before loading
  await context.refresh();
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
  assert.equal(snapshot.instanceId, IRIS2);
  assert.equal(snapshot.instance.name, "IRIS-2");
  assert.equal(snapshot.instance.connection, "iris-2:52773");
  assert.equal(storage.data.get("icc-instance-context"), IRIS2);
});

test("inactive, unreachable and unknown instances can't be selected", async () => {
  const { context, dispatched } = makeContext();
  await context.refresh();
  const before = dispatched.length;
  for (const id of [IRIS3, IRIS4, "iris-doesnotexist"]) assert.equal(context.select(id), false, id);
  assert.equal(context.get().instanceId, PRIMARY_ID);
  assert.equal(dispatched.length, before);
});

test("All Active Instances is not an option", async () => {
  const { context } = makeContext();
  await context.refresh();
  assert.equal("ALL_ACTIVE" in module, false);
  assert.equal(context.select("all"), false);
  assert.equal(context.get().instanceId, PRIMARY_ID);
});

test("the selection survives a reload (same storage, new context)", async () => {
  const storage = memoryStorage();
  const first = makeContext({ storage });
  await first.context.refresh();
  first.context.select(IRIS2);

  const reloaded = makeContext({ storage });
  await reloaded.context.refresh();
  assert.equal(reloaded.context.get().instanceId, IRIS2);
});

test("a saved choice that is gone, inactive, unreachable or the old 'all' falls back to the Primary", async () => {
  for (const saved of ["iris-deleted000000", IRIS3, IRIS4, "all"]) {
    const { context } = makeContext({ storage: memoryStorage({ "icc-instance-context": saved }) });
    await context.refresh();
    assert.equal(context.get().instanceId, PRIMARY_ID, saved);
  }
  // An unreachable saved instance is named, so the page can say why.
  const unreachable = makeContext({ storage: memoryStorage({ "icc-instance-context": IRIS4 }) });
  await unreachable.context.refresh();
  assert.equal(unreachable.context.get().fallbackFrom, "IRIS-4");
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
  const unsubscribe = context.subscribe((snapshot) => seen.push(snapshot.instanceId));
  await context.refresh();
  context.select(IRIS2);
  context.select(IRIS2);  // no change: no event
  await context.refresh();  // same list: no event
  assert.deepEqual(seen, [PRIMARY_ID, IRIS2]);
  assert.equal(dispatched.length, 2);
  assert.ok(Object.isFrozen(dispatched[0]) && Object.isFrozen(dispatched[0].instances[0]));
  unsubscribe();
  context.select(PRIMARY_ID);
  assert.equal(seen.length, 2);
  assert.equal(dispatched.length, 3);
});

test("an updated list moves a selection that is no longer active back to the Primary", async () => {
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
  const entries = [
    { id: PRIMARY_ID, selectable: true }, { id: IRIS2, selectable: true }, { id: IRIS3, selectable: false },
  ];
  assert.equal(resolveSelection(entries, IRIS2), IRIS2);
  assert.equal(resolveSelection(entries, IRIS3), PRIMARY_ID);
  assert.equal(resolveSelection(entries, "all"), PRIMARY_ID);
  assert.equal(resolveSelection(entries, null), PRIMARY_ID);
});
