// /v2/process(es) — see docs/api-matrix.md section 5 (Processes).
//
// v2-only by design: v1 (pre-2026.2) has no named suspend/resume/terminate
// routes for processes (only a generic PATCH we have no verified body schema
// for) and uses entirely different field names in its process list/detail
// response. Rather than guess that contract, this page requires IRIS 2026.2+ —
// see the capability check in js/pages/processes-page.js.

import { request, unwrapResult } from './client.js';

export function listProcesses({ filter, maxRows } = {}) {
  return request('v2/processes', { query: { filter, maxRows } }).then(unwrapResult);
}

export function getProcess(id) {
  return request('v2/process', { query: { id } }).then(unwrapResult);
}

export function suspendProcess(id) {
  return request('v2/process/suspend', { method: 'POST', query: { id } });
}

export function resumeProcess(id) {
  return request('v2/process/resume', { method: 'POST', query: { id } });
}

export function terminateProcess(id) {
  return request('v2/process/terminate', { method: 'POST', query: { id } });
}

export function broadcastMessage({ message, pidList }) {
  return request('v2/process/broadcast', { method: 'POST', body: { Message: message, PidList: pidList } });
}
