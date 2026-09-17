// /v2/task(s) — see docs/api-matrix.md section 4 (Task Management). v2-only,
// same rationale as js/api/process-api.js.

import { request, unwrapResult } from './client.js';

export function listTasks({ filter, onDemand, maxRows } = {}) {
  return request('v2/tasks', { query: { filter, onDemand, maxRows } }).then(unwrapResult);
}

export function getTask(id) {
  return request('v2/task', { query: { id } }).then(unwrapResult);
}

export function deleteTask(id) {
  return request('v2/task', { method: 'DELETE', query: { id } });
}

export function getTaskInfo(id) {
  return request('v2/task/info', { query: { id } }).then(unwrapResult);
}

export function getTaskHistory({ taskId, filter, userOnly, maxRows } = {}) {
  return request('v2/task/history', { query: { taskId, filter, userOnly, maxRows } }).then(unwrapResult);
}

export function getUpcomingTasks({ filter, hoursOffset, toDatetime, maxRows } = {}) {
  return request('v2/task/upcoming', { query: { filter, hoursOffset, toDatetime, maxRows } }).then(unwrapResult);
}

export function runTask(id, { runNow = true, datetime } = {}) {
  return request('v2/task/run', { method: 'POST', query: { id }, body: { RunNow: runNow, Datetime: datetime } });
}

export function suspendTask(id) {
  return request('v2/task/suspend', { method: 'POST', query: { id } });
}

export function resumeTask(id) {
  return request('v2/task/resume', { method: 'POST', query: { id } });
}

export function getTaskManagerStatus() {
  return request('v2/task/manager').then(unwrapResult);
}

export function runTaskManager() {
  return request('v2/task/manager/run', { method: 'POST' });
}

export function suspendTaskManager() {
  return request('v2/task/manager/suspend', { method: 'POST' });
}

export function resumeTaskManager() {
  return request('v2/task/manager/resume', { method: 'POST' });
}
