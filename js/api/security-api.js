// /v2/security/* — see docs/api-matrix.md sections 6 (Permission Management)
// and 7 (Security, Audit & Encryption). Scope: Users, Roles, Resources,
// Services, Audit, SQL privileges, Encryption settings. X.509 credentials and
// OAuth2 (client + server, ~20 endpoints) are deferred — see docs/api-matrix.md.

import { request, unwrapResult } from './client.js';
import { requestMaybeAsync } from './async-api.js';

// ---- Users ----
export function listUsers({ names, maxRows } = {}) {
  return request('v2/security/users', { query: { names, maxRows } }).then(unwrapResult);
}
export function getUser(name) {
  return request('v2/security/user', { query: { name } }).then(unwrapResult);
}
// `name` is required on every method for this path per the spec, including
// POST — confirmed live: creating without it 400s even though the name is
// also present in the body's `User.Name`.
export function createUser(name, user, password) {
  return request('v2/security/user', { method: 'POST', query: { name }, body: { User: user, Password: password } });
}
export function updateUser(name, body) {
  return request('v2/security/user', { method: 'PUT', query: { name }, body });
}
export function deleteUser(name) {
  return request('v2/security/user', { method: 'DELETE', query: { name } });
}
export function changeUserPassword(name, password) {
  return request('v2/security/user/password', { method: 'POST', query: { name }, body: { Password: password } });
}

// ---- Roles ----
export function listRoles({ filter, maxRows } = {}) {
  return request('v2/security/roles', { query: { filter, maxRows } }).then(unwrapResult);
}
export function getRole(name) {
  return request('v2/security/role', { query: { name } }).then(unwrapResult);
}
export function saveRole(name, body) {
  return request('v2/security/role', { method: 'PUT', query: { name }, body });
}
export function deleteRole(name) {
  return request('v2/security/role', { method: 'DELETE', query: { name } });
}
export function getRoleOwners(name) {
  return request('v2/security/role/owners', { query: { name } }).then(unwrapResult);
}

// ---- Resources ----
export function listResources({ names, maxRows } = {}) {
  return request('v2/security/resources', { query: { names, maxRows } }).then(unwrapResult);
}
export function getResource(name) {
  return request('v2/security/resource', { query: { name } }).then(unwrapResult);
}
export function saveResource(name, body) {
  return request('v2/security/resource', { method: 'PUT', query: { name }, body });
}
export function deleteResource(name) {
  return request('v2/security/resource', { method: 'DELETE', query: { name } });
}

// ---- Services ----
export function listServices({ maxRows } = {}) {
  return request('v2/security/services', { query: { maxRows } }).then(unwrapResult);
}
export function getService(name) {
  return request('v2/security/service', { query: { name } }).then(unwrapResult);
}
export function saveService(name, body) {
  return request('v2/security/service', { method: 'PUT', query: { name }, body });
}

// ---- Audit ----
export function getAuditEnabled() {
  return request('v2/security/audit/enabled').then(unwrapResult);
}
export function setAuditEnabled(enabled) {
  return request('v2/security/audit/enabled', { method: 'PUT', body: { Enabled: enabled } });
}
export function listAuditEvents({ names, eventOwner, maxRows } = {}) {
  return request('v2/security/audit/events', { query: { names, eventOwner, maxRows } }).then(unwrapResult);
}
export function getAuditEvent({ source, type, name }) {
  return request('v2/security/audit/event', { query: { source, type, name } }).then(unwrapResult);
}
export function saveAuditEvent({ source, type, name }, body) {
  return request('v2/security/audit/event', { method: 'PUT', query: { source, type, name }, body });
}
export function deleteAuditEvent({ source, type, name }) {
  return request('v2/security/audit/event', { method: 'DELETE', query: { source, type, name } });
}
// Async — see js/api/async-api.js.
export function listAuditRecords(filters = {}) {
  return requestMaybeAsync('v2/security/audit/records', { method: 'POST', query: filters });
}
export function getAuditRecord({ utcTimeStamp, systemID, auditIndex }) {
  return request('v2/security/audit/record', { query: { utcTimeStamp, systemID, auditIndex } }).then(unwrapResult);
}
export function purgeAuditRecords(body) {
  return request('v2/security/audit/record/purge', { method: 'POST', body });
}
export function copyAuditRecords(body) {
  return request('v2/security/audit/record/copy', { method: 'POST', body });
}

// ---- SQL privileges ----
export function listSqlPrivileges({ grantee, namespace, includeSystem, maxRows }) {
  return request('v2/security/sql-privileges', { query: { grantee, namespace, includeSystem, maxRows } }).then(unwrapResult);
}
export function grantSqlPrivilege(params) {
  return request('v2/security/sql-privilege/grant', { method: 'POST', query: params });
}
export function revokeSqlPrivilege(params) {
  return request('v2/security/sql-privilege/revoke', { method: 'POST', query: params });
}
export function listSqlAdminPrivileges({ grantee, namespace, maxRows }) {
  return request('v2/security/sql-admin-privileges', { query: { grantee, namespace, maxRows } }).then(unwrapResult);
}
export function grantSqlAdminPrivilege(params) {
  return request('v2/security/sql-admin-privilege/grant', { method: 'POST', query: params });
}
export function revokeSqlAdminPrivilege(params) {
  return request('v2/security/sql-admin-privilege/revoke', { method: 'POST', query: params });
}

// ---- Encryption ----
export function getEncryptionSettings() {
  return request('v2/security/encryption/settings').then(unwrapResult);
}
export function saveEncryptionSettings(body) {
  return request('v2/security/encryption/settings', { method: 'PUT', body });
}
export function listEncryptionKeys() {
  return request('v2/security/encryption/keys').then(unwrapResult);
}
