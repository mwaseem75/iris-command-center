// Application bootstrap: wires sidebar navigation and starts the dashboard.
// Only the Dashboard view is functional this step — every other nav item
// is a disabled visual placeholder (see index.html's `disabled` attributes
// and `nav-item__badge` "Soon" labels), so no routing logic is needed for
// them yet beyond what's already in the markup.

import { loadDashboard, initDashboardControls } from "./dashboard.js";

function init() {
  initDashboardControls();
  loadDashboard();
}

document.addEventListener("DOMContentLoaded", init);
