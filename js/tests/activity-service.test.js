// Unit tests for js/services/activity-service.js — the in-memory activity
// log every mutating action in the app writes to (the "...Execute -> Record"
// half of the confirm/preview/execute/record pipeline).

import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { recordActivity, getActivities, subscribeActivities } from '../services/activity-service.js';

describe('recordActivity', () => {
  test('new entries appear first (most recent on top)', () => {
    recordActivity({ action: 'First', target: 'a', status: 'success', request: {} });
    recordActivity({ action: 'Second', target: 'b', status: 'success', request: {} });
    const [top] = getActivities();
    assert.equal(top.action, 'Second');
  });

  test('assigns each entry a unique, increasing id', () => {
    recordActivity({ action: 'One', target: 'a', status: 'success', request: {} });
    recordActivity({ action: 'Two', target: 'b', status: 'success', request: {} });
    const [second, first] = getActivities();
    assert.ok(second.id > first.id);
  });

  test('stamps each entry with a Date timestamp', () => {
    recordActivity({ action: 'Timestamped', target: 'a', status: 'success', request: {} });
    const [entry] = getActivities();
    assert.ok(entry.timestamp instanceof Date);
  });

  test('preserves status, request, response, and errorMessage as given', () => {
    recordActivity({
      action: 'Delete namespace',
      target: 'TEST',
      status: 'error',
      request: { method: 'DELETE', path: 'v2/namespace' },
      errorMessage: 'Insufficient privilege',
    });
    const [entry] = getActivities();
    assert.equal(entry.status, 'error');
    assert.equal(entry.request.method, 'DELETE');
    assert.equal(entry.errorMessage, 'Insufficient privilege');
  });

  test('caps the log at 50 entries, dropping the oldest', () => {
    for (let i = 0; i < 60; i += 1) {
      recordActivity({ action: `Action ${i}`, target: String(i), status: 'success', request: {} });
    }
    const activities = getActivities();
    assert.equal(activities.length, 50);
    // The most recent 50 of 60 actions (i = 10..59) should be present; the
    // oldest 10 (i = 0..9) should have been dropped off the end.
    assert.equal(activities[0].action, 'Action 59');
    assert.equal(activities[49].action, 'Action 10');
  });
});

describe('subscribeActivities', () => {
  test('listener fires with the full list on every recordActivity call', () => {
    let lastSeen = null;
    const unsubscribe = subscribeActivities((activities) => {
      lastSeen = activities;
    });
    recordActivity({ action: 'Notify me', target: 'x', status: 'success', request: {} });
    unsubscribe();
    assert.ok(Array.isArray(lastSeen));
    assert.equal(lastSeen[0].action, 'Notify me');
  });

  test('unsubscribe stops further notifications', () => {
    let calls = 0;
    const unsubscribe = subscribeActivities(() => {
      calls += 1;
    });
    unsubscribe();
    recordActivity({ action: 'Should not notify', target: 'x', status: 'success', request: {} });
    assert.equal(calls, 0);
  });
});
