// App startup: sets up sidebar navigation and loads the first page.
//
// Also connects Observability and Investigation (each can open the other
// for the same time window). This is the only place that knows about both.

import { initNavigation, navigateTo } from "./nav.js";
import { initThemeSelector } from "./theme.js";
import {
  PRIMARY_ID,
  getInstanceContext,
  initInstanceSelector,
  onInstanceContextChange,
  placeInstanceSelector,
  refreshInstanceContext,
  selectInstanceContext,
} from "./instance-context.js";
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
import { loadInstances, initInstancesControls } from "./instances.js";
import { loadFleet, initFleetControls } from "./fleet.js";

// Pages that show the selected instance's IRIS data.
const INSTANCE_VIEWS = new Set([
  "system", "namespaces", "processes", "databases", "web-apps", "tasks", "security",
  "journal", "investigation", "extensions", "ai-assistant",
]);
// Of those, the pages that also offer changes (which run on the Primary only).
const VIEWS_WITH_CHANGES = new Set(["namespaces", "databases", "web-apps", "tasks", "security", "ai-assistant"]);
// Pages that exist to make changes, so they work on the Primary only.
const PRIMARY_ONLY_VIEWS = { "issue-resolver": "Issue Resolver", operations: "Operations" };
// Pages with the instance selector in their header: the instance pages plus
// the Dashboard and Health Center (which follow the selection themselves).
// Not the Fleet Overview (every active instance), the Primary-only pages or
// Command Center's own pages.
const SELECTOR_VIEWS = new Set([...INSTANCE_VIEWS, "dashboard", "health-center"]);

// What each page loads when it's opened (and again when the instance changes).
const LOADERS = {
  fleet: () => loadFleet(),
  dashboard: () => onDashboardShown(),
  system: () => loadSystemInfo(),
  namespaces: () => loadNamespaces(),
  processes: () => loadProcesses(),
  databases: () => loadDatabases(),
  "web-apps": () => loadWebApps(),
  tasks: () => loadTasks(),
  security: () => Promise.all([
    loadSecurity(),
    loadSecurityAccess(),
    refreshSecurityAuthIfLoaded(),
    refreshSecurityWalletIfLoaded(),
    refreshSecurityX509IfLoaded(),
  ]),
  journal: () => loadJournal(),
  operations: () => loadOperations(),
  "ai-assistant": () => loadAssistantContext(),
  observability: () => loadExecutionTraces(),
  extensions: () => loadExtensions(),
  "issue-resolver": () => loadIssueResolver(),
  "health-center": () => loadHealthCenter(),
  // The message log comes through the Primary's own connection.
  investigation: () => Promise.all([loadInvestigation(), isPrimarySelected() ? loadMessageLog() : null]),
  capabilities: () => loadCapabilities(),
  instances: () => loadInstances(),
};

let currentView = "dashboard";
let currentLoad = Promise.resolve();

function isPrimarySelected(ctx = getInstanceContext()) {
  return Boolean(ctx.instance && ctx.instance.primary);
}

function contextKey(ctx) {
  return ctx.instanceId;
}

// Says which instance the page shows, or why it can't show the selection;
// returns true in that case (the page then loads nothing).
function applyInstanceScope(view) {
  const ctx = getInstanceContext();
  const primary = isPrimarySelected(ctx);
  document.body.dataset.instanceScope = primary ? "primary" : "other";

  let message = "";
  let blocked = false;
  if (PRIMARY_ONLY_VIEWS[view] && !primary) {
    message = `${PRIMARY_ONLY_VIEWS[view]} makes changes, which run on the Primary instance only. Switch to Primary to use it.`;
    blocked = true;
  } else if (SELECTOR_VIEWS.has(view) && primary && ctx.fallbackFrom) {
    message = `${ctx.fallbackFrom} isn't reachable right now, so the Primary instance is selected.`;
  } else if (INSTANCE_VIEWS.has(view) && !primary && ctx.instance) {
    const where = ctx.instance.connection ? `${ctx.instance.name} (${ctx.instance.connection})` : ctx.instance.name;
    message = `Showing ${where}.`;
    if (VIEWS_WITH_CHANGES.has(view)) message += " Changes run on the Primary instance only, so they aren't offered here.";
  }
  document.getElementById("context-notice-text").textContent = message;
  document.getElementById("context-notice").hidden = !message;
  // These pages have no instance selector, so the notice offers the switch.
  document.getElementById("context-notice-primary").hidden = !(PRIMARY_ONLY_VIEWS[view] && !primary);
  document.querySelectorAll(".view[data-view]").forEach((section) => {
    section.toggleAttribute("data-context-blocked", blocked && section.dataset.view === view);
  });
  return blocked;
}

// The instance selector goes in the open page's header, where it applies,
// and the instances are checked again so it only offers reachable ones (a
// selected instance that stopped answering falls back to the Primary).
function placeSelectorFor(view) {
  const shown = SELECTOR_VIEWS.has(view);
  placeInstanceSelector(shown ? document.querySelector(`#view-${view} > .view__header`) : null);
  if (shown) refreshInstanceContext();
}

function openView(view) {
  currentView = view;
  placeSelectorFor(view);
  if (applyInstanceScope(view) || !LOADERS[view]) return;
  currentLoad = Promise.resolve(LOADERS[view]()).catch(() => {});
}

function init() {
  initThemeSelector();
  initInstanceSelector();
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
  initInstancesControls();
  initFleetControls();
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
  initNavigation(openView);

  document.getElementById("context-notice-primary").addEventListener("click", () => {
    selectInstanceContext(PRIMARY_ID);
  });

  // A different instance in the instance selector: close any open detail
  // panel and reload the open page once its current load (for the old
  // instance) has finished, so the last data shown is the new instance's.
  // The Dashboard and Health Center follow the selector themselves, and the
  // Fleet Overview always shows every active instance.
  let lastKey = contextKey(getInstanceContext());
  placeSelectorFor(currentView);
  applyInstanceScope(currentView);
  onInstanceContextChange((ctx) => {
    const key = contextKey(ctx);
    if (key === lastKey) {
      applyInstanceScope(currentView);  // e.g. a renamed instance
      return;
    }
    lastKey = key;
    document.querySelectorAll(".ns-drawer, .ns-drawer-backdrop").forEach((el) => {
      el.hidden = true;
    });
    const view = currentView;
    if (applyInstanceScope(view) || ["dashboard", "health-center", "fleet"].includes(view) || !LOADERS[view]) return;
    currentLoad = currentLoad.then(() => (currentView === view ? LOADERS[view]() : null)).catch(() => {});
  });

  loadDashboard();
}

document.addEventListener("DOMContentLoaded", init);
