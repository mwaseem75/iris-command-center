// Unit tests for js/state.js — session state, privilege checks, and the
// API-version routing that lets this app work against both IRIS 2026.2
// (/v2/...) and older releases (/v1/...) without hardcoding a version.
//
// Run: node --test js/tests   (no dependencies — Node's built-in test runner)

import { test, describe, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { getState, setState, subscribe, isAuthenticated, getApiPrefix, hasPrivilege } from '../state.js';

// state.js is a module-level singleton, so every test resets it first —
// otherwise tests would leak session state into each other via import cache.
beforeEach(() => {
  setState({ session: null });
});

describe('isAuthenticated', () => {
  test('false when no session', () => {
    assert.equal(isAuthenticated(), false);
  });

  test('true once a session is set', () => {
    setState({ session: { mode: 'basic', username: '_SYSTEM' } });
    assert.equal(isAuthenticated(), true);
  });
});

describe('getApiPrefix', () => {
  test('defaults to v2 with no session', () => {
    assert.equal(getApiPrefix(), 'v2');
  });

  test('v1 when the server explicitly reports apiVersion 1', () => {
    setState({ session: { serverInfo: { apiVersion: 1 } } });
    assert.equal(getApiPrefix(), 'v1');
  });

  test('v2 when the server reports apiVersion 2', () => {
    setState({ session: { serverInfo: { apiVersion: 2 } } });
    assert.equal(getApiPrefix(), 'v2');
  });

  test('v2 for any other/unexpected apiVersion value (fail toward the newer API)', () => {
    setState({ session: { serverInfo: { apiVersion: 3 } } });
    assert.equal(getApiPrefix(), 'v2');
  });
});

describe('hasPrivilege', () => {
  test('false with no session', () => {
    assert.equal(hasPrivilege('Operate'), false);
  });

  test('false when the named privilege is absent', () => {
    setState({ session: { serverInfo: { privileges: { Secure: { use: true } } } } });
    assert.equal(hasPrivilege('Operate'), false);
  });

  test('false when the privilege is present but use=false', () => {
    setState({ session: { serverInfo: { privileges: { Operate: { use: false } } } } });
    assert.equal(hasPrivilege('Operate'), false);
  });

  test('true when the privilege is present with use=true', () => {
    setState({ session: { serverInfo: { privileges: { Operate: { use: true } } } } });
    assert.equal(hasPrivilege('Operate'), true);
  });
});

describe('subscribe', () => {
  test('listener is called on every setState', () => {
    let calls = 0;
    const unsubscribe = subscribe(() => {
      calls += 1;
    });
    setState({ session: { mode: 'basic' } });
    setState({ session: null });
    unsubscribe();
    assert.equal(calls, 2);
  });

  test('unsubscribe stops further notifications', () => {
    let calls = 0;
    const unsubscribe = subscribe(() => {
      calls += 1;
    });
    unsubscribe();
    setState({ session: { mode: 'basic' } });
    assert.equal(calls, 0);
  });

  test('listener receives the current state object', () => {
    let received = null;
    const unsubscribe = subscribe((state) => {
      received = state;
    });
    setState({ session: { mode: 'jwt' } });
    unsubscribe();
    assert.equal(received, getState());
    assert.equal(received.session.mode, 'jwt');
  });
});
