// Minimal client-side view switching. No URL/hash routing, no framework —
// each nav button's data-view attribute is matched against a <section>
// carrying the same data-view attribute; exactly one view is shown at a
// time. This is the first navigation logic in the app (Step 1 had only
// one functional view), so there is no prior convention to preserve
// beyond the existing `.nav-item`/`.view`/`disabled` markup it reads.

const NAV_SELECTOR = ".nav-item[data-view]";
const VIEW_SELECTOR = ".view[data-view]";

// Set once by initNavigation() so navigateTo() (used by cross-view links,
// e.g. Observability <-> Investigation) can trigger the exact same
// view-opened callback a real nav click would — a programmatic click,
// not a second, parallel navigation mechanism.
let activeOnNavigate = null;

function showView(name) {
  document.querySelectorAll(VIEW_SELECTOR).forEach((section) => {
    section.hidden = section.dataset.view !== name;
  });
  document.querySelectorAll(NAV_SELECTOR).forEach((button) => {
    const isActive = button.dataset.view === name;
    button.classList.toggle("nav-item--active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
}

/**
 * Wires every ENABLED nav button to switch views on click and calls
 * `onNavigate(viewName)` afterward. Still-`disabled` items (Processes,
 * Databases, ...) are left exactly as index.html already has them —
 * this never attaches a handler to a disabled button, so they remain
 * inert placeholders with no behavior change.
 */
export function initNavigation(onNavigate) {
  activeOnNavigate = typeof onNavigate === "function" ? onNavigate : null;
  document.querySelectorAll(NAV_SELECTOR).forEach((button) => {
    if (button.disabled) return;
    button.addEventListener("click", () => {
      navigateTo(button.dataset.view);
    });
  });
}

/**
 * Switches to `viewName` exactly as clicking its nav button would —
 * updates the visible section/active nav state and invokes the same
 * onNavigate(viewName) callback passed to initNavigation(). Exists so one
 * view can send the operator to another already-loaded view (e.g.
 * Observability's "Investigate around this time" cross-link) without
 * duplicating nav.js's own view-switching logic or introducing URL
 * routing this app deliberately doesn't have.
 */
export function navigateTo(viewName) {
  showView(viewName);
  if (activeOnNavigate) {
    activeOnNavigate(viewName);
  }
}
