// Central HTTP client for the IRIS SysAdmin REST API.
//
// Responsibilities: base URL + auth header attachment, JSON handling, timeouts,
// error normalization, and a single place to react to 401s (session expiry).
// Never logs request/response bodies or headers — they can contain passwords,
// tokens, or wallet secrets.

import { config } from '../config.js';

export class ApiError extends Error {
  constructor(message, { status, errors, raw, code } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status ?? 0;
    this.errors = errors ?? [];
    this.raw = raw;
    this.code = code;
  }
}

// Thrown when a request could not be recovered after a 401 (refresh failed, or
// no refresh is possible in Basic-auth mode). The router/app shell listens for
// this via onSessionExpired rather than catching it at every call site.
export class SessionExpiredError extends ApiError {
  constructor() {
    super('Your session has expired. Please log in again.', { status: 401 });
    this.name = 'SessionExpiredError';
  }
}

let authHeaderProvider = () => null; // () => string | null
let unauthorizedHandler = null; // async () => boolean (true = recovered, retry once)
let sessionExpiredHandler = null; // () => void

export function setAuthHeaderProvider(fn) {
  authHeaderProvider = fn;
}

export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn;
}

export function setSessionExpiredHandler(fn) {
  sessionExpiredHandler = fn;
}

function buildUrl(baseUrl, path, query) {
  const url = new URL(baseUrl.replace(/\/$/, '') + '/' + path.replace(/^\//, ''), window.location.origin);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      url.searchParams.set(key, value);
    }
  }
  return url.toString();
}

async function parseErrorBody(response) {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) {
    return { message: response.statusText, errors: [] };
  }
  try {
    const body = await response.json();
    // The live API has been observed using both `status.Errors` (as documented in
    // mainspec_v2.json) and `status.errors` (as actually returned) — handle both.
    const statusBlock = body.status || {};
    const errors = statusBlock.Errors || statusBlock.errors || [];
    const summary = statusBlock.summary || body.msg || '';
    const message = summary || errors[0] || response.statusText;
    return { message, errors, raw: body };
  } catch {
    return { message: response.statusText, errors: [] };
  }
}

/**
 * @param {string} path - path relative to baseUrl, e.g. "info" or "v2/processes"
 * @param {object} [options]
 * @param {'GET'|'POST'|'PUT'|'DELETE'|'PATCH'} [options.method]
 * @param {object} [options.body] - JSON-serializable request body
 * @param {object} [options.query] - query string parameters
 * @param {'admin'|'mgmnt'} [options.api] - which base URL to use (default 'admin')
 * @param {string} [options.baseUrl] - literal base URL, overrides `api` — used by the
 *   REST Explorer to call into arbitrary discovered applications' own base paths
 * @param {false|object} [options.auth] - false to skip auth entirely (e.g. /login);
 *   omit to use the registered session auth header provider.
 * @param {boolean} [options._isRetry] - internal, prevents infinite 401 retry loops
 */
const BODY_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export async function request(path, options = {}) {
  const { method = 'GET', body, query, api = 'admin', baseUrl: baseUrlOverride, auth, raw = false, _isRetry = false } = options;
  const baseUrl = baseUrlOverride ?? (api === 'mgmnt' ? config.mgmntBaseUrl : config.apiBaseUrl);
  const url = buildUrl(baseUrl, path, query);

  // IRIS's REST framework requires Content-Type: application/json on any
  // operation whose RESTSpec declares a body parameter — even an optional one —
  // and 415s otherwise. Rather than track which of our ~30 mutating endpoints
  // declare an (optional) body, always send one for body-bearing methods; a
  // stray `{}` is harmless on endpoints that ignore it. Confirmed empirically:
  // POST /v2/task/suspend 415'd with no body even though its only field,
  // LeaveInQueue, is optional.
  const effectiveBody = BODY_METHODS.has(method) ? (body ?? {}) : body;

  const headers = { Accept: 'application/json' };
  if (effectiveBody !== undefined) headers['Content-Type'] = 'application/json';

  if (auth && auth.basic) {
    headers.Authorization = 'Basic ' + btoa(`${auth.basic.username}:${auth.basic.password}`);
  } else if (auth !== false) {
    const headerValue = authHeaderProvider();
    if (headerValue) headers.Authorization = headerValue;
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), config.requestTimeoutMs);

  let response;
  try {
    response = await fetch(url, {
      method,
      headers,
      body: effectiveBody !== undefined ? JSON.stringify(effectiveBody) : undefined,
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === 'AbortError') {
      throw new ApiError('Request timed out.', { status: 0 });
    }
    throw new ApiError('Network error — could not reach the server.', { status: 0 });
  }
  clearTimeout(timeout);

  if (response.status === 401 && auth === undefined) {
    if (!_isRetry && unauthorizedHandler) {
      const recovered = await unauthorizedHandler();
      if (recovered) {
        return request(path, { ...options, _isRetry: true });
      }
    }
    sessionExpiredHandler?.();
    throw new SessionExpiredError();
  }

  if (!response.ok) {
    const { message, errors, raw } = await parseErrorBody(response);
    throw new ApiError(message, { status: response.status, errors, raw });
  }

  let parsedBody = null;
  if (response.status !== 204) {
    const text = await response.text();
    if (text) {
      try {
        parsedBody = JSON.parse(text);
      } catch {
        parsedBody = text;
      }
    }
  }

  // Some endpoints (e.g. audit record search, database integrity checks) run
  // async: a 202 carries the real result location in the `Location` header
  // rather than the body. `raw: true` exposes status/headers for callers that
  // need to follow that — see js/api/async-api.js.
  if (raw) {
    return { status: response.status, headers: response.headers, body: parsedBody };
  }
  return parsedBody;
}

// Unwraps the {status, console, result} envelope used by most /v2 and /v1
// SysAdmin API responses. Some endpoints (e.g. /login on 2026.2) return a flat
// body instead — see docs/api-matrix.md section 12 — so this passes those through.
export function unwrapResult(body) {
  if (body && typeof body === 'object' && 'result' in body) return body.result;
  return body;
}

// Custom REST apps in this project (ISOE.HealthAnalyzerREST, ISOE.AskIrisREST) always
// respond HTTP 200 and report failure inside the BaseResponse envelope's `status.errors`
// instead — so `request()`'s ok/not-ok check never fires for them. Callers that need
// server-side errors to surface as a normal thrown ApiError (rather than silently
// unwrapping to an empty `result`) should use this instead of unwrapResult().
export function unwrapOrThrow(body) {
  const statusBlock = (body && body.status) || {};
  const errors = statusBlock.errors || statusBlock.Errors || [];
  if (errors.length > 0) {
    const first = errors[0];
    const message = statusBlock.summary || (typeof first === 'string' ? first : first?.error) || 'Request failed.';
    const code = typeof first === 'object' ? first?.code : undefined;
    throw new ApiError(message, { status: 200, errors, raw: body, code });
  }
  return unwrapResult(body);
}
