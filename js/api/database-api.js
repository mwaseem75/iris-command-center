// /v2/database(s) and /v2/database-dir(s) — see docs/api-matrix.md section 5.
// Two related resources: "database" (Config.Databases namespace bindings,
// read-only here) and "database-dir" (the actual on-disk database, full CRUD
// + mount/dismount/compact/integrity-check).

import { request, unwrapResult } from './client.js';
import { requestMaybeAsync } from './async-api.js';

// ---- Config.Databases bindings (read-only) ----
export function listDatabases({ filter, maxRows } = {}) {
  return request('v2/databases', { query: { filter, maxRows } }).then(unwrapResult);
}
export function getDatabase(name) {
  return request('v2/database', { query: { name } }).then(unwrapResult);
}

// ---- Local database directories ----
export function listDatabaseDirs({ maxRows } = {}) {
  return request('v2/database-dirs', { query: { maxRows } }).then(unwrapResult);
}
export function getDatabaseDir(dir) {
  return request('v2/database-dir', { query: { dir } }).then(unwrapResult);
}
export function createDatabaseDir(body) {
  return request('v2/database-dir', { method: 'POST', body });
}
export function updateDatabaseDir(dir, body) {
  return request('v2/database-dir', { method: 'PUT', query: { dir }, body });
}
export function deleteDatabaseDir(dir) {
  return request('v2/database-dir', { method: 'DELETE', query: { dir } });
}
// Async — see js/api/async-api.js. Confirmed live: this returns 202 with the
// real data at the Location header, not in the immediate response body.
export function getDatabaseDirInfo(dir) {
  return requestMaybeAsync('v2/database-dir/info', { method: 'POST', query: { dir } });
}
export function getDatabaseDirVolumes(dir) {
  return request('v2/database-dir/volumes', { query: { dir } }).then(unwrapResult);
}
export function mountDatabaseDir(dir, body = {}) {
  return request('v2/database-dir/mount', { method: 'POST', query: { dir }, body });
}
export function dismountDatabaseDir(dir) {
  return request('v2/database-dir/dismount', { method: 'POST', query: { dir } });
}
export function compactDatabaseDir(dir, body = {}) {
  return request('v2/database-dir/compact', { method: 'POST', query: { dir }, body });
}
// Async — see js/api/async-api.js.
export function integrityCheckDatabaseDir(body) {
  return requestMaybeAsync('v2/database-dir/integrity-check', { method: 'POST', body });
}
