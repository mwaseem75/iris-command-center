// Color themes: Midnight (the default :root palette), Slate and Light.
// Each theme is a set of CSS color-token overrides on
// <html data-theme="..."> (see css/styles.css); Midnight is simply no
// attribute. The choice is remembered in localStorage — a per-viewer
// convenience only, so every storage access is guarded and the app works
// (in Midnight) when storage is unavailable. index.html's <head> applies the
// saved theme before first paint; this module keeps the selector in sync.

const STORAGE_KEY = "icc-theme";
const THEMES = ["midnight", "slate", "light"];
const DEFAULT_THEME = "midnight";

function readSavedTheme() {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    return THEMES.includes(saved) ? saved : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

function saveTheme(theme) {
  try {
    window.localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    // Storage unavailable (private window, blocked site data): the theme
    // still applies for this page view, it just isn't remembered.
  }
}

export function applyTheme(theme) {
  const valid = THEMES.includes(theme) ? theme : DEFAULT_THEME;
  if (valid === DEFAULT_THEME) delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = valid;
  return valid;
}

export function initThemeSelector() {
  const select = document.getElementById("theme-select");
  const current = applyTheme(readSavedTheme());
  if (!select) return;
  select.value = current;
  select.addEventListener("change", () => {
    saveTheme(applyTheme(select.value));
  });
}
