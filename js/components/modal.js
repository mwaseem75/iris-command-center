// Generic modal container: overlay + dialog box, Escape-to-close, focus trap on
// open, and an accessible role="dialog". Used by confirm-dialog.js directly and
// by any page that needs a detail drawer.

let openModals = 0;

/**
 * @param {object} config
 * @param {string} config.title
 * @param {HTMLElement} config.content
 * @param {string} [config.size] - 'sm' | 'md' | 'lg'
 * @param {() => void} [config.onClose]
 * @returns {{ close: () => void, element: HTMLElement }}
 */
export function openModal({ title, content, size = 'md', onClose }) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';

  const dialog = document.createElement('div');
  dialog.className = `modal modal--${size}`;
  dialog.setAttribute('role', 'dialog');
  dialog.setAttribute('aria-modal', 'true');
  dialog.tabIndex = -1;

  const header = document.createElement('div');
  header.className = 'modal__header';
  const titleEl = document.createElement('h2');
  titleEl.className = 'modal__title';
  titleEl.textContent = title;
  const closeButton = document.createElement('button');
  closeButton.type = 'button';
  closeButton.className = 'modal__close';
  closeButton.setAttribute('aria-label', 'Close dialog');
  closeButton.textContent = '×';
  header.append(titleEl, closeButton);

  const body = document.createElement('div');
  body.className = 'modal__body';
  body.appendChild(content);

  dialog.append(header, body);
  overlay.appendChild(dialog);
  document.body.appendChild(overlay);
  openModals += 1;
  document.body.classList.add('has-modal');

  const previouslyFocused = document.activeElement;
  dialog.focus();

  function close() {
    if (!overlay.isConnected) return;
    overlay.remove();
    openModals = Math.max(0, openModals - 1);
    if (openModals === 0) document.body.classList.remove('has-modal');
    document.removeEventListener('keydown', onKeydown);
    if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
    onClose?.();
  }

  function onKeydown(e) {
    if (e.key === 'Escape') close();
    if (e.key === 'Tab') {
      const focusable = dialog.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  }

  document.addEventListener('keydown', onKeydown);
  closeButton.addEventListener('click', close);
  overlay.addEventListener('mousedown', (e) => {
    if (e.target === overlay) close();
  });

  return { close, element: dialog };
}
