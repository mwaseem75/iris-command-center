// Minimal global state store with a pub/sub subscription model.
// Not a framework — just enough for components to react to session/auth changes.

const state = {
  // null when logged out. Shape when set:
  // { mode: 'jwt' | 'basic', username, accessToken, refreshToken, tokenExpiresAt, serverInfo }
  session: null,
};

const listeners = new Set();

export function getState() {
  return state;
}

export function setState(patch) {
  Object.assign(state, patch);
  for (const listener of listeners) listener(state);
}

export function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function isAuthenticated() {
  return state.session !== null;
}

// The live SysAdmin API is versioned (/v1/... or /v2/...) depending on the
// connected IRIS release — see docs/api-matrix.md section 10. GET /info reports
// which one via `apiVersion` (1 or 2); we read that once per session rather than
// hardcoding a version, so the app degrades instead of breaking on older IRIS.
export function getApiPrefix() {
  const apiVersion = state.session?.serverInfo?.apiVersion;
  return apiVersion === 1 ? 'v1' : 'v2';
}

export function hasPrivilege(name) {
  return Boolean(state.session?.serverInfo?.privileges?.[name]?.use);
}
