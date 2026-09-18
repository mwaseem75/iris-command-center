// Application bootstrap: wires sidebar navigation and starts the initial
// view. Dashboard, System, Processes, Databases, and Web Apps are
// functional (Phase 3 Steps 1-5); every remaining nav item is still a
// disabled visual placeholder (see index.html's `disabled` attributes) —
// nav.js never attaches a handler to a disabled button, so they stay inert
// with no change in behavior.

import { initNavigation } from "./nav.js";
import { loadDashboard, initDashboardControls } from "./dashboard.js";
import { loadSystemInfo, initSystemControls } from "./system.js";
import { loadProcesses, initProcessesControls } from "./processes.js";
import { loadDatabases, initDatabasesControls } from "./databases.js";
import { loadWebApps, initWebAppsControls } from "./web-apps.js";

function init() {
  initDashboardControls();
  initSystemControls();
  initProcessesControls();
  initDatabasesControls();
  initWebAppsControls();

  // Fetch fresh data every time a detail view is opened, so it can never
  // show stale information from an earlier visit.
  initNavigation((view) => {
    if (view === "system") {
      loadSystemInfo();
    } else if (view === "processes") {
      loadProcesses();
    } else if (view === "databases") {
      loadDatabases();
    } else if (view === "web-apps") {
      loadWebApps();
    }
  });

  loadDashboard();
}

document.addEventListener("DOMContentLoaded", init);
