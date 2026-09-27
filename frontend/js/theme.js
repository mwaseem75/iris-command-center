// Color themes: Midnight (default), Slate, Professional and Light.
//
// Each theme overrides the CSS color tokens via <html data-theme="...">;
// Midnight is no attribute at all. The choice is saved in localStorage if
// available. index.html applies it before first paint; this module keeps
// the header switch in sync.

const STORAGE_KEY = "icc-theme";
const THEMES = ["midnight", "slate", "professional", "light"];
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
    // No storage (private window etc.): the theme still applies, it just
    // isn't remembered.
  }
}

export function applyTheme(theme) {
  const valid = THEMES.includes(theme) ? theme : DEFAULT_THEME;
  if (valid === DEFAULT_THEME) delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = valid;
  return valid;
}

export function initThemeSelector() {
  const group = document.getElementById("theme-select");
  const current = applyTheme(readSavedTheme());
  if (!group) return;
  const options = [...group.querySelectorAll("button[value]")];
  const sync = (theme) => {
    options.forEach((button) => button.setAttribute("aria-pressed", String(button.value === theme)));
  };
  sync(current);
  options.forEach((button) => {
    button.addEventListener("click", () => {
      const theme = applyTheme(button.value);
      saveTheme(theme);
      sync(theme);
    });
  });
}
