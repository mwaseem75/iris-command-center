// Databases — local database directories (full CRUD + mount/dismount/compact/
// integrity-check) and Config.Databases namespace bindings (read-only).
// Built custom rather than on utils/crud-section.js because the directory
// resource's create and edit request bodies use genuinely different schemas
// (create needs `Directory`; edit identifies the directory via query param and
// never repeats it in the body) and it has lifecycle actions beyond CRUD.

import { getApiPrefix, hasPrivilege } from '../state.js';
import { createDataTable } from '../components/data-table.js';
import { createStatusBadge } from '../components/status-badge.js';
import { openModal } from '../components/modal.js';
import { createJsonViewer } from '../components/json-viewer.js';
import { createForm } from '../utils/form-builder.js';
import { performAction } from '../utils/perform-action.js';
import { detailRow, actionButton, loadingRow, errorState, emptyCard } from '../utils/dom-helpers.js';
import * as databaseApi from '../api/database-api.js';

let destroyed = false;

const TABS = [
  { key: 'directories', label: 'Directories' },
  { key: 'bindings', label: 'Namespace Bindings' },
];

export function render(container) {
  destroyed = false;
  container.replaceChildren();
  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Databases';
  container.appendChild(heading);

  if (getApiPrefix() !== 'v2') {
    container.appendChild(
      emptyCard('Requires IRIS 2026.2 or later', 'Database management uses REST endpoints only available on IRIS 2026.2+.')
    );
    return;
  }
  if (!hasPrivilege('Manage')) {
    container.appendChild(
      emptyCard('Insufficient privilege', 'Database management requires the %Admin_Manage privilege, which your account does not currently hold.')
    );
    return;
  }

  const tabBar = document.createElement('div');
  tabBar.className = 'tab-bar';
  const tabButtons = {};
  for (const tab of TABS) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tab-bar__item';
    button.textContent = tab.label;
    button.addEventListener('click', () => switchTab(tab.key));
    tabBar.appendChild(button);
    tabButtons[tab.key] = button;
  }
  const contentArea = document.createElement('div');
  container.append(tabBar, contentArea);

  function switchTab(key) {
    for (const [k, btn] of Object.entries(tabButtons)) btn.classList.toggle('tab-bar__item--active', k === key);
    if (key === 'directories') renderDirectories(contentArea);
    else renderBindings(contentArea);
  }

  switchTab('directories');
}

export function destroy() {
  destroyed = true;
}

// ---------- Directories tab ----------

