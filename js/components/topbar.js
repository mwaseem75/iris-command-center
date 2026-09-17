// Topbar: always-visible connected-server + current-user identity, and logout.
// Quality requirement: "show the connected IRIS server and current user clearly"
// on every authenticated screen, not just the dashboard.

import { getState, subscribe } from '../state.js';
import { logout } from '../services/auth-service.js';
import { navigate } from '../router.js';
import { createActivityTrigger } from './activity-panel.js';

export function renderTopbar(container) {
  const serverLabel = document.createElement('span');
  serverLabel.className = 'topbar__server';

  const userLabel = document.createElement('span');
  userLabel.className = 'topbar__user';

  const logoutButton = document.createElement('button');
  logoutButton.type = 'button';
  logoutButton.className = 'button button--ghost';
  logoutButton.textContent = 'Log out';
  logoutButton.addEventListener('click', async () => {
    logoutButton.disabled = true;
    await logout();
    navigate('/login');
  });

  const identity = document.createElement('div');
  identity.className = 'topbar__identity';
  identity.append(serverLabel, userLabel);

  const actions = document.createElement('div');
  actions.className = 'topbar__actions';
  actions.append(createActivityTrigger(), logoutButton);

  container.append(identity, actions);

  function update() {
    const { session } = getState();
    if (!session) {
      serverLabel.textContent = '';
      userLabel.textContent = '';
      return;
    }
    const info = session.serverInfo;
    serverLabel.textContent = info
      ? `${info.product === 'iris' ? 'IRIS' : info.product} · ${info.serverVersion?.match(/\d{4}\.\d+/)?.[0] ?? ''}`
      : 'Connecting…';
    serverLabel.title = info?.serverVersion ?? '';
    userLabel.textContent = session.username;
  }

  subscribe(update);
  update();
}
