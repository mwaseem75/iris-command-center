// Wallets — collections (full CRUD) and secrets (name/type metadata only;
// values are write-only everywhere in this API, and this page never asks the
// server for one). See js/api/wallet-api.js for the security note on why the
// confirm-dialog preview and activity log show a redacted request for secret
// writes rather than the real WalletSecretConfig.

import { hasPrivilege } from '../state.js';
import { createDataTable } from '../components/data-table.js';
import { createStatusBadge } from '../components/status-badge.js';
import { openModal } from '../components/modal.js';
import { createForm } from '../utils/form-builder.js';
import { performAction } from '../utils/perform-action.js';
import { showToast } from '../components/toast.js';
import { detailRow, actionButton, loadingRow, errorState, emptyCard } from '../utils/dom-helpers.js';
import * as walletApi from '../api/wallet-api.js';

let destroyed = false;

const SECRET_TYPES = ['%Wallet.KeyValue', '%Wallet.SymmetricKey', '%Wallet.RSA'];

export function render(container) {
  destroyed = false;
  container.replaceChildren();
  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Wallets';
  container.appendChild(heading);

  if (!hasPrivilege('Wallet')) {
    container.appendChild(
      emptyCard('Insufficient privilege', 'Wallet management requires the %Admin_Wallet privilege, which your account does not currently hold.')
    );
    return;
  }

  const notice = document.createElement('div');
  notice.className = 'health-banner health-banner--warning';
  notice.textContent = 'Secret values are write-only. This API has no endpoint that returns a stored value, and this page never displays or logs one — only secret names and types are ever shown.';
  container.appendChild(notice);

  const toolbar = document.createElement('div');
  toolbar.className = 'dashboard-controls';
  const refreshButton = actionButton('Refresh', 'button--ghost', load);
  const createButton = actionButton('New Collection', 'button--primary', () => openCollectionForm(null));
  toolbar.append(refreshButton, createButton);

  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';
  container.append(toolbar, statusArea, tableContainer);

  let table = null;

  async function load() {
    statusArea.replaceChildren(loadingRow('Loading wallet collections…'));
    tableContainer.hidden = true;
    try {
      const rows = (await walletApi.listWalletCollections({ maxRows: 500 })) || [];
      if (destroyed) return;
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      if (table) {
        table.setRows(rows);
      } else {
        table = createDataTable({
          columns: [
            { key: 'Name', label: 'Collection' },
            { key: 'EditResource', label: 'Edit resource' },
            { key: 'UseResource', label: 'Use resource' },
          ],
          rows,
          searchFields: ['Name'],
          pageSize: 12,
          emptyMessage: 'No wallet collections found.',
          onRowClick: (row) => openCollectionDetail(row.Name),
        });
        tableContainer.replaceChildren(table.element);
      }
    } catch (err) {
      if (destroyed) return;
      statusArea.replaceChildren(errorState(err, load));
      tableContainer.hidden = true;
    }
  }

  async function openCollectionDetail(name) {
    const content = document.createElement('div');
    content.className = 'loading-text';
    content.innerHTML = '<span class="spinner"></span> Loading collection…';
    const modal = openModal({ title: `Wallet: ${name}`, content, size: 'lg' });

    try {
      const [detail, secrets] = await Promise.all([walletApi.getWalletCollection(name), walletApi.listWalletSecrets(name, { maxRows: 200 })]);
      if (destroyed) return;
      content.replaceChildren(buildCollectionBody(name, detail, secrets || [], modal, () => openCollectionDetail(name)));
    } catch (err) {
      content.replaceChildren(errorState(err));
    }
  }

  function buildCollectionBody(name, detail, secrets, modal, refreshThisModal) {
    const wrapper = document.createElement('div');
    wrapper.append(
      detailRow('Edit resource', detail.EditResource || '—'),
      detailRow('Use resource', detail.UseResource || '—')
    );

    const secretsTitle = document.createElement('h3');
    secretsTitle.className = 'identity-card__subtitle';
    secretsTitle.textContent = 'Secrets (names and types only — values are never shown)';
    wrapper.appendChild(secretsTitle);

    const secretsTable = createDataTable({
      columns: [
        // Secret names are returned as "<collection>.<secret>" (confirmed live —
        // this is also how they must be addressed on create/delete); strip the
        // redundant collection prefix since we're already inside its detail view.
        { key: 'Name', label: 'Name', render: (s) => s.Name.startsWith(`${name}.`) ? s.Name.slice(name.length + 1) : s.Name },
        { key: 'Type', label: 'Type' },
        {
          key: 'actions',
          label: '',
          render: (s) =>
            actionButton('Delete', 'button--danger', async () => {
              const ok = await performAction({
                title: 'Delete secret',
                message: `Delete secret "${s.Name}" from "${name}"? This cannot be undone.`,
                danger: true,
                confirmLabel: 'Delete',
                request: { method: 'DELETE', path: `v2/wallet/secret?name=${encodeURIComponent(s.Name)}` },
                execute: () => walletApi.deleteWalletSecret(s.Name),
                activityLabel: `Delete wallet secret ${s.Name}`,
              });
              if (ok) refreshThisModal();
            }),
        },
      ],
      rows: secrets,
      searchFields: ['Name', 'Type'],
      pageSize: 8,
      emptyMessage: 'No secrets in this collection.',
    });
    wrapper.appendChild(secretsTable.element);

    const actions = document.createElement('div');
    actions.className = 'confirm-dialog__actions';
    actions.append(
      actionButton('New secret', 'button--primary', () => {
        modal.close();
        openSecretForm(name, refreshThisModal);
      }),
      actionButton('Edit collection', 'button--ghost', () => {
        modal.close();
        openCollectionForm(name, detail);
      }),
      actionButton('Delete collection', 'button--danger', async () => {
        const ok = await performAction({
          title: 'Delete wallet collection',
          message: `Delete collection "${name}" and all ${secrets.length} secret(s) in it? This cannot be undone.`,
          danger: true,
          confirmLabel: 'Delete',
          request: { method: 'DELETE', path: `v2/wallet/collection?name=${encodeURIComponent(name)}` },
          execute: () => walletApi.deleteWalletCollection(name),
          activityLabel: `Delete wallet collection ${name}`,
        });
        if (ok) {
          modal.close();
          load();
        }
      })
    );
    wrapper.appendChild(actions);
    return wrapper;
  }

  function openCollectionForm(name, detail = {}) {
    const isCreate = name === null;
    const form = createForm(
      [
        { key: 'EditResource', label: 'Edit resource', type: 'text', help: 'Security resource required to edit this collection.' },
        { key: 'UseResource', label: 'Use resource', type: 'text', help: 'Security resource required to use secrets in this collection.' },
      ],
      detail
    );
    const content = document.createElement('div');
    const nameField = isCreate ? buildNameField('Collection name') : null;
    if (nameField) content.appendChild(nameField.element);
    content.appendChild(form.element);
    const submitRow = document.createElement('div');
    submitRow.className = 'confirm-dialog__actions';
    submitRow.appendChild(
      actionButton(isCreate ? 'Create' : 'Save changes', 'button--primary', async () => {
        const targetName = isCreate ? nameField.input.value.trim() : name;
        if (!targetName) return;
        const body = form.getValues();
        modal.close();
        const ok = await performAction({
          title: isCreate ? 'Create wallet collection' : 'Save collection',
          message: isCreate ? `Create wallet collection "${targetName}"?` : `Save changes to "${targetName}"?`,
          request: { method: 'PUT', path: `v2/wallet/collection?name=${encodeURIComponent(targetName)}`, body },
          execute: () => walletApi.saveWalletCollection(targetName, body),
          activityLabel: `${isCreate ? 'Create' : 'Update'} wallet collection ${targetName}`,
        });
        if (ok) load();
      })
    );
    content.appendChild(submitRow);
    const modal = openModal({ title: isCreate ? 'New wallet collection' : `Edit collection: ${name}`, content, size: 'md' });
  }

  function openSecretForm(collectionName, onSaved) {
    const content = document.createElement('div');

    const nameField = buildNameField('Secret name');
    const typeField = document.createElement('div');
    typeField.className = 'form-field';
    const typeLabel = document.createElement('label');
    typeLabel.textContent = 'Secret type';
    const typeSelect = document.createElement('select');
    typeSelect.className = 'text-input';
    for (const t of SECRET_TYPES) {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      typeSelect.appendChild(opt);
    }
    typeField.append(typeLabel, typeSelect);

    const keyField = buildTextField('Key', 'e.g. username, api_key');
    const valueField = buildTextField('Value', '', 'password');

    const help = document.createElement('p');
    help.className = 'form-field__help';
    help.textContent = 'Stored as { Secret: { <key>: <value> } }. This value is sent directly to IRIS and is never shown again by this app.';

    content.append(nameField.element, typeField, keyField.element, valueField.element, help);

    const submitRow = document.createElement('div');
    submitRow.className = 'confirm-dialog__actions';
    submitRow.appendChild(
      actionButton('Save secret', 'button--primary', async () => {
        const localName = nameField.input.value.trim();
        const key = keyField.input.value.trim();
        const value = valueField.input.value;
        if (!localName || !key || !value) {
          showToast({ message: 'Name, key, and value are all required.', variant: 'info' });
          return;
        }
        // Confirmed live: a secret's identity is "<collection>.<secret>" — the
        // API has no separate "collection" field on this endpoint.
        const fullName = `${collectionName}.${localName}`;
        const realBody = { Type: typeSelect.value, WalletSecretConfig: { Secret: { [key]: value } } };
        modal.close();

        // Security: the confirm-dialog preview and the activity log both echo
        // the `request` object verbatim, so a redacted body is what's shown/
        // recorded — the real value only ever reaches execute()'s closure.
        const redactedRequest = {
          method: 'PUT',
          path: `v2/wallet/secret?name=${encodeURIComponent(fullName)}`,
          body: { Type: typeSelect.value, WalletSecretConfig: '[hidden — secret values are never displayed or logged]' },
        };
        const ok = await performAction({
          title: 'Save secret',
          message: `Save secret "${localName}" in "${collectionName}"? The value will be sent to IRIS and cannot be viewed again afterward.`,
          request: redactedRequest,
          execute: () => walletApi.saveWalletSecret(fullName, realBody),
          activityLabel: `Save wallet secret ${fullName}`,
        });
        if (ok) onSaved();
      })
    );
    content.appendChild(submitRow);

    const modal = openModal({ title: 'New secret', content, size: 'md' });
    nameField.input.focus();
  }

  refreshButton.addEventListener('click', load);
  load();
}

export function destroy() {
  destroyed = true;
}

function buildNameField(label) {
  const wrapper = document.createElement('div');
  wrapper.className = 'form-field';
  const labelEl = document.createElement('label');
  labelEl.textContent = label;
  const input = document.createElement('input');
  input.className = 'text-input';
  input.required = true;
  wrapper.append(labelEl, input);
  return { element: wrapper, input };
}

function buildTextField(label, help, type = 'text') {
  const wrapper = document.createElement('div');
  wrapper.className = 'form-field';
  const labelEl = document.createElement('label');
  labelEl.textContent = label;
  const input = document.createElement('input');
  input.className = 'text-input';
  input.type = type;
  if (type === 'password') input.autocomplete = 'new-password';
  wrapper.append(labelEl, input);
  if (help) {
    const helpEl = document.createElement('p');
    helpEl.className = 'form-field__help';
    helpEl.textContent = help;
    wrapper.appendChild(helpEl);
  }
  return { element: wrapper, input };
}
