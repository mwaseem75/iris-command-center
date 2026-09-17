// Security — Users, Roles, Resources, Services, Audit, SQL Privileges,
// Encryption. All %Admin_Secure. X.509 credentials and OAuth2 are deferred —
// see docs/api-matrix.md sections 9 and 12.

import { hasPrivilege } from '../state.js';
import { renderCrudSection } from '../utils/crud-section.js';
import { createForm } from '../utils/form-builder.js';
import { createDataTable } from '../components/data-table.js';
import { createStatusBadge } from '../components/status-badge.js';
import { openModal } from '../components/modal.js';
import { createJsonViewer } from '../components/json-viewer.js';
import { confirmAction } from '../components/confirm-dialog.js';
import { performAction } from '../utils/perform-action.js';
import { promptForValue, promptForValues } from '../utils/prompt.js';
import { showToast } from '../components/toast.js';
import { detailRow, actionButton, loadingRow, errorState, emptyCard } from '../utils/dom-helpers.js';
import * as securityApi from '../api/security-api.js';

let activeSection = null;
let destroyed = false;

const TABS = [
  { key: 'users', label: 'Users' },
  { key: 'roles', label: 'Roles' },
  { key: 'resources', label: 'Resources' },
  { key: 'services', label: 'Services' },
  { key: 'audit', label: 'Audit' },
  { key: 'sql', label: 'SQL Privileges' },
  { key: 'encryption', label: 'Encryption' },
];

