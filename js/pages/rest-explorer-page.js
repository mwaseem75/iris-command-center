// REST API Explorer — discovers REST-enabled applications via /api/mgmnt,
// shows their real OpenAPI (Swagger 2.0) definitions, and lets you execute
// requests against them with the same preview/confirm/record discipline as
// everywhere else in this app. Integrated with Web Applications (its detail
// view can hand off a specific app here) rather than a standalone Swagger
// clone — see js/pages/webapps-page.js.
//
// The definitions returned here are genuinely Swagger 2.0: body parameters
// are declared as a `parameters` entry with `in: "body"` + a `schema`, not an
// OpenAPI 3 `requestBody`. Legacy (%CSP.REST) apps' definitions carry no
// parameter schemas at all beyond the path template itself — see
// docs/api-matrix.md section 11/12 for how this was discovered.

import { createDataTable } from '../components/data-table.js';
import { createStatusBadge } from '../components/status-badge.js';
import { createJsonViewer } from '../components/json-viewer.js';
import { openModal } from '../components/modal.js';
import { createApiPreview } from '../components/api-preview.js';
import { confirmAction } from '../components/confirm-dialog.js';
import { recordActivity } from '../services/activity-service.js';
import { showToast } from '../components/toast.js';
import { loadingRow, errorState, actionButton, emptyCard } from '../utils/dom-helpers.js';
import * as restApi from '../api/rest-api.js';

let destroyed = false;
let pendingApp = null;

/** Called from webapps-page.js to jump straight into exploring a specific app. */
export function openInExplorer(app) {
  pendingApp = app;
  window.location.hash = '#/rest-explorer';
}

const SAFE_METHODS = new Set(['get']);

export function render(container) {
  destroyed = false;
  container.replaceChildren();
  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'REST API Explorer';
  container.appendChild(heading);

  const body = document.createElement('div');
  container.appendChild(body);

  if (pendingApp) {
    const app = pendingApp;
    pendingApp = null;
    renderAppDetail(body, app);
  } else {
    renderAppList(body);
  }
}

export function destroy() {
  destroyed = true;
}

// ---------- App discovery ----------

async function renderAppList(container) {
  container.replaceChildren(loadingRow('Discovering REST applications via /api/mgmnt…'));
  try {
    const [restSpecApps, legacyApps] = await Promise.all([
      restApi.listRestSpecApps(),
      restApi.listLegacyApps(),
    ]);
    if (destroyed) return;

    // Both lists describe the same kind of thing (a REST application) in
    // slightly different shapes — normalize before merging. RESTSpec (v2)
    // entries have `webApplications`; legacy entries have `name` as the
    // actual web-app path already.
    const merged = [
      ...(legacyApps || []).map((a) => ({ name: a.name, dispatchClass: a.dispatchClass, namespace: a.namespace, swaggerSpec: a.swaggerSpec, enabled: a.enabled, kind: 'Legacy (%CSP.REST)' })),
      ...(restSpecApps || []).map((a) => ({ name: a.webApplications || a.name, dispatchClass: a.dispatchClass, namespace: a.namespace, swaggerSpec: a.swaggerSpec, enabled: undefined, kind: 'RESTSpec (v2)' })),
    ];

    if (merged.length === 0) {
      container.replaceChildren(emptyCard('No REST applications found', 'The connected instance reported no discoverable REST applications.'));
      return;
    }

    const table = createDataTable({
      columns: [
        { key: 'name', label: 'Application' },
        { key: 'kind', label: 'Spec style' },
        { key: 'namespace', label: 'Namespace' },
        { key: 'dispatchClass', label: 'Dispatch class' },
        {
          key: 'enabled',
          label: 'Status',
          render: (a) => (a.enabled === undefined ? '—' : createStatusBadge(a.enabled ? 'Enabled' : 'Disabled', a.enabled ? 'success' : 'warning')),
        },
      ],
      rows: merged,
      searchFields: ['name', 'dispatchClass', 'namespace'],
      pageSize: 15,
      emptyMessage: 'No REST applications found.',
      onRowClick: (app) => renderAppDetail(container, app),
    });
    container.replaceChildren(table.element);
  } catch (err) {
    if (destroyed) return;
    container.replaceChildren(errorState(err, () => renderAppList(container)));
  }
}

// ---------- App detail: path/method browser ----------

