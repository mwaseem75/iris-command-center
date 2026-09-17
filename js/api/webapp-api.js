// /v2/web-app(s) — see docs/api-matrix.md section 3.

import { request, unwrapResult } from './client.js';

export function listWebApps({ filter, maxRows } = {}) {
  return request('v2/web-apps', { query: { filter, maxRows } }).then(unwrapResult);
}
export function getWebApp(name) {
  return request('v2/web-app', { query: { name } }).then(unwrapResult);
}
export function saveWebApp(name, body) {
  return request('v2/web-app', { method: 'PUT', query: { name }, body });
}
export function deleteWebApp(name) {
  return request('v2/web-app', { method: 'DELETE', query: { name } });
}

export function listPctAccesses({ names, allowTypes, classes, maxRows } = {}) {
  return request('v2/web-app/pct-accesses', { query: { names, allowTypes, classes, maxRows } }).then(unwrapResult);
}
export function savePctAccess({ name, allowType, cls }, body) {
  return request('v2/web-app/pct-access', { method: 'PUT', query: { name, allowType, class: cls }, body });
}
export function deletePctAccess({ name, allowType, cls }) {
  return request('v2/web-app/pct-access', { method: 'DELETE', query: { name, allowType, class: cls } });
}
