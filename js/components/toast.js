// Toast notifications. Mounted once by app.js into a fixed container;
// showToast() can be called from anywhere without holding a reference to it.

let container = null;

export function mountToastContainer() {
  if (container) return container;
  container = document.createElement('div');
  container.className = 'toast-container';
  container.setAttribute('role', 'status');
  container.setAttribute('aria-live', 'polite');
  document.body.appendChild(container);
  return container;
}

/**
 * @param {object} options
 * @param {string} options.message
 * @param {'info'|'success'|'error'} [options.variant]
 * @param {number} [options.durationMs]
 */
export function showToast({ message, variant = 'info', durationMs = 5000 }) {
  if (!container) mountToastContainer();

  const toast = document.createElement('div');
  toast.className = `toast toast--${variant}`;
  toast.textContent = message;
  container.appendChild(toast);

  requestAnimationFrame(() => toast.classList.add('toast--visible'));

  const remove = () => {
    toast.classList.remove('toast--visible');
    toast.addEventListener('transitionend', () => toast.remove(), { once: true });
  };
  const timer = setTimeout(remove, durationMs);
  toast.addEventListener('click', () => {
    clearTimeout(timer);
    remove();
  });
}
