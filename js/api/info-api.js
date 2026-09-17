// GET /info — server/API/user info. See docs/api-matrix.md section 1.

import { request } from './client.js';

/**
 * @param {object} [options]
 * @param {{username: string, password: string}} [options.basicAuth] - explicit Basic
 *   credentials to probe with, used only during login before any session exists.
 */
export function getInfo({ basicAuth } = {}) {
  return request('info', {
    auth: basicAuth ? { basic: basicAuth } : undefined,
  });
}
