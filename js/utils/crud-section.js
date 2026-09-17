// Generic list + detail/edit + create + delete section for simple
// name-keyed resources (Namespace, Device, DeviceSubtype, ...). Not every
// resource fits this shape (Database directories have divergent create/edit
// schemas and extra lifecycle actions, so that page is custom) but it
// removes real duplication across the ones that do.

import { createDataTable } from '../components/data-table.js';
import { openModal } from '../components/modal.js';
import { createForm } from './form-builder.js';
import { performAction } from './perform-action.js';
import { loadingRow, errorState, actionButton, detailRow } from './dom-helpers.js';

/**
 * @param {HTMLElement} container
 * @param {object} config
 * @param {string} config.resourceLabel - e.g. "Namespace"
 * @param {string} config.idField - e.g. "Name"
 * @param {{key: string, label: string, render?: Function}[]} config.columns
 * @param {string[]} config.searchFields
 * @param {() => Promise<any[]>} config.list
 * @param {(id: string) => Promise<any>} config.get
 * @param {(id: string|null, body: object) => Promise<any>} config.save - id is null for create
 * @param {(id: string) => Promise<any>} [config.remove]
 * @param {{key: string, label: string, type?: string, options?: string[], required?: boolean, help?: string}[]} config.formFields
 * @param {(id: string|null) => string} config.pathFor - REST path used in the api-preview, e.g. id => `v2/namespace?name=${id}`
 * @param {(row: any) => string} [config.deleteWarning]
 * @param {boolean} [config.canCreate]
 * @param {boolean} [config.canEdit]
 * @param {boolean} [config.canDelete]
 */