export function render(container) {
  destroyed = false;
  container.replaceChildren();
  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Security';
  container.appendChild(heading);

  if (!hasPrivilege('Secure')) {
    container.appendChild(
      emptyCard('Insufficient privilege', 'Security administration requires the %Admin_Secure privilege, which your account does not currently hold.')
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

    if (key === 'users') renderUsers(contentArea);
    else if (key === 'roles') renderRoles(contentArea);
    else if (key === 'resources') renderResources(contentArea);
    else if (key === 'services') renderServices(contentArea);
    else if (key === 'audit') renderAudit(contentArea);
    else if (key === 'sql') renderSqlPrivileges(contentArea);
    else if (key === 'encryption') renderEncryption(contentArea);
  }

  switchTab('users');
}

export function destroy() {
  destroyed = true;
  activeSection?.destroy?.();
  activeSection = null;
}

// ---------- Users ----------

function renderUsers(container) {
  activeSection = renderCrudSection(container, {
    resourceLabel: 'User',
    idField: 'Name',
    columns: [
      { key: 'Name', label: 'Name' },
      { key: 'FullName', label: 'Full name' },
      { key: 'Type', label: 'Type' },
      { key: 'Enabled', label: 'Enabled', render: (r) => createStatusBadge(r.Enabled ? 'Enabled' : 'Disabled', r.Enabled ? 'success' : 'warning') },
    ],
    searchFields: ['Name', 'FullName'],
    list: () => securityApi.listUsers({ maxRows: 500 }),
    get: (name) => securityApi.getUser(name),
    save: (id, body, isCreate) => {
      const { Password, Roles, ...rest } = body;
      const userBody = { ...rest, Roles: typeof Roles === 'string' ? Roles.split(',').map((s) => s.trim()).filter(Boolean) : Roles };
      if (isCreate) return securityApi.createUser(id, userBody, Password);
      return securityApi.updateUser(id, userBody);
    },
    remove: (name) => securityApi.deleteUser(name),
    formFields: [
      { key: 'FullName', label: 'Full name', type: 'text' },
      { key: 'Password', label: 'Password', type: 'password', excludeFromDetail: true, help: 'Required when creating a user. Leave blank when editing to keep the current password — use "Change password" for that instead.' },
      { key: 'Enabled', label: 'Login enabled', type: 'checkbox' },
      { key: 'Comment', label: 'Comment', type: 'text' },
      { key: 'EmailAddress', label: 'Email address', type: 'text' },
      { key: 'Roles', label: 'Roles (comma-separated)', type: 'text', help: 'e.g. %Operator, %SQL' },
      { key: 'ChangePassword', label: 'Require password change at next login', type: 'checkbox' },
      { key: 'PasswordNeverExpires', label: 'Password never expires', type: 'checkbox' },
      { key: 'AccountNeverExpires', label: 'Account never expires', type: 'checkbox' },
    ],
    pathFor: (id) => `v2/security/user?name=${encodeURIComponent(id)}`,
    deleteWarning: () => 'Delete this user permanently? This cannot be undone.',
  });
}

// ---------- Roles (custom — Resources are read-only, GrantedRoles is a comma list) ----------

function renderRoles(container) {
  container.replaceChildren();
  const toolbar = document.createElement('div');
  toolbar.className = 'dashboard-controls';
  const refreshButton = actionButton('Refresh', 'button--ghost', load);
  const createButton = actionButton('New Role', 'button--primary', () => openRoleForm(null));
  toolbar.append(refreshButton, createButton);

  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  container.append(toolbar, statusArea, tableContainer);

  let table = null;
  let localDestroyed = false;

  async function load() {
    statusArea.replaceChildren(loadingRow('Loading roles…'));
    tableContainer.hidden = true;
    try {
      const rows = (await securityApi.listRoles({ maxRows: 500 })) || [];
      if (localDestroyed) return;
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      if (table) {
        table.setRows(rows);
      } else {
        table = createDataTable({
          columns: [
            { key: 'Name', label: 'Name' },
            { key: 'Description', label: 'Description' },
            { key: 'EscalationOnly', label: 'Escalation only', render: (r) => (r.EscalationOnly ? 'Yes' : 'No') },
          ],
          rows,
          searchFields: ['Name', 'Description'],
          pageSize: 12,
          emptyMessage: 'No roles found.',
          onRowClick: (row) => openRoleDetail(row.Name),
        });
        tableContainer.replaceChildren(table.element);
      }
    } catch (err) {
      if (localDestroyed) return;
      statusArea.replaceChildren(errorState(err, load));
      tableContainer.hidden = true;
    }
  }

  async function openRoleDetail(name) {
    const content = document.createElement('div');
    content.className = 'loading-text';
    content.innerHTML = '<span class="spinner"></span> Loading role…';
    const modal = openModal({ title: `Role: ${name}`, content, size: 'md' });
    try {
      const [detail, owners] = await Promise.all([securityApi.getRole(name), securityApi.getRoleOwners(name).catch(() => [])]);
      if (localDestroyed) return;
      const wrapper = document.createElement('div');
      wrapper.append(
        detailRow('Description', detail.Description || '—'),
        detailRow('Escalation only', detail.EscalationOnly ? 'Yes' : 'No'),
        detailRow('Granted roles', (detail.GrantedRoles || []).join(', ') || '—'),
        detailRow('Held by', (owners || []).map((o) => o.Name).join(', ') || '—')
      );

      if ((detail.Resources || []).length > 0) {
        const title = document.createElement('h3');
        title.className = 'identity-card__subtitle';
        title.textContent = 'Resource permissions';
        wrapper.appendChild(title);
        for (const res of detail.Resources) {
          wrapper.appendChild(detailRow(res.Name, res.Permissions || '—'));
        }
      }

      const actions = document.createElement('div');
      actions.className = 'confirm-dialog__actions';
      actions.append(
        actionButton('Edit', 'button--ghost', () => {
          modal.close();
          openRoleForm(name, detail);
        }),
        actionButton('Delete', 'button--danger', async () => {
          const ok = await performAction({
            title: 'Delete role',
            message: `Delete role "${name}" permanently? Any users or roles that hold it will lose the privileges it grants.`,
            danger: true,
            confirmLabel: 'Delete',
            request: { method: 'DELETE', path: `v2/security/role?name=${encodeURIComponent(name)}` },
            execute: () => securityApi.deleteRole(name),
            activityLabel: `Delete role ${name}`,
          });
          if (ok) {
            modal.close();
            load();
          }
        })
      );
      wrapper.appendChild(actions);
      content.replaceChildren(wrapper);
    } catch (err) {
      content.replaceChildren(errorState(err));
    }
  }

  function openRoleForm(name, detail = {}) {
    const isCreate = name === null;
    const form = createForm(
      [
        { key: 'Description', label: 'Description', type: 'text' },
        { key: 'EscalationOnly', label: 'Escalation only', type: 'checkbox' },
        { key: 'GrantedRolesText', label: 'Granted roles (comma-separated)', type: 'text' },
      ],
      { ...detail, GrantedRolesText: (detail.GrantedRoles || []).join(', ') }
    );
    const content = document.createElement('div');
    const nameField = isCreate ? buildNameField('Role name') : null;
    if (nameField) content.appendChild(nameField.element);
    content.appendChild(form.element);
    const submitRow = document.createElement('div');
    submitRow.className = 'confirm-dialog__actions';
    const submitButton = actionButton(isCreate ? 'Create' : 'Save changes', 'button--primary', async () => {
      const targetName = isCreate ? nameField.input.value.trim() : name;
      if (!targetName) return;
      const values = form.getValues();
      const body = {
        Description: values.Description,
        EscalationOnly: values.EscalationOnly,
        GrantedRoles: values.GrantedRolesText ? values.GrantedRolesText.split(',').map((s) => s.trim()).filter(Boolean) : [],
      };
      modal.close();
      const ok = await performAction({
        title: isCreate ? 'Create role' : 'Save role',
        message: isCreate ? `Create role "${targetName}"?` : `Save changes to role "${targetName}"?`,
        request: { method: 'PUT', path: `v2/security/role?name=${encodeURIComponent(targetName)}`, body },
        execute: () => securityApi.saveRole(targetName, body),
        activityLabel: `${isCreate ? 'Create' : 'Update'} role ${targetName}`,
      });
      if (ok) load();
    });
    submitRow.appendChild(submitButton);
    content.appendChild(submitRow);
    const modal = openModal({ title: isCreate ? 'New role' : `Edit role: ${name}`, content, size: 'md' });
  }

  activeSection = {
    destroy() {
      localDestroyed = true;
    },
  };
  load();
}

// ---------- Resources ----------

function renderResources(container) {
  activeSection = renderCrudSection(container, {
    resourceLabel: 'Resource',
    idField: 'Name',
    columns: [
      { key: 'Name', label: 'Name' },
      { key: 'Description', label: 'Description' },
      { key: 'ResourceType', label: 'Type' },
      { key: 'PublicPermission', label: 'Public permission' },
    ],
    searchFields: ['Name', 'Description'],
    list: () => securityApi.listResources({ maxRows: 500 }),
    get: (name) => securityApi.getResource(name),
    save: (id, body) => securityApi.saveResource(id, body),
    remove: (name) => securityApi.deleteResource(name),
    formFields: [
      { key: 'Description', label: 'Description', type: 'text', required: true },
      { key: 'PublicPermission', label: 'Public permission (R, W, U combination)', type: 'text', help: 'e.g. "R", "RW", or blank for none' },
    ],
    pathFor: (id) => `v2/security/resource?name=${encodeURIComponent(id)}`,
    canDelete: true,
  });
}

// ---------- Services (list + edit only, no create/delete — system-defined) ----------

function renderServices(container) {
  container.replaceChildren();
  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  container.append(statusArea, tableContainer);
  let localDestroyed = false;

  function load() {
    statusArea.replaceChildren(loadingRow('Loading services…'));
    tableContainer.hidden = true;
    securityApi
      .listServices({ maxRows: 200 })
      .then((rows) => {
        if (localDestroyed) return;
        statusArea.replaceChildren();
        tableContainer.hidden = false;
        const table = createDataTable({
          columns: [
            { key: 'Name', label: 'Name' },
            { key: 'Enabled', label: 'Status', render: (r) => createStatusBadge(r.Enabled ? 'Enabled' : 'Disabled', r.Enabled ? 'success' : 'warning') },
            { key: 'Description', label: 'Description' },
            { key: 'AuthenticationMethods', label: 'Auth methods', render: (r) => (r.AuthenticationMethods || []).join(', ') || '—' },
          ],
          rows: rows || [],
          searchFields: ['Name', 'Description'],
          pageSize: 15,
          emptyMessage: 'No services found.',
          onRowClick: (row) => openServiceDetail(row.Name),
        });
        tableContainer.replaceChildren(table.element);
      })
      .catch((err) => {
        if (localDestroyed) return;
        statusArea.replaceChildren(errorState(err, load));
        tableContainer.hidden = true;
      });
  }

  async function openServiceDetail(name) {
    const content = document.createElement('div');
    content.className = 'loading-text';
    content.innerHTML = '<span class="spinner"></span> Loading service…';
    const modal = openModal({ title: `Service: ${name}`, content, size: 'md' });
    try {
      const detail = await securityApi.getService(name);
      if (localDestroyed) return;
      const form = createForm(
        [
          { key: 'Enabled', label: 'Enabled', type: 'checkbox' },
          { key: 'Description', label: 'Description', type: 'text' },
          { key: 'ClientSystems', label: 'Allowed client systems (comma-separated IPs/hosts, blank = all)', type: 'text' },
        ],
        { ...detail, ClientSystems: Array.isArray(detail.ClientSystems) ? detail.ClientSystems.join(', ') : detail.ClientSystems }
      );
      const wrapper = document.createElement('div');
      wrapper.appendChild(form.element);
      const submitRow = document.createElement('div');
      submitRow.className = 'confirm-dialog__actions';
      submitRow.appendChild(
        actionButton('Save changes', 'button--primary', async () => {
          const values = form.getValues();
          const body = {
            Enabled: values.Enabled,
            Description: values.Description,
            ClientSystems: values.ClientSystems ? values.ClientSystems.split(',').map((s) => s.trim()).filter(Boolean) : [],
          };
          modal.close();
          const ok = await performAction({
            title: 'Save service settings',
            message: `Save changes to "${name}"? Disabling a service in use can immediately break client connections.`,
            danger: !values.Enabled && detail.Enabled,
            request: { method: 'PUT', path: `v2/security/service?name=${encodeURIComponent(name)}`, body },
            execute: () => securityApi.saveService(name, body),
            activityLabel: `Update service ${name}`,
          });
          if (ok) load();
        })
      );
      wrapper.appendChild(submitRow);
      content.replaceChildren(wrapper);
    } catch (err) {
      content.replaceChildren(errorState(err));
    }
  }

  activeSection = {
    destroy() {
      localDestroyed = true;
    },
  };
  load();
}

// ---------- Audit ----------

function renderAudit(container) {
  container.replaceChildren();
  let localDestroyed = false;

  const enabledCard = document.createElement('div');
  enabledCard.className = 'card task-manager-row';
  const filterCard = document.createElement('div');
  filterCard.className = 'card';
  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  tableContainer.hidden = true;
  container.append(enabledCard, filterCard, statusArea, tableContainer);

  function loadEnabled() {
    enabledCard.replaceChildren(loadingRow('Loading audit status…'));
    securityApi
      .getAuditEnabled()
      .then((res) => {
        if (localDestroyed) return;
        const title = document.createElement('h3');
        title.className = 'metric-card__title';
        title.textContent = 'Auditing';
        const badge = createStatusBadge(res.Enabled ? 'Enabled' : 'Disabled', res.Enabled ? 'success' : 'warning');
        const toggleButton = actionButton(res.Enabled ? 'Disable auditing' : 'Enable auditing', res.Enabled ? 'button--danger' : 'button--primary', async () => {
          const ok = await performAction({
            title: res.Enabled ? 'Disable auditing' : 'Enable auditing',
            message: res.Enabled
              ? 'Disable auditing system-wide? No new audit events will be recorded until re-enabled.'
              : 'Enable auditing system-wide?',
            danger: res.Enabled,
            request: { method: 'PUT', path: 'v2/security/audit/enabled', body: { Enabled: !res.Enabled } },
            execute: () => securityApi.setAuditEnabled(!res.Enabled),
            activityLabel: res.Enabled ? 'Disable auditing' : 'Enable auditing',
          });
          if (ok) loadEnabled();
        });
        enabledCard.replaceChildren(title, badge, toggleButton);
      })
      .catch((err) => {
        if (localDestroyed) return;
        enabledCard.replaceChildren(errorState(err, loadEnabled));
      });
  }

  const filterForm = createForm([
    { key: 'usernames', label: 'Username(s)', type: 'text' },
    { key: 'eventSources', label: 'Event source(s)', type: 'text' },
    { key: 'beginDateTime', label: 'From ($ZDATETIME, blank = beginning)', type: 'text', help: 'e.g. 2026-09-01 00:00:00' },
    { key: 'endDateTime', label: 'To (blank = now)', type: 'text' },
  ]);
  filterCard.appendChild(filterForm.element);
  const filterActions = document.createElement('div');
  filterActions.className = 'confirm-dialog__actions';
  const searchButton = actionButton('Search', 'button--primary', () => searchRecords());
  const purgeButton = actionButton('Purge old records', 'button--danger', () => purgeRecords());
  const copyButton = actionButton('Copy to namespace…', 'button--ghost', () => copyRecords());
  filterActions.append(searchButton, purgeButton, copyButton);
  filterCard.appendChild(filterActions);

  async function searchRecords() {
    const values = filterForm.getValues();
    statusArea.replaceChildren(loadingRow('Searching audit records… this can take a few seconds.'));
    tableContainer.hidden = true;
    try {
      const records = (await securityApi.listAuditRecords({ ...values, maxRows: 200 })) || [];
      if (localDestroyed) return;
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      const table = createDataTable({
        columns: [
          { key: 'TimeStamp', label: 'Time' },
          { key: 'Event', label: 'Event' },
          { key: 'EventSource', label: 'Source' },
          { key: 'Username', label: 'User' },
          { key: 'Description', label: 'Description' },
        ],
        rows: records,
        searchFields: ['Event', 'EventSource', 'Username', 'Description'],
        pageSize: 12,
        emptyMessage: 'No audit records match this filter.',
        onRowClick: (row) => openRecordDetail(row),
      });
      tableContainer.replaceChildren(table.element);
    } catch (err) {
      if (localDestroyed) return;
      statusArea.replaceChildren(errorState(err, searchRecords));
    }
  }

  function openRecordDetail(row) {
    const content = document.createElement('div');
    content.append(createJsonViewer(row));
    openModal({ title: `Audit event: ${row.Event}`, content, size: 'lg' });
  }

  async function purgeRecords() {
    const values = filterForm.getValues();
    const ok = await performAction({
      title: 'Purge audit records',
      message: values.beginDateTime || values.endDateTime
        ? `Permanently delete audit records between "${values.beginDateTime || 'the beginning'}" and "${values.endDateTime || 'now'}"? This cannot be undone.`
        : 'Permanently delete ALL audit records with no date filter applied? This cannot be undone and removes the entire audit history.',
      danger: true,
      confirmLabel: 'Purge',
      request: { method: 'POST', path: 'v2/security/audit/record/purge', body: { BeginDateTime: values.beginDateTime, EndDateTime: values.endDateTime } },
      execute: () => securityApi.purgeAuditRecords({ BeginDateTime: values.beginDateTime, EndDateTime: values.endDateTime }),
      activityLabel: 'Purge audit records',
    });
    if (ok) searchRecords();
  }

  async function copyRecords() {
    const targetNs = await promptForValue({ title: 'Copy audit records', label: 'Target namespace' });
    if (!targetNs) return;
    const values = filterForm.getValues();
    await performAction({
      title: 'Copy audit records',
      message: `Copy matching audit records to namespace "${targetNs}"?`,
      request: {
        method: 'POST',
        path: 'v2/security/audit/record/copy',
        body: { AuditCopyNamespace: targetNs, BeginDateTime: values.beginDateTime, EndDateTime: values.endDateTime },
      },
      execute: () => securityApi.copyAuditRecords({ AuditCopyNamespace: targetNs, BeginDateTime: values.beginDateTime, EndDateTime: values.endDateTime }),
      activityLabel: `Copy audit records to ${targetNs}`,
    });
  }

  activeSection = {
    destroy() {
      localDestroyed = true;
    },
  };
  loadEnabled();
}

// ---------- SQL Privileges ----------

function renderSqlPrivileges(container) {
  container.replaceChildren();
  let localDestroyed = false;

  const filterCard = document.createElement('div');
  filterCard.className = 'card';
  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  tableContainer.hidden = true;
  container.append(filterCard, statusArea, tableContainer);

  const filterForm = createForm([
    { key: 'grantee', label: 'Grantee (user or role)', type: 'text', required: true },
    { key: 'namespace', label: 'Namespace', type: 'text', required: true },
  ]);
  filterCard.appendChild(filterForm.element);
  const searchRow = document.createElement('div');
  searchRow.className = 'confirm-dialog__actions';
  searchRow.appendChild(actionButton('Search', 'button--primary', search));
  filterCard.appendChild(searchRow);

  async function search() {
    const { grantee, namespace } = filterForm.getValues();
    if (!grantee || !namespace) {
      showToast({ message: 'Grantee and namespace are both required.', variant: 'info' });
      return;
    }
    statusArea.replaceChildren(loadingRow('Loading privileges…'));
    tableContainer.hidden = true;
    try {
      const [tablePrivs, adminPrivs] = await Promise.all([
        securityApi.listSqlPrivileges({ grantee, namespace }).catch(() => []),
        securityApi.listSqlAdminPrivileges({ grantee, namespace }).catch(() => []),
      ]);
      if (localDestroyed) return;
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      const wrapper = document.createElement('div');

      const tableTitle = document.createElement('h3');
      tableTitle.className = 'identity-card__subtitle';
      tableTitle.textContent = 'Table/object privileges';
      wrapper.appendChild(tableTitle);
      const table1 = createDataTable({
        columns: [
          { key: 'Type', label: 'Type' },
          { key: 'Name', label: 'Object' },
          { key: 'Privilege', label: 'Privilege' },
          { key: 'GrantedBy', label: 'Granted by' },
          {
            key: 'actions',
            label: '',
            render: (r) =>
              actionButton('Revoke', 'button--danger', () =>
                revoke({ namespace, grantee, type: r.Type, object: r.Name, action: r.Privilege })
              ),
          },
        ],
        rows: tablePrivs || [],
        searchFields: ['Name', 'Privilege'],
        pageSize: 10,
        emptyMessage: 'No table privileges found for this grantee/namespace.',
      });
      wrapper.appendChild(table1.element);

      const grantRow = document.createElement('div');
      grantRow.className = 'confirm-dialog__actions';
      grantRow.appendChild(actionButton('Grant table privilege…', 'button--ghost', () => grantTablePrivilege(grantee, namespace)));
      wrapper.appendChild(grantRow);

      const adminTitle = document.createElement('h3');
      adminTitle.className = 'identity-card__subtitle';
      adminTitle.textContent = 'SQL admin privileges';
      wrapper.appendChild(adminTitle);
      const table2 = createDataTable({
        columns: [
          { key: 'Privilege', label: 'Privilege' },
          { key: 'GrantedVia', label: 'Granted via' },
          {
            key: 'actions',
            label: '',
            render: (r) => actionButton('Revoke', 'button--danger', () => revokeAdmin({ privilege: r.Privilege, grantee, namespace })),
          },
        ],
        rows: adminPrivs || [],
        searchFields: ['Privilege'],
        pageSize: 10,
        emptyMessage: 'No SQL admin privileges found for this grantee/namespace.',
      });
      wrapper.appendChild(table2.element);

      const grantAdminRow = document.createElement('div');
      grantAdminRow.className = 'confirm-dialog__actions';
      grantAdminRow.appendChild(actionButton('Grant admin privilege…', 'button--ghost', () => grantAdminPrivilege(grantee, namespace)));
      wrapper.appendChild(grantAdminRow);

      tableContainer.replaceChildren(wrapper);
    } catch (err) {
      if (localDestroyed) return;
      statusArea.replaceChildren(errorState(err, search));
    }
  }

  async function revoke(params) {
    const ok = await performAction({
      title: 'Revoke SQL privilege',
      message: `Revoke ${params.action} on "${params.object}" from ${params.grantee}?`,
      danger: true,
      confirmLabel: 'Revoke',
      request: { method: 'POST', path: 'v2/security/sql-privilege/revoke', body: params },
      execute: () => securityApi.revokeSqlPrivilege(params),
      activityLabel: `Revoke SQL privilege ${params.action} on ${params.object}`,
    });
    if (ok) search();
  }

  async function revokeAdmin(params) {
    const ok = await performAction({
      title: 'Revoke SQL admin privilege',
      message: `Revoke "${params.privilege}" from ${params.grantee}?`,
      danger: true,
      confirmLabel: 'Revoke',
      request: { method: 'POST', path: 'v2/security/sql-admin-privilege/revoke', body: params },
      execute: () => securityApi.revokeSqlAdminPrivilege(params),
      activityLabel: `Revoke SQL admin privilege ${params.privilege}`,
    });
    if (ok) search();
  }

  async function grantTablePrivilege(grantee, namespace) {
    const values = await promptForValues({
      title: 'Grant table privilege',
      fields: [
        { key: 'object', label: 'Table/object (schema.table)', type: 'text', required: true },
        { key: 'action', label: 'Privilege (SELECT, INSERT, UPDATE, DELETE, ...)', type: 'text', required: true },
      ],
    });
    if (!values) return;
    const { object, action } = values;
    const params = { namespace, grantee, type: 'Table', object, action };
    await performAction({
      title: 'Grant SQL privilege',
      message: `Grant ${action} on "${object}" to ${grantee}?`,
      request: { method: 'POST', path: 'v2/security/sql-privilege/grant', body: params },
      execute: () => securityApi.grantSqlPrivilege(params),
      activityLabel: `Grant SQL privilege ${action} on ${object}`,
    });
    search();
  }

  async function grantAdminPrivilege(grantee, namespace) {
    const privilege = await promptForValue({ title: 'Grant SQL admin privilege', label: 'Privilege (e.g. %ALTER_TABLE)' });
    if (!privilege) return;
    const params = { privilege, grantee, namespace };
    await performAction({
      title: 'Grant SQL admin privilege',
      message: `Grant "${privilege}" to ${grantee}?`,
      request: { method: 'POST', path: 'v2/security/sql-admin-privilege/grant', body: params },
      execute: () => securityApi.grantSqlAdminPrivilege(params),
      activityLabel: `Grant SQL admin privilege ${privilege}`,
    });
    search();
  }

  activeSection = {
    destroy() {
      localDestroyed = true;
    },
  };
}

// ---------- Encryption ----------

function renderEncryption(container) {
  container.replaceChildren();
  let localDestroyed = false;
  const settingsCard = document.createElement('div');
  settingsCard.className = 'card';
  const keysCard = document.createElement('div');
  keysCard.className = 'card';
  container.append(settingsCard, keysCard);

  function load() {
    settingsCard.replaceChildren(loadingRow('Loading encryption settings…'));
    keysCard.replaceChildren();
    Promise.all([securityApi.getEncryptionSettings(), securityApi.listEncryptionKeys().catch(() => [])])
      .then(([settings, keys]) => {
        if (localDestroyed) return;
        const form = createForm(
          [
            { key: 'DBEncStartMode', label: 'Startup mode', type: 'select', options: ['None', 'Manual', 'Automatic'] },
            { key: 'DBEncJournal', label: 'Encrypt journal files', type: 'checkbox' },
            { key: 'DBEncIRISSecurity', label: 'Encrypt IRISSECURITY database', type: 'checkbox' },
            { key: 'DBEncIRISTemp', label: 'Encrypt IRISTEMP database', type: 'checkbox' },
            { key: 'AuditEncrypt', label: 'Encrypt audit database', type: 'checkbox' },
          ],
          settings
        );
        settingsCard.replaceChildren(form.element);
        const submitRow = document.createElement('div');
        submitRow.className = 'confirm-dialog__actions';
        submitRow.appendChild(
          actionButton('Save changes', 'button--primary', async () => {
            const body = form.getValues();
            const ok = await performAction({
              title: 'Update encryption settings',
              message: 'Save changes to encryption startup settings? Incorrect settings can prevent the instance from starting.',
              danger: true,
              request: { method: 'PUT', path: 'v2/security/encryption/settings', body },
              execute: () => securityApi.saveEncryptionSettings(body),
              activityLabel: 'Update encryption settings',
            });
            if (ok) load();
          })
        );
        settingsCard.appendChild(submitRow);

        const keysTitle = document.createElement('h3');
        keysTitle.className = 'metric-card__title';
        keysTitle.textContent = 'Activated encryption keys';
        const keysTable = createDataTable({
          columns: [
            { key: 'Id', label: 'Key ID' },
            { key: 'KeyLen', label: 'Key length' },
            { key: 'IsDefault', label: 'Default', render: (r) => (r.IsDefault ? 'Yes' : 'No') },
          ],
          rows: keys || [],
          searchFields: ['Id'],
          pageSize: 10,
          emptyMessage: 'No encryption keys are currently activated.',
        });
        keysCard.replaceChildren(keysTitle, keysTable.element);
      })
      .catch((err) => {
        if (localDestroyed) return;
        settingsCard.replaceChildren(errorState(err, load));
      });
  }

  activeSection = {
    destroy() {
      localDestroyed = true;
    },
  };
  load();
}

function buildNameField(label) {
  const wrapper = document.createElement('div');
  wrapper.className = 'form-field';
  const labelEl = document.createElement('label');
  labelEl.textContent = label;
  labelEl.setAttribute('for', 'entity-id');
  const input = document.createElement('input');
  input.className = 'text-input';
  input.id = 'entity-id';
  input.required = true;
  wrapper.append(labelEl, input);
  return { element: wrapper, input };
}
