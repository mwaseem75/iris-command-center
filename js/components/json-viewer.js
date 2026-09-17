// Collapsible JSON tree viewer, built on native <details>/<summary> so
// expand/collapse needs no custom JS state and is keyboard-accessible for free.

export function createJsonViewer(value) {
  const container = document.createElement('div');
  container.className = 'json-viewer';
  container.appendChild(renderValue(value));
  return container;
}

function renderValue(value) {
  if (Array.isArray(value)) return renderContainer(value.map((v, i) => [i, v]), '[', ']');
  if (value !== null && typeof value === 'object') return renderContainer(Object.entries(value), '{', '}');

  const span = document.createElement('span');
  span.className = `json-viewer__value json-viewer__value--${typeof value}`;
  span.textContent = typeof value === 'string' ? `"${value}"` : String(value);
  return span;
}

function renderContainer(entries, open, close) {
  if (entries.length === 0) {
    const span = document.createElement('span');
    span.className = 'json-viewer__value';
    span.textContent = `${open}${close}`;
    return span;
  }

  const details = document.createElement('details');
  details.className = 'json-viewer__node';
  details.open = false;

  const summary = document.createElement('summary');
  summary.textContent = `${open} ${entries.length} ${entries.length === 1 ? 'item' : 'items'} ${close}`;
  details.appendChild(summary);

  const list = document.createElement('div');
  list.className = 'json-viewer__children';
  for (const [key, val] of entries) {
    const row = document.createElement('div');
    row.className = 'json-viewer__row';
    const keyEl = document.createElement('span');
    keyEl.className = 'json-viewer__key';
    keyEl.textContent = `${key}: `;
    row.append(keyEl, renderValue(val));
    list.appendChild(row);
  }
  details.appendChild(list);
  return details;
}
