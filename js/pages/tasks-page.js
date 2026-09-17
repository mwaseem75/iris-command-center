// Tasks — list, upcoming, history, task manager controls, and per-task
// run/suspend/resume/delete actions. v2-only (IRIS 2026.2+), same rationale as
// js/api/process-api.js. Task creation/editing (the ~30-field task config form)
// is deferred — everything else in the spec's Task Management module is here.

import { getApiPrefix, hasPrivilege } from '../state.js';
import { createDataTable } from '../components/data-table.js';
import { createStatusBadge } from '../components/status-badge.js';
import { openModal } from '../components/modal.js';
import { createJsonViewer } from '../components/json-viewer.js';
import { performAction } from '../utils/perform-action.js';
import { detailRow, actionButton, loadingRow, errorState, emptyCard } from '../utils/dom-helpers.js';
import * as taskApi from '../api/task-api.js';

let destroyed = false;

const TABS = [
  { key: 'tasks', label: 'Tasks' },
  { key: 'upcoming', label: 'Upcoming' },
  { key: 'history', label: 'History' },
];

export function render(container) {
  destroyed = false;
  container.replaceChildren();

  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Tasks';

  if (getApiPrefix() !== 'v2') {
    container.append(
      heading,
      emptyCard(
        'Requires IRIS 2026.2 or later',
        'Task management uses REST endpoints only available on IRIS 2026.2+. The connected instance reports an older API version.'
      )
    );
    return;
  }
  const canOperate = hasPrivilege('Operate');
  const canTask = hasPrivilege('Task');
  if (!canOperate && !canTask) {
    container.append(
      heading,
      emptyCard(
        'Insufficient privilege',
        'Viewing tasks requires the %Admin_Operate or %Admin_Task privilege, which your account does not currently hold.'
      )
    );
    return;
  }

  const managerCard = document.createElement('section');
  managerCard.className = 'card';

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

  container.append(heading, managerCard, tabBar, contentArea);

  const tableCache = {};
  let activeTab = 'tasks';

  async function loadManager() {
    managerCard.replaceChildren(loadingRow('Loading task manager status…'));
    try {
      const status = await taskApi.getTaskManagerStatus();
      if (destroyed) return;
      renderManager(status);
    } catch (err) {
      if (destroyed) return;
      managerCard.replaceChildren(errorState(err, loadManager));
    }
  }

  function renderManager(status) {
    const isRunning = status.Status === 'Running';
    const row = document.createElement('div');
    row.className = 'task-manager-row';
    const title = document.createElement('h3');
    title.className = 'metric-card__title';
    title.textContent = 'Task manager';
    const badge = createStatusBadge(status.Status || 'Unknown', isRunning ? 'success' : 'warning');

    const actions = document.createElement('div');
    actions.className = 'confirm-dialog__actions';
    actions.appendChild(
      actionButton('Run', 'button--ghost', () =>
        managerAction('run', 'Run the task manager?', () => taskApi.runTaskManager(), 'v2/task/manager/run')
      )
    );
    actions.appendChild(
      actionButton('Suspend', 'button--ghost', () =>
        managerAction(
          'suspend',
          'Suspend the task manager? All scheduled tasks will stop running until resumed.',
          () => taskApi.suspendTaskManager(),
          'v2/task/manager/suspend'
        )
      )
    );
    actions.appendChild(
      actionButton('Resume', 'button--primary', () =>
        managerAction('resume', 'Resume the task manager?', () => taskApi.resumeTaskManager(), 'v2/task/manager/resume')
      )
    );

    row.append(title, badge, actions);
    managerCard.replaceChildren(row);
  }

  async function managerAction(verb, message, execute, path) {
    const ok = await performAction({
      title: `${verb[0].toUpperCase()}${verb.slice(1)} task manager`,
      message,
      request: { method: 'POST', path, body: {} },
      execute,
      activityLabel: `${verb[0].toUpperCase()}${verb.slice(1)} task manager`,
    });
    if (ok) loadManager();
  }

  function switchTab(key) {
    activeTab = key;
    for (const [k, btn] of Object.entries(tabButtons)) {
      btn.classList.toggle('tab-bar__item--active', k === key);
    }
    renderTab();
  }

  async function renderTab() {
    if (tableCache[activeTab]) {
      contentArea.replaceChildren(tableCache[activeTab].element);
      return;
    }
    contentArea.replaceChildren(loadingRow('Loading…'));
    try {
      if (activeTab === 'tasks') {
        const rows = await taskApi.listTasks({ maxRows: 500 });
        if (destroyed) return;
        const table = buildTasksTable(rows || []);
        tableCache.tasks = table;
        contentArea.replaceChildren(table.element);
      } else if (activeTab === 'upcoming') {
        const rows = await taskApi.getUpcomingTasks({ maxRows: 200 });
        if (destroyed) return;
        const table = buildUpcomingTable(rows || []);
        tableCache.upcoming = table;
        contentArea.replaceChildren(table.element);
      } else if (activeTab === 'history') {
        const rows = await taskApi.getTaskHistory({ maxRows: 200 });
        if (destroyed) return;
        const table = buildHistoryTable(rows || []);
        tableCache.history = table;
        contentArea.replaceChildren(table.element);
      }
    } catch (err) {
      if (destroyed) return;
      contentArea.replaceChildren(errorState(err, renderTab));
    }
  }

  function buildTasksTable(rows) {
    const wrapper = document.createElement('div');
    wrapper.className = 'card';
    const table = createDataTable({
      columns: [
        { key: 'Id', label: 'ID' },
        { key: 'Name', label: 'Name' },
        { key: 'Namespace', label: 'Namespace' },
        { key: 'Type', label: 'Type' },
        { key: 'Suspended', label: 'Status', render: (r) => createStatusBadge(r.Suspended ? 'Suspended' : 'Active', r.Suspended ? 'warning' : 'success') },
        { key: 'NextScheduled', label: 'Next scheduled', render: (r) => r.NextScheduled || '—' },
        { key: 'LastFinished', label: 'Last finished', render: (r) => r.LastFinished || 'Never' },
      ],
      rows,
      searchFields: ['Name', 'Namespace', 'Type', 'Id'],
      pageSize: 12,
      emptyMessage: 'No tasks found.',
      onRowClick: (row) => openTaskDetail(row.Id),
    });
    wrapper.appendChild(table.element);
    return { element: wrapper, refresh: (newRows) => table.setRows(newRows) };
  }

  function buildUpcomingTable(rows) {
    const wrapper = document.createElement('div');
    wrapper.className = 'card';
    const table = createDataTable({
      columns: [
        { key: 'Id', label: 'ID' },
        { key: 'Name', label: 'Name' },
        { key: 'Namespace', label: 'Namespace' },
        { key: 'Datetime', label: 'Scheduled for' },
        { key: 'Suspended', label: 'Status', render: (r) => createStatusBadge(r.Suspended ? 'Suspended' : 'Active', r.Suspended ? 'warning' : 'success') },
      ],
      rows,
      searchFields: ['Name', 'Namespace'],
      pageSize: 12,
      emptyMessage: 'Nothing scheduled.',
      onRowClick: (row) => openTaskDetail(row.Id),
    });
    wrapper.appendChild(table.element);
    return { element: wrapper };
  }

  function buildHistoryTable(rows) {
    const wrapper = document.createElement('div');
    wrapper.className = 'card';
    const table = createDataTable({
      columns: [
        { key: 'LogDatetime', label: 'Logged at' },
        { key: 'Name', label: 'Task' },
        { key: 'Namespace', label: 'Namespace' },
        { key: 'Result', label: 'Result', render: (r) => createStatusBadge(r.Result || '—', r.ErrNumber ? 'error' : 'success') },
        { key: 'Username', label: 'Run as' },
      ],
      rows,
      searchFields: ['Name', 'Namespace', 'Result', 'Username'],
      pageSize: 15,
      emptyMessage: 'No task history recorded.',
    });
    wrapper.appendChild(table.element);
    return { element: wrapper };
  }

  async function openTaskDetail(id) {
    const content = document.createElement('div');
    content.innerHTML = '<span class="spinner"></span> Loading task detail…';
    content.className = 'loading-text';
    const modal = openModal({ title: `Task ${id}`, content, size: 'lg' });

    try {
      const [config, info] = await Promise.all([taskApi.getTask(id), taskApi.getTaskInfo(id)]);
      if (destroyed) return;
      content.replaceChildren(buildTaskDetailBody(id, config, info, () => modal.close()));
    } catch (err) {
      content.replaceChildren(errorState(err));
    }
  }

  function buildTaskDetailBody(id, config, info, closeModal) {
    const wrapper = document.createElement('div');
    wrapper.append(
      detailRow('Name', config.Name || '—'),
      detailRow('Namespace', config.NameSpace || '—'),
      detailRow('Task class', config.TaskClass || '—'),
      detailRow('Description', config.Description || '—'),
      detailRow('Run as', config.RunAsUser || '—'),
      detailRow('Priority', config.Priority || '—'),
      detailRow('Schedule', describeSchedule(config)),
      detailRow('Status', info.Status || '—'),
      detailRow('Suspended', info.Suspended ? 'Yes' : 'No'),
      detailRow('Last started', info.LastStarted || 'Never'),
      detailRow('Last finished', info.LastFinished || 'Never'),
      detailRow('Next scheduled', info.NextScheduled || '—')
    );
    if (info.Error) {
      const errRow = detailRow('Last error', info.Error);
      errRow.querySelector('.identity-row__value').classList.add('text-error');
      wrapper.appendChild(errRow);
    }

    const actions = document.createElement('div');
    actions.className = 'confirm-dialog__actions';

    actions.appendChild(
      actionButton('Run now', 'button--ghost', async () => {
        const ok = await performAction({
          title: 'Run task now',
          message: `Run "${config.Name}" now, outside its normal schedule?`,
          request: { method: 'POST', path: `v2/task/run?id=${id}`, body: { RunNow: true } },
          execute: () => taskApi.runTask(id, { runNow: true }),
          activityLabel: `Run task ${config.Name}`,
        });
        if (ok) {
          closeModal();
          delete tableCache.tasks;
          delete tableCache.history;
          if (activeTab !== 'tasks') switchTab('tasks');
          else renderTab();
        }
      })
    );

    if (!info.Suspended) {
      actions.appendChild(
        actionButton('Suspend', 'button--ghost', async () => {
          const ok = await performAction({
            title: 'Suspend task',
            message: `Suspend "${config.Name}"? It will not run again until resumed.`,
            request: { method: 'POST', path: `v2/task/suspend?id=${id}`, body: {} },
            execute: () => taskApi.suspendTask(id),
            activityLabel: `Suspend task ${config.Name}`,
          });
          if (ok) {
            closeModal();
            delete tableCache.tasks;
            switchTab('tasks');
          }
        })
      );
    } else {
      actions.appendChild(
        actionButton('Resume', 'button--primary', async () => {
          const ok = await performAction({
            title: 'Resume task',
            message: `Resume "${config.Name}"?`,
            request: { method: 'POST', path: `v2/task/resume?id=${id}`, body: {} },
            execute: () => taskApi.resumeTask(id),
            activityLabel: `Resume task ${config.Name}`,
          });
          if (ok) {
            closeModal();
            delete tableCache.tasks;
            switchTab('tasks');
          }
        })
      );
    }

    actions.appendChild(
      actionButton('Delete', 'button--danger', async () => {
        const ok = await performAction({
          title: 'Delete task',
          message: `Delete "${config.Name}" permanently? This cannot be undone.`,
          danger: true,
          confirmLabel: 'Delete',
          request: { method: 'DELETE', path: `v2/task?id=${id}` },
          execute: () => taskApi.deleteTask(id),
          activityLabel: `Delete task ${config.Name}`,
        });
        if (ok) {
          closeModal();
          delete tableCache.tasks;
          delete tableCache.upcoming;
          switchTab('tasks');
        }
      })
    );

    wrapper.appendChild(actions);

    const rawDetails = document.createElement('details');
    rawDetails.className = 'metric-card__raw';
    const summary = document.createElement('summary');
    summary.textContent = 'View raw task data';
    rawDetails.append(summary, createJsonViewer({ config, info }));
    wrapper.appendChild(rawDetails);

    return wrapper;
  }

  loadManager();
  switchTab('tasks');
}

export function destroy() {
  destroyed = true;
}

function describeSchedule(config) {
  if (config.TimePeriod) {
    return `${config.TimePeriod}${config.TimePeriodEvery > 1 ? ` (every ${config.TimePeriodEvery})` : ''}`;
  }
  if (config.DailyFrequency) {
    return `Daily — ${config.DailyFrequency}${config.DailyFrequencyTime ? ` at ${config.DailyFrequencyTime}` : ''}`;
  }
  return '—';
}
