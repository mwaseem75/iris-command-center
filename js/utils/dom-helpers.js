// Small DOM-building helpers shared across list/detail pages (processes, tasks, ...).

export function detailRow(label, value) {
  const row = document.createElement('div');
  row.className = 'identity-row';
  const l = document.createElement('span');
  l.className = 'identity-row__label';
  l.textContent = label;
  const v = document.createElement('span');
  v.className = 'identity-row__value';
  v.textContent = value;
  row.append(l, v);
  return row;
}

export function actionButton(label, className, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = `button ${className}`;
  button.textContent = label;
  button.addEventListener('click', onClick);
  return button;
}

export function loadingRow(message = 'Loading…') {
  const el = document.createElement('p');
  el.className = 'loading-text';
  el.innerHTML = `<span class="spinner"></span> ${message}`;
  return el;
}

export function errorState(err, retry) {
  const wrapper = document.createElement('div');
  wrapper.className = 'card empty-state';
  const title = document.createElement('p');
  title.className = 'empty-state__title';
  title.textContent = err?.status === 403 ? 'Insufficient privilege' : 'Something went wrong';
  const body = document.createElement('p');
  body.className = 'empty-state__body';
  body.textContent = err?.message || 'An unexpected error occurred.';
  wrapper.append(title, body);
  if (retry) {
    const retryButton = document.createElement('button');
    retryButton.type = 'button';
    retryButton.className = 'button button--ghost';
    retryButton.style.marginTop = 'var(--space-3)';
    retryButton.textContent = 'Retry';
    retryButton.addEventListener('click', retry);
    wrapper.appendChild(retryButton);
  }
  return wrapper;
}

export function emptyCard(title, body) {
  const wrapper = document.createElement('div');
  wrapper.className = 'card empty-state';
  const titleEl = document.createElement('p');
  titleEl.className = 'empty-state__title';
  titleEl.textContent = title;
  const bodyEl = document.createElement('p');
  bodyEl.className = 'empty-state__body';
  bodyEl.textContent = body;
  wrapper.append(titleEl, bodyEl);
  return wrapper;
}
