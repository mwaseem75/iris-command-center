// Web Applications — list/detail/create/edit/delete, plus %-class access
// configuration. Detail view links straight into the REST Explorer for
// REST-dispatch apps ("integrated with web applications", not a bolted-on
// generic Swagger viewer).
//
// Scope note: Web application config has 40+ fields; the create/edit form
// covers the ones an admin actually touches day to day. `AutheEnabled` is
// exposed as its raw bitmask rather than per-bit checkboxes — the bit
// assignments *are* documented (see the field's help text below) but a
// read-modify-write checkbox UI wasn't worth building yet; edit the number
// directly using that reference. `MatchRoles` is deliberately left out of
// the form entirely: it's not a simple role list but an array of
// {MatchRole, TargetRoles[]} mapping pairs, and a text field can't represent
// that without corrupting it — shown nowhere, editable nowhere, until a
// proper mapping-pair UI exists.

import { hasPrivilege } from '../state.js';
import { renderCrudSection } from '../utils/crud-section.js';
import { createStatusBadge } from '../components/status-badge.js';
import { detailRow, emptyCard, actionButton, errorState } from '../utils/dom-helpers.js';
import * as webappApi from '../api/webapp-api.js';
import { openInExplorer } from './rest-explorer-page.js';

let section = null;

export function render(container) {
  container.replaceChildren();
  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Web Applications';
  container.appendChild(heading);

  if (!hasPrivilege('Secure')) {
    container.appendChild(
      emptyCard('Insufficient privilege', 'Web application management requires the %Admin_Secure privilege, which your account does not currently hold.')
    );
    return;
  }

  section = renderCrudSection(container, {
    resourceLabel: 'Web application',
    idField: 'Name',
    columns: [
      { key: 'Name', label: 'Path' },
      { key: 'NamespaceDefault', label: 'Namespace' },
      { key: 'Type', label: 'Type' },
      { key: 'Enabled', label: 'Status', render: (r) => createStatusBadge(r.Enabled ? 'Enabled' : 'Disabled', r.Enabled ? 'success' : 'warning') },
      { key: 'AuthenticationMethods', label: 'Auth methods', render: (r) => (r.AuthenticationMethods || []).join(', ') || '—' },
    ],
    searchFields: ['Name', 'Type'],
    list: () => webappApi.listWebApps({ maxRows: 500 }),
    get: (name) => webappApi.getWebApp(name),
    save: (id, body) => webappApi.saveWebApp(id, body),
    remove: (name) => webappApi.deleteWebApp(name),
    formFields: [
      { key: 'NameSpace', label: 'Namespace', type: 'text', required: true },
      { key: 'Description', label: 'Description', type: 'text' },
      { key: 'DispatchClass', label: 'Dispatch class', type: 'text', help: 'ObjectScript class handling requests, e.g. %Api.Admin or a custom %CSP.REST subclass.' },
      { key: 'Enabled', label: 'Enabled', type: 'checkbox' },
      { key: 'Resource', label: 'Resource', type: 'text', help: 'Security resource required to access this application.' },
      { key: 'Path', label: 'Physical path (CSP/file-serving apps only)', type: 'text' },
      { key: 'ServeFiles', label: 'Serve files', type: 'select', options: ['Never', 'Always', 'Always and cached', 'Use CSP security'] },
      { key: 'Recurse', label: 'Recurse into subdirectories', type: 'checkbox' },
      { key: 'Timeout', label: 'Session timeout (seconds)', type: 'number' },
      {
        key: 'AutheEnabled',
        label: 'Authentication methods (bitmask)',
        type: 'number',
        help: 'Sum the bits to enable: 32=Password, 64=Unauthenticated, 4=Kerberos, 2048=LDAP, 8192=Delegated, 16384=LoginToken, 1048576=TwoFactor SMS, 2097152=TwoFactor password.',
      },
      { key: 'CSRFToken', label: 'CSRF token required', type: 'checkbox' },
      { key: 'IsNameSpaceDefault', label: 'Default app for its namespace', type: 'checkbox', excludeFromDetail: true },
    ],
    pathFor: (id) => `v2/web-app?name=${encodeURIComponent(id)}`,
    deleteWarning: () => 'Delete this web application? Clients using this path will immediately lose access.',

    async renderExtraDetail(wrapper, detail, id) {
      try {
        const accesses = await webappApi.listPctAccesses({ names: id, maxRows: 50 });
        if (accesses?.length) {
          const title = document.createElement('h3');
          title.className = 'identity-card__subtitle';
          title.textContent = '%-class access';
          wrapper.appendChild(title);
          for (const access of accesses) {
            wrapper.appendChild(detailRow(`${access.Class} (${access.AllowType})`, access.AllowAccess ? 'Allowed' : 'Denied'));
          }
        }
      } catch (err) {
        wrapper.appendChild(errorState(err));
      }
    },

    extraActions: (detail, id, { closeModal }) => [
      actionButton('Explore REST API', 'button--ghost', () => {
        closeModal();
        openInExplorer({ name: id });
      }),
    ],
  });
}

export function destroy() {
  section?.destroy();
  section = null;
}
