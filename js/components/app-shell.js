// Root layout: builds the persistent DOM skeleton (login outlet + authenticated
// shell with sidebar/topbar/content outlet) once at boot. The router swaps
// `hidden` on the two top-level regions and mounts pages into the content outlet.

import { renderSidebar } from './sidebar.js';
import { renderTopbar } from './topbar.js';

export function mountAppShell(root) {
  root.replaceChildren();

  const loginContainer = document.createElement('div');
  loginContainer.id = 'login-outlet';
  loginContainer.hidden = true;

  const shellContainer = document.createElement('div');
  shellContainer.id = 'shell';
  shellContainer.className = 'app-shell';
  shellContainer.hidden = true;

  const sidebar = document.createElement('aside');
  sidebar.className = 'app-shell__sidebar';
  renderSidebar(sidebar);

  const topbar = document.createElement('header');
  topbar.className = 'app-shell__topbar';
  renderTopbar(topbar);

  const content = document.createElement('main');
  content.className = 'app-shell__content';
  content.id = 'content-outlet';

  shellContainer.append(sidebar, topbar, content);
  root.append(loginContainer, shellContainer);

  return { loginContainer, shellContainer, contentContainer: content };
}