export function renderCrudSection(container, config) {
  const { resourceLabel, idField, columns, searchFields, list, get, save, remove, formFields, pathFor } = config;
  const canCreate = config.canCreate !== false;
  const canEdit = config.canEdit !== false;
  const canDelete = config.canDelete !== false && Boolean(remove);

  let destroyed = false;
  let table = null;

  const toolbar = document.createElement('div');
  toolbar.className = 'dashboard-controls';
  const refreshButton = document.createElement('button');
  refreshButton.type = 'button';
  refreshButton.className = 'button button--ghost';
  refreshButton.textContent = 'Refresh';
  toolbar.appendChild(refreshButton);
  if (canCreate) {
    const createButton = document.createElement('button');
    createButton.type = 'button';
    createButton.className = 'button button--primary';
    createButton.textContent = `New ${resourceLabel}`;
    createButton.addEventListener('click', () => openFormModal(null));
    toolbar.appendChild(createButton);
  }

  const statusArea = document.createElement('div');
  const tableContainer = document.createElement('div');
  tableContainer.className = 'card';

  container.append(toolbar, statusArea, tableContainer);

  async function load() {
    statusArea.replaceChildren(loadingRow(`Loading ${resourceLabel.toLowerCase()}s…`));
    tableContainer.hidden = true;
    try {
      const rows = (await list()) || [];
      if (destroyed) return;
      statusArea.replaceChildren();
      tableContainer.hidden = false;
      if (table) {
        table.setRows(rows);
      } else {
        table = createDataTable({
          columns,
          rows,
          searchFields,
          pageSize: 12,
          emptyMessage: `No ${resourceLabel.toLowerCase()}s found.`,
          onRowClick: (row) => openDetail(row[idField]),
        });
        tableContainer.replaceChildren(table.element);
      }
    } catch (err) {
      if (destroyed) return;
      statusArea.replaceChildren(errorState(err, load));
      tableContainer.hidden = true;
    }
  }

  async function openDetail(id) {
    const content = document.createElement('div');
    content.className = 'loading-text';
    content.innerHTML = `<span class="spinner"></span> Loading ${resourceLabel.toLowerCase()}…`;
    const modal = openModal({ title: `${resourceLabel}: ${id}`, content, size: 'md' });

    try {
      const detail = await get(id);
      if (destroyed) return;
      const wrapper = document.createElement('div');
      for (const field of formFields) {
        if (field.excludeFromDetail) continue;
        wrapper.appendChild(detailRow(field.label, formatValue(detail[field.key])));
      }

      if (config.renderExtraDetail) {
        await config.renderExtraDetail(wrapper, detail, id);
      }

      const actions = document.createElement('div');
      actions.className = 'confirm-dialog__actions';
      if (config.extraActions) {
        for (const btn of config.extraActions(detail, id, { closeModal: () => modal.close(), reload: load })) {
          actions.appendChild(btn);
        }
      }
      if (canEdit) {
        actions.appendChild(
          actionButton('Edit', 'button--ghost', () => {
            modal.close();
            openFormModal(id, detail);
          })
        );
      }
      if (canDelete) {
        actions.appendChild(
          actionButton('Delete', 'button--danger', async () => {
            const ok = await performAction({
              title: `Delete ${resourceLabel.toLowerCase()}`,
              message: config.deleteWarning ? config.deleteWarning(detail) : `Delete "${id}" permanently? This cannot be undone.`,
              danger: true,
              confirmLabel: 'Delete',
              request: { method: 'DELETE', path: pathFor(id) },
              execute: () => remove(id),
              activityLabel: `Delete ${resourceLabel.toLowerCase()} ${id}`,
            });
            if (ok) {
              modal.close();
              load();
            }
          })
        );
      }
      if (actions.children.length > 0) wrapper.appendChild(actions);
      content.replaceChildren(wrapper);
    } catch (err) {
      content.replaceChildren(errorState(err));
    }
  }

  function openFormModal(id, initialValues = {}) {
    const isCreate = id === null;
    const form = createForm(formFields, initialValues);

    const idField_ = isCreate
      ? (() => {
          const f = document.createElement('div');
          f.className = 'form-field';
          const label = document.createElement('label');
          label.textContent = resourceLabel + ' name';
          label.setAttribute('for', 'entity-id');
          const input = document.createElement('input');
          input.className = 'text-input';
          input.id = 'entity-id';
          input.required = true;
          f.append(label, input);
          return { element: f, input };
        })()
      : null;

    const content = document.createElement('div');
    if (idField_) content.appendChild(idField_.element);
    content.appendChild(form.element);

    const submitRow = document.createElement('div');
    submitRow.className = 'confirm-dialog__actions';
    const submitButton = document.createElement('button');
    submitButton.type = 'button';
    submitButton.className = 'button button--primary';
    submitButton.textContent = isCreate ? 'Create' : 'Save changes';
    submitRow.appendChild(submitButton);
    content.appendChild(submitRow);

    const modal = openModal({ title: isCreate ? `New ${resourceLabel}` : `Edit ${resourceLabel}: ${id}`, content, size: 'md' });
    if (idField_) idField_.input.focus();
    else form.focus();

    submitButton.addEventListener('click', async () => {
      const targetId = isCreate ? idField_.input.value.trim() : id;
      if (!targetId) return;
      const body = form.getValues();
      modal.close();
      const ok = await performAction({
        title: isCreate ? `Create ${resourceLabel.toLowerCase()}` : `Save ${resourceLabel.toLowerCase()}`,
        message: isCreate
          ? `Create ${resourceLabel.toLowerCase()} "${targetId}" with these settings?`
          : `Save changes to "${targetId}"?`,
        request: { method: isCreate ? 'POST' : 'PUT', path: pathFor(targetId), body },
        execute: () => save(targetId, body, isCreate),
        activityLabel: `${isCreate ? 'Create' : 'Update'} ${resourceLabel.toLowerCase()} ${targetId}`,
      });
      if (ok) load();
    });
  }

  refreshButton.addEventListener('click', load);
  load();

  return {
    destroy() {
      destroyed = true;
    },
    reload: load,
  };
}

function formatValue(value) {
  if (value === undefined || value === null || value === '') return '—';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.join(', ') || '—';
  return String(value);
}
