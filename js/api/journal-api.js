// /v2/journal/* — journal file listing/detail, journal record browsing, and
// journal configuration. See docs/api-matrix.md section 8.
//
// `POST /v2/journal/file/records` runs async (202 + Location header, same
// pattern as audit record search — see docs/api-matrix.md section 13), so it
// goes through js/api/async-api.js's requestMaybeAsync rather than a plain
// request(). Confirmed live: its `file` parameter must be a query parameter
// even though the method is POST, same as several other endpoints in this API.

import { request, unwrapResult } from './client.js';
import { requestMaybeAsync } from './async-api.js';

export const listJournalFiles = ({ mirror, maxRows } = {}) =>
  request('v2/journal/files', { query: { mirror, maxRows } }).then(unwrapResult);

export const getJournalFile = (file) => request('v2/journal/file', { query: { file } }).then(unwrapResult);

export const getJournalSettings = () => request('v2/journal/settings').then(unwrapResult);

export const getJournalRecord = (file, address) =>
  request('v2/journal/file/record', { query: { file, address } }).then(unwrapResult);

export function listJournalRecords(file, { matchColumnName, matchOperator, matchValue, reverse, initialOffset, maxRows } = {}) {
  return requestMaybeAsync('v2/journal/file/records', {
    method: 'POST',
    query: {
      file,
      matchColumnName,
      matchOperator,
      matchValue,
      reverse: reverse ? 1 : undefined,
      initialOffset,
      maxRows,
    },
  });
}
