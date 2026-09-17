// Small colored status pill, used throughout tables and detail views.

/**
 * @param {string} label
 * @param {'success'|'warning'|'error'|'info'} [variant]
 */
export function createStatusBadge(label, variant = 'info') {
  const badge = document.createElement('span');
  badge.className = `status-badge status-badge--${variant}`;
  badge.textContent = label;
  return badge;
}
