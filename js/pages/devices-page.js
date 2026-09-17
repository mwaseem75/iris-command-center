// Devices — device list/CRUD, device subtype list/CRUD, and telnet/IO settings.

import { getApiPrefix, hasPrivilege } from '../state.js';
import { renderCrudSection } from '../utils/crud-section.js';
import { createForm } from '../utils/form-builder.js';
import { performAction } from '../utils/perform-action.js';
import { emptyCard, loadingRow, errorState } from '../utils/dom-helpers.js';
import * as deviceApi from '../api/device-api.js';

let activeSection = null;
let destroyed = false;

const TABS = [
  { key: 'devices', label: 'Devices' },
  { key: 'subtypes', label: 'Subtypes' },
  { key: 'settings', label: 'Settings' },
];

export function render(container) {
  destroyed = false;
  container.replaceChildren();
  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Devices';
  container.appendChild(heading);

  if (getApiPrefix() !== 'v2') {
    container.appendChild(
      emptyCard('Requires IRIS 2026.2 or later', 'Device management uses REST endpoints only available on IRIS 2026.2+.')
    );
    return;
  }
  if (!hasPrivilege('Manage')) {
    container.appendChild(
      emptyCard('Insufficient privilege', 'Device management requires the %Admin_Manage privilege, which your account does not currently hold.')
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

    if (key === 'devices') {
      activeSection = renderCrudSection(contentArea, {
        resourceLabel: 'Device',
        idField: 'Name',
        columns: [
          { key: 'Name', label: 'Name' },
          { key: 'Type', label: 'Type' },
          { key: 'SubType', label: 'Subtype' },
          { key: 'PhysicalDevice', label: 'Physical device' },
          { key: 'Description', label: 'Description' },
        ],
        searchFields: ['Name', 'Type', 'SubType', 'Description'],
        list: () => deviceApi.listDevices({ maxRows: 500 }),
        get: (name) => deviceApi.getDevice(name),
        save: (id, body) => deviceApi.saveDevice(id, body),
        remove: (name) => deviceApi.deleteDevice(name),
        formFields: [
          { key: 'Type', label: 'Type', type: 'select', options: ['TRM', 'SPL', 'MT', 'BT', 'IPC', 'OTH'], required: true, help: 'TRM=Terminal, SPL=Spool, MT=Magnetic tape, BT=Cartridge tape, IPC=Interprocess, OTH=Other' },
          { key: 'SubType', label: 'Subtype', type: 'text', required: true },
          { key: 'PhysicalDevice', label: 'Physical device', type: 'text', required: true },
          { key: 'Description', label: 'Description', type: 'text' },
          { key: 'AlternateDevice', label: 'Alternate device', type: 'text' },
          { key: 'OpenParameters', label: 'Open parameters', type: 'text' },
          { key: 'Prompt', label: 'Prompt option', type: 'number', help: 'Blank = show selection prompt, 1 = auto-use if current, 2 = auto-use with defaults' },
          { key: 'Alias', label: 'Alias (numeric device ID)', type: 'number' },
        ],
        pathFor: (id) => `v2/device?name=${encodeURIComponent(id)}`,
      });
    } else if (key === 'subtypes') {
      activeSection = renderCrudSection(contentArea, {
        resourceLabel: 'Device subtype',
        idField: 'Name',
        columns: [
          { key: 'Name', label: 'Name' },
          { key: 'RightMargin', label: 'Right margin' },
          { key: 'ScreenLength', label: 'Screen length' },
        ],
        searchFields: ['Name'],
        list: () => deviceApi.listDeviceSubtypes({ maxRows: 500 }),
        get: (name) => deviceApi.getDeviceSubtype(name),
        save: (id, body) => deviceApi.saveDeviceSubtype(id, body),
        remove: (name) => deviceApi.deleteDeviceSubtype(name),
        formFields: [
          { key: 'RightMargin', label: 'Right margin', type: 'number', required: true },
          { key: 'ScreenLength', label: 'Screen length', type: 'number', required: true },
          { key: 'Backspace', label: 'Backspace code', type: 'text', help: 'e.g. $C(8)' },
          { key: 'FormFeed', label: 'Form feed code', type: 'text' },
          { key: 'EraseEOL', label: 'Erase to end of line', type: 'text' },
          { key: 'EraseEOF', label: 'Erase to end of file', type: 'text' },
          { key: 'CursorControl', label: 'Cursor control', type: 'text' },
        ],
        pathFor: (id) => `v2/device/subtype?name=${encodeURIComponent(id)}`,
      });
    } else if (key === 'settings') {
      renderSettings(contentArea);
    }
  }

  async function renderSettings(area) {
    area.replaceChildren(loadingRow('Loading device settings…'));
    try {
      const settings = await deviceApi.getDeviceSettings();
      if (destroyed) return;
      const card = document.createElement('div');
      card.className = 'card';
      const form = createForm(
        [
          { key: 'TelnetPort', label: 'Telnet port', type: 'number' },
          { key: 'TelnetDNSLookup', label: 'Telnet DNS lookup', type: 'select', options: ['ON', 'OFF'] },
        ],
        { TelnetPort: settings.TelnetSettings?.Port, TelnetDNSLookup: settings.TelnetSettings?.DNSLookup }
      );
      card.appendChild(form.element);
      const saveRow = document.createElement('div');
      saveRow.className = 'confirm-dialog__actions';
      const saveButton = document.createElement('button');
      saveButton.type = 'button';
      saveButton.className = 'button button--primary';
      saveButton.textContent = 'Save settings';
      saveButton.addEventListener('click', async () => {
        const values = form.getValues();
        const body = { TelnetSettings: { Port: values.TelnetPort, DNSLookup: values.TelnetDNSLookup } };
        await performAction({
          title: 'Update device settings',
          message: 'Save changes to telnet/device IO settings?',
          request: { method: 'PUT', path: 'v2/device/settings', body },
          execute: () => deviceApi.saveDeviceSettings(body),
          activityLabel: 'Update device settings',
        });
      });
      saveRow.appendChild(saveButton);
      card.appendChild(saveRow);
      area.replaceChildren(card);
    } catch (err) {
      if (destroyed) return;
      area.replaceChildren(errorState(err, () => renderSettings(area)));
    }
  }

  switchTab('devices');
}

export function destroy() {
  destroyed = true;
  activeSection?.destroy?.();
  activeSection = null;
}
