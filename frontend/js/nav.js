// Simple page switching, no routing. Each nav button's data-view matches a
// <section data-view="..."> and only one is shown at a time.

const NAV_SELECTOR = ".nav-item[data-view]";
const VIEW_SELECTOR = ".view[data-view]";

// Saved by initNavigation() so navigateTo() can run the same callback as a
// real nav click.
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
 * Hook up every enabled nav button to switch pages and call
 * `onNavigate(viewName)`. Disabled buttons are left alone.
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
 * Switch to `viewName` as if its nav button was clicked (same onNavigate
 * callback). Used for links between pages, e.g. Observability's
 * "Investigate around this time".
 */
export function navigateTo(viewName) {
  showView(viewName);
  if (activeOnNavigate) {
    activeOnNavigate(viewName);
  }
}
