// Shows the exact API request about to be executed, inside a confirm dialog.
// Security principle: every mutating operation must show its real request
// before the user commits to it — this is not a summary, it's the literal call.

/**
 * @param {object} config
 * @param {string} config.method
 * @param {string} config.path - e.g. "v2/process/terminate?id=1234"
 * @param {object} [config.body]
 * @param {string} [config.basePath] - defaults to /api/admin/; the REST Explorer
 *   overrides this since it previews requests against arbitrary discovered apps.
 */
export function createApiPreview({ method, path, body, basePath = '/api/admin/' }) {
  const container = document.createElement('div');
  container.className = 'api-preview';

  const requestLine = document.createElement('div');
  requestLine.className = 'api-preview__line';
  const methodSpan = document.createElement('span');
  methodSpan.className = `api-preview__method api-preview__method--${method.toLowerCase()}`;
  methodSpan.textContent = method;
  const pathSpan = document.createElement('span');
  pathSpan.className = 'api-preview__path';
  pathSpan.textContent = ` ${basePath.replace(/\/?$/, '/')}${path.replace(/^\//, '')}`;
  requestLine.append(methodSpan, pathSpan);
  container.appendChild(requestLine);

  if (body !== undefined && Object.keys(body).length > 0) {
    const pre = document.createElement('pre');
    pre.className = 'api-preview__body';
    pre.textContent = JSON.stringify(body, null, 2);
    container.appendChild(pre);
  }

  return container;
}
