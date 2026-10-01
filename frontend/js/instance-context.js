// Global instance context: which IRIS instance (or "All Active Instances")
// the console is working with, chosen in the header selector.
//
// This is only the foundation. No screen uses the context yet, and "All
// Active Instances" is just a selection: nothing queries several instances.
//
// Other modules read it with getInstanceContext() and follow changes with
// onInstanceContextChange(callback); the same snapshot is also dispatched as
// the "icc:instance-context-change" event on document. A snapshot holds only
// safe fields (id, name, primary, active, host:port) - never a password or
// Wallet reference.
//
// The choice is saved in localStorage (like the theme). A saved instance that
// no longer exists or is inactive falls back to the Primary, which is always
// active.

import { IrisApi } from "./api.js";

export const PRIMARY_ID = "primary";
export const ALL_ACTIVE = "all";
export const CONTEXT_EVENT = "icc:instance-context-change";
const STORAGE_KEY = "icc-instance-context";

// Shown until the list loads (or if it can't be loaded).
const PRIMARY_PLACEHOLDER = { id: PRIMARY_ID, name: "Primary", primary: true, active: true, connection: "" };

/** "http://iris-2:52773" -> "iris-2:52773"; "" if it isn't a URL. */
export function connectionLabel(baseUrl) {
  try {
    return new URL(baseUrl).host;
  } catch {
    return "";
  }
}

// Only the fields the selector needs, so nothing else (whatever the API adds
// later) can reach the context.
function toEntry(instance) {
  return {
    id: String(instance.id),
    name: String(instance.name),
    primary: instance.primary === true,
    active: instance.active === true,
    connection: connectionLabel(instance.base_url),
  };
}

/** The selection to use: the wanted one if it's still available, else the Primary. */
export function resolveSelection(entries, wanted) {
  const active = entries.filter((entry) => entry.active);
  if (wanted === ALL_ACTIVE) return active.length > 0 ? ALL_ACTIVE : PRIMARY_ID;
  return active.some((entry) => entry.id === wanted) ? wanted : PRIMARY_ID;
}

/**
 * The context store, without any DOM: `loadInstances` returns the
 * GET /api/iris/instances body, `storage` is localStorage (or a stand-in),
 * and `dispatch` gets every new snapshot. Exported for tests; the app uses
 * the single instance below.
 */
export function createInstanceContext({ loadInstances, storage = null, dispatch = null } = {}) {
  let entries = [{ ...PRIMARY_PLACEHOLDER }];
  // The Primary until the list has loaded; then the saved choice, if it's
  // still available.
  let selection = PRIMARY_ID;
  let wanted = readSaved();
  let last = null;
  const listeners = new Set();

  function readSaved() {
    try {
      return storage ? storage.getItem(STORAGE_KEY) : null;
    } catch {
      return null;  // no storage (private window etc.)
    }
  }

  function save(value) {
    try {
      if (storage) storage.setItem(STORAGE_KEY, value);
    } catch {
      // Not remembered, but the selection still applies.
    }
  }

  function snapshot() {
    const activeInstances = entries.filter((entry) => entry.active).map((entry) => Object.freeze({ ...entry }));
    const instance = selection === ALL_ACTIVE ? null : entries.find((entry) => entry.id === selection) || null;
    return Object.freeze({
      mode: selection === ALL_ACTIVE ? "all" : "instance",
      instanceId: selection === ALL_ACTIVE ? null : selection,
      instance: instance ? Object.freeze({ ...instance }) : null,
      activeInstances: Object.freeze(activeInstances),
      instances: Object.freeze(entries.map((entry) => Object.freeze({ ...entry }))),
    });
  }

  // Tell listeners, but only when something they can see changed.
  function publish() {
    const next = snapshot();
    const key = JSON.stringify(next);
    if (key === last) return;
    last = key;
    for (const listener of listeners) listener(next);
    if (dispatch) dispatch(next);
  }

  return {
    get: snapshot,

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    /** Take a fresh instance list (e.g. from the Instances screen). */
    setInstances(instances) {
      const list = Array.isArray(instances) ? instances.map(toEntry) : [];
      entries = list.some((entry) => entry.primary) ? list : [{ ...PRIMARY_PLACEHOLDER }, ...list];
      selection = resolveSelection(entries, wanted || selection);
      wanted = null;
      publish();
    },

    /** Load the list from the backend; on failure keep what we have. */
    async refresh() {
      try {
        const body = await loadInstances();
        this.setInstances(body && body.instances);
        return true;
      } catch {
        publish();  // still the Primary (or the last good list)
        return false;
      }
    },

    /** Select an active instance id or ALL_ACTIVE. Returns false if it isn't selectable. */
    select(value) {
      if (resolveSelection(entries, value) !== value) return false;
      selection = value;
      wanted = null;
      save(value);
      publish();
      return true;
    },
  };
}

function storageOrNull() {
  try {
    return globalThis.localStorage || null;
  } catch {
    return null;
  }
}

const context = createInstanceContext({
  loadInstances: () => IrisApi.getInstances(),
  storage: storageOrNull(),
  dispatch: (snapshot) => {
    if (typeof document !== "undefined") {
      document.dispatchEvent(new CustomEvent(CONTEXT_EVENT, { detail: snapshot }));
    }
  },
});

