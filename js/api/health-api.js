// HealthAnalyzer — this project's own custom REST app (not part of IRIS's
// built-in SysAdmin API), deployed via iris/classes/ISOE/ to expose the
// Embedded Python bonus feature over HTTP. See docs/health-analyzer.md.
//
// Same auth situation as /api/mgmnt (Phase 7): it's a separate web
// application, so a JWT issued for /api/admin won't be accepted here either —
// reuses the same credential resolution.

import { request, unwrapOrThrow } from './client.js';
import { config } from '../config.js';
import { getMgmntAuth } from '../services/mgmnt-auth.js';

/**
 * @param {object} [irisMetrics] - already-gathered IRIS metrics; see
 *   js/services/health-service.js for what populates this from the
 *   project's own documented SysAdmin REST API.
 */
export async function analyzeHealth(irisMetrics = {}) {
  const auth = await getMgmntAuth();
  if (!auth) return null;
  const body = await request('analyze', {
    method: 'POST',
    baseUrl: config.healthApiBaseUrl,
    auth: { basic: auth },
    body: irisMetrics,
  });
  return unwrapOrThrow(body);
}
