// Application bootstrap: wires sidebar navigation and starts the initial
// view. Dashboard, System, and Processes are functional (Phase 3 Steps
// 1-3); every remaining nav item is still a disabled visual placeholder
// (see index.html's `disabled` attributes) — nav.js never attaches a
// handler to a disabled button, so they stay inert with no change in
// behavior.

import { initNavigation } from "./nav.js";
import { loadDashboard, initDashboardControls } from "./dashboard.js";
import { loadSystemInfo, initSystemControls } from "./system.js";
import { loadProcesses, initProcessesControls } from "./processes.js";

function init() {
  initDashboardControls();
  initSystemControls();
  initProcessesControls();

  // Fetch fresh data every time a detail view is opened, so it can never
  // show stale information from an earlier visit.
  initNavigation((view) => {
    if (view === "system") {
      loadSystemInfo();
    } else if (view === "processes") {
      loadProcesses();
    }
  });

  loadDashboard();
}

document.addEventListener("DOMContentLoaded", init);
