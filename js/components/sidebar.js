// Sidebar navigation. Lists every planned section from the architecture;
// only routes actually implemented so far are clickable — the rest render
// disabled with a phase marker so the shell looks complete without pretending
// unfinished pages work (see quality requirement: don't ship features that
// can't be demonstrated reliably).

const NAV_ITEMS = [
  { path: '/dashboard', label: 'Dashboard', implemented: true },
  { path: '/processes', label: 'Processes', implemented: true },
  { path: '/tasks', label: 'Tasks', implemented: true },
  { path: '/databases', label: 'Databases', implemented: true },
  { path: '/namespaces', label: 'Namespaces', implemented: true },
  { path: '/devices', label: 'Devices', implemented: true },
  { path: '/security', label: 'Security', implemented: true },
  { path: '/wallets', label: 'Wallets', implemented: true },
  { path: '/web-applications', label: 'Web Applications', implemented: true },
  { path: '/rest-explorer', label: 'REST Explorer', implemented: true },
  { path: '/logs', label: 'Logs', implemented: true },
  { path: '/health-report', label: 'Health Report', implemented: true },
  { path: '/ai-assistant', label: 'Ask IRIS', implemented: true },
];

export function renderSidebar(container) {
  const brand = document.createElement('div');
  brand.className = 'app-shell__brand';
  brand.textContent = 'IRIS Command Center';

  const nav = document.createElement('nav');
  nav.className = 'sidebar-nav';
  nav.setAttribute('aria-label', 'Primary');

  const links = NAV_ITEMS.map((item) => {
    const link = document.createElement('a');
    link.className = 'sidebar-nav__item';
    link.dataset.path = item.path;
    link.textContent = item.label;
    if (item.implemented) {
      link.href = `#${item.path}`;
    } else {
      link.href = '#';
      link.classList.add('sidebar-nav__item--disabled');
      link.setAttribute('aria-disabled', 'true');
      link.title = 'Not implemented yet';
      link.addEventListener('click', (e) => e.preventDefault());
    }
    nav.appendChild(link);
    return link;
  });

  function updateActive() {
    const current = window.location.hash.replace(/^#/, '') || '/dashboard';
    for (const link of links) {
      link.classList.toggle('sidebar-nav__item--active', link.dataset.path === current);
    }
  }
  window.addEventListener('hashchange', updateActive);
  updateActive();

  container.append(brand, nav);
}
