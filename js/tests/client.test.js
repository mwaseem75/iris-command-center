// Unit tests for js/api/client.js's response-envelope handling: unwrapResult,
// unwrapOrThrow, and the ApiError/SessionExpiredError classes.
//
// unwrapOrThrow exists to close a real bug found in Phase 9: the custom REST
// apps in this project (ISOE.HealthAnalyzerREST, ISOE.AskIrisREST) always
// respond HTTP 200 and report failure inside the BaseResponse envelope's
// status.errors instead of a non-2xx status — so a caller using plain
// unwrapResult() would silently get back an empty {} on a server-side error
// rather than an exception. These tests exist to keep that bug fixed.
//
// request() itself isn't tested here — it needs `fetch`/`window`, which are
// browser globals; testing it would mean mocking most of the browser
// platform for little benefit over exercising it live (which every phase of
// this project already did against a real IRIS instance — see docs/api-matrix.md).

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { ApiError, SessionExpiredError, unwrapResult, unwrapOrThrow } from '../api/client.js';

describe('ApiError', () => {
  test('defaults status to 0 and errors to an empty array', () => {
    const err = new ApiError('Something broke');
    assert.equal(err.status, 0);
    assert.deepEqual(err.errors, []);
    assert.equal(err.code, undefined);
    assert.equal(err.name, 'ApiError');
  });

  test('carries status, errors, raw, and code through', () => {
    const raw = { status: { errors: ['x'] } };
    const err = new ApiError('Bad request', { status: 400, errors: ['x'], raw, code: 'bad_request' });
    assert.equal(err.status, 400);
    assert.deepEqual(err.errors, ['x']);
    assert.equal(err.raw, raw);
    assert.equal(err.code, 'bad_request');
  });

  test('is a real Error (instanceof, message, stack)', () => {
    const err = new ApiError('Boom');
    assert.ok(err instanceof Error);
    assert.equal(err.message, 'Boom');
    assert.ok(typeof err.stack === 'string');
  });
});

describe('SessionExpiredError', () => {
  test('is an ApiError with status 401 and a fixed message', () => {
    const err = new SessionExpiredError();
    assert.ok(err instanceof ApiError);
    assert.equal(err.status, 401);
    assert.match(err.message, /session has expired/i);
    assert.equal(err.name, 'SessionExpiredError');
  });
});

describe('unwrapResult', () => {
  test('unwraps the standard {status, console, result} envelope', () => {
    const body = { status: { errors: [] }, console: [], result: { score: 100 } };
    assert.deepEqual(unwrapResult(body), { score: 100 });
  });

  test('unwraps to null/primitive results correctly (not just objects)', () => {
    assert.equal(unwrapResult({ result: null }), null);
    assert.equal(unwrapResult({ result: 42 }), 42);
  });

  test('passes through a body with no "result" key unchanged (e.g. /login on 2026.2)', () => {
    const body = { accessToken: 'abc', refreshToken: 'def' };
    assert.equal(unwrapResult(body), body);
  });

  test('passes through non-object bodies unchanged', () => {
    assert.equal(unwrapResult('plain text'), 'plain text');
    assert.equal(unwrapResult(null), null);
  });
});

describe('unwrapOrThrow', () => {
  test('unwraps normally when status.errors is empty (the happy path)', () => {
    const body = { status: { errors: [] }, result: { chunksIndexed: 12 } };
    assert.deepEqual(unwrapOrThrow(body), { chunksIndexed: 12 });
  });

  test('throws an ApiError when status.errors is non-empty, instead of returning {}', () => {
    // This is the exact Phase 8 regression: a caught server-side exception
    // still responds HTTP 200 with result:{} and the real error tucked into
    // status.errors. unwrapResult() alone would hand back {} silently;
    // unwrapOrThrow() must throw instead.
    const body = {
      status: { errors: [{ error: 'Ask IRIS reindex error: boom', code: 'error' }], summary: 'Ask IRIS reindex error: boom' },
      console: ['Traceback...'],
      result: {},
    };
    assert.throws(() => unwrapOrThrow(body), (err) => {
      assert.ok(err instanceof ApiError);
      assert.equal(err.message, 'Ask IRIS reindex error: boom');
      assert.equal(err.code, 'error');
      assert.equal(err.status, 200);
      return true;
    });
  });

  test('surfaces the not_configured code distinctly from a generic error', () => {
    const body = {
      status: { errors: [{ error: 'No OpenAI API key configured.', code: 'not_configured' }], summary: '' },
      result: {},
    };
    assert.throws(() => unwrapOrThrow(body), (err) => {
      assert.equal(err.code, 'not_configured');
      return true;
    });
  });

  test('handles the legacy capitalized status.Errors field, and plain string errors', () => {
    const body = { status: { Errors: ['Legacy string error'] }, result: {} };
    assert.throws(() => unwrapOrThrow(body), (err) => {
      assert.equal(err.message, 'Legacy string error');
      assert.equal(err.code, undefined);
      return true;
    });
  });

  test('falls back to a generic message when neither summary nor a usable error string exists', () => {
    const body = { status: { errors: [{}] }, result: {} };
    assert.throws(() => unwrapOrThrow(body), (err) => {
      assert.equal(err.message, 'Request failed.');
      return true;
    });
  });
});
