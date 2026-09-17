// Simple bounded pagination control: prev/next + "Page X of Y". Used by
// data-table.js to keep long tables from rendering everything at once.

/**
 * @param {object} config
 * @param {number} config.pageSize
 * @param {(page: number) => void} config.onPageChange
 */
export function createPagination({ pageSize, onPageChange }) {
  const element = document.createElement('div');
  element.className = 'pagination';
  element.hidden = true;

  const prevButton = document.createElement('button');
  prevButton.type = 'button';
  prevButton.className = 'button button--ghost';
  prevButton.textContent = 'Previous';

  const label = document.createElement('span');
  label.className = 'pagination__label';

  const nextButton = document.createElement('button');
  nextButton.type = 'button';
  nextButton.className = 'button button--ghost';
  nextButton.textContent = 'Next';

  element.append(prevButton, label, nextButton);

  let page = 1;
  let totalItems = 0;

  function totalPages() {
    return Math.max(1, Math.ceil(totalItems / pageSize));
  }

  function render() {
    element.hidden = totalPages() <= 1;
    label.textContent = `Page ${page} of ${totalPages()}`;
    prevButton.disabled = page <= 1;
    nextButton.disabled = page >= totalPages();
  }

  prevButton.addEventListener('click', () => {
    if (page > 1) {
      page -= 1;
      render();
      onPageChange(page);
    }
  });
  nextButton.addEventListener('click', () => {
    if (page < totalPages()) {
      page += 1;
      render();
      onPageChange(page);
    }
  });

  return {
    element,
    setTotalItems(count) {
      totalItems = count;
      if (page > totalPages()) page = 1;
      render();
    },
    resetPage() {
      page = 1;
      render();
    },
    getPage() {
      return page;
    },
  };
}
