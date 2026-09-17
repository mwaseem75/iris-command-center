// Credential resolution for /api/mgmnt and for executing requests against
// arbitrary REST applications discovered through it (REST Explorer).
//
// Confirmed live (Phase 7): /api/mgmnt has no /login route at all (404, not
// 401, when probed with valid Basic credentials) — it only ever accepts HTTP
// Basic, regardless of IRIS version. It also rejects the JWT issued for
// /api/admin outright (401), because that token is audience-scoped to
// /api/admin (its payload carries `"app":"/api/admin/"`). So when the primary
// session is in JWT mode, there is no password in memory to reuse — the app
// deliberately never retains one — and this module fills that one gap with a
// single one-time prompt, cached for the rest of the session and cleared on
// logout (see auth-service.js).

import { getState } from '../state.js';
import { promptForValues } from '../utils/prompt.js';

let cachedAuth = null; // { username, password } — only populated when the primary session is JWT
let pendingPrompt = null; // in-flight promise, shared so concurrent callers don't each open their own prompt

export function clearMgmntAuthCache() {
  cachedAuth = null;
  pendingPrompt = null;
}

/** @returns {Promise<{username: string, password: string} | null>} null if the user cancels */
export async function getMgmntAuth() {
  const { session } = getState();
  if (session?.mode === 'basic') {
    return { username: session.username, password: session.password };
  }
  if (cachedAuth) return cachedAuth;

  // Callers commonly fire several requests at once (Promise.all) — without
  // sharing the in-flight prompt, each would independently see no cached
  // value yet and open its own credential dialog. Confirmed live: two
  // simultaneous /api/mgmnt discovery calls produced two stacked prompts,
  // and only the first was ever answered, hanging the second forever.
  if (pendingPrompt) return pendingPrompt;

  pendingPrompt = promptForValues({
    title: 'Basic authentication required',
    description:
      'The IRIS Management API (used by the REST Explorer) only supports HTTP Basic authentication, even on instances where the rest of this app uses JWT. Enter your IRIS credentials to continue — they are held in memory for this session only.',
    fields: [
      { key: 'username', label: 'Username', type: 'text', required: true },
      { key: 'password', label: 'Password', type: 'password', required: true },
    ],
  }).then((values) => {
    pendingPrompt = null;
    if (values) cachedAuth = values;
    return values;
  });

  return pendingPrompt;
}
