// Thin wrapper around the /login, /logout, /refresh, /revoke endpoints.
// See docs/api-matrix.md section 1 and section 10 (JWT availability is
// version-gated to IRIS 2026.2+ — callers must handle a 404/network failure
// here as "this instance doesn't support JWT auth", not as a hard error).

import { request } from './client.js';

/** @returns {Promise<{access_token, refresh_token, sub, iat, exp}>} */
export function login(user, password) {
  return request('login', {
    method: 'POST',
    auth: false,
    body: { user, password },
  });
}

export function logout() {
  return request('logout', { method: 'POST' });
}

/** @returns {Promise<{access_token, refresh_token, sub, iat, exp}>} */
export function refresh(refreshToken) {
  return request('refresh', {
    method: 'POST',
    auth: false,
    body: { refresh_token: refreshToken },
  });
}

export function revoke(accessToken) {
  return request('revoke', {
    method: 'POST',
    body: { access_token: accessToken },
  });
}
