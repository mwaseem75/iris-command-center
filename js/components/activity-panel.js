// Global activity panel — the "...Record" step of the project's core pattern.
// A topbar button (with a live count) opens a modal listing every mutating
// action performed this session, most recent first, with its outcome and the
// exact request that was sent.

import { getActivities, subscribeActivities } from '../services/activity-service.js';
import { openModal } from './modal.js';
import { createStatusBadge } from './status-badge.js';
import { createApiPreview } from './api-preview.js';
import { createJsonViewer } from './json-viewer.js';

export function createActivityTrigger() {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'button button--ghost activity-trigger';
  button.setAttribute('aria-label', 'View activity log');

  const label = document.createElement('span');
  label.textContent = 'Activity';
  const count = document.createElement('span');
  count.className = 'activity-trigger__count';
  count.hidden = true;
  button.append(label, count);

  function update(entries) {
    if (entries.length === 0) {
      count.hidden = true;
      return;
    }
    count.hidden = false;
    count.textContent = String(entries.length);
  }

  subscribeActivities(update);
  update(getActivities());

  button.addEventListener('click', () => openActivityPanel());

  return button;
}

function openActivityPanel() {
  const content = document.createElement('div');
  content.className = 'activity-panel';
  render(content);

  const unsubscribe = subscribeActivities(() => render(content));
  openModal({ title: 'Activity', content, size: 'lg', onClose: unsubscribe });
}

function render(container) {
  const entries = getActivities();
  container.replaceChildren();

  if (entries.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'empty-state__body';
    empty.textContent = 'No actions recorded yet this session. Mutating operations you confirm will appear here.';
    container.appendChild(empty);
    return;
  }

  for (const entry of entries) {
    const item = document.createElement('div');
    item.className = 'activity-item';

    const header = document.createElement('div');
    header.className = 'activity-item__header';
    header.append(
      createStatusBadge(entry.status === 'success' ? 'Success' : 'Error', entry.status === 'success' ? 'success' : 'error'),
      textSpan('activity-item__action', entry.action),
      textSpan('activity-item__time', entry.timestamp.toLocaleTimeString())
    );
    item.appendChild(header);

    if (entry.errorMessage) {
      const err = document.createElement('p');
      err.className = 'activity-item__error';
      err.textContent = entry.errorMessage;
      item.appendChild(err);
    }

    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = 'View request/response';
    details.append(summary, createApiPreview(entry.request));
    if (entry.response !== undefined) {
      const responseLabel = document.createElement('p');
      responseLabel.className = 'confirm-dialog__preview-label';
      responseLabel.textContent = 'Response:';
      details.append(responseLabel, createJsonViewer(entry.response));
    }
    item.appendChild(details);

    container.appendChild(item);
  }
}

function textSpan(className, text) {
  const span = document.createElement('span');
  span.className = className;
  span.textContent = text;
  return span;
}
