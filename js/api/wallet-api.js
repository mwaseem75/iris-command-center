// /v2/wallet/* — see docs/api-matrix.md section 7 (Wallets & Secrets).
//
// Security-critical: GET /v2/wallet/secrets returns only {Name, Type} — there
// is no endpoint anywhere in this API that returns a secret's value. Writing a
// secret is genuinely write-only (the WalletSecret schema is marked
// `writeOnly` in mainspec_v2.json). Callers of saveWalletSecret MUST NOT pass
// the real config to anything that logs or previews the request verbatim
// (js/utils/perform-action.js's `request` param) — see js/pages/wallets-page.js
// for how the confirm/preview/activity-log request is redacted while the real
// value still reaches `execute()`.

import { request, unwrapResult } from './client.js';

export function listWalletCollections({ names, maxRows } = {}) {
  return request('v2/wallet/collections', { query: { names, maxRows } }).then(unwrapResult);
}
export function getWalletCollection(name) {
  return request('v2/wallet/collection', { query: { name } }).then(unwrapResult);
}
export function saveWalletCollection(name, body) {
  return request('v2/wallet/collection', { method: 'PUT', query: { name }, body });
}
export function deleteWalletCollection(name) {
  return request('v2/wallet/collection', { method: 'DELETE', query: { name } });
}

export function listWalletSecrets(collection, { maxRows } = {}) {
  return request('v2/wallet/secrets', { query: { collection, maxRows } }).then(unwrapResult);
}
export function saveWalletSecret(name, body) {
  return request('v2/wallet/secret', { method: 'PUT', query: { name }, body });
}
export function deleteWalletSecret(name) {
  return request('v2/wallet/secret', { method: 'DELETE', query: { name } });
}
