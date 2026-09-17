// Dashboard metric card. Each card is independently loading/error/ready so one
// failed or unauthorized endpoint doesn't take down the rest of the dashboard.

import { createJsonViewer } from './json-viewer.js';

/**
 * @param {object} config
 * @param {string} config.title
 * @param {'loading'|'error'|'ready'} config.state
 * @param {string} [config.value] - headline value (ready state)
 * @param {string} [config.subtitle]
 * @param {{label: string, variant?: string}[]} [config.badges]
 * @param {string} [config.errorMessage]
 * @param {boolean} [config.privilegeMissing]
 * @param {string} [config.requiredPrivilege]
 * @param {*} [config.raw] - if provided, adds a "View raw data" expandable section
 */
export function createMetricCard(config) {
  const card = document.createElement('section');
  card.className = 'card metric-card';

  const title = document.createElement('h3');
  title.className = 'metric-card__title';
  title.textContent = config.title;
  card.appendChild(title);

  if (config.state === 'loading') {
    const loading = document.createElement('p');
    loading.className = 'loading-text';
    loading.innerHTML = '<span class="spinner"></span> Loading…';
    card.appendChild(loading);
    return card;
  }

  if (config.state === 'error') {
    const badge = document.createElement('span');
    badge.className = `status-badge status-badge--${config.privilegeMissing ? 'warning' : 'error'}`;
    badge.textContent = config.privilegeMissing ? 'Insufficient privilege' : 'Error';
    card.appendChild(badge);

    const message = document.createElement('p');
    message.className = 'metric-card__error';
    message.textContent = config.privilegeMissing
      ? `Requires the ${config.requiredPrivilege} privilege, which your account does not currently hold.`
      : config.errorMessage || 'This metric could not be loaded.';
    card.appendChild(message);
    return card;
  }

  if (config.value !== undefined) {
    const value = document.createElement('p');
    value.className = 'metric-card__value';
    value.textContent = config.value;
    card.appendChild(value);
  }

  if (config.subtitle) {
    const subtitle = document.createElement('p');
    subtitle.className = 'metric-card__subtitle';
    subtitle.textContent = config.subtitle;
    card.appendChild(subtitle);
  }

  if (config.badges?.length) {
    const badgeRow = document.createElement('div');
    badgeRow.className = 'metric-card__badges';
    for (const b of config.badges) {
      const badge = document.createElement('span');
      badge.className = `status-badge status-badge--${b.variant || 'info'}`;
      badge.textContent = b.label;
      badgeRow.appendChild(badge);
    }
    card.appendChild(badgeRow);
  }

  if (config.raw !== undefined) {
    const details = document.createElement('details');
    details.className = 'metric-card__raw';
    const summary = document.createElement('summary');
    summary.textContent = 'View raw data';
    details.appendChild(summary);
    details.appendChild(createJsonViewer(config.raw));
    card.appendChild(details);
  }

  return card;
}
