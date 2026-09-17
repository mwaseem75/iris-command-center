// /v2/namespace(s) — was deferred as "out of scope" in Phase 0's initial matrix
// (not one of the six core contest modules), but the project's own phase plan
// (Phase 5) explicitly includes namespace management, so it's implemented here.
// Scope: core namespace CRUD only — global/package/routine mapping
// sub-resources (18 more endpoints) are deferred; see docs/api-matrix.md.

import { request, unwrapResult } from './client.js';

export function listNamespaces({ filter, maxRows } = {}) {
  return request('v2/namespaces', { query: { filter, maxRows } }).then(unwrapResult);
}

export function getNamespace(name) {
  return request('v2/namespace', { query: { name } }).then(unwrapResult);
}

export function saveNamespace(name, body) {
  return request('v2/namespace', { method: 'PUT', query: { name }, body });
}

export function deleteNamespace(name) {
  return request('v2/namespace', { method: 'DELETE', query: { name } });
}
