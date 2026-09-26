// Shared modal behaviour for the detail panels (the `.ns-drawer` elements
// on Namespaces, Databases, Processes, Web Apps, Tasks, Security and Demo
// Activity).
//
// Each page still shows/hides its own panel with the `hidden` attribute and
// handles Escape itself. This module watches that attribute and adds:
// - role="dialog" and aria-modal="true"
// - page scroll lock while a panel is open
// - Tab / Shift+Tab kept inside the panel
// - focus moved in on open (if the page didn't already) and back on close

const WORKSPACE_SELECTOR = ".ns-drawer";
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), ' +
  'textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
const OPEN_CLASS = "detail-workspace-open";

const openers = new Map(); // workspace -> element to return focus to
let lastInteracted = null;  // last element focused outside any panel

function isVisible(el) {
  return Boolean(el && el.isConnected && (el.offsetWidth || el.offsetHeight || el.getClientRects().length));
}

function focusableIn(workspace) {
  return [...workspace.querySelectorAll(FOCUSABLE)].filter((el) => isVisible(el) && !el.closest("[hidden]"));
}

// Pages often re-render while a panel is open, replacing the element that
// opened it. Build a selector (tag, first class, data-* attributes) to
// find the new one.
function identitySelector(el) {
  if (!(el instanceof Element)) return null;
  const parts = [el.tagName.toLowerCase()];
  if (el.classList.length) parts.push(`.${CSS.escape(el.classList[0])}`);
  const data = Object.entries(el.dataset);
  if (data.length === 0 && !el.id) return null;
  if (el.id) parts.push(`#${CSS.escape(el.id)}`);
  for (const [key, value] of data) {
    const attr = `data-${key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`;
    parts.push(`[${attr}="${CSS.escape(value)}"]`);
  }
  return parts.join("");
}

function openWorkspaces() {
  return [...document.querySelectorAll(WORKSPACE_SELECTOR)].filter((ws) => !ws.hidden);
}

function onOpened(workspace) {
  const active = document.activeElement;
  const opener = active && active !== document.body && !workspace.contains(active) ? active : lastInteracted;
  openers.set(workspace, { element: opener, selector: identitySelector(opener) });
  document.documentElement.classList.add(OPEN_CLASS);
  // Pages usually focus something in the panel themselves; only do it if not.
  if (!workspace.contains(document.activeElement)) {
    const [first] = focusableIn(workspace);
    (first || workspace).focus({ preventScroll: true });
  }
}

function onClosed(workspace) {
  if (openWorkspaces().length === 0) document.documentElement.classList.remove(OPEN_CLASS);
  const saved = openers.get(workspace);
  openers.delete(workspace);
  const active = document.activeElement;
  const focusWasInside = !active || active === document.body || workspace.contains(active);
  if (!focusWasInside) return;
  let target = saved && saved.element;
  if (!isVisible(target) && saved && saved.selector) {
    target = [...document.querySelectorAll(saved.selector)].find((el) => isVisible(el) && !el.closest(WORKSPACE_SELECTOR));
  }
  if (isVisible(target)) target.focus({ preventScroll: true });
  // Don't leave focus inside the hidden panel.
  else if (active && workspace.contains(active)) active.blur();
}

function trapTab(event) {
  if (event.key !== "Tab") return;
  const workspace = event.currentTarget;
  const items = focusableIn(workspace);
  if (items.length === 0) {
    event.preventDefault();
    workspace.focus();
    return;
  }
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && (document.activeElement === first || document.activeElement === workspace)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function initDetailWorkspaces() {
  const workspaces = [...document.querySelectorAll(WORKSPACE_SELECTOR)];
  if (workspaces.length === 0) return;

  // Remember what opened the panel (row, card or button) so focus can go
  // back there.
  const remember = (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target || target.closest(WORKSPACE_SELECTOR)) return;
    lastInteracted = target.closest(`${FOCUSABLE}, tr[tabindex], [role="button"]`) || lastInteracted;
  };
  document.addEventListener("pointerdown", remember, true);
  document.addEventListener("focusin", remember, true);

  const observer = new MutationObserver((records) => {
    for (const record of records) {
      const workspace = record.target;
      if (workspace.hidden) onClosed(workspace);
      else onOpened(workspace);
    }
  });

  for (const workspace of workspaces) {
    workspace.setAttribute("role", "dialog");
    workspace.setAttribute("aria-modal", "true");
    if (!workspace.hasAttribute("tabindex")) workspace.tabIndex = -1;
    workspace.addEventListener("keydown", trapTab);
    observer.observe(workspace, { attributes: true, attributeFilter: ["hidden"] });
  }
}
