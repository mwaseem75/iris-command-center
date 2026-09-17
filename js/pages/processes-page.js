// Processes — list, detail, and suspend/resume/terminate/broadcast actions.
// v2-only (IRIS 2026.2+) — see js/api/process-api.js for why.
//
// Note: the list and detail endpoints use two different field-naming
// generations for the same resource (confirmed live — see docs/api-matrix.md
// section 12). Table columns read list-shape fields; the detail modal reads
// detail-shape fields. This is intentional, not an inconsistency in our code.

import { getApiPrefix, hasPrivilege } from '../state.js';
import { createDataTable } from '../components/data-table.js';
import { createStatusBadge } from '../components/status-badge.js';
import { openModal } from '../components/modal.js';
import { createJsonViewer } from '../components/json-viewer.js';
import { performAction } from '../utils/perform-action.js';
import { showToast } from '../components/toast.js';
import { detailRow, actionButton, loadingRow, errorState, emptyCard } from '../utils/dom-helpers.js';
import * as processApi from '../api/process-api.js';

let destroyed = false;

const RUN_STATE_VARIANT = (state) => {
  if (!state) return 'info';
  if (state.includes('SUSP')) return 'warning';
  if (state === 'RUN') return 'success';
  return 'info';
};

export function render(container) {
  destroyed = false;
  container.replaceChildren();

  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Processes';

  if (getApiPrefix() !== 'v2') {
    container.append(
      heading,
      emptyCard(
        'Requires IRIS 2026.2 or later',
        'Process management uses REST endpoints only available on IRIS 2026.2+. The connected instance reports an older API version.'
      )
    );
    return;
  }
  if (!hasPrivilege('Operate')) {
    container.append(
      heading,
      emptyCard(
        'Insufficient privilege',
        'Viewing and managing processes requires the %Admin_Operate privilege, which your account does not currently hold.'
      )
    );
    return;
  }

  const toolbar = document.createElement('div');
  toolbar.className = 'dashboard-controls';
  const refreshButton = document.createElement('button');
  refreshButton.type = 'button';
  refreshButton.className = 'button button--ghost';
  refreshButton.textContent = 'Refresh';
  const broadcastButton = document.createElement('button');
  broadcastButton.type = 'button';
  broadcastButton.className = 'button button--ghost';
  broadcastButton.textContent = 'Broadcast message';
  toolbar.append(refreshButton, broadcastButton);

  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  const statusArea = document.createElement('div');

  container.append(heading, toolbar, statusArea, tableContainer);

  let table = null;
  let currentRows = [];

  function columns() {
    return [
      { key: 'Pid', label: 'PID' },
      { key: 'Username', label: 'User', render: (r) => r.Username || '(system)' },
      { key: 'Nspace', label: 'Namespace', render: (r) => r.Nspace || '—' },
      { key: 'Routine', label: 'Routine' },
      { key: 'State', label: 'State', render: (r) => createStatusBadge(r.State || '—', RUN_STATE_VARIANT(r.State)) },
      { key: 'CPUTime', label: 'CPU (ms)' },
      { key: 'ElapsedTime', label: 'Elapsed' },
    ];
  }

  async function load() {
    statusArea.replaceChildren(loadingRow('Loading processes…'));
    tableContainer.hidden = true;
    try {
      const rows = await processApi.listProcesses({ maxRows: 500 });
      if (destroyed) return;
      currentRows = rows || [];
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      if (table) {
        table.setRows(currentRows);
      } else {
        table = createDataTable({
          columns: columns(),
          rows: currentRows,
          searchFields: ['Pid', 'Username', 'Nspace', 'Routine', 'State'],
          pageSize: 15,
          emptyMessage: 'No active processes.',
          onRowClick: (row) => openDetail(row.Pid),
        });
        tableContainer.replaceChildren(table.element);
      }
    } catch (err) {
      if (destroyed) return;
      statusArea.replaceChildren(errorState(err, load));
      tableContainer.hidden = true;
    }
  }

  async function openDetail(pid) {
    const content = document.createElement('div');
    content.className = 'loading-text';
    content.innerHTML = '<span class="spinner"></span> Loading process detail…';
    const modal = openModal({ title: `Process ${pid}`, content, size: 'lg' });

    try {
      const detail = await processApi.getProcess(pid);
      if (destroyed) return;
      content.replaceChildren(buildDetailBody(pid, detail, () => modal.close()));
    } catch (err) {
      content.replaceChildren(errorState(err));
    }
  }

  function buildDetailBody(pid, detail, closeModal) {
    const wrapper = document.createElement('div');
    wrapper.className = 'process-detail';

    wrapper.append(
      detailRow('Namespace', detail.NameSpace || '—'),
      detailRow('OS user', detail.OSUserName || '—'),
      detailRow('State', detail.State || '—'),
      detailRow('Routine', detail.Routine || '—'),
      detailRow('Location', detail.Location || '—'),
      detailRow('CPU time (ms)', String(detail.CPUTime ?? '—')),
      detailRow('Memory used / allocated (KB)', `${detail.MemoryUsed ?? '—'} / ${detail.MemoryAllocated ?? '—'}`),
      detailRow('Roles', (detail.Roles || []).join(', ') || '—'),
      detailRow('Open devices', (detail.OpenDevices || []).join(', ') || 'None')
    );

    const actions = document.createElement('div');
    actions.className = 'confirm-dialog__actions';

    // Note: CanBeSuspended/CanBeTerminated are eligibility flags ("is this kind of
    // process allowed to be suspended at all"), not current-state flags — there is
    // no separate CanBeResumed field. We use the actual State string to decide
    // whether the current action is Suspend or Resume.
    const isSuspended = Boolean(detail.State?.includes('SUSP'));

    if (detail.CanBeSuspended && !isSuspended) {
      actions.appendChild(
        actionButton('Suspend', 'button--ghost', async () => {
          const ok = await performAction({
            title: 'Suspend process',
            message: `Suspend process ${pid} (namespace ${detail.NameSpace || '—'})? It will stop executing until resumed.`,
            request: { method: 'POST', path: `v2/process/suspend?id=${pid}`, body: {} },
            execute: () => processApi.suspendProcess(pid),
            activityLabel: `Suspend process ${pid}`,
          });
          if (ok) {
            closeModal();
            load();
          }
        })
      );
    }
    if (detail.CanBeSuspended && isSuspended) {
      actions.appendChild(
        actionButton('Resume', 'button--primary', async () => {
          const ok = await performAction({
            title: 'Resume process',
            message: `Resume process ${pid} (namespace ${detail.NameSpace || '—'})?`,
            request: { method: 'POST', path: `v2/process/resume?id=${pid}`, body: {} },
            execute: () => processApi.resumeProcess(pid),
            activityLabel: `Resume process ${pid}`,
          });
          if (ok) {
            closeModal();
            load();
          }
        })
      );
    }
    if (detail.CanBeTerminated) {
      actions.appendChild(
        actionButton('Terminate', 'button--danger', async () => {
          const ok = await performAction({
            title: 'Terminate process',
            message: `Terminate process ${pid} (namespace ${detail.NameSpace || '—'}, routine ${detail.Routine || '—'})? This immediately kills the process and cannot be undone.`,
            danger: true,
            confirmLabel: 'Terminate',
            request: { method: 'POST', path: `v2/process/terminate?id=${pid}`, body: {} },
            execute: () => processApi.terminateProcess(pid),
            activityLabel: `Terminate process ${pid}`,
          });
          if (ok) {
            closeModal();
            load();
          }
        })
      );
    }
    if (actions.children.length > 0) wrapper.appendChild(actions);

    const rawDetails = document.createElement('details');
    rawDetails.className = 'metric-card__raw';
    const summary = document.createElement('summary');
    summary.textContent = 'View raw process data';
    rawDetails.append(summary, createJsonViewer(detail));
    wrapper.appendChild(rawDetails);

    return wrapper;
  }

  broadcastButton.addEventListener('click', async () => {
    const recipients = currentRows.filter((r) => r.CanReceiveBroadcast);
    if (recipients.length === 0) {
      showToast({ message: 'No processes are currently able to receive a broadcast.', variant: 'info' });
      return;
    }
    const content = document.createElement('div');
    const field = document.createElement('div');
    field.className = 'form-field';
    const label = document.createElement('label');
    label.textContent = `Message (will be sent to ${recipients.length} process(es) attached to a terminal)`;
    const input = document.createElement('input');
    input.className = 'text-input';
    input.type = 'text';
    field.append(label, input);
    content.append(field);

    const modal = openModal({ title: 'Broadcast message', content, size: 'sm' });
    const sendRow = document.createElement('div');
    sendRow.className = 'confirm-dialog__actions';
    sendRow.appendChild(
      actionButton('Send', 'button--primary', async () => {
        const message = input.value.trim();
        if (!message) return;
        const pidList = recipients.map((r) => r.Pid);
        modal.close();
        await performAction({
          title: 'Broadcast message',
          message: `Send "${message}" to ${pidList.length} process(es)?`,
          request: { method: 'POST', path: 'v2/process/broadcast', body: { Message: message, PidList: pidList } },
          execute: () => processApi.broadcastMessage({ message, pidList }),
          activityLabel: 'Broadcast message',
        });
      })
    );
    content.appendChild(sendRow);
  });

  refreshButton.addEventListener('click', load);
  load();
}

export function destroy() {
  destroyed = true;
}
