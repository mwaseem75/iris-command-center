// IRIS Management API (/api/mgmnt) — REST application discovery and OpenAPI
// spec retrieval, plus a generic executor for calling into whatever endpoints
// those discovered apps expose. See docs/api-matrix.md section 11 for how
// this spec was recovered (mainspec_v2.json doesn't cover /api/mgmnt at all —
// it's self-documenting, discovered live from a running instance) and
// js/services/mgmnt-auth.js for why every call here needs explicit Basic auth
// rather than the session's normal auth header.

import { request } from './client.js';
import { getMgmntAuth } from '../services/mgmnt-auth.js';

class MgmntAuthCancelled extends Error {
  constructor() {
    super('Authentication was cancelled.');
    this.name = 'MgmntAuthCancelled';
  }
}

async function mgmntRequest(path, options = {}) {
  const auth = await getMgmntAuth();
  if (!auth) throw new MgmntAuthCancelled();
  return request(path, { ...options, api: 'mgmnt', auth: { basic: auth } });
}

/** RESTSpec-based (v2) applications, e.g. /api/mgmnt itself. */
export function listRestSpecApps() {
  return mgmntRequest('v2/');
}

/** OpenAPI 2.0 definition of a v2 (RESTSpec) application. */
export function getRestSpecAppDefinition(namespace, applicationName) {
  return mgmntRequest(`v2/${encodeURIComponent(namespace)}/${encodeURIComponent(applicationName)}`);
}

/** Legacy (%CSP.REST subclass) applications — most built-in IRIS APIs are this shape. */
export function listLegacyApps() {
  return mgmntRequest('');
}

/** OpenAPI 2.0 definition of a legacy %CSP.REST application, derived from its UrlMap. */
export function getLegacyAppDefinition(namespace, webApplication) {
  return mgmntRequest(`v1/${encodeURIComponent(namespace)}/spec/${encodeURIComponent(webApplication)}`);
}

/**
 * Fetches a spec directly by its path relative to /api/mgmnt, as returned in
 * a discovery listing's `swaggerSpec` field (e.g.
 * "v2/%25SYS/%25Api.Mgmnt.v2" once the /api/mgmnt/ prefix is stripped).
 * Simpler and more robust than re-deriving namespace/app-name separately for
 * the two differently-shaped listing entries (legacy vs RESTSpec).
 */
export function getSpecByRelativePath(relativePath) {
  return mgmntRequest(relativePath);
}

/**
 * Executes a request against a discovered application's own base path (not
 * /api/admin or /api/mgmnt). Always uses explicit Basic auth — see
 * js/services/mgmnt-auth.js — since a discovered app's own auth requirements
 * are unknown and JWT tokens are audience-scoped to the app that issued them.
 */
export async function executeDiscoveredRequest({ baseUrl, path, method = 'GET', query, body }) {
  const auth = await getMgmntAuth();
  if (!auth) throw new MgmntAuthCancelled();
  return request(path, { baseUrl, method, query, body, auth: { basic: auth }, raw: true });
}

export { MgmntAuthCancelled };
