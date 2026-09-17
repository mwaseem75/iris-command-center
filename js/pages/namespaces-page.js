// Namespaces — core CRUD (create/edit/delete). Global/package/routine mapping
// sub-resources are deferred (see js/api/namespace-api.js).

import { getApiPrefix, hasPrivilege } from '../state.js';
import { renderCrudSection } from '../utils/crud-section.js';
import { emptyCard } from '../utils/dom-helpers.js';
import * as namespaceApi from '../api/namespace-api.js';

let section = null;

export function render(container) {
  container.replaceChildren();
  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Namespaces';
  container.appendChild(heading);

  if (getApiPrefix() !== 'v2') {
    container.appendChild(
      emptyCard('Requires IRIS 2026.2 or later', 'Namespace management uses REST endpoints only available on IRIS 2026.2+.')
    );
    return;
  }
  if (!hasPrivilege('Manage')) {
    container.appendChild(
      emptyCard('Insufficient privilege', 'Namespace management requires the %Admin_Manage privilege, which your account does not currently hold.')
    );
    return;
  }

  section = renderCrudSection(container, {
    resourceLabel: 'Namespace',
    idField: 'Name',
    columns: [
      { key: 'Name', label: 'Name' },
      { key: 'Globals', label: 'Globals DB' },
      { key: 'Routines', label: 'Routines DB' },
      { key: 'TempGlobals', label: 'Temp Globals DB' },
    ],
    searchFields: ['Name', 'Globals', 'Routines'],
    list: () => namespaceApi.listNamespaces({ maxRows: 500 }),
    get: (name) => namespaceApi.getNamespace(name),
    save: (id, body) => namespaceApi.saveNamespace(id, body),
    remove: (name) => namespaceApi.deleteNamespace(name),
    formFields: [
      { key: 'Globals', label: 'Globals database', type: 'text', required: true, help: 'Default database for globals in this namespace.' },
      { key: 'Routines', label: 'Routines database', type: 'text', required: true, help: 'Default database for routines/classes.' },
      { key: 'TempGlobals', label: 'Temp globals database', type: 'text', help: 'Defaults to IRISTEMP if left blank.' },
    ],
    pathFor: (id) => `v2/namespace?name=${encodeURIComponent(id)}`,
    deleteWarning: () => 'Delete this namespace and any web applications mapped to it? This cannot be undone.',
  });
}

export function destroy() {
  section?.destroy();
  section = null;
}
