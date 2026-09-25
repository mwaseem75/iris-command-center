// Application bootstrap: wires sidebar navigation and starts the initial
// view. Every nav item is functional: Dashboard, System, Namespaces,
// Processes, Databases, Web Apps, Tasks, Security, Journal, Operations,
// AI Assistant, Observability, Extensions, Investigation, and the API
// Capability Explorer.
//
// Also wires the one cross-link between Observability and Investigation
// (see nav.js's navigateTo() and each view's own setTimeWindow()) — this
// is the only place either view's module is aware the other exists.

import { initNavigation, navigateTo } from "./nav.js";
import { initThemeSelector } from "./theme.js";
import { loadDashboard, initDashboardControls, onDashboardShown } from "./dashboard.js";
import { loadSystemInfo, initSystemControls } from "./system.js";
import { loadNamespaces, initNamespacesControls } from "./namespaces.js";
import { loadProcesses, initProcessesControls } from "./processes.js";
import { loadDatabases, initDatabasesControls } from "./databases.js";
import { loadWebApps, initWebAppsControls } from "./web-apps.js";
import { loadTasks, initTasksControls } from "./tasks.js";
import { loadSecurity, initSecurityControls } from "./security.js";
import { loadSecurityAccess, initSecurityAccessControls } from "./security-access.js";
import { initSecurityAuthControls, refreshSecurityAuthIfLoaded } from "./security-auth.js";
import { initSecurityWalletControls, refreshSecurityWalletIfLoaded } from "./security-wallet.js";
import { initSecurityX509Controls, refreshSecurityX509IfLoaded } from "./security-x509.js";
import { loadJournal, initJournalControls } from "./journal.js";
import { loadOperations, initOperationsControls } from "./operations.js";
import { initAiAssistantControls } from "./ai-assistant.js";
import {
  loadExecutionTraces,
  initObservabilityControls,
  setTimeWindow as setObservabilityTimeWindow,
  focusTrace as focusObservabilityTrace,
} from "./observability.js";
import { initDemoActivity } from "./demo-activity.js";
import { loadExtensions, initExtensionsControls } from "./extensions.js";
import {
  loadInvestigation,
  initInvestigationControls,
  setTimeWindow as setInvestigationTimeWindow,
} from "./investigation.js";
import { loadCapabilities, initCapabilitiesControls } from "./capabilities.js";

function init() {
  initThemeSelector();
  // Opening a trace from the Dashboard or Demo Activity reuses the
  // existing Observability detail: focus the trace, then navigate, so the
  // view's normal view-opened load renders the real, fresh trace list.
  const openTrace = (traceId) => {
    focusObservabilityTrace(traceId);
    navigateTo("observability");
  };
  initDashboardControls({ onOpenTrace: openTrace });
  initDemoActivity({
    // After every rehearsal attempt, re-read the real traces everywhere
    // they are shown — nothing is injected client-side.
    onCompleted: () => {
      loadDashboard();
      loadExecutionTraces();
    },
    onOpenTrace: openTrace,
  });
  initSystemControls();
  initNamespacesControls();
  initProcessesControls();
  initDatabasesControls();
  initWebAppsControls();
  initTasksControls();
  initSecurityControls();
  initSecurityAccessControls();
  initSecurityAuthControls();
  initSecurityWalletControls();
  initSecurityX509Controls();
  initJournalControls();
  initOperationsControls();
  initAiAssistantControls();
  // These two cross-links are the only coupling between Observability and
  // Investigation: each just sets the OTHER view's own filter fields
  // (never re-implementing the other's rendering) and then navigates,
  // so the target view's normal view-opened load picks the filter up.
  initObservabilityControls({
    onInvestigateTimeWindow: ({ begin, end }) => {
      setInvestigationTimeWindow(begin, end);
      navigateTo("investigation");
    },
  });
  initExtensionsControls();
  initInvestigationControls({
    onInvestigateTraces: ({ begin, end }) => {
      setObservabilityTimeWindow(begin, end);
      navigateTo("observability");
    },
  });
  initCapabilitiesControls();

  // Fetch fresh data every time a detail view is opened, so it can never
  // show stale information from an earlier visit.
  initNavigation((view) => {
    if (view === "dashboard") {
      onDashboardShown();
    } else if (view === "system") {
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
      loadSecurityAccess();
      refreshSecurityAuthIfLoaded();
      refreshSecurityWalletIfLoaded();
      refreshSecurityX509IfLoaded();
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
