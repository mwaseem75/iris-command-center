// Logs & Diagnostics — journal files/records/settings, and background
// (async) task history. See docs/api-matrix.md section 8.
//
// Journal files and records are read-only (no create/edit/delete — a
// journal is a historical record, not an editable resource), so the files
// list reuses renderCrudSection with canCreate/canEdit/canDelete all false,
// which turns its detail modal into a plain read-only view. Records within
// a file are browsed in a nested modal rather than a second CRUD section,
// since there's no stable per-record "resource" to list/detail/edit beyond
// a one-off filtered search — the same shape as Security's Audit tab.

import { hasPrivilege } from '../state.js';
import { renderCrudSection } from '../utils/crud-section.js';
import { createForm } from '../utils/form-builder.js';
import { createDataTable } from '../components/data-table.js';
import { createStatusBadge } from '../components/status-badge.js';
import { createJsonViewer } from '../components/json-viewer.js';
import { openModal } from '../components/modal.js';
import { loadingRow, errorState, actionButton, detailRow, emptyCard } from '../utils/dom-helpers.js';
import * as journalApi from '../api/journal-api.js';
import * as asyncApi from '../api/async-api.js';

let activeSection = null;
let destroyed = false;

const OPERATE_PRIVILEGE = 'Operate';

const TABS = [
  { key: 'journal', label: 'Journal' },
  { key: 'activity', label: 'Activity' },
];

