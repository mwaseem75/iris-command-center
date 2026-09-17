// /v2/device(s) — see docs/api-matrix.md section 5 (Devices).

import { request, unwrapResult } from './client.js';

export function listDevices({ names, maxRows } = {}) {
  return request('v2/devices', { query: { names, maxRows } }).then(unwrapResult);
}
export function getDevice(name) {
  return request('v2/device', { query: { name } }).then(unwrapResult);
}
export function saveDevice(name, body) {
  return request('v2/device', { method: 'PUT', query: { name }, body });
}
export function deleteDevice(name) {
  return request('v2/device', { method: 'DELETE', query: { name } });
}

export function getDeviceSettings() {
  return request('v2/device/settings').then(unwrapResult);
}
export function saveDeviceSettings(body) {
  return request('v2/device/settings', { method: 'PUT', body });
}

export function listDeviceSubtypes({ names, maxRows } = {}) {
  return request('v2/device/subtypes', { query: { names, maxRows } }).then(unwrapResult);
}
export function getDeviceSubtype(name) {
  return request('v2/device/subtype', { query: { name } }).then(unwrapResult);
}
export function saveDeviceSubtype(name, body) {
  return request('v2/device/subtype', { method: 'PUT', query: { name }, body });
}
export function deleteDeviceSubtype(name) {
  return request('v2/device/subtype', { method: 'DELETE', query: { name } });
}