async function renderAppDetail(container, app) {
  container.replaceChildren(loadingRow(`Loading definition for ${app.name}…`));
  try {
    // A hand-off from webapps-page.js only knows the app's path, not its
    // swaggerSpec URL (that's an /api/mgmnt-specific detail webapps-page.js
    // has no reason to know) — resolve the full discovery entry by name first.
    let resolvedApp = app;
    if (!resolvedApp.swaggerSpec) {
      const [restSpecApps, legacyApps] = await Promise.all([restApi.listRestSpecApps(), restApi.listLegacyApps()]);
      if (destroyed) return;
      const found = [...(legacyApps || []), ...(restSpecApps || [])].find((a) => (a.webApplications || a.name) === app.name);
      if (!found) throw new Error(`"${app.name}" was not found among discoverable REST applications.`);
      resolvedApp = { ...found, name: found.webApplications || found.name };
    }

    // swaggerSpec is a full path like "/api/mgmnt/v1/%25SYS/spec/api/admin" or
    // "/api/mgmnt/v2/%25SYS/%25Api.Mgmnt.v2" — strip the known /api/mgmnt/
    // prefix and fetch it directly, rather than re-deriving namespace/app-name
    // ourselves from two differently-shaped listing entries.
    const relative = resolvedApp.swaggerSpec.replace(/^\/api\/mgmnt\//, '');
    const spec = await restApi.getSpecByRelativePath(relative);
    if (destroyed) return;
    renderSpecBrowser(container, resolvedApp, spec);
  } catch (err) {
    if (destroyed) return;
    container.replaceChildren(errorState(err, () => renderAppDetail(container, app)));
  }
}

function renderSpecBrowser(container, app, spec) {
  const wrapper = document.createElement('div');

  const backButton = actionButton('← All applications', 'button--ghost', () => renderAppList(container));
  wrapper.appendChild(backButton);

  const info = document.createElement('div');
  info.className = 'card';
  const title = document.createElement('h3');
  title.className = 'metric-card__title';
  title.textContent = `${app.name} — base path: ${spec.basePath || '(unknown)'}`;
  info.appendChild(title);
  if (spec.info?.description) {
    const desc = document.createElement('p');
    desc.className = 'metric-card__subtitle';
    desc.textContent = spec.info.description;
    info.appendChild(desc);
  }
  wrapper.appendChild(info);

  const rows = [];
  for (const [path, methods] of Object.entries(spec.paths || {})) {
    for (const [method, operation] of Object.entries(methods)) {
      if (!['get', 'post', 'put', 'delete', 'patch'].includes(method)) continue;
      rows.push({ path, method: method.toUpperCase(), description: operation.summary || operation.description || '—', operation });
    }
  }

  const tableCard = document.createElement('div');
  tableCard.className = 'card';
  const table = createDataTable({
    columns: [
      { key: 'method', label: 'Method', render: (r) => createStatusBadge(r.method, SAFE_METHODS.has(r.method.toLowerCase()) ? 'success' : 'warning') },
      { key: 'path', label: 'Path' },
      { key: 'description', label: 'Description' },
    ],
    rows,
    searchFields: ['path', 'description'],
    pageSize: 15,
    emptyMessage: 'This application has no documented operations.',
    onRowClick: (row) => openRequestBuilder(app, spec, row),
  });
  tableCard.appendChild(table.element);
  wrapper.appendChild(tableCard);

  container.replaceChildren(wrapper);
}

// ---------- Request builder ----------

function openRequestBuilder(app, spec, row) {
  const content = document.createElement('div');

  // Path template placeholders (Swagger 2.0 uses {name}) always need a value,
  // regardless of whether a formal parameter schema documents them.
  const pathParamNames = [...row.path.matchAll(/\{([^}]+)\}/g)].map((m) => m[1]);
  const declaredParams = row.operation.parameters || [];
  const pathParams = pathParamNames.map((name) => ({
    name,
    in: 'path',
    required: true,
    declared: declaredParams.find((p) => p.name === name && p.in === 'path'),
  }));
  const queryParams = declaredParams.filter((p) => p.in === 'query');
  const bodyParam = declaredParams.find((p) => p.in === 'body');

  const inputs = { path: {}, query: {}, body: null };

  if (pathParams.length > 0) {
    const section = document.createElement('div');
    const title = document.createElement('p');
    title.className = 'confirm-dialog__preview-label';
    title.textContent = 'Path parameters';
    section.appendChild(title);
    for (const p of pathParams) {
      const field = buildField(p.name, p.declared?.description);
      inputs.path[p.name] = field.input;
      section.appendChild(field.element);
    }
    content.appendChild(section);
  }

  if (queryParams.length > 0) {
    const section = document.createElement('div');
    const title = document.createElement('p');
    title.className = 'confirm-dialog__preview-label';
    title.textContent = 'Query parameters';
    section.appendChild(title);
    for (const p of queryParams) {
      const field = buildField(`${p.name}${p.required ? ' (required)' : ''}`, p.description);
      inputs.query[p.name] = field.input;
      section.appendChild(field.element);
    }
    content.appendChild(section);
  }

  let bodyTextarea = null;
  if (bodyParam && !SAFE_METHODS.has(row.method.toLowerCase())) {
    const section = document.createElement('div');
    const title = document.createElement('p');
    title.className = 'confirm-dialog__preview-label';
    title.textContent = 'Request body (JSON)';
    section.appendChild(title);
    bodyTextarea = document.createElement('textarea');
    bodyTextarea.className = 'text-input json-editor';
    bodyTextarea.rows = 6;
    bodyTextarea.value = JSON.stringify(exampleFromSchema(bodyParam.schema), null, 2);
    section.appendChild(bodyTextarea);
    content.appendChild(section);
  }

  const previewArea = document.createElement('div');
  content.appendChild(previewArea);

  function buildRequest() {
    let path = row.path;
    for (const [name, input] of Object.entries(inputs.path)) {
      path = path.replace(`{${name}}`, encodeURIComponent(input.value || `{${name}}`));
    }
    const query = {};
    for (const [name, input] of Object.entries(inputs.query)) {
      if (input.value) query[name] = input.value;
    }
    let body;
    if (bodyTextarea) {
      try {
        body = bodyTextarea.value.trim() ? JSON.parse(bodyTextarea.value) : undefined;
      } catch {
        body = undefined;
      }
    }
    return { method: row.method, path, query, body };
  }

  function updatePreview() {
    const { method, path, query } = buildRequest();
    const qs = Object.keys(query).length ? '?' + new URLSearchParams(query).toString() : '';
    previewArea.replaceChildren(createApiPreview({ method, path: `${path}${qs}`, basePath: spec.basePath }));
  }
  for (const input of [...Object.values(inputs.path), ...Object.values(inputs.query)]) {
    input.addEventListener('input', updatePreview);
  }
  updatePreview();

  const actions = document.createElement('div');
  actions.className = 'confirm-dialog__actions';
  const sendButton = actionButton('Send request', 'button--primary', () => runRequest(app, spec, row, buildRequest(), modal));
  actions.appendChild(sendButton);
  content.appendChild(actions);

  const modal = openModal({ title: `${row.method} ${row.path}`, content, size: 'lg' });
}

