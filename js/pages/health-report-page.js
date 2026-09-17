// Health Report — the visible face of the Embedded Python bonus feature.
// Gathers IRIS metrics from this app's own REST API (js/services/health-service.js),
// sends them to the HealthAnalyzer REST endpoint (backed by real psutil data
// and IRIS-side Python scoring — see docs/health-analyzer.md), and displays
// the full analysis: score, status, severity, warnings, recommendations,
// anomalies, and the real OS metrics Embedded Python uniquely provided.

import { createStatusBadge } from '../components/status-badge.js';
import { createJsonViewer } from '../components/json-viewer.js';
import { loadingRow, errorState, actionButton } from '../utils/dom-helpers.js';
import { runHealthAnalysis } from '../services/health-service.js';

let destroyed = false;

const STATUS_VARIANT = { healthy: 'success', warning: 'warning', critical: 'error' };

export function render(container) {
  destroyed = false;
  container.replaceChildren();

  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Health Report';

  const subtitle = document.createElement('p');
  subtitle.className = 'metric-card__subtitle';
  subtitle.textContent = 'Powered by Embedded Python: real CPU/memory metrics via psutil, scored server-side inside IRIS.';

  const controls = document.createElement('div');
  controls.className = 'dashboard-controls';
  const runButton = actionButton('Run analysis', 'button--primary', () => load());
  controls.appendChild(runButton);

  const resultArea = document.createElement('div');

  container.append(heading, subtitle, controls, resultArea);

  async function load() {
    runButton.disabled = true;
    resultArea.replaceChildren(loadingRow('Running Embedded Python analysis…'));
    try {
      const analysis = await runHealthAnalysis();
      if (destroyed) return;
      if (analysis === null) {
        resultArea.replaceChildren();
        const note = document.createElement('p');
        note.className = 'empty-state__body';
        note.textContent = 'Analysis cancelled — Basic authentication is required for this endpoint.';
        resultArea.appendChild(note);
        return;
      }
      resultArea.replaceChildren(buildReport(analysis));
    } catch (err) {
      if (destroyed) return;
      resultArea.replaceChildren(errorState(err, load));
    } finally {
      runButton.disabled = false;
    }
  }

  load();
}

export function destroy() {
  destroyed = true;
}

function buildReport(analysis) {
  const wrapper = document.createElement('div');
  wrapper.className = 'health-report';

  const scoreCard = document.createElement('section');
  scoreCard.className = 'card health-report__score-card';
  const scoreValue = document.createElement('div');
  scoreValue.className = `health-report__score health-report__score--${analysis.status}`;
  scoreValue.textContent = String(analysis.score);
  const scoreLabel = document.createElement('div');
  scoreLabel.className = 'health-report__score-label';
  scoreLabel.append(
    createStatusBadge(analysis.status.toUpperCase(), STATUS_VARIANT[analysis.status] || 'info'),
    document.createTextNode(` · severity: ${analysis.severity}`)
  );
  const checkedAt = document.createElement('p');
  checkedAt.className = 'metric-card__subtitle';
  checkedAt.textContent = `Checked at ${new Date(analysis.checkedAt).toLocaleString()}`;
  scoreCard.append(scoreValue, scoreLabel, checkedAt);
  wrapper.appendChild(scoreCard);

  if (analysis.pythonMetrics) {
    const pyCard = document.createElement('section');
    pyCard.className = 'card';
    const pyTitle = document.createElement('h3');
    pyTitle.className = 'metric-card__title';
    pyTitle.textContent = 'Live OS metrics (psutil, via Embedded Python)';
    const pyGrid = document.createElement('div');
    pyGrid.className = 'metrics-grid';
    pyGrid.appendChild(miniMetric('CPU usage', `${analysis.pythonMetrics.cpu_percent.toFixed(1)}%`));
    pyGrid.appendChild(miniMetric('Memory usage', `${analysis.pythonMetrics.memory_percent.toFixed(1)}%`));
    pyGrid.appendChild(miniMetric('Memory total', formatBytes(analysis.pythonMetrics.memory_total_bytes)));
    pyGrid.appendChild(miniMetric('Memory available', formatBytes(analysis.pythonMetrics.memory_available_bytes)));
    pyCard.append(pyTitle, pyGrid);
    wrapper.appendChild(pyCard);
  }

  wrapper.appendChild(buildListCard('Warnings', analysis.warnings, (w) => `${w.metric}: ${w.message}`, analysis.warnings.length === 0 ? 'No warnings.' : null));
  wrapper.appendChild(buildListCard('Recommendations', analysis.recommendations, (r) => r, analysis.recommendations.length === 0 ? 'Nothing to recommend right now.' : null));
  wrapper.appendChild(buildListCard('Anomalies', analysis.anomalies, (a) => a, analysis.anomalies.length === 0 ? 'No anomalies detected.' : null));

  const rawDetails = document.createElement('details');
  rawDetails.className = 'metric-card__raw';
  const summary = document.createElement('summary');
  summary.textContent = 'View raw analysis response';
  rawDetails.append(summary, createJsonViewer(analysis));
  wrapper.appendChild(rawDetails);

  return wrapper;
}

function miniMetric(label, value) {
  const card = document.createElement('div');
  card.className = 'metric-card';
  const title = document.createElement('div');
  title.className = 'metric-card__title';
  title.textContent = label;
  const val = document.createElement('div');
  val.className = 'metric-card__value';
  val.textContent = value;
  card.append(title, val);
  return card;
}

function buildListCard(title, items, render, emptyMessage) {
  const card = document.createElement('section');
  card.className = 'card';
  const titleEl = document.createElement('h3');
  titleEl.className = 'metric-card__title';
  titleEl.textContent = title;
  card.appendChild(titleEl);
  if (items.length === 0 && emptyMessage) {
    const empty = document.createElement('p');
    empty.className = 'metric-card__subtitle';
    empty.textContent = emptyMessage;
    card.appendChild(empty);
    return card;
  }
  const list = document.createElement('ul');
  list.className = 'health-report__list';
  for (const item of items) {
    const li = document.createElement('li');
    li.textContent = render(item);
    list.appendChild(li);
  }
  card.appendChild(list);
  return card;
}

function formatBytes(bytes) {
  if (!bytes) return '—';
  const gb = bytes / 1024 / 1024 / 1024;
  return `${gb.toFixed(2)} GB`;
}
