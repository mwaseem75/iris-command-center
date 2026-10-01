// Instance context: which IRIS instance the instance-aware pages read,
// chosen in the instance selector at the right of their page header (one
// selector, moved into the open page's header by app.js; the Fleet Overview
// shows every active instance and has none).
//
// Other modules read it with getInstanceContext() and follow changes with
// onInstanceContextChange(callback); the same snapshot is also dispatched as
// the "icc:instance-context-change" event on document. A snapshot holds only
// safe fields (id, name, primary, active, selectable, host:port) - never a
// password or Wallet reference.
//
// Only selectable instances can be chosen: active, and either the Primary or
// an instance that answers right now. Each refresh (app start, opening the
// selector or an instance page, the Instances screen) checks every active
// instance other than the Primary with the read-only GET /api/iris/info
// (activation already required a compatible check; this checks it's still
// reachable). The choice is saved in localStorage (like the theme); a saved or
// selected instance that is gone, inactive or unreachable falls back to the
// Primary, which is always active, and the snapshot names it (fallbackFrom)
// so pages can say so. Page reads never fall back: they use the selection.

import { IrisApi } from "./api.js";

export const PRIMARY_ID = "primary";
export const CONTEXT_EVENT = "icc:instance-context-change";
const STORAGE_KEY = "icc-instance-context";

// Shown until the list loads (or if it can't be loaded).
const PRIMARY_PLACEHOLDER = { id: PRIMARY_ID, name: "Primary", primary: true, active: true, selectable: true, connection: "" };

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
// `reachable` is the set of instance ids that answered the last check.
function toEntry(instance, reachable) {
  const primary = instance.primary === true;
  const active = instance.active === true;
  return {
    id: String(instance.id),
    name: String(instance.name),
    primary,
    active,
    selectable: active && (primary || reachable.has(String(instance.id))),
    connection: connectionLabel(instance.base_url),
  };
}

/** The selection to use: the wanted one if it's still selectable, else the Primary. */
export function resolveSelection(entries, wanted) {
  return entries.some((entry) => entry.selectable && entry.id === wanted) ? wanted : PRIMARY_ID;
}

/**
 * The context store, without any DOM: `loadInstances` returns the
 * GET /api/iris/instances body, `checkInstance(id)` resolves true if that
 * instance answers now, `storage` is localStorage (or a stand-in), and
 * `dispatch` gets every new snapshot. Exported for tests; the app uses the
 * single instance below.
 */
export function createInstanceContext({ loadInstances, checkInstance = async () => false, storage = null, dispatch = null } = {}) {
  let entries = [{ ...PRIMARY_PLACEHOLDER }];
  // The Primary until the list has loaded; then the saved choice, if it's
  // still available.
  let selection = PRIMARY_ID;
  let wanted = readSaved();
  let reachable = new Set();  // ids that answered the last check
  let fallbackFrom = null;    // name of an instance we had to leave for the Primary
  let refreshing = null;      // the refresh in progress, shared by overlapping callers
  let last = null;
  const listeners = new Set();

  // Check every active instance other than the Primary, all at once.
  async function check(instances) {
    const ids = instances.filter((instance) => instance.active === true && instance.primary !== true)
      .map((instance) => String(instance.id));
    const results = await Promise.allSettled(ids.map((id) => checkInstance(id)));
    return new Set(ids.filter((_, i) => results[i].status === "fulfilled" && results[i].value === true));
  }

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
    const instance = entries.find((entry) => entry.id === selection) || null;
    return Object.freeze({
      instanceId: selection,
      instance: instance ? Object.freeze({ ...instance }) : null,
      instances: Object.freeze(entries.map((entry) => Object.freeze({ ...entry }))),
      fallbackFrom,
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

    /**
     * Take a fresh instance list; `answered` is the set of ids that answered
     * a check just now (default: the last check's result).
     */
    setInstances(instances, answered = reachable) {
      reachable = answered;
      const previous = entries;
      const list = Array.isArray(instances) ? instances.map((instance) => toEntry(instance, reachable)) : [];
      entries = list.some((entry) => entry.primary) ? list : [{ ...PRIMARY_PLACEHOLDER }, ...list];
      const intended = wanted || selection;
      selection = resolveSelection(entries, intended);
      wanted = null;
      if (selection !== intended) {
        const left = entries.find((entry) => entry.id === intended) || previous.find((entry) => entry.id === intended);
        fallbackFrom = left ? left.name : null;
      }
      publish();
    },

    /** Load the list from the backend and check the instances; on failure keep what we have. */
    refresh() {
      if (refreshing) return refreshing;
      refreshing = (async () => {
        try {
          const body = await loadInstances();
          const instances = body && Array.isArray(body.instances) ? body.instances : [];
          this.setInstances(instances, await check(instances));
          return true;
        } catch {
          publish();  // still the Primary (or the last good list)
          return false;
        } finally {
          refreshing = null;
        }
      })();
      return refreshing;
    },

    /** Select a selectable instance id. Returns false if it isn't selectable. */
    select(value) {
      if (resolveSelection(entries, value) !== value) return false;
      selection = value;
      wanted = null;
      fallbackFrom = null;
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
  // Reachable now: the instance answers the read-only info route.
  checkInstance: (id) => IrisApi.getInfo(id).then(() => true, () => false),
  storage: storageOrNull(),
  dispatch: (snapshot) => {
    if (typeof document !== "undefined") {
      document.dispatchEvent(new CustomEvent(CONTEXT_EVENT, { detail: snapshot }));
    }
  },
});

/** The current context: { instanceId, instance, instances, fallbackFrom }. */
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
  return ctx.instance && !ctx.instance.primary ? ctx.instanceId : undefined;
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
  context.refresh();  // and check the (possibly new or reactivated) instances
}

// --- instance selector (in the open page's header) ---

const ICONS = { primary: "⌂", instance: "≣" };

function optionButton({ value, icon, name, meta, selected }) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "instance-selector__option";
  button.setAttribute("role", "option");
  button.setAttribute("aria-selected", String(selected));
  button.dataset.value = value;
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

export function initInstanceSelector() {
  const root = document.getElementById("instance-selector");
  if (!root) return;
  const button = document.getElementById("instance-selector-button");
  const list = document.getElementById("instance-selector-list");
  const icon = document.getElementById("instance-selector-icon");
  const name = document.getElementById("instance-selector-name");
  const meta = document.getElementById("instance-selector-meta");

  const render = (snapshot) => {
    const current = snapshot.instance || PRIMARY_PLACEHOLDER;
    icon.textContent = current.primary ? ICONS.primary : ICONS.instance;
    name.textContent = current.name;
    meta.textContent = current.connection;

    // Only selectable instances are offered (active and answering now).
    list.replaceChildren(...snapshot.instances.filter((entry) => entry.selectable).map((entry) => optionButton({
      value: entry.id,
      icon: entry.primary ? ICONS.primary : ICONS.instance,
      name: entry.name,
      meta: entry.connection,
      selected: snapshot.instanceId === entry.id,
    })));
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

/**
 * Show the selector at the right of `header` (a page's .view__header), after
 * its title block; with no header, hide it. Called by app.js when a page opens.
 */
export function placeInstanceSelector(header) {
  const root = document.getElementById("instance-selector");
  if (!root) return;
  document.getElementById("instance-selector-list").hidden = true;
  document.getElementById("instance-selector-button").setAttribute("aria-expanded", "false");
  if (!header || !header.firstElementChild) {
    root.hidden = true;
    return;
  }
  if (root.previousElementSibling !== header.firstElementChild) header.firstElementChild.after(root);
  root.hidden = false;
}
