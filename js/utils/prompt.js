// Small modal-based replacements for window.prompt() — native browser prompts
// are jarring next to the rest of the app's UI and block automated testing.

import { openModal } from '../components/modal.js';
import { createForm } from './form-builder.js';

/** @returns {Promise<string|null>} */
export function promptForValue({ title, label }) {
  return promptForValues({ title, fields: [{ key: 'value', label, type: 'text', required: true }] }).then(
    (values) => values?.value ?? null
  );
}

/** @returns {Promise<object|null>} resolves null if cancelled */
export function promptForValues({ title, description, fields }) {
  return new Promise((resolve) => {
    const form = createForm(fields);
    const content = document.createElement('div');
    if (description) {
      const desc = document.createElement('p');
      desc.className = 'confirm-dialog__message';
      desc.textContent = description;
      content.appendChild(desc);
    }
    content.appendChild(form.element);

    const actions = document.createElement('div');
    actions.className = 'confirm-dialog__actions';
    const cancelButton = document.createElement('button');
    cancelButton.type = 'button';
    cancelButton.className = 'button button--ghost';
    cancelButton.textContent = 'Cancel';
    const submitButton = document.createElement('button');
    submitButton.type = 'button';
    submitButton.className = 'button button--primary';
    submitButton.textContent = 'Continue';
    actions.append(cancelButton, submitButton);
    content.appendChild(actions);

    let settled = false;
    const modal = openModal({
      title,
      content,
      size: 'sm',
      onClose: () => {
        if (!settled) {
          settled = true;
          resolve(null);
        }
      },
    });

    cancelButton.addEventListener('click', () => {
      settled = true;
      resolve(null);
      modal.close();
    });
    submitButton.addEventListener('click', () => {
      settled = true;
      resolve(form.getValues());
      modal.close();
    });

    form.focus();
  });
}
