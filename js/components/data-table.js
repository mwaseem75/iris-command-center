// Reusable searchable, paginated table. Client-side only (the SysAdmin API
// already bounds list results via `maxRows`, so no server-side paging exists to
// delegate to) — this just keeps a bounded number of rows in the DOM at once.

import { createPagination } from './pagination.js';

/**
 * @param {object} config
 * @param {{key: string, label: string, render?: (row: any) => Node|string}[]} config.columns
 * @param {any[]} config.rows
 * @param {string[]} [config.searchFields] - row keys to match against the search box
 * @param {number} [config.pageSize]
 * @param {string} [config.emptyMessage]
 * @param {(row: any) => void} [config.onRowClick]
 */
export function createDataTable({ columns, rows, searchFields = [], pageSize = 10, emptyMessage = 'No results.', onRowClick }) {
  const container = document.createElement('div');
  container.className = 'data-table';

  const toolbar = document.createElement('div');
  toolbar.className = 'data-table__toolbar';
  const searchInput = document.createElement('input');
  searchInput.type = 'search';
  searchInput.className = 'text-input data-table__search';
  searchInput.placeholder = 'Search…';
  searchInput.setAttribute('aria-label', 'Search table');
  toolbar.appendChild(searchInput);

  const tableWrapper = document.createElement('div');
  tableWrapper.className = 'data-table__wrapper';
  const table = document.createElement('table');
  const thead = document.createElement('thead');
  const headRow = document.createElement('tr');
  for (const col of columns) {
    const th = document.createElement('th');
    th.textContent = col.label;
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);
  const tbody = document.createElement('tbody');
  table.append(thead, tbody);
  tableWrapper.appendChild(table);

  const pagination = createPagination({
    pageSize,
    onPageChange: () => renderPage(),
  });

  container.append(toolbar, tableWrapper, pagination.element);

  let allRows = rows;
  let filteredRows = rows;

  function applyFilter() {
    const query = searchInput.value.trim().toLowerCase();
    filteredRows = !query
      ? allRows
      : allRows.filter((row) => searchFields.some((key) => String(row[key] ?? '').toLowerCase().includes(query)));
    pagination.setTotalItems(filteredRows.length);
    renderPage();
  }

  function renderPage() {
    tbody.replaceChildren();
    if (filteredRows.length === 0) {
      const tr = document.createElement('tr');
      const td = document.createElement('td');
      td.colSpan = columns.length;
      td.className = 'data-table__empty';
      td.textContent = emptyMessage;
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }
    const page = pagination.getPage();
    const start = (page - 1) * pageSize;
    const pageRows = filteredRows.slice(start, start + pageSize);
    for (const row of pageRows) {
      const tr = document.createElement('tr');
      if (onRowClick) {
        tr.classList.add('data-table__row--clickable');
        tr.tabIndex = 0;
        tr.addEventListener('click', () => onRowClick(row));
        tr.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onRowClick(row);
          }
        });
      }
      for (const col of columns) {
        const td = document.createElement('td');
        const value = col.render ? col.render(row) : row[col.key];
        if (value instanceof Node) td.appendChild(value);
        else td.textContent = value ?? '—';
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  searchInput.addEventListener('input', () => {
    pagination.resetPage();
    applyFilter();
  });

  applyFilter();

  return {
    element: container,
    setRows(newRows) {
      allRows = newRows;
      applyFilter();
    },
  };
}