/** The current context: { mode: "instance" | "all", instanceId, instance, activeInstances, instances }. */
export function getInstanceContext() {
  return context.get();
}

/** Call `callback(snapshot)` on every change; returns an unsubscribe function. */
export function onInstanceContextChange(callback) {
  return context.subscribe(callback);
}

/** The id to send as ?instance= for the selected instance; undefined for the Primary. */
export function selectedInstanceId() {
  const ctx = context.get();
  return ctx.mode === "instance" && ctx.instance && !ctx.instance.primary ? ctx.instanceId : undefined;
}

export function selectInstanceContext(value) {
  return context.select(value);
}

export function refreshInstanceContext() {
  return context.refresh();
}

/** Used by the Instances screen after it reloads, so the selector follows changes. */
export function updateInstanceContextList(instances) {
  context.setInstances(instances);
}

// --- header selector ---

const ICONS = { primary: "⌂", instance: "≣", all: "⧉" };

function optionButton({ value, icon, name, meta, selected, disabled }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "instance-selector__option";
  button.setAttribute("role", "option");
  button.setAttribute("aria-selected", String(selected));
  button.dataset.value = value;
  if (disabled) {
    button.disabled = true;
    button.setAttribute("aria-disabled", "true");
  }
  const iconEl = document.createElement("span");
  iconEl.className = "instance-selector__icon";
  iconEl.setAttribute("aria-hidden", "true");
  iconEl.textContent = icon;
  const text = document.createElement("span");
  text.className = "instance-selector__text";
  const nameEl = document.createElement("span");
  nameEl.className = "instance-selector__name";
  nameEl.textContent = name;
  const metaEl = document.createElement("span");
  metaEl.className = "instance-selector__meta";
  metaEl.textContent = meta;
  text.append(nameEl, metaEl);
  const check = document.createElement("span");
  check.className = "instance-selector__check";
  check.setAttribute("aria-hidden", "true");
  check.textContent = selected ? "✓" : "";
  button.append(iconEl, text, check);
  return button;
}

function activeCountLabel(count) {
  return `${count} active instance${count === 1 ? "" : "s"}`;
}

export function initInstanceSelector() {
  const root = document.getElementById("instance-selector");
  if (!root) return;
  const button = document.getElementById("instance-selector-button");
  const list = document.getElementById("instance-selector-list");
  const icon = document.getElementById("instance-selector-icon");
  const name = document.getElementById("instance-selector-name");
  const meta = document.getElementById("instance-selector-meta");

  const render = (snapshot) => {
    if (snapshot.mode === "all") {
      icon.textContent = ICONS.all;
      name.textContent = "All Active Instances";
      meta.textContent = activeCountLabel(snapshot.activeInstances.length);
    } else {
      const current = snapshot.instance || PRIMARY_PLACEHOLDER;
      icon.textContent = current.primary ? ICONS.primary : ICONS.instance;
      name.textContent = current.name;
      meta.textContent = current.connection;
    }
    root.dataset.mode = snapshot.mode;

    list.replaceChildren();
    for (const entry of snapshot.instances) {
      list.append(optionButton({
        value: entry.id,
        icon: entry.primary ? ICONS.primary : ICONS.instance,
        name: entry.name,
        meta: entry.active ? entry.connection : `Inactive · ${entry.connection}`,
        selected: snapshot.mode === "instance" && snapshot.instanceId === entry.id,
        disabled: !entry.active,
      }));
    }
    const divider = document.createElement("div");
    divider.className = "instance-selector__divider";
    divider.setAttribute("role", "separator");
    list.append(divider, optionButton({
      value: ALL_ACTIVE,
      icon: ICONS.all,
      name: "All Active Instances",
      meta: `Group context · ${activeCountLabel(snapshot.activeInstances.length)}`,
      selected: snapshot.mode === "all",
      disabled: snapshot.activeInstances.length === 0,
    }));
  };

  const enabledOptions = () => [...list.querySelectorAll(".instance-selector__option:not([disabled])")];

  const setOpen = (open) => {
    list.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
    if (open) {
      const target = list.querySelector('[aria-selected="true"]:not([disabled])') || enabledOptions()[0];
      if (target) target.focus();
    }
  };

  button.addEventListener("click", () => {
    const opening = list.hidden;
    setOpen(opening);
    // Refresh in the background so the list is current.
    if (opening) refreshInstanceContext();
  });

  list.addEventListener("click", (event) => {
    const option = event.target.closest(".instance-selector__option");
    if (!option || option.disabled) return;
    selectInstanceContext(option.dataset.value);
    setOpen(false);
    button.focus();
  });

  list.addEventListener("keydown", (event) => {
    const options = enabledOptions();
    const index = options.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      const next = options[(index + step + options.length) % options.length];
      if (next) next.focus();
    } else if (event.key === "Escape") {
      setOpen(false);
      button.focus();
    }
  });

  // Close on a click elsewhere or when focus leaves the selector.
  document.addEventListener("click", (event) => {
    if (!list.hidden && !root.contains(event.target)) setOpen(false);
  });
  root.addEventListener("focusout", (event) => {
    if (!list.hidden && event.relatedTarget && !root.contains(event.relatedTarget)) setOpen(false);
  });

  onInstanceContextChange(render);
  render(getInstanceContext());
  refreshInstanceContext();
}
