// Dashboard — identity panel (Phase 1/2) plus live monitoring metrics (Phase 3).
//
// Important: the SysAdmin API has no literal OS-level "CPU %" or "memory %"
// endpoint. What's actually available is qualitative subsystem health, internal
// resource-contention counters, license consumption, and IRIS shared-memory
// segment allocation — see js/api/monitor-api.js. The cards below are built
// around what's real rather than a guessed gauge; a true health *score* that
// synthesizes CPU/memory/process signals via Embedded Python lands in Phase 8.

import { getState, subscribe, hasPrivilege } from '../state.js';
import { fetchServerInfo } from '../services/auth-service.js';
import { createMetricCard } from '../components/metric-card.js';
import { createStatusBadge } from '../components/status-badge.js';
import { navigate } from '../router.js';
import { runHealthAnalysis } from '../services/health-service.js';
import { loadingRow, errorState, actionButton } from '../utils/dom-helpers.js';
import * as monitorApi from '../api/monitor-api.js';
import { ApiError } from '../api/client.js';

let unsubscribeIdentity = null;
let autoRefreshTimer = null;
let destroyed = false;

const AUTO_REFRESH_INTERVAL_MS = 15000;
const OPERATE_PRIVILEGE = 'Operate';
const HEALTH_STATUS_VARIANT = { healthy: 'success', warning: 'warning', critical: 'error' };

export function render(container) {
  destroyed = false;
  container.replaceChildren();

  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Dashboard';

  const identityCard = document.createElement('section');
  identityCard.className = 'card identity-card';
  identityCard.setAttribute('aria-live', 'polite');

  const controls = buildControls(() => loadMetrics(true));
  const healthBanner = document.createElement('div');
  healthBanner.className = 'health-banner';
  healthBanner.hidden = true;

  const metricsGrid = document.createElement('div');
  metricsGrid.className = 'metrics-grid';

  const pythonHealthCard = buildPythonHealthCard();

  container.append(heading, identityCard, pythonHealthCard.element, controls.element, healthBanner, metricsGrid);

  function renderIdentity() {
    const { session } = getState();
    identityCard.replaceChildren();
    if (!session?.serverInfo) {
      const loading = document.createElement('p');
      loading.className = 'loading-text';
      loading.innerHTML = '<span class="spinner"></span> Loading server information…';
      identityCard.append(loading);
      return;
    }
    const info = session.serverInfo;
    identityCard.append(
      buildRow('Connected user', session.username),
      buildRow('Auth mode', session.mode === 'jwt' ? 'JWT (IRIS 2026.2+)' : 'HTTP Basic'),
      buildRow('IRIS server', info.serverVersion || '—'),
      buildRow('Product', info.product || '—'),
      buildRow('System mode', info.systemMode || '(default)'),
      buildRow('Namespaces', (info.namespaces || []).map((n) => n.name).join(', ') || '—')
    );
    const privTitle = document.createElement('h2');
    privTitle.className = 'identity-card__subtitle';
    privTitle.textContent = 'Available privileges';
    identityCard.append(privTitle);
    const privList = document.createElement('ul');
    privList.className = 'privilege-list';
    const names = Object.keys(info.privileges || {});
    if (names.length === 0) {
      const none = document.createElement('li');
      none.textContent = 'No %Admin privileges reported.';
      privList.append(none);
    } else {
      for (const name of names) {
        const li = document.createElement('li');
        const badge = document.createElement('span');
        badge.className = 'status-badge status-badge--success';
        badge.textContent = name;
        li.append(badge);
        privList.append(li);
      }
    }
    identityCard.append(privList);
  }

  async function loadMetrics(manual = false) {
    if (destroyed) return;
    controls.setLoading(true);

    if (!hasPrivilege(OPERATE_PRIVILEGE)) {
      healthBanner.hidden = true;
      metricsGrid.replaceChildren(
        createMetricCard({
          title: 'Monitoring metrics',
          state: 'error',
          privilegeMissing: true,
          requiredPrivilege: '%Admin_Operate',
        })
      );
      controls.setLoading(false);
      controls.setLastRefreshed(new Date());
      return;
    }

    const [mainResult, resourcesResult, licenseResult, usageResult, sharedMemResult] = await Promise.allSettled([
      monitorApi.getMainDashboard(),
      monitorApi.getSystemResources(),
      monitorApi.getLicenseUsage(),
      monitorApi.getSystemUsage(),
      monitorApi.getSharedMemoryUsage(),
    ]);

    if (destroyed) return;

    renderHealthBanner(healthBanner, mainResult);
    metricsGrid.replaceChildren(
      ...buildMainCards(mainResult, licenseResult),
      buildResourceContentionCard(resourcesResult),
      buildSystemUsageCard(usageResult),
      buildSharedMemoryCard(sharedMemResult)
    );

    controls.setLoading(false);
    controls.setLastRefreshed(new Date());
  }

  unsubscribeIdentity?.();
  unsubscribeIdentity = subscribe(renderIdentity);
  renderIdentity();

  if (!getState().session?.serverInfo) {
    fetchServerInfo()
      .catch(() => {})
      .finally(loadMetrics);
  } else {
    loadMetrics();
  }

  controls.onAutoRefreshChange((enabled) => {
    clearInterval(autoRefreshTimer);
    if (enabled) autoRefreshTimer = setInterval(loadMetrics, AUTO_REFRESH_INTERVAL_MS);
  });
}