export function render(container) {
  destroyed = false;
  container.replaceChildren();

  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Logs';
  container.appendChild(heading);

  if (!hasPrivilege(OPERATE_PRIVILEGE)) {
    container.appendChild(
      emptyCard(
        'Insufficient privilege',
        'Journal and background-task history require the %Admin_Operate privilege, which your account does not currently hold.'
      )
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
    activeSection?.destroy?.();
    activeSection = null;
    for (const [k, btn] of Object.entries(tabButtons)) btn.classList.toggle('tab-bar__item--active', k === key);
    contentArea.replaceChildren();

    if (key === 'journal') activeSection = renderJournal(contentArea);
    else if (key === 'activity') activeSection = renderActivity(contentArea);
  }

  switchTab('journal');
}

export function destroy() {
  destroyed = true;
  activeSection?.destroy?.();
  activeSection = null;
}

// ---------- Journal ----------

function renderJournal(container) {
  let localDestroyed = false;

  const settingsCard = document.createElement('div');
  settingsCard.className = 'card';
  container.appendChild(settingsCard);

  function loadSettings() {
    settingsCard.replaceChildren(loadingRow('Loading journal settings…'));
    journalApi
      .getJournalSettings()
      .then((settings) => {
        if (localDestroyed) return;
        settingsCard.replaceChildren(buildSettingsCard(settings));
      })
      .catch((err) => {
        if (localDestroyed) return;
        settingsCard.replaceChildren(errorState(err, loadSettings));
      });
  }
  loadSettings();

  const filesContainer = document.createElement('div');
  container.appendChild(filesContainer);

  const section = renderCrudSection(filesContainer, {
    resourceLabel: 'Journal file',
    idField: 'Name',
    columns: [
      { key: 'Name', label: 'File' },
      { key: 'Size', label: 'Size', render: (r) => formatBytes(r.Size) },
      { key: 'CreationTime', label: 'Created' },
      { key: 'Reason', label: 'Reason' },
    ],
    searchFields: ['Name', 'Reason'],
    list: () => journalApi.listJournalFiles({ maxRows: 200 }),
    get: (file) => journalApi.getJournalFile(file),
    formFields: [
      { key: 'CreationTime', label: 'Created' },
      { key: 'FirstRecordAddress', label: 'First record address' },
      { key: 'LastRecordAddress', label: 'Last record address' },
      { key: 'End', label: 'End address' },
      { key: 'FileCount', label: 'File count (this journal set)' },
      { key: 'MaxSize', label: 'Max size (bytes)' },
      { key: 'ClusterStartTime', label: 'Cluster start time' },
      { key: 'MinTransFileCount', label: 'Min transaction file count' },
      { key: 'FileGUID', label: 'File GUID' },
    ],
    pathFor: (file) => `v2/journal/file?file=${encodeURIComponent(file)}`,
    canCreate: false,
    canEdit: false,
    renderExtraDetail: (wrapper, detail) => {
      if (detail.Databases?.length) {
        const title = document.createElement('h3');
        title.className = 'identity-card__subtitle';
        title.textContent = `Databases referenced (${detail.Databases.length})`;
        wrapper.appendChild(title);
        const list = document.createElement('ul');
        list.className = 'privilege-list';
        for (const db of detail.Databases) {
          const li = document.createElement('li');
          const badge = document.createElement('span');
          badge.className = 'status-badge status-badge--info';
          badge.textContent = db.DatabasePathOrAlias;
          li.appendChild(badge);
          list.appendChild(li);
        }
        wrapper.appendChild(list);
      }
      if (detail.PrevFile?.File) wrapper.appendChild(detailRow('Previous file', detail.PrevFile.File));
      if (detail.NextFile?.File) wrapper.appendChild(detailRow('Next file', detail.NextFile.File));
    },
    extraActions: (detail, id, { closeModal }) => [
      actionButton('View records', 'button--primary', () => {
        closeModal();
        openRecordsModal(id);
      }),
    ],
  });

  return {
    destroy() {
      localDestroyed = true;
      section.destroy();
    },
  };
}

function buildSettingsCard(settings) {
  const wrapper = document.createElement('div');
  const title = document.createElement('h3');
  title.className = 'metric-card__title';
  title.textContent = 'Journal settings';
  wrapper.appendChild(title);
  wrapper.append(
    detailRow('Current directory', settings.CurrentDirectory || '—'),
    detailRow('Alternate directory', settings.AlternateDirectory || '—'),
    detailRow('File size limit', `${settings.FileSizeLimit ?? '—'} MB`),
    detailRow('Days before purge', String(settings.DaysBeforePurge ?? '—')),
    detailRow('Backups before purge', String(settings.BackupsBeforePurge ?? '—')),
    detailRow('Compress files', settings.CompressFiles ? 'Yes' : 'No'),
    detailRow('Freeze on error', settings.FreezeOnError ? 'Yes' : 'No')
  );
  return wrapper;
}

function openRecordsModal(file) {
  const content = document.createElement('div');

  const filterForm = createForm([
    { key: 'matchColumnName', label: 'Match column (e.g. Address, ProcessID)', type: 'text' },
    { key: 'matchOperator', label: 'Match operator (e.g. =, >, <)', type: 'text' },
    { key: 'matchValue', label: 'Match value', type: 'number' },
    { key: 'reverse', label: 'Reverse order (newest first)', type: 'checkbox' },
    { key: 'initialOffset', label: 'Initial offset', type: 'number' },
    { key: 'maxRows', label: 'Max rows', type: 'number', help: 'Default 100 if left blank.' },
  ]);
  content.appendChild(filterForm.element);

  const actionsRow = document.createElement('div');
  actionsRow.className = 'confirm-dialog__actions';
  const searchButton = actionButton('Search', 'button--primary', () => search());
  actionsRow.appendChild(searchButton);
  content.appendChild(actionsRow);

  const resultArea = document.createElement('div');
  content.appendChild(resultArea);

  let localDestroyed = false;
  openModal({
    title: `Records: ${file}`,
    content,
    size: 'lg',
    onClose: () => {
      localDestroyed = true;
    },
  });

  async function search() {
    const values = filterForm.getValues();
    resultArea.replaceChildren(loadingRow('Searching journal records… this can take a few seconds.'));
    searchButton.disabled = true;
    try {
      const records = (await journalApi.listJournalRecords(file, { ...values, maxRows: values.maxRows || 100 })) || [];
      if (localDestroyed) return;
      resultArea.replaceChildren();
      const table = createDataTable({
        columns: [
          { key: 'Address', label: 'Address' },
          { key: 'TypeName', label: 'Type' },
          { key: 'TimeStamp', label: 'Time' },
          { key: 'ProcessID', label: 'Process' },
          { key: 'DatabaseName', label: 'Database' },
          { key: 'GlobalNode', label: 'Global' },
        ],
        rows: records,
        searchFields: ['TypeName', 'DatabaseName', 'GlobalNode'],
        pageSize: 10,
        emptyMessage: 'No records match this filter.',
        onRowClick: (row) => openRecordDetailModal(file, row.Address),
      });
      resultArea.appendChild(table.element);
    } catch (err) {
      if (localDestroyed) return;
      resultArea.replaceChildren(errorState(err, search));
    } finally {
      if (!localDestroyed) searchButton.disabled = false;
    }
  }

  search();
}

function openRecordDetailModal(file, address) {
  const content = document.createElement('div');
  content.appendChild(loadingRow('Loading record…'));
  let localDestroyed = false;
  openModal({
    title: `Record at ${address}`,
    content,
    size: 'md',
    onClose: () => {
      localDestroyed = true;
    },
  });

  journalApi
    .getJournalRecord(file, address)
    .then((detail) => {
      if (localDestroyed) return;
      const wrapper = document.createElement('div');
      wrapper.append(
        detailRow('Type', detail.TypeName || '—'),
        detailRow('Timestamp', detail.TimeStamp || '—'),
        detailRow('Process ID', String(detail.ProcessID ?? '—')),
        detailRow('Job ID', String(detail.JobID ?? '—')),
        detailRow('In transaction', detail.InTransaction ? 'Yes' : 'No'),
        detailRow('Previous address', String(detail.PrevAddress ?? '—')),
        detailRow('Next address', String(detail.NextAddress ?? '—'))
      );
      if (detail.SetKill && Object.keys(detail.SetKill).length > 0) {
        const title = document.createElement('h3');
        title.className = 'identity-card__subtitle';
        title.textContent = 'Set/Kill detail';
        wrapper.appendChild(title);
        wrapper.appendChild(createJsonViewer(detail.SetKill));
      }
      content.replaceChildren(wrapper);
    })
    .catch((err) => {
      if (localDestroyed) return;
      content.replaceChildren(errorState(err));
    });
}

// ---------- Activity (background async task history) ----------

function renderActivity(container) {
  let localDestroyed = false;

  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  tableContainer.hidden = true;
  container.append(statusArea, tableContainer);

  function load() {
    statusArea.replaceChildren(loadingRow('Loading background task history…'));
    tableContainer.hidden = true;
    asyncApi
      .listAsyncResults({ maxRows: 200 })
      .then((results) => {
        if (localDestroyed) return;
        statusArea.replaceChildren();
        tableContainer.hidden = false;
        const table = createDataTable({
          columns: [
            { key: 'TaskName', label: 'Task' },
            { key: 'State', label: 'State', render: (r) => createStatusBadge(r.State, stateVariant(r.State)) },
            { key: 'TimeQueued', label: 'Queued' },
            { key: 'TimeFinished', label: 'Finished' },
          ],
          rows: results || [],
          searchFields: ['TaskName', 'State'],
          pageSize: 15,
          emptyMessage: 'No background tasks recorded.',
          onRowClick: (row) => openAsyncDetailModal(row.GUID),
        });
        tableContainer.replaceChildren(table.element);
      })
      .catch((err) => {
        if (localDestroyed) return;
        statusArea.replaceChildren(errorState(err, load));
      });
  }
  load();

  return {
    destroy() {
      localDestroyed = true;
    },
  };
}

function stateVariant(state) {
  if (state === 'Finished') return 'success';
  if (state === 'Failed' || state === 'Cancelled') return 'error';
  return 'warning';
}

function openAsyncDetailModal(guid) {
  const content = document.createElement('div');
  content.appendChild(loadingRow('Loading task…'));
  let localDestroyed = false;
  openModal({
    title: `Task ${guid}`,
    content,
    size: 'md',
    onClose: () => {
      localDestroyed = true;
    },
  });

  asyncApi
    .getAsyncResult(guid)
    .then((detail) => {
      if (localDestroyed) return;
      const wrapper = document.createElement('div');
      wrapper.append(
        detailRow('Task', detail.TaskName || '—'),
        detailRow('State', detail.State || '—'),
        detailRow('Queued', detail.TimeQueued || '—'),
        detailRow('Started', detail.TimeStarted || '—'),
        detailRow('Finished', detail.TimeFinished || '—')
      );
      if (detail.FailureReason) wrapper.appendChild(detailRow('Failure reason', detail.FailureReason));
      if (detail.Result !== undefined && detail.Result !== null) {
        const title = document.createElement('h3');
        title.className = 'identity-card__subtitle';
        title.textContent = 'Result';
        wrapper.appendChild(title);
        wrapper.appendChild(createJsonViewer(detail.Result));
      }
      if (detail.Console?.length) {
        const title2 = document.createElement('h3');
        title2.className = 'identity-card__subtitle';
        title2.textContent = 'Console output';
        wrapper.appendChild(title2);
        wrapper.appendChild(createJsonViewer(detail.Console));
      }
      content.replaceChildren(wrapper);
    })
    .catch((err) => {
      if (localDestroyed) return;
      content.replaceChildren(errorState(err));
    });
}

// ---------- helpers ----------

function formatBytes(bytes) {
  if (typeof bytes !== 'number') return '—';
  const mb = bytes / 1024 / 1024;
  return mb >= 1 ? `${mb.toFixed(2)} MB` : `${(bytes / 1024).toFixed(1)} KB`;
}
