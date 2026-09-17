// Some mutating/query operations run asynchronously: instead of the result,
// they return 202 with a `Location` response header pointing at
// GET /v2/async-result?id=<guid>, which must be polled until State is no
// longer "Pending"/"Running". Confirmed live (Phase 6) on
// POST /v2/security/audit/records — the spec documents this ("Accepted"
// response, `Location` header) but it's easy to miss since the response body
// alone is just `{}`. See docs/api-matrix.md section 12.

import { request, unwrapResult, ApiError } from './client.js';

const POLL_INTERVAL_MS = 700;
const POLL_TIMEOUT_MS = 30000;

/**
 * Issues a request that may respond synchronously (200) or asynchronously
 * (202 + Location header) and returns the eventual result either way.
 */
export async function requestMaybeAsync(path, options = {}) {
  const { status, headers, body } = await request(path, { ...options, raw: true });

  if (status !== 202) return unwrapResult(body);

  const location = headers.get('Location') || headers.get('location');
  if (!location) {
    // Spec promises a Location header on every 202; if a server response omits
    // it there's nothing to poll, so surface what little we have.
    return unwrapResult(body);
  }
  return pollAsyncResult(location);
}

async function pollAsyncResult(location) {
  const path = location.replace(/^\/api\/admin\//, '');
  const deadline = Date.now() + POLL_TIMEOUT_MS;

  while (Date.now() < deadline) {
    const taskBody = await request(path, { api: 'admin' });
    const task = unwrapResult(taskBody);

    if (task.State === 'Finished') return task.Result;
    if (task.State === 'Failed' || task.State === 'Cancelled') {
      throw new ApiError(task.FailureReason || `Background task ${task.State.toLowerCase()}.`, { status: 0 });
    }
    await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
  }
  throw new ApiError('Timed out waiting for the server to finish this operation.', { status: 0 });
}

export function getAsyncResult(id) {
  return request('v2/async-result', { query: { id } }).then(unwrapResult);
}

export function listAsyncResults({ start, end, maxRows } = {}) {
  return request('v2/async-results', { query: { start, end, maxRows } }).then(unwrapResult);
}
