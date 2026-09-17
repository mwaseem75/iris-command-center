// Lightweight hash-based router. Routes are registered up front; each route
// module exports a `render(container)` function and an optional `destroy()`
// for cleanup. Unimplemented routes (most of the app, for now — see
// js/pages/*.js placeholders) simply aren't registered and fall back to
// the default redirect below rather than erroring.

import { isAuthenticated } from './state.js';
import * as loginPage from './pages/login-page.js';
import * as dashboardPage from './pages/dashboard-page.js';
import * as processesPage from './pages/processes-page.js';
import * as tasksPage from './pages/tasks-page.js';
import * as databasesPage from './pages/databases-page.js';
import * as namespacesPage from './pages/namespaces-page.js';
import * as devicesPage from './pages/devices-page.js';
import * as securityPage from './pages/security-page.js';
import * as walletsPage from './pages/wallets-page.js';
import * as webappsPage from './pages/webapps-page.js';
import * as restExplorerPage from './pages/rest-explorer-page.js';
import * as healthReportPage from './pages/health-report-page.js';
import * as askIrisPage from './pages/ask-iris-page.js';
import * as logsPage from './pages/logs-page.js';

const routes = {
  '/login': { page: loginPage, requiresAuth: false, shell: false },
  '/dashboard': { page: dashboardPage, requiresAuth: true, shell: true },
  '/processes': { page: processesPage, requiresAuth: true, shell: true },
  '/tasks': { page: tasksPage, requiresAuth: true, shell: true },
  '/databases': { page: databasesPage, requiresAuth: true, shell: true },
  '/namespaces': { page: namespacesPage, requiresAuth: true, shell: true },
  '/devices': { page: devicesPage, requiresAuth: true, shell: true },
  '/security': { page: securityPage, requiresAuth: true, shell: true },
  '/wallets': { page: walletsPage, requiresAuth: true, shell: true },
  '/web-applications': { page: webappsPage, requiresAuth: true, shell: true },
  '/rest-explorer': { page: restExplorerPage, requiresAuth: true, shell: true },
  '/logs': { page: logsPage, requiresAuth: true, shell: true },
  '/health-report': { page: healthReportPage, requiresAuth: true, shell: true },
  '/ai-assistant': { page: askIrisPage, requiresAuth: true, shell: true },
};

let currentPage = null;
let outletProvider = null; // () => { shellContainer, contentContainer } — set by app.js

export function setOutletProvider(fn) {
  outletProvider = fn;
}

function currentPath() {
  const hash = window.location.hash.replace(/^#/, '');
  return hash || '/dashboard';
}

function navigate(path, { replace = false } = {}) {
  if (replace) {
    const url = new URL(window.location.href);
    url.hash = `#${path}`;
    window.location.replace(url.toString());
  } else {
    window.location.hash = `#${path}`;
  }
}

async function resolve() {
  const path = currentPath();
  const route = routes[path];
  const authed = isAuthenticated();

  if (!route) {
    navigate(authed ? '/dashboard' : '/login', { replace: true });
    return;
  }
  if (route.requiresAuth && !authed) {
    navigate('/login', { replace: true });
    return;
  }
  if (path === '/login' && authed) {
    navigate('/dashboard', { replace: true });
    return;
  }

  if (currentPage?.destroy) {
    try {
      currentPage.destroy();
    } catch {
      // Non-fatal — proceed to mount the next page regardless.
    }
  }

  const { shellContainer, contentContainer, loginContainer } = outletProvider();
  if (route.shell) {
    shellContainer.hidden = false;
    loginContainer.hidden = true;
    await route.page.render(contentContainer);
  } else {
    shellContainer.hidden = true;
    loginContainer.hidden = false;
    await route.page.render(loginContainer);
  }
  currentPage = route.page;
}

export function startRouter() {
  window.addEventListener('hashchange', resolve);
  resolve();
}

export { navigate };
