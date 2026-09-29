// App startup: sets up sidebar navigation and loads the first page.
//
// Also connects Observability and Investigation (each can open the other
// for the same time window). This is the only place that knows about both.

import { initNavigation, navigateTo } from "./nav.js";
import { initThemeSelector } from "./theme.js";
import { loadDashboard, initDashboardControls, onDashboardShown } from "./dashboard.js";
import { loadSystemInfo, initSystemControls } from "./system.js";
import { loadNamespaces, initNamespacesControls } from "./namespaces.js";
import { loadProcesses, initProcessesControls } from "./processes.js";
import { loadDatabases, initDatabasesControls } from "./databases.js";
import { loadWebApps, initWebAppsControls, resolveWebAppIssue } from "./web-apps.js";
import { loadTasks, initTasksControls } from "./tasks.js";
import { loadSecurity, initSecurityControls } from "./security.js";
import { loadSecurityAccess, initSecurityAccessControls } from "./security-access.js";
import { initSecurityAuthControls, refreshSecurityAuthIfLoaded } from "./security-auth.js";
import { initSecurityWalletControls, refreshSecurityWalletIfLoaded } from "./security-wallet.js";
import { initSecurityX509Controls, refreshSecurityX509IfLoaded } from "./security-x509.js";
import { loadJournal, initJournalControls } from "./journal.js";
import { loadOperations, initOperationsControls, resolveJournalIssue } from "./operations.js";
import { askAssistant, initAiAssistantControls, loadAssistantContext } from "./ai-assistant.js";
import {
  loadExecutionTraces,
  initObservabilityControls,
  setTimeWindow as setObservabilityTimeWindow,
  focusTrace as focusObservabilityTrace,
} from "./observability.js";
import { initDemoActivity } from "./demo-activity.js";
import { initDetailWorkspaces } from "./detail-workspace.js";
import { loadExtensions, initExtensionsControls } from "./extensions.js";
import { loadIssueResolver, initIssueResolverControls } from "./issue-resolver.js";
import { loadHealthCenter, initHealthCenterControls } from "./health-center.js";
import {
  loadInvestigation,
  initInvestigationControls,
  setTimeWindow as setInvestigationTimeWindow,
} from "./investigation.js";
import { loadCapabilities, initCapabilitiesControls } from "./capabilities.js";
import { loadMessageLog, initMessageLogControls } from "./message-log.js";

function init() {
  initThemeSelector();
  // Modal behaviour for all detail panels (see detail-workspace.js).
  initDetailWorkspaces();
  // Opening a trace from the Dashboard or Demo Activity: focus it, then go to
  // Observability, which loads the trace list as usual.
  const openTrace = (traceId) => {
    focusObservabilityTrace(traceId);
    navigateTo("observability");
  };
  initDashboardControls({ onOpenTrace: openTrace });
  initDemoActivity({
    // After a rehearsal, reload the traces wherever they're shown.
    onCompleted: () => {
      loadDashboard();
      loadExecutionTraces();
    },
    onOpenTrace: openTrace,
  });
  initSystemControls();
  initNamespacesControls();
  initProcessesControls();
  initDatabasesControls({ onOpenTrace: openTrace });
  initWebAppsControls();
  initTasksControls();
  initSecurityControls();
  initSecurityAccessControls();
  initSecurityAuthControls();
  initSecurityWalletControls();
  initSecurityX509Controls();
  initJournalControls();
  initOperationsControls();
  initAiAssistantControls({ onOpenTrace: openTrace });
  // Each link sets the other page's time filter and switches to it; the page
  // picks the filter up when it loads.
  initObservabilityControls({
    onInvestigateTimeWindow: ({ begin, end }) => {
      setInvestigationTimeWindow(begin, end);
      navigateTo("investigation");
    },
  });
  // Extensions links to the Security Wallet tab and to Embedded Python in
  // the AI Assistant instead of duplicating either.
  initExtensionsControls({
    onOpenWallet: () => {
      navigateTo("security");
      document.getElementById("security-tab-wallet").click();
    },
    onOpenEmbeddedPython: () => {
      navigateTo("ai-assistant");
      askAssistant("Show Embedded Python host diagnostics");
    },
  });
  initInvestigationControls({
    onInvestigateTraces: ({ begin, end }) => {
      setObservabilityTimeWindow(begin, end);
      navigateTo("observability");
    },
    onOpenTrace: openTrace,
  });
  initCapabilitiesControls();
  initMessageLogControls();
  initHealthCenterControls();
  initIssueResolverControls({
    onOpenDatabases: () => navigateTo("databases"),
    // Resource-aware: a web-app issue resolves on the Web Apps page.
    onOpenWebApps: (issue) => {
      resolveWebAppIssue(issue);
      navigateTo("web-apps");
    },
    onOpenOperations: (issue) => {
      resolveJournalIssue(issue);
      navigateTo("operations");
    },
    // Detection-only issues: just open the page named by their catalog entry.
    onInvestigate: (page) => navigateTo(page),
    onOpenTrace: openTrace,
    // After the rehearsal, reload the traces wherever they're shown.
    onRehearsalFinished: () => {
      loadDashboard();
      loadExecutionTraces();
    },
  });

  // Reload data each time a page is opened so it's never stale.
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
    } else if (view === "ai-assistant") {
      loadAssistantContext();
    } else if (view === "observability") {
      loadExecutionTraces();
    } else if (view === "extensions") {
      loadExtensions();
    } else if (view === "issue-resolver") {
      loadIssueResolver();
    } else if (view === "health-center") {
      loadHealthCenter();
    } else if (view === "investigation") {
      loadInvestigation();
      loadMessageLog();
    } else if (view === "capabilities") {
      loadCapabilities();
    }
  });

  loadDashboard();
}

document.addEventListener("DOMContentLoaded", init);