export function destroy() {
  destroyed = true;
  unsubscribeIdentity?.();
  unsubscribeIdentity = null;
  clearInterval(autoRefreshTimer);
  autoRefreshTimer = null;
}

// ---------- controls (refresh / auto-refresh / last-updated) ----------

function buildControls(onRefresh) {
  const bar = document.createElement('div');
  bar.className = 'dashboard-controls';

  const refreshButton = document.createElement('button');
  refreshButton.type = 'button';
  refreshButton.className = 'button button--ghost';
  const refreshSpinner = document.createElement('span');
  refreshSpinner.className = 'spinner';
  refreshSpinner.hidden = true;
  const refreshLabel = document.createElement('span');
  refreshLabel.textContent = 'Refresh';
  refreshButton.append(refreshSpinner, refreshLabel);
  refreshButton.addEventListener('click', onRefresh);

  const autoLabel = document.createElement('label');
  autoLabel.className = 'switch';
  const autoInput = document.createElement('input');
  autoInput.type = 'checkbox';
  const autoSlider = document.createElement('span');
  autoSlider.className = 'switch__slider';
  autoLabel.append(autoInput, autoSlider, document.createTextNode(' Auto-refresh (15s)'));

  const lastRefreshed = document.createElement('span');
  lastRefreshed.className = 'dashboard-controls__timestamp';

  bar.append(refreshButton, autoLabel, lastRefreshed);

  let changeHandler = null;
  autoInput.addEventListener('change', () => changeHandler?.(autoInput.checked));

  return {
    element: bar,
    setLoading(isLoading) {
      refreshButton.disabled = isLoading;
      refreshSpinner.hidden = !isLoading;
      refreshLabel.textContent = isLoading ? 'Refreshing…' : 'Refresh';
    },
    setLastRefreshed(date) {
      lastRefreshed.textContent = `Last refreshed: ${date.toLocaleTimeString()}`;
    },
    onAutoRefreshChange(fn) {
      changeHandler = fn;
    },
  };
}

// ---------- Embedded Python health card (Phase 8) ----------
//
// Auto-runs on mount rather than waiting for a click: the credential prompt
// it may trigger reuses Phase 7's cached Basic-auth flow (js/services/mgmnt-auth.js),
// and the contest brief specifically calls out that the dashboard "must
// visibly use" the Embedded Python result, so this card should not require
// an extra step to demonstrate it.

