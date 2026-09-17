// /v1|v2/monitor/* — dashboard and system usage endpoints. See docs/api-matrix.md
// section 2. Field shapes are identical between v1 and v2 (only the path prefix
// differs) — confirmed empirically against real IRIS 2026.1 and 2026.2 instances.
//
// Note: this API surface has no literal OS-level "CPU %" or "memory %" metric.
// What it actually exposes is qualitative subsystem health (Normal/Warning/...),
// internal resource-contention counters, license consumption, and IRIS shared
// memory segment allocation. The dashboard is built around what's really there
// rather than a guessed CPU/memory gauge — see js/pages/dashboard-page.js.

import { request, unwrapResult } from './client.js';
import { getApiPrefix } from '../state.js';

function get(path) {
  return request(`${getApiPrefix()}/monitor/${path}`).then(unwrapResult);
}

export const getMainDashboard = () => get('dashboard/main');
export const getSystemResources = () => get('dashboard/system-resources');
export const getLicenseUsage = () => get('license-usage');
export const getSystemUsage = () => get('system-usage');
export const getSharedMemoryUsage = () => get('system-usage/shared-memory');
