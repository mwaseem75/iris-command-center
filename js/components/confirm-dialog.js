// Confirmation dialog for mutating operations. Every destructive/administrative
// action in the app should go through this rather than executing directly.

import { openModal } from './modal.js';
import { createApiPreview } from './api-preview.js';

/**
 * @param {object} config
 * @param {string} config.title
 * @param {string} config.message
 * @param {boolean} [config.danger] - high-risk styling (e.g. terminate, delete)
 * @param {string} [config.confirmLabel]
 * @param {{method: string, path: string, body?: object}} [config.request] - shown via api-preview
 * @returns {Promise<boolean>}
 */
export function confirmAction({ title, message, danger = false, confirmLabel = 'Confirm', request }) {
  return new Promise((resolve) => {
    const content = document.createElement('div');
    content.className = 'confirm-dialog';

    const messageEl = document.createElement('p');
    messageEl.className = 'confirm-dialog__message';
    messageEl.textContent = message;
    content.appendChild(messageEl);

    if (request) {
      const previewLabel = document.createElement('p');
      previewLabel.className = 'confirm-dialog__preview-label';
      previewLabel.textContent = 'API request to be executed:';
      content.append(previewLabel, createApiPreview(request));
    }

    const actions = document.createElement('div');
    actions.className = 'confirm-dialog__actions';

    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'button button--ghost';
    cancelButton.textContent = 'Cancel';

    const confirmButton = document.createElement('button');
    confirmButton.type = 'button';
    confirmButton.className = `button ${danger ? 'button--danger' : 'button--primary'}`;
    confirmButton.textContent = confirmLabel;

    actions.append(cancelButton, confirmButton);
    content.appendChild(actions);

    let settled = false;
    const modal = openModal({
      title,
      content,
      size: 'sm',
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(false);
        }
      },
    });

    cancelButton.addEventListener('click', () => {
      settled = true;
      resolve(false);
      modal.close();
    });
    confirmButton.addEventListener('click', () => {
      settled = true;
      resolve(true);
      modal.close();
    });

    confirmButton.focus();
  });
}