function buildPythonHealthCard() {
  const card = document.createElement('section');
  card.className = 'card';

  const header = document.createElement('div');
  header.className = 'dashboard-controls';
  const title = document.createElement('h3');
  title.className = 'metric-card__title';
  title.textContent = 'Embedded Python health score';
  const rerunButton = actionButton('Re-run', 'button--ghost', () => load());
  header.append(title, rerunButton);

  const subtitle = document.createElement('p');
  subtitle.className = 'metric-card__subtitle';
  subtitle.textContent = 'Real CPU/memory metrics via psutil, scored server-side inside IRIS.';

  const body = document.createElement('div');

  card.append(header, subtitle, body);

  function buildSummary(analysis) {
    const wrap = document.createElement('div');

    const scoreRow = document.createElement('div');
    scoreRow.className = 'dashboard-controls';
    const score = document.createElement('span');
    score.className = `health-report__score health-report__score--${analysis.status}`;
    score.style.fontSize = '2.5rem';
    score.textContent = String(analysis.score);
    const badge = createStatusBadge(analysis.status.toUpperCase(), HEALTH_STATUS_VARIANT[analysis.status] || 'info');
    scoreRow.append(score, badge);
    wrap.appendChild(scoreRow);

    if (analysis.warnings?.length) {
      const topWarning = document.createElement('p');
      topWarning.className = 'metric-card__subtitle';
      topWarning.textContent = `${analysis.warnings[0].metric}: ${analysis.warnings[0].message}`;
      wrap.appendChild(topWarning);
    }

    wrap.appendChild(actionButton('View full report', 'button--ghost', () => navigate('/health-report')));
    return wrap;
  }

  async function load() {
    rerunButton.disabled = true;
    body.replaceChildren(loadingRow('Running Embedded Python analysis…'));
    try {
      const analysis = await runHealthAnalysis();
      if (destroyed) return;
      if (analysis === null) {
        const note = document.createElement('p');
        note.className = 'empty-state__body';
        note.textContent = 'Skipped — Basic authentication is required for this endpoint.';
        body.replaceChildren(note);
        return;
      }
      body.replaceChildren(buildSummary(analysis));
    } catch (err) {
      if (destroyed) return;
      body.replaceChildren(errorState(err, load));
    } finally {
      if (!destroyed) rerunButton.disabled = false;
    }
  }

  load();

  return { element: card };
}

// ---------- health banner ----------

function computeHealth(main) {
  const reasons = [];
  const subsystems = main.SystemUsage || {};
  for (const [key, val] of Object.entries(subsystems)) {
    if (typeof val === 'string' && val !== 'Normal') reasons.push(`${key}: ${val}`);
  }
  const seriousAlerts = main.Alerts?.SeriousAlerts || 0;
  const appErrors = main.Alerts?.ApplicationErrors || 0;
  if (seriousAlerts > 0) reasons.push(`${seriousAlerts} serious alert(s)`);
  if (appErrors > 0) reasons.push(`${appErrors} application error(s)`);

  const licenseUse = main.Licensing?.LicenseUse ?? 0;
  const licenseLimit = main.Licensing?.LicenseLimit ?? 0;
  const licenseRatio = licenseLimit > 0 ? licenseUse / licenseLimit : 0;
  if (licenseRatio > 0.9) reasons.push('License usage above 90%');

  let status = 'healthy';
  if (seriousAlerts > 0 || appErrors > 0) status = 'critical';
  else if (reasons.length > 0) status = 'warning';

  return { status, reasons };
}

function renderHealthBanner(banner, mainResult) {
  if (mainResult.status !== 'fulfilled') {
    banner.hidden = true;
    return;
  }
  const { status, reasons } = computeHealth(mainResult.value);
  banner.hidden = false;
  banner.className = `health-banner health-banner--${status}`;
  banner.textContent =
    status === 'healthy'
      ? 'System status: healthy — all monitored subsystems normal.'
      : `System status: ${status} — ${reasons.join('; ')}.`;
}

// ---------- cards derived from dashboard/main ----------

function apiErrorCard(title, result) {
  const err = result.reason;
  return createMetricCard({
    title,
    state: 'error',
    privilegeMissing: err instanceof ApiError && err.status === 403,
    requiredPrivilege: '%Admin_Operate',
    errorMessage: err instanceof ApiError ? err.message : 'This metric could not be loaded.',
  });
}