async function runRequest(app, spec, row, builtRequest, builderModal) {
  const isSafe = SAFE_METHODS.has(row.method.toLowerCase());
  const fullPath = `${spec.basePath.replace(/\/$/, '')}${builtRequest.path}`;

  const execute = () =>
    restApi.executeDiscoveredRequest({
      baseUrl: spec.basePath,
      path: builtRequest.path,
      method: builtRequest.method,
      query: builtRequest.query,
      body: builtRequest.body,
    });

  const previewRequest = { method: row.method, path: builtRequest.path, basePath: spec.basePath, body: builtRequest.body };

  if (!isSafe) {
    const confirmed = await confirmAction({
      title: `Execute ${row.method} ${row.path}`,
      message: `This sends a real ${row.method} request to ${app.name}. It is not a read-only operation — review the request carefully before continuing.`,
      danger: true,
      confirmLabel: 'Send',
      request: previewRequest,
    });
    if (!confirmed) return;
  }

  try {
    const result = await execute();
    if (destroyed) return;
    builderModal.close();
    showResponse(row, result);
    recordActivity({
      action: `${row.method} ${row.path} on ${app.name}`,
      target: fullPath,
      status: result.status < 400 ? 'success' : 'error',
      request: previewRequest,
      response: { status: result.status, body: result.body },
    });
  } catch (err) {
    if (err?.name === 'MgmntAuthCancelled') return;
    showToast({ message: `Request failed: ${err.message || 'unknown error'}`, variant: 'error' });
    recordActivity({
      action: `${row.method} ${row.path} on ${app.name}`,
      target: fullPath,
      status: 'error',
      request: previewRequest,
      errorMessage: err.message,
    });
  }
}

function showResponse(row, result) {
  const content = document.createElement('div');
  const statusBadge = createStatusBadge(`HTTP ${result.status}`, result.status < 400 ? 'success' : 'error');
  content.appendChild(statusBadge);

  const headersDetails = document.createElement('details');
  const headersSummary = document.createElement('summary');
  headersSummary.textContent = 'Response headers';
  headersDetails.appendChild(headersSummary);
  const headersList = document.createElement('div');
  headersList.className = 'json-viewer';
  const headerEntries = [];
  result.headers.forEach((value, key) => headerEntries.push([key, value]));
  headersList.appendChild(createJsonViewer(Object.fromEntries(headerEntries)));
  headersDetails.appendChild(headersList);
  content.appendChild(headersDetails);

  const bodyTitle = document.createElement('p');
  bodyTitle.className = 'confirm-dialog__preview-label';
  bodyTitle.textContent = 'Response body';
  content.appendChild(bodyTitle);
  content.appendChild(createJsonViewer(result.body));

  openModal({ title: `${row.method} ${row.path} — response`, content, size: 'lg' });
}

function buildField(label, help) {
  const wrapper = document.createElement('div');
  wrapper.className = 'form-field';
  const labelEl = document.createElement('label');
  labelEl.textContent = label;
  const input = document.createElement('input');
  input.className = 'text-input';
  input.type = 'text';
  wrapper.append(labelEl, input);
  if (help) {
    const helpEl = document.createElement('p');
    helpEl.className = 'form-field__help';
    helpEl.textContent = help;
    wrapper.appendChild(helpEl);
  }
  return { element: wrapper, input };
}

function exampleFromSchema(schema) {
  if (!schema) return {};
  if (schema.example) return schema.example;
  if (schema.properties) {
    const obj = {};
    for (const [key, prop] of Object.entries(schema.properties)) {
      obj[key] = prop.example ?? (prop.type === 'string' ? '' : prop.type === 'integer' || prop.type === 'number' ? 0 : prop.type === 'boolean' ? false : {});
    }
    return obj;
  }
  return {};
}
