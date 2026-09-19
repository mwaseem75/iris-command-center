// Application bootstrap: wires sidebar navigation and starts the initial
// view. Every nav item is functional: Dashboard, System, Namespaces,
// Processes, Databases, Web Apps, Tasks, Security, Journal, Operations,
// AI Assistant, Observability, Extensions, Investigation, and the API
// Capability Explorer.

import { initNavigation } from "./nav.js";
import { loadDashboard, initDashboardControls } from "./dashboard.js";
import { loadSystemInfo, initSystemControls } from "./system.js";
import { loadNamespaces, initNamespacesControls } from "./namespaces.js";
import { loadProcesses, initProcessesControls } from "./processes.js";
import { loadDatabases, initDatabasesControls } from "./databases.js";
import { loadWebApps, initWebAppsControls } from "./web-apps.js";
import { loadTasks, initTasksControls } from "./tasks.js";
import { loadSecurity, initSecurityControls } from "./security.js";
import { loadJournal, initJournalControls } from "./journal.js";
import { loadOperations, initOperationsControls } from "./operations.js";
import { initAiAssistantControls } from "./ai-assistant.js";
import { loadExecutionTraces, initObservabilityControls } from "./observability.js";
import { loadExtensions, initExtensionsControls } from "./extensions.js";
import { loadInvestigation, initInvestigationControls } from "./investigation.js";
import { loadCapabilities, initCapabilitiesControls } from "./capabilities.js";

function init() {
  initDashboardControls();
  initSystemControls();
  initNamespacesControls();
  initProcessesControls();
  initDatabasesControls();
  initWebAppsControls();
  initTasksControls();
  initSecurityControls();
  initJournalControls();
  initOperationsControls();
  initAiAssistantControls();
  initObservabilityControls();
  initExtensionsControls();
  initInvestigationControls();
  initCapabilitiesControls();

  // Fetch fresh data every time a detail view is opened, so it can never
  // show stale information from an earlier visit.
  initNavigation((view) => {
    if (view === "system") {
      loadSystemInfo();
    } else if (view === "namespaces") {
      loadNamespaces();
    } else if (view === "processes") {
      loadProcesses();
    } else if (view === "databases") {
      loadDatabases();
    } else if (view === "web-apps") {
      loadWebApps();
    } else if (view === "tasks") {
      loadTasks();
    } else if (view === "security") {
      loadSecurity();
    } else if (view === "journal") {
      loadJournal();
    } else if (view === "operations") {
      loadOperations();
    } else if (view === "observability") {
      loadExecutionTraces();
    } else if (view === "extensions") {
      loadExtensions();
    } else if (view === "investigation") {
      loadInvestigation();
    } else if (view === "capabilities") {
      loadCapabilities();
    }
  });

  loadDashboard();
}

document.addEventListener("DOMContentLoaded", init);
