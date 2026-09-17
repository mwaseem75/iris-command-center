// Runtime configuration for IRIS Command Center.
//
// This is the single place that knows where the backend lives. Nothing else in the
// app should hardcode a URL. Edit the values below to point at your IRIS instance,
// or override any of them per-session via URL query params (handy for local dev
// against multiple containers without editing this file), e.g.:
//   index.html?apiBaseUrl=http://localhost:52774/api/admin
//
// Production deployment note: when this app is served BY IRIS itself (as a CSP web
// application's static content, alongside /api/admin on the same origin), the
// relative default below just works with no changes and no CORS configuration.

const DEFAULTS = Object.freeze({
  // Base path for the SysAdmin REST API (mainspec_v2.json / docs/api-matrix.md).
  apiBaseUrl: '/api/admin',

  // Base path for the IRIS Management API (REST app discovery, OpenAPI specs).
  // See docs/api-matrix.md section 11 for what's implemented here.
  mgmntBaseUrl: '/api/mgmnt',

  // Base path for this project's own custom REST app exposing the Embedded
  // Python HealthAnalyzer — not part of IRIS's built-in SysAdmin API. See
  // docs/health-analyzer.md for how it's deployed (iris/classes/ISOE/).
  healthApiBaseUrl: '/api/health',

  // Base path for this project's own custom REST app exposing Ask IRIS —
  // Vector Search + LangChain, backed by Embedded Python. The LLM provider
  // and its API key are never known to the frontend: the key is read
  // server-side from a wallet secret (see docs/ask-iris.md).
  askIrisApiBaseUrl: '/api/ai',

  // When true, the UI is allowed to show clearly-labeled placeholder/demo content
  // in places a live IRIS instance isn't reachable. Never used to fake API
  // responses silently — see docs/security.md.
  demoMode: false,

  // Request timeout, in milliseconds, for every API call (see js/api/client.js).
  requestTimeoutMs: 15000,
});

const QUERY_OVERRIDABLE_KEYS = ['apiBaseUrl', 'mgmntBaseUrl', 'healthApiBaseUrl', 'askIrisApiBaseUrl', 'demoMode'];

function readQueryOverrides() {
  if (typeof window === 'undefined') return {};
  const params = new URLSearchParams(window.location.search);
  const overrides = {};
  for (const key of QUERY_OVERRIDABLE_KEYS) {
    if (!params.has(key)) continue;
    const raw = params.get(key);
    overrides[key] = raw === 'true' ? true : raw === 'false' ? false : raw;
  }
  return overrides;
}

// window.IRIS_CONFIG lets a deployment inject config without editing this file
// (e.g. a small uncommitted script tag added by an installer), layered under
// query overrides so a link can still force a specific target during testing.
const windowConfig = (typeof window !== 'undefined' && window.IRIS_CONFIG) || {};

export const config = Object.freeze({
  ...DEFAULTS,
  ...windowConfig,
  ...readQueryOverrides(),
});
