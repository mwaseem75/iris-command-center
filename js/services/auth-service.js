// Session lifecycle: login (with JWT/Basic capability detection), logout,
// token refresh, and wiring into the API client's auth header + 401 handling.
//
// Login algorithm (see docs/api-matrix.md section 10 for why this is necessary):
// IRIS only supports JWT login (`POST /login`) starting in version 2026.2. Older
// instances 401 on it outright. Rather than guess the server version up front
// (impossible — /info itself requires auth), we simply try JWT first and fall
// back to HTTP Basic, validated directly against /info, on any failure. This
// makes the login screen version-agnostic: it behaves identically either way.

import { setState, getState } from '../state.js';
import { setAuthHeaderProvider, setUnauthorizedHandler, setSessionExpiredHandler, unwrapResult } from '../api/client.js';
import * as authApi from '../api/auth-api.js';
import * as infoApi from '../api/info-api.js';
import { showToast } from '../components/toast.js';
import { clearMgmntAuthCache } from './mgmnt-auth.js';

let refreshTimer = null;

export class InvalidCredentialsError extends Error {
  constructor() {
    super('Invalid username or password.');
    this.name = 'InvalidCredentialsError';
  }
}

function buildAuthHeader() {
  const { session } = getState();
  if (!session) return null;
  if (session.mode === 'jwt') return `Bearer ${session.accessToken}`;
  if (session.mode === 'basic') return 'Basic ' + btoa(`${session.username}:${session.password}`);
  return null;
}

async function handleUnauthorized() {
  const { session } = getState();
  if (!session || session.mode !== 'jwt' || !session.refreshToken) return false;
  try {
    await refreshAccessToken();
    return true;
  } catch {
    return false;
  }
}

function handleSessionExpired() {
  const hadSession = getState().session !== null;
  clearSession();
  if (hadSession) {
    showToast({ message: 'Your session has expired. Please log in again.', variant: 'error' });
  }
  if (window.location.hash !== '#/login') {
    window.location.hash = '#/login';
  }
}

setAuthHeaderProvider(buildAuthHeader);
setUnauthorizedHandler(handleUnauthorized);
setSessionExpiredHandler(handleSessionExpired);

function scheduleRefresh(expiresAtMs) {
  clearTimeout(refreshTimer);
  const delay = Math.max((expiresAtMs - Date.now()) * 0.8, 5000);
  refreshTimer = setTimeout(() => {
    refreshAccessToken().catch(() => handleSessionExpired());
  }, delay);
}

async function refreshAccessToken() {
  const { session } = getState();
  if (!session || session.mode !== 'jwt') throw new Error('No refreshable session.');
  const data = await authApi.refresh(session.refreshToken);
  const expiresAtMs = data.exp * 1000;
  setState({
    session: {
      ...getState().session,
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      tokenExpiresAt: expiresAtMs,
    },
  });
  scheduleRefresh(expiresAtMs);
}

function clearSession() {
  clearTimeout(refreshTimer);
  refreshTimer = null;
  setState({ session: null });
  clearMgmntAuthCache();
}

/**
 * Attempts JWT login first, falls back to Basic auth (validated against /info).
 * On success, populates state.session (including serverInfo from /info) and
 * schedules JWT refresh if applicable. Throws InvalidCredentialsError if both
 * mechanisms reject the credentials.
 */
export async function login(username, password) {
  try {
    const data = await authApi.login(username, password);
    if (data && data.access_token) {
      const expiresAtMs = data.exp * 1000;
      setState({
        session: {
          mode: 'jwt',
          username,
          accessToken: data.access_token,
          refreshToken: data.refresh_token,
          tokenExpiresAt: expiresAtMs,
          serverInfo: null,
        },
      });
      scheduleRefresh(expiresAtMs);
      await fetchServerInfo();
      return getState().session;
    }
  } catch {
    // JWT unavailable on this instance, or credentials rejected — fall back to Basic below.
  }

  try {
    const infoBody = await infoApi.getInfo({ basicAuth: { username, password } });
    setState({
      session: { mode: 'basic', username, password, serverInfo: unwrapResult(infoBody) },
    });
    return getState().session;
  } catch {
    throw new InvalidCredentialsError();
  }
}

/** Re-fetches GET /info and stores it on the current session. */
export async function fetchServerInfo() {
  const body = await infoApi.getInfo();
  const serverInfo = unwrapResult(body);
  setState({ session: { ...getState().session, serverInfo } });
  return serverInfo;
}

export async function logout() {
  const { session } = getState();
  if (session?.mode === 'jwt') {
    try {
      await authApi.logout();
    } catch {
      // Best-effort — proceed to clear local state regardless.
    }
  }
  clearSession();
}
