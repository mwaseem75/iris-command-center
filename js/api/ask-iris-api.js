// Ask IRIS — this project's own custom REST app (not part of IRIS's built-in
// SysAdmin API), deployed via iris/classes/ISOE/ to expose the Vector Search
// + LangChain bonus feature over HTTP. See docs/ask-iris.md.
//
// Same auth situation as /api/mgmnt and /api/health: a separate web
// application, so the JWT issued for /api/admin won't be accepted here
// either — reuses the same credential resolution.

import { request, unwrapOrThrow } from './client.js';
import { config } from '../config.js';
import { getMgmntAuth } from '../services/mgmnt-auth.js';

/** @returns {Promise<{configured: boolean, detail: string|null, indexedChunks: number}|null>} */
export async function getStatus() {
  const auth = await getMgmntAuth();
  if (!auth) return null;
  const body = await request('status', {
    method: 'GET',
    baseUrl: config.askIrisApiBaseUrl,
    auth: { basic: auth },
  });
  return unwrapOrThrow(body);
}

/** @returns {Promise<{answer: string, sources: Array<{source: string, heading: string, score: number}>}|null>} */
export async function askQuestion(question) {
  const auth = await getMgmntAuth();
  if (!auth) return null;
  const body = await request('ask', {
    method: 'POST',
    baseUrl: config.askIrisApiBaseUrl,
    auth: { basic: auth },
    body: { question },
  });
  return unwrapOrThrow(body);
}

/** @returns {Promise<{chunksIndexed: number, sources: string[]}|null>} */
export async function reindex() {
  const auth = await getMgmntAuth();
  if (!auth) return null;
  const body = await request('reindex', {
    method: 'POST',
    baseUrl: config.askIrisApiBaseUrl,
    auth: { basic: auth },
  });
  return unwrapOrThrow(body);
}
