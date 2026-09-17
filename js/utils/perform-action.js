// Shared confirm -> execute -> record -> notify flow for mutating operations.
// Implements the project's "...Preview -> Confirm -> Execute -> Record" pattern
// in one place so every action across pages behaves consistently.

import { confirmAction } from '../components/confirm-dialog.js';
import { recordActivity } from '../services/activity-service.js';
import { showToast } from '../components/toast.js';
import { ApiError } from '../api/client.js';

/**
 * @param {object} config
 * @param {string} config.title - confirm dialog title
 * @param {string} config.message - confirm dialog message
 * @param {boolean} [config.danger]
 * @param {string} [config.confirmLabel]
 * @param {{method: string, path: string, body?: object}} config.request - shown in the preview and recorded
 * @param {() => Promise<*>} config.execute - performs the actual API call
 * @param {string} config.activityLabel - e.g. "Suspend process 1234"
 * @returns {Promise<boolean>} whether the action was confirmed and succeeded
 */
export async function performAction({ title, message, danger = false, confirmLabel = 'Confirm', request, execute, activityLabel }) {
  const confirmed = await confirmAction({ title, message, danger, confirmLabel, request });
  if (!confirmed) return false;

  try {
    const response = await execute();
    recordActivity({ action: activityLabel, target: request.path, status: 'success', request, response });
    showToast({ message: `${activityLabel} succeeded.`, variant: 'success' });
    return true;
  } catch (err) {
    const errorMessage = err instanceof ApiError ? err.message : 'The action failed unexpectedly.';
    recordActivity({ action: activityLabel, target: request.path, status: 'error', request, errorMessage });
    showToast({ message: `${activityLabel} failed: ${errorMessage}`, variant: 'error' });
    return false;
  }
}