function buildMainCards(mainResult, licenseResult) {
  if (mainResult.status !== 'fulfilled') {
    return [apiErrorCard('Dashboard overview', mainResult)];
  }
  const main = mainResult.value;
  const cards = [];

  const statusBadges = Object.entries(main.SystemUsage || {})
    .filter(([, v]) => typeof v === 'string')
    .map(([k, v]) => ({ label: `${k}: ${v}`, variant: v === 'Normal' ? 'success' : 'warning' }));
  cards.push(
    createMetricCard({
      title: 'Subsystem status',
      state: 'ready',
      subtitle: `Uptime: ${main.Status?.UpTime || '—'} · Last backup: ${main.Status?.LastBackup || 'Never'}`,
      badges: statusBadges,
      raw: main.Status,
    })
  );

  cards.push(
    createMetricCard({
      title: 'Active processes',
      state: 'ready',
      value: String(main.SystemUsage?.Processes ?? '—'),
      subtitle: `CSP sessions: ${main.SystemUsage?.CSPSessions ?? '—'}`,
      raw: (main.SystemUsage?.BusyProcesses || []).filter((p) => p.Process !== ''),
    })
  );

  const seriousAlerts = main.Alerts?.SeriousAlerts || 0;
  const appErrors = main.Alerts?.ApplicationErrors || 0;
  cards.push(
    createMetricCard({
      title: 'Alerts',
      state: 'ready',
      value: String(seriousAlerts + appErrors),
      subtitle: 'Total serious alerts + application errors',
      badges: [
        { label: `Serious: ${seriousAlerts}`, variant: seriousAlerts > 0 ? 'error' : 'success' },
        { label: `App errors: ${appErrors}`, variant: appErrors > 0 ? 'error' : 'success' },
      ],
    })
  );

  const limit = main.Licensing?.LicenseLimit ?? 0;
  const use = main.Licensing?.LicenseUse ?? 0;
  const pct = limit > 0 ? Math.round((use / limit) * 100) : 0;
  cards.push(
    createMetricCard({
      title: 'License usage',
      state: 'ready',
      value: `${use} / ${limit}`,
      subtitle: `${pct}% of licensed units in use (peak: ${main.Licensing?.LicenseUseHigh ?? '—'})`,
      badges: [{ label: pct > 90 ? 'Near limit' : 'Within limit', variant: pct > 90 ? 'warning' : 'success' }],
      raw: licenseResult.status === 'fulfilled' ? licenseResult.value : undefined,
    })
  );

  const upcoming = main.UpcomingTasks || [];
  cards.push(
    createMetricCard({
      title: 'Upcoming tasks',
      state: 'ready',
      value: String(upcoming.length),
      subtitle: upcoming[0] ? `Next: ${upcoming[0].Task} at ${upcoming[0].Time}` : 'Nothing scheduled',
      raw: upcoming,
    })
  );

  return cards;
}

function buildResourceContentionCard(result) {
  if (result.status !== 'fulfilled') return apiErrorCard('System resource contention', result);
  const resources = result.value || [];
  const busy = resources.filter((r) => r.Bseize > 0 || r.BusySet > 0);
  return createMetricCard({
    title: 'System resource contention',
    state: 'ready',
    value: String(busy.length),
    subtitle: busy.length === 0 ? 'No internal resource contention detected' : 'Resources with contention — see raw data',
    raw: resources,
  });
}

function buildSystemUsageCard(result) {
  if (result.status !== 'fulfilled') return apiErrorCard('Journal & routine activity', result);
  const usage = result.value || {};
  return createMetricCard({
    title: 'Journal & routine activity',
    state: 'ready',
    value: `${(usage.JournalEntries ?? 0).toLocaleString()} entries`,
    subtitle: `Since last update: ${usage.LastUpdate || '—'}`,
    raw: usage,
  });
}

function buildSharedMemoryCard(result) {
  if (result.status !== 'fulfilled') return apiErrorCard('Shared memory', result);
  const rows = result.value || [];
  // "Total" combines three separate pools (SMH/SMT/GST) whose individual allocation
  // ceilings live in different summary rows below it — there's no single field here
  // that represents "capacity", so we show the raw used-pages count rather than a
  // computed percentage (AllUsed can legitimately exceed any one pool's allocation).
  const total = rows.find((r) => r.Description === 'Total');
  return createMetricCard({
    title: 'Shared memory',
    state: 'ready',
    value: total ? `${total.AllUsed.toLocaleString()} pages` : '—',
    subtitle: total ? 'Total used across all shared-memory pools (SMH + SMT + GST)' : 'No summary row returned',
    raw: rows,
  });
}

function buildRow(label, value) {
  const row = document.createElement('div');
  row.className = 'identity-row';
  const labelEl = document.createElement('span');
  labelEl.className = 'identity-row__label';
  labelEl.textContent = label;
  const valueEl = document.createElement('span');
  valueEl.className = 'identity-row__value';
  valueEl.textContent = value;
  row.append(labelEl, valueEl);
  return row;
}
