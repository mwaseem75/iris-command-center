// Unit tests for js/services/mgmnt-auth.js — credential resolution for
// /api/mgmnt (and anything discovered through the REST Explorer).
//
// The concurrent-callers test below is a regression test for a real bug
// found in Phase 7: the first version of getMgmntAuth() cached the
// *resolved* credentials but not the *in-flight prompt promise*, so two
// simultaneous callers (e.g. Promise.all([callA(), callB()])) each saw no
// cached value yet and opened their own credential dialog — only the first
// could ever be answered, hanging the second forever. Fixed by caching the
// pending promise itself so concurrent callers share one prompt; this test
// exists to keep that fixed.
//
// promptForValues opens a real DOM modal, which doesn't exist under Node, so
// it's replaced with a test double via node:test's built-in module mocking
// (mock.module — no external mocking library needed).

import { test, describe, beforeEach, afterEach, mock } from 'node:test';
import assert from 'node:assert/strict';
import { setState } from '../state.js';

describe('getMgmntAuth', () => {
  let promptCallCount;
  let resolvePrompt;
  let promptMock;

  beforeEach(() => {
    setState({ session: null });
    promptCallCount = 0;
    promptMock = mock.module('../utils/prompt.js', {
      exports: {
        promptForValues: () => {
          promptCallCount += 1;
          return new Promise((resolve) => {
            resolvePrompt = resolve;
          });
        },
      },
    });
  });

  afterEach(() => {
    promptMock.restore();
    mock.reset();
  });

  test('returns the session credentials directly in Basic-auth mode, without prompting', async () => {
    const { getMgmntAuth, clearMgmntAuthCache } = await import(`../services/mgmnt-auth.js?t=${Date.now()}-1`);
    clearMgmntAuthCache();
    setState({ session: { mode: 'basic', username: '_SYSTEM', password: 'SYS' } });

    const auth = await getMgmntAuth();

    assert.deepEqual(auth, { username: '_SYSTEM', password: 'SYS' });
    assert.equal(promptCallCount, 0);
  });

  test('prompts once in JWT mode, then caches the answer for later calls', async () => {
    const { getMgmntAuth, clearMgmntAuthCache } = await import(`../services/mgmnt-auth.js?t=${Date.now()}-2`);
    clearMgmntAuthCache();
    setState({ session: { mode: 'jwt', username: '_SYSTEM' } });

    const firstCall = getMgmntAuth();
    resolvePrompt({ username: '_SYSTEM', password: 'SYS' });
    const first = await firstCall;

    const second = await getMgmntAuth();

    assert.deepEqual(first, { username: '_SYSTEM', password: 'SYS' });
    assert.deepEqual(second, { username: '_SYSTEM', password: 'SYS' });
    assert.equal(promptCallCount, 1, 'the second call should reuse the cached answer, not prompt again');
  });

  test('concurrent callers share one in-flight prompt rather than opening two', async () => {
    const { getMgmntAuth, clearMgmntAuthCache } = await import(`../services/mgmnt-auth.js?t=${Date.now()}-3`);
    clearMgmntAuthCache();
    setState({ session: { mode: 'jwt', username: '_SYSTEM' } });

    const callA = getMgmntAuth();
    const callB = getMgmntAuth();

    assert.equal(promptCallCount, 1, 'two concurrent callers must share a single prompt');

    resolvePrompt({ username: '_SYSTEM', password: 'SYS' });
    const [resultA, resultB] = await Promise.all([callA, callB]);

    assert.deepEqual(resultA, { username: '_SYSTEM', password: 'SYS' });
    assert.deepEqual(resultB, { username: '_SYSTEM', password: 'SYS' });
  });

  test('a cancelled prompt (resolves null) is not cached — the next call prompts again', async () => {
    const { getMgmntAuth, clearMgmntAuthCache } = await import(`../services/mgmnt-auth.js?t=${Date.now()}-4`);
    clearMgmntAuthCache();
    setState({ session: { mode: 'jwt', username: '_SYSTEM' } });

    const firstCall = getMgmntAuth();
    resolvePrompt(null);
    const first = await firstCall;
    assert.equal(first, null);

    const secondCall = getMgmntAuth();
    resolvePrompt({ username: '_SYSTEM', password: 'SYS' });
    const second = await secondCall;

    assert.deepEqual(second, { username: '_SYSTEM', password: 'SYS' });
    assert.equal(promptCallCount, 2, 'cancelling must not poison the cache for future attempts');
  });

  test('clearMgmntAuthCache forces a fresh prompt on the next call', async () => {
    const { getMgmntAuth, clearMgmntAuthCache } = await import(`../services/mgmnt-auth.js?t=${Date.now()}-5`);
    clearMgmntAuthCache();
    setState({ session: { mode: 'jwt', username: '_SYSTEM' } });

    const firstCall = getMgmntAuth();
    resolvePrompt({ username: '_SYSTEM', password: 'SYS' });
    await firstCall;
    assert.equal(promptCallCount, 1);

    clearMgmntAuthCache();

    const secondCall = getMgmntAuth();
    resolvePrompt({ username: '_SYSTEM', password: 'NEW' });
    const second = await secondCall;

    assert.deepEqual(second, { username: '_SYSTEM', password: 'NEW' });
    assert.equal(promptCallCount, 2);
  });
});