function renderDirectories(container) {
  container.replaceChildren();

  const toolbar = document.createElement('div');
  toolbar.className = 'dashboard-controls';
  const refreshButton = document.createElement('button');
  refreshButton.type = 'button';
  refreshButton.className = 'button button--ghost';
  refreshButton.textContent = 'Refresh';
  const createButton = document.createElement('button');
  createButton.type = 'button';
  createButton.className = 'button button--primary';
  createButton.textContent = 'New database';
  toolbar.append(refreshButton, createButton);

  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  container.append(toolbar, statusArea, tableContainer);

  let table = null;

  async function load() {
    statusArea.replaceChildren(loadingRow('Loading database directories…'));
    tableContainer.hidden = true;
    try {
      const rows = (await databaseApi.listDatabaseDirs({ maxRows: 500 })) || [];
      if (destroyed) return;
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      if (table) {
        table.setRows(rows);
      } else {
        table = createDataTable({
          columns: [
            { key: 'Directory', label: 'Directory' },
            { key: 'Status', label: 'Status', render: (r) => createStatusBadge(r.Status || '—', r.Status?.includes('Mounted') ? 'success' : 'warning') },
            { key: 'Size', label: 'Size (MB)' },
            { key: 'MaxSize', label: 'Max size' },
            { key: 'Resource', label: 'Resource' },
            { key: 'Encrypted', label: 'Encrypted', render: (r) => (r.Encrypted ? 'Yes' : 'No') },
          ],
          rows,
          searchFields: ['Directory', 'Resource', 'Status'],
          pageSize: 10,
          emptyMessage: 'No local databases found.',
          onRowClick: (row) => openDetail(row.Directory),
        });
        tableContainer.replaceChildren(table.element);
      }
    } catch (err) {
      if (destroyed) return;
      statusArea.replaceChildren(errorState(err, load));
      tableContainer.hidden = true;
    }
  }

  async function openDetail(dir) {
    const content = document.createElement('div');
    content.className = 'loading-text';
    content.innerHTML = '<span class="spinner"></span> Loading database detail…';
    const modal = openModal({ title: dir, content, size: 'lg' });

    try {
      const [detail, volumes, info] = await Promise.all([
        databaseApi.getDatabaseDir(dir),
        databaseApi.getDatabaseDirVolumes(dir).catch(() => []),
        databaseApi.getDatabaseDirInfo(dir).catch(() => null),
      ]);
      if (destroyed) return;
      content.replaceChildren(buildDetailBody(dir, detail, volumes, info, () => modal.close()));
    } catch (err) {
      content.replaceChildren(errorState(err));
    }
  }

  function buildDetailBody(dir, detail, volumes, info, closeModal) {
    const wrapper = document.createElement('div');
    wrapper.append(
      detailRow('Resource name', detail.ResourceName || '—'),
      detailRow('Max size (MB)', detail.MaxSize > 0 ? String(detail.MaxSize) : 'Unlimited'),
      detailRow('Global journal state', detail.GlobalJournalState ? 'Enabled' : 'Disabled'),
      detailRow('Read only', detail.ReadOnly ? 'Yes' : 'No'),
      detailRow('Cluster mount mode', detail.ClusterMountMode ? 'Yes' : 'No'),
      detailRow('New volume directory', detail.NewVolumeDirectory || '—')
    );

    if (info) {
      wrapper.append(
        detailRow('Block size', `${info.BlockSize?.toLocaleString() ?? '—'} bytes`),
        detailRow('Disk free', info.DiskFree || '—'),
        detailRow('Available space', info.AvailableSpace !== undefined ? `${info.AvailableSpace}%` : '—'),
        detailRow('Mounted', info.Mounted ? 'Yes' : 'No'),
        detailRow('Full', info.Full ? 'Yes — this database cannot grow further' : 'No')
      );
    }

    if (volumes.length > 0) {
      const volTitle = document.createElement('h3');
      volTitle.className = 'identity-card__subtitle';
      volTitle.textContent = 'Volumes';
      wrapper.appendChild(volTitle);
      for (const vol of volumes) {
        wrapper.appendChild(
          detailRow(vol.File || `Volume ${vol.VolumeNumber}`, `${vol.Size} MB used · ${vol.DiskFree.toLocaleString()} KB free on disk`)
        );
      }
    }

    const actions = document.createElement('div');
    actions.className = 'confirm-dialog__actions';
    actions.append(
      actionButton('Edit', 'button--ghost', () => {
        closeModal();
        openEditModal(dir, detail);
      }),
      actionButton('Mount', 'button--ghost', () => runLifecycleAction(dir, 'mount', closeModal)),
      actionButton('Dismount', 'button--ghost', () => runLifecycleAction(dir, 'dismount', closeModal, true)),
      actionButton('Compact', 'button--ghost', () => runLifecycleAction(dir, 'compact', closeModal)),
      actionButton('Integrity check', 'button--ghost', () => runIntegrityCheck(dir, closeModal)),
      actionButton('Delete', 'button--danger', () => runDelete(dir, closeModal))
    );
    wrapper.appendChild(actions);

    const rawDetails = document.createElement('details');
    rawDetails.className = 'metric-card__raw';
    const summary = document.createElement('summary');
    summary.textContent = 'View raw data';
    rawDetails.append(summary, createJsonViewer({ detail, volumes, info }));
    wrapper.appendChild(rawDetails);

    return wrapper;
  }

  async function runLifecycleAction(dir, verb, closeModal, danger = false) {
    const labels = { mount: 'Mount', dismount: 'Dismount', compact: 'Compact' };
    const execers = {
      mount: () => databaseApi.mountDatabaseDir(dir),
      dismount: () => databaseApi.dismountDatabaseDir(dir),
      compact: () => databaseApi.compactDatabaseDir(dir),
    };
    const messages = {
      mount: `Mount database "${dir}"?`,
      dismount: `Dismount database "${dir}"? Its data will become unavailable to all namespaces until remounted.`,
      compact: `Compact database "${dir}" to reclaim free space? This can take time on large databases.`,
    };
    const ok = await performAction({
      title: `${labels[verb]} database`,
      message: messages[verb],
      danger,
      confirmLabel: labels[verb],
      request: { method: 'POST', path: `v2/database-dir/${verb}?dir=${encodeURIComponent(dir)}`, body: {} },
      execute: execers[verb],
      activityLabel: `${labels[verb]} database ${dir}`,
    });
    if (ok) {
      closeModal();
      load();
    }
  }

  async function runIntegrityCheck(dir, closeModal) {
    const ok = await performAction({
      title: 'Run integrity check',
      message: `Run an integrity check on "${dir}"? This can be resource-intensive and may take time.`,
      request: { method: 'POST', path: 'v2/database-dir/integrity-check', body: { Databases: [dir] } },
      execute: () => databaseApi.integrityCheckDatabaseDir({ Databases: [dir] }),
      activityLabel: `Integrity check on ${dir}`,
    });
    if (ok) closeModal();
  }

  async function runDelete(dir, closeModal) {
    const ok = await performAction({
      title: 'Delete database',
      message: `Permanently delete database "${dir}" and its data files? This cannot be undone.`,
      danger: true,
      confirmLabel: 'Delete',
      request: { method: 'DELETE', path: `v2/database-dir?dir=${encodeURIComponent(dir)}` },
      execute: () => databaseApi.deleteDatabaseDir(dir),
      activityLabel: `Delete database ${dir}`,
    });
    if (ok) {
      closeModal();
      load();
    }
  }

  function openEditModal(dir, detail) {
    const form = createForm(
      [
        { key: 'ResourceName', label: 'Resource name', type: 'text' },
        { key: 'MaxSize', label: 'Max size (MB, 0 = unlimited)', type: 'number' },
        { key: 'ExpansionSize', label: 'Expansion size (MB, 0 = system default)', type: 'number' },
        { key: 'GlobalJournalState', label: 'Journal this database', type: 'checkbox' },
        { key: 'ReadOnly', label: 'Read only', type: 'checkbox' },
        { key: 'ClusterMountMode', label: 'Cluster mount mode', type: 'checkbox' },
      ],
      detail
    );
    const content = document.createElement('div');
    content.appendChild(form.element);
    const submitRow = document.createElement('div');
    submitRow.className = 'confirm-dialog__actions';
    const submitButton = document.createElement('button');
    submitButton.type = 'button';
    submitButton.className = 'button button--primary';
    submitButton.textContent = 'Save changes';
    submitRow.appendChild(submitButton);
    content.appendChild(submitRow);

    const modal = openModal({ title: `Edit ${dir}`, content, size: 'md' });
    submitButton.addEventListener('click', async () => {
      const body = form.getValues();
      modal.close();
      const ok = await performAction({
        title: 'Save database settings',
        message: `Save changes to "${dir}"?`,
        request: { method: 'PUT', path: `v2/database-dir?dir=${encodeURIComponent(dir)}`, body },
        execute: () => databaseApi.updateDatabaseDir(dir, body),
        activityLabel: `Update database ${dir}`,
      });
      if (ok) load();
    });
  }

  createButton.addEventListener('click', () => {
    const form = createForm([
      { key: 'Directory', label: 'Directory path', type: 'text', required: true, help: 'Absolute path on the server, e.g. /usr/irissys/mgr/mydata/' },
      { key: 'ResourceName', label: 'Resource name', type: 'text', help: 'Defaults to a generated %DB_ name if left blank.' },
      { key: 'Size', label: 'Initial size (MB)', type: 'number' },
      { key: 'GlobalJournalState', label: 'Journal this database', type: 'checkbox' },
      { key: 'Encrypted', label: 'Encrypted', type: 'checkbox' },
    ]);
    const content = document.createElement('div');
    content.appendChild(form.element);
    const submitRow = document.createElement('div');
    submitRow.className = 'confirm-dialog__actions';
    const submitButton = document.createElement('button');
    submitButton.type = 'button';
    submitButton.className = 'button button--primary';
    submitButton.textContent = 'Create';
    submitRow.appendChild(submitButton);
    content.appendChild(submitRow);

    const modal = openModal({ title: 'New database', content, size: 'md' });
    submitButton.addEventListener('click', async () => {
      const body = form.getValues();
      if (!body.Directory) return;
      modal.close();
      const ok = await performAction({
        title: 'Create database',
        message: `Create a new local database at "${body.Directory}"?`,
        request: { method: 'POST', path: 'v2/database-dir', body },
        execute: () => databaseApi.createDatabaseDir(body),
        activityLabel: `Create database ${body.Directory}`,
      });
      if (ok) load();
    });
  });

  refreshButton.addEventListener('click', load);
  load();
}

// ---------- Namespace Bindings tab (read-only) ----------

function renderBindings(container) {
  container.replaceChildren();
  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  container.append(statusArea, tableContainer);

  statusArea.replaceChildren(loadingRow('Loading namespace bindings…'));
  tableContainer.hidden = true;

  databaseApi
    .listDatabases({ maxRows: 500 })
    .then((rows) => {
      if (destroyed) return;
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      const table = createDataTable({
        columns: [
          { key: 'Name', label: 'Name' },
          { key: 'Directory', label: 'Directory' },
          { key: 'Status', label: 'Status', render: (r) => createStatusBadge(r.Status || '—', r.Status?.includes('Mounted') ? 'success' : 'warning') },
          { key: 'MountRequired', label: 'Mount required', render: (r) => (r.MountRequired ? 'Yes' : 'No') },
        ],
        rows: rows || [],
        searchFields: ['Name', 'Directory'],
        pageSize: 12,
        emptyMessage: 'No database bindings found.',
      });
      tableContainer.replaceChildren(table.element);
    })
    .catch((err) => {
      if (destroyed) return;
      statusArea.replaceChildren(errorState(err, () => renderBindings(container)));
      tableContainer.hidden = true;
    });
}
