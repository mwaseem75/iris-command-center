// Global activity log: records the outcome of every mutating operation the app
// performs, per the project's "...Execute → Record" pattern. In-memory only
// (cleared on reload, same as session state) — this is an in-app audit trail
// for the current session, not a replacement for IRIS's own audit log (Phase 7).

const MAX_ENTRIES = 50;
let entries = [];
let nextId = 1;
const listeners = new Set();

function notify() {
  for (const listener of listeners) listener(entries);
}

/**
 * @param {object} config
 * @param {string} config.action - e.g. "Suspend process"
 * @param {string} config.target - e.g. "PID 1234"
 * @param {'success'|'error'} config.status
 * @param {{method: string, path: string, body?: object}} config.request
 * @param {*} [config.response]
 * @param {string} [config.errorMessage]
 */
export function recordActivity({ action, target, status, request, response, errorMessage }) {
  entries = [
    { id: nextId++, timestamp: new Date(), action, target, status, request, response, errorMessage },
    ...entries,
  ].slice(0, MAX_ENTRIES);
  notify();
}

export function getActivities() {
  return entries;
}

export function subscribeActivities(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
