// Instances page: the IRIS instances the Command Center can connect to.
//
// Reads: GET /api/iris/instances (InstanceView only, never a password).
//
// The Primary comes from the backend's environment: it can be checked, but
// its Edit/Delete buttons are disabled and it has no Deactivate (the backend
// refuses all three anyway). Other instances change only through the
// backend's instance.* operations, which do the authorization, the live
// compatibility check, the change and its verification:
// - Add: Test Connection (POST /instances/test, stores nothing) must report
//   "compatible" before Add Instance is enabled; editing a field clears it.
// - Edit: Test Connection is a dry run of the update. The backend re-checks
//   the connection when it needs to (an active instance whose URL, username,
//   namespace or password changed); a blank password keeps the stored one.
// - Activate / Deactivate / Delete: a dry run first, then the checkbox and
//   the confirm button.
// - Check: POST /instances/{id}/check, saved as the instance's last check.
//
// Only a confirm button sends confirmed=true without dry_run. Passwords are
// read from the field when a request is sent and never kept, shown or
// logged; the field is cleared whenever the dialog closes.

import { IrisApi, ApiError } from "./api.js";
import { updateInstanceContextList } from "./instance-context.js";

const PLACEHOLDER = "—";  // shown for empty values

// InstanceCheckStatus (backend/app/instances/models.py) -> label and badge.
const CHECK_STATUS = {
  compatible: ["Compatible", "status-badge--ok"],
  incompatible: ["Incompatible", "status-badge--error"],
  unreachable: ["Unreachable", "status-badge--error"],
  auth_failed: ["Auth Failed", "status-badge--error"],
};

const dom = {
  refreshButton: document.getElementById("instances-refresh-button"),
  addButton: document.getElementById("instances-add-button"),
  errorBanner: document.getElementById("instances-error-banner"),
  errorBannerText: document.getElementById("instances-error-banner-text"),
  loadingState: document.getElementById("instances-loading-state"),
  empty: document.getElementById("instances-empty"),
  content: document.getElementById("instances-content"),
  tableBody: document.getElementById("instances-table-body"),
};

const formDom = {
  backdrop: document.getElementById("instance-form-backdrop"),
  drawer: document.getElementById("instance-form-drawer"),
  title: document.getElementById("instance-form-title"),
  close: document.getElementById("instance-form-close"),
  form: document.getElementById("instance-form"),
  hint: document.getElementById("instance-form-hint"),
  name: document.getElementById("instance-form-name"),
  url: document.getElementById("instance-form-url"),
  username: document.getElementById("instance-form-username"),
  namespace: document.getElementById("instance-form-namespace"),
  password: document.getElementById("instance-form-password"),
  passwordRequired: document.getElementById("instance-form-password-required"),
  passwordToggle: document.getElementById("instance-form-password-toggle"),
  loading: document.getElementById("instance-form-loading"),
  loadingText: document.getElementById("instance-form-loading-text"),
  error: document.getElementById("instance-form-error"),
  errorText: document.getElementById("instance-form-error-text"),
  testResult: document.getElementById("instance-form-test-result"),
  ack: document.getElementById("instance-form-ack"),
  ackCheckbox: document.getElementById("instance-form-ack-checkbox"),
  ackLabel: document.getElementById("instance-form-ack-label"),
  result: document.getElementById("instance-form-result"),
  resultList: document.getElementById("instance-form-result-list"),
  cancelButton: document.getElementById("instance-form-cancel"),
  testButton: document.getElementById("instance-form-test-button"),
  submitButton: document.getElementById("instance-form-submit-button"),
};

const confirmDom = {
  backdrop: document.getElementById("instance-confirm-backdrop"),
  drawer: document.getElementById("instance-confirm-drawer"),
  title: document.getElementById("instance-confirm-title"),
  close: document.getElementById("instance-confirm-close"),
  banner: document.getElementById("instance-confirm-banner"),
  heading: document.getElementById("instance-confirm-heading"),
  message: document.getElementById("instance-confirm-message"),
  target: document.getElementById("instance-confirm-target"),
  loading: document.getElementById("instance-confirm-loading"),
  loadingText: document.getElementById("instance-confirm-loading-text"),
  error: document.getElementById("instance-confirm-error"),
  errorText: document.getElementById("instance-confirm-error-text"),
  preview: document.getElementById("instance-confirm-preview"),
  ack: document.getElementById("instance-confirm-ack"),
  ackCheckbox: document.getElementById("instance-confirm-ack-checkbox"),
  ackLabel: document.getElementById("instance-confirm-ack-label"),
  result: document.getElementById("instance-confirm-result"),
  resultList: document.getElementById("instance-confirm-result-list"),
  cancelButton: document.getElementById("instance-confirm-cancel"),
  confirmButton: document.getElementById("instance-confirm-button"),
};

const checkDom = {
  backdrop: document.getElementById("instance-check-backdrop"),
  drawer: document.getElementById("instance-check-drawer"),
  close: document.getElementById("instance-check-close"),
  subtitle: document.getElementById("instance-check-subtitle"),
  loading: document.getElementById("instance-check-loading"),
  error: document.getElementById("instance-check-error"),
  errorText: document.getElementById("instance-check-error-text"),
  result: document.getElementById("instance-check-result"),
  doneButton: document.getElementById("instance-check-done"),
};

// What the confirmation dialog says for each action.
const CONFIRM_ACTIONS = {
  activate: {
    title: "Confirm Activate",
    heading: "Activate Instance?",
    message: "The backend runs a live compatibility check first; the instance is activated only if it is compatible.",
    banner: "banner--info",
    ack: "I confirm that I want to activate this instance.",
    button: "Activate Instance",
    buttonClass: "btn--warning",
    running: "Activating…",
  },
  deactivate: {
    title: "Confirm Deactivate",
    heading: "Deactivate Instance?",
    message: "This will deactivate the instance. The instance definition and credentials will be kept and it can be reactivated later.",
    banner: "banner--warning",
    ack: "I confirm that I want to deactivate this instance.",
    button: "Deactivate Instance",
    buttonClass: "btn--danger",
    running: "Deactivating…",
  },
  delete: {
    title: "Confirm Delete",
    heading: "Delete Instance?",
    message: "This will permanently delete the instance and its stored credentials. This action cannot be undone.",
    banner: "banner--error",
    ack: "I confirm that I want to delete this instance.",
    button: "Delete Instance",
    buttonClass: "btn--danger",
    running: "Deleting…",
  },
};

let instances = [];
let isLoading = false;
let reloadQueued = false;  // a change finished while a load was running
// { mode: "add" | "edit", instance, tested, done, token }; null when closed.
let formState = null;
// { action, instance, previewed, done, token }; null when closed.
let confirmState = null;
// Bumped on every open/close so a late response can't update a newer dialog.
let dialogToken = 0;

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatDateTime(iso) {
  if (!iso) return PLACEHOLDER;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? String(iso) : date.toLocaleString();
}

// ApiError messages are the backend's own safe text; anything else is generic.
function errorMessage(err, fallback) {
  return err instanceof ApiError && err.message ? err.message : fallback;
}

function setErrorBanner(message) {
  dom.errorBannerText.textContent = message || "";
  dom.errorBanner.hidden = !message;
}

function setLoading(loading) {
  isLoading = loading;
  dom.loadingState.hidden = !loading || instances.length > 0;
  dom.refreshButton.disabled = loading;
  dom.refreshButton.classList.toggle("btn--spinning", loading);
}

function addInfoRows(list, rows) {
  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "info-list__row";
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.className = "info-list__value";
    dd.textContent = textOrPlaceholder(value);
    row.append(dt, dd);
    list.append(row);
  }
}

function makeCheckBadge(check) {
  const [label, variant] = check
    ? CHECK_STATUS[check.status] || [textOrPlaceholder(check.status), "status-badge--neutral"]
    : ["Not Checked", "status-badge--warning"];
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = label;
  return badge;
}

// --- Table ---

function makeActionButton(label, icon, action, instance, { variant = "", disabled = false, title = "" } = {}) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `btn btn--sm ${variant}`.trim();
  button.dataset.action = action;
  button.dataset.instanceId = instance.id;
  button.disabled = disabled;
  if (title) button.title = title;
  const iconEl = document.createElement("span");
  iconEl.className = "btn__icon";
  iconEl.setAttribute("aria-hidden", "true");
  iconEl.textContent = icon;
  button.append(iconEl, document.createTextNode(label));
  return button;
}

function cell(content, className = "") {
  const td = document.createElement("td");
  td.className = `data-table__cell ${className}`.trim();
  if (content instanceof Node) td.append(content);
  else td.textContent = textOrPlaceholder(content);
  return td;
}

function renderNameCell(instance) {
  const wrapper = document.createElement("div");
  const name = document.createElement("span");
  name.className = "inst-name";
  name.textContent = instance.name;
  wrapper.append(name);
  if (instance.primary) {
    const chip = document.createElement("span");
    chip.className = "status-badge status-badge--accent inst-primary-chip";
    chip.textContent = "Primary";
    wrapper.append(chip);
  } else if (instance.docker_managed) {
    const chip = document.createElement("span");
    chip.className = "status-badge status-badge--neutral inst-primary-chip";
    chip.textContent = "Docker-managed";
    chip.title = "Managed by Docker Compose (the iris-2 service)";
    wrapper.append(chip);
  }
  return wrapper;
}

function renderStatusCell(instance) {
  const wrapper = document.createElement("div");
  wrapper.className = "inst-status";
  const state = document.createElement("span");
  state.className = "inst-state";
  state.dataset.active = String(instance.active);
  const dot = document.createElement("span");
  dot.className = "inst-state__dot";
  dot.setAttribute("aria-hidden", "true");
  state.append(dot, document.createTextNode(instance.active ? "Active" : "Inactive"));
  wrapper.append(state, makeCheckBadge(instance.last_check));
  return wrapper;
}

function renderLastCheckCell(check) {
  if (!check) return document.createTextNode(PLACEHOLDER);
  const wrapper = document.createElement("div");
  const time = document.createElement("span");
  time.textContent = formatDateTime(check.checked_at);
  wrapper.append(time);
  if (check.status !== "compatible" && (check.detail || check.failure)) {
    const detail = document.createElement("span");
    detail.className = "inst-last-check__detail";
    detail.textContent = check.detail || check.failure;
    detail.title = detail.textContent;
    wrapper.append(detail);
  }
  return wrapper;
}

function renderActionsCell(instance) {
  const actions = document.createElement("div");
  actions.className = "inst-actions";
  actions.append(makeActionButton("Check", "▶", "check", instance));
  if (instance.primary) {
    const reason = "The Primary instance comes from the environment and can't be changed.";
    actions.append(
      makeActionButton("Edit", "✎", "edit", instance, { disabled: true, title: reason }),
      makeActionButton("Delete", "🗑︎", "delete", instance, { disabled: true, title: reason }),
    );
    return actions;
  }
  // The Docker-managed instance (the iris-2 service) can be checked and
  // (de)activated, but not edited or deleted; the backend refuses both too.
  const managed = instance.docker_managed
    ? { disabled: true, title: "Managed by Docker Compose (the iris-2 service): it can't be edited or deleted here." }
    : null;
  actions.append(
    instance.active
      ? makeActionButton("Deactivate", "❚❚", "deactivate", instance)
      : makeActionButton("Activate", "▶", "activate", instance, { variant: "btn--accent-outline" }),
    makeActionButton("Edit", "✎", "edit", instance, managed || {}),
    makeActionButton("Delete", "🗑︎", "delete", instance, managed || { variant: "btn--danger-outline" }),
  );
  return actions;
}

function renderTable() {
  dom.tableBody.replaceChildren();
  for (const instance of instances) {
    const row = document.createElement("tr");
    row.dataset.instanceId = instance.id;
    row.append(
      cell(renderNameCell(instance)),
      cell(instance.id, "data-table__cell--mono"),
      cell(instance.base_url, "data-table__cell--mono"),
      cell(instance.username),
      cell(instance.namespace),
      cell(renderStatusCell(instance)),
      cell(renderLastCheckCell(instance.last_check)),
      cell(renderActionsCell(instance), "inst-actions-cell"),
    );
    dom.tableBody.append(row);
  }
  dom.content.hidden = instances.length === 0;
  dom.empty.hidden = instances.length > 0;
}

// The Primary and the Docker-managed instance: when the screen opens, run the
// existing compatibility check (POST .../check) so their status is current,
// then show the results. User-defined instances are checked on request only.
let systemCheckRunning = false;

async function checkSystemInstances() {
  const targets = instances.filter((instance) => instance.primary || instance.docker_managed);
  if (systemCheckRunning || targets.length === 0) return;
  systemCheckRunning = true;
  try {
    await Promise.allSettled(targets.map((instance) => IrisApi.checkInstance(instance.id)));
  } finally {
    systemCheckRunning = false;
  }
  loadInstances();
}

/** With checkSystem (the screen being opened), also checks the Primary and the Docker-managed instance. */
export async function loadInstances({ checkSystem = false } = {}) {
  if (isLoading) {
    reloadQueued = true;
    return;
  }
  setLoading(true);
  try {
    const response = await IrisApi.getInstances();
    instances = Array.isArray(response && response.instances) ? response.instances : [];
    setErrorBanner("");
    renderTable();
    // Keep the header's instance selector in step (e.g. after (de)activate or delete).
    updateInstanceContextList(instances);
    if (checkSystem) checkSystemInstances();
  } catch (err) {
    setErrorBanner(`Could not load instances. ${errorMessage(err, "An unexpected error occurred.")}`);
  } finally {
    setLoading(false);
  }
  if (reloadQueued) {
    reloadQueued = false;
    loadInstances();
  }
}

function findInstance(id) {
  return instances.find((instance) => instance.id === id) || null;
}

// --- Check result (shared by Test Connection and Check) ---

function renderCheck(container, check) {
  container.replaceChildren();
  const compatible = check.status === "compatible";
  const banner = document.createElement("div");
  banner.className = `banner ${compatible ? "banner--success" : "banner--error"} inst-check__banner`;
  const icon = document.createElement("span");
  icon.className = "banner__icon";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = compatible ? "✓" : "⚠";
  const text = document.createElement("div");
  const title = document.createElement("strong");
  title.className = "inst-check__title";
  title.textContent = (CHECK_STATUS[check.status] || [textOrPlaceholder(check.status)])[0];
  // e.g. "Incompatible — IRIS 2025.3" when the server reported its version.
  const release = typeof check.server_version === "string" && check.server_version.match(/\b(20\d\d\.\d+)\b/);
  if (check.status === "incompatible" && release) title.textContent += ` — IRIS ${release[1]}`;
  const detail = document.createElement("span");
  detail.textContent = compatible
    ? "This instance is compatible with IRIS Command Center."
    : check.detail || check.failure || "The instance did not pass the compatibility check.";
  text.append(title, detail);
  banner.append(icon, text);

  const ok = Array.isArray(check.endpoints_ok) ? check.endpoints_ok : [];
  const missing = Array.isArray(check.endpoints_missing) ? check.endpoints_missing : [];
  const list = document.createElement("dl");
  list.className = "info-list";
  const rows = [
    ["Product", check.product],
    ["Version", check.server_version],
    ["API Version", check.api_version],
    ["Required Endpoints", ok.length + missing.length ? `${ok.length} of ${ok.length + missing.length} available` : null],
  ];
  if (missing.length) rows.push(["Missing Endpoints", missing.join(", ")]);
  rows.push(
    ["Management API", typeof check.mgmnt_api_available === "boolean"
      ? (check.mgmnt_api_available ? "Available" : "Not available")
      : null],
    ["Checked", formatDateTime(check.checked_at)],
  );
  addInfoRows(list, rows);
  container.append(banner, list);
  container.hidden = false;
}

function renderOperationResult(list, result) {
  list.replaceChildren();
  const rows = [
    ["Status", result.status],
    ["Detail", result.detail],
  ];
  if (result.handler_result) rows.push(["Execution Detail", result.handler_result.detail]);
  if (result.verification) {
    rows.push(["Verification Status", result.verification.status]);
    rows.push(["Verification Detail", result.verification.detail]);
  }
  addInfoRows(list, rows);
}

// --- Add / Edit Instance ---

function setPasswordVisible(visible) {
  formDom.password.type = visible ? "text" : "password";
  formDom.passwordToggle.setAttribute("aria-pressed", String(visible));
  formDom.passwordToggle.setAttribute("aria-label", visible ? "Hide password" : "Show password");
}

function setFormBusy(busy, text = "") {
  formDom.loading.hidden = !busy;
  formDom.loadingText.textContent = text;
  formDom.testButton.disabled = busy || formState.done;
  formDom.cancelButton.disabled = busy;
  updateFormSubmitEnabled(busy);
}

// Add: enabled after a compatible test and the confirmation. Edit: Update
// Instance stays clickable (a disabled button silently ignores clicks); a
// click runs the dry run and asks for the confirmation first (handleSubmitClick).
function updateFormSubmitEnabled(busy = false) {
  const ready = formState && (formState.mode === "edit" || (formState.tested && formDom.ackCheckbox.checked));
  formDom.submitButton.disabled = busy || !formState || formState.done || !ready;
}

// Tell the user what's left before the update is sent, by the checkbox.
function askForConfirmation() {
  if (!formDom.testResult.querySelector(".inst-confirm-hint")) {
    const hint = document.createElement("p");
    hint.className = "ns-hint inst-confirm-hint";
    hint.textContent = "Tick the confirmation below, then click Update Instance again to apply this change.";
    formDom.testResult.append(hint);
  }
  formDom.testResult.hidden = false;
  formDom.ackCheckbox.focus();
}

async function handleSubmitClick() {
  if (!formState || formState.done) return;
  if (formState.mode === "edit") {
    if (!formState.tested) {
      // The same dry run as Test Connection; nothing is changed yet.
      await handleFormTest({ preventDefault() {} });
      if (formState && formState.tested) askForConfirmation();
      return;
    }
    if (!formDom.ackCheckbox.checked) {
      askForConfirmation();
      return;
    }
  }
  await submitForm();
}

function showFormError(message) {
  formDom.errorText.textContent = message || "";
  formDom.error.hidden = !message;
}

// Any edit after a test means the test no longer applies.
function clearFormTest() {
  if (!formState || formState.done) return;
  formState.tested = false;
  formDom.testResult.hidden = true;
  formDom.testResult.replaceChildren();
  formDom.ack.hidden = true;
  formDom.ackCheckbox.checked = false;
  formDom.result.hidden = true;
  showFormError("");
  updateFormSubmitEnabled();
}

function openForm(mode, instance = null) {
  dialogToken += 1;
  formState = { mode, instance, tested: false, done: false, token: dialogToken };
  const isEdit = mode === "edit";
  formDom.form.reset();
  for (const input of formDom.form.querySelectorAll("input")) input.disabled = false;
  setPasswordVisible(false);
  formDom.title.textContent = isEdit ? "Edit Instance" : "Add Instance";
  formDom.hint.textContent = isEdit
    ? "Test Connection is a dry run of the update: when the instance is active and its URL, username, namespace " +
      "or password changes, the backend re-checks the connection. Nothing is saved until you confirm."
    : "Enter the connection details and test them. Add Instance is enabled only after a compatible test; " +
      "the password is stored in the IRIS Wallet, never in plain text.";
  formDom.name.value = isEdit ? instance.name : "";
  formDom.url.value = isEdit ? instance.base_url : "";
  formDom.username.value = isEdit ? instance.username : "";
  formDom.namespace.value = isEdit ? instance.namespace : "USER";
  formDom.password.value = "";
  formDom.password.placeholder = isEdit ? "Enter new password to change (leave blank to keep current)" : "";
  formDom.passwordRequired.hidden = isEdit;
  formDom.ackLabel.textContent = isEdit
    ? "I confirm that I want to update this instance."
    : "I confirm that I want to add this instance.";
  formDom.submitButton.textContent = isEdit ? "Update Instance" : "Add Instance";
  formDom.cancelButton.textContent = "Cancel";
  formDom.testButton.hidden = false;
  formDom.submitButton.hidden = false;
  formDom.testResult.hidden = true;
  formDom.testResult.replaceChildren();
  formDom.ack.hidden = true;
  formDom.result.hidden = true;
  showFormError("");
  setFormBusy(false);
  formDom.backdrop.hidden = false;
  formDom.drawer.hidden = false;
  formDom.name.focus();
}

function closeForm() {
  dialogToken += 1;
  formDom.password.value = "";
  setPasswordVisible(false);
  formDom.backdrop.hidden = true;
  formDom.drawer.hidden = true;
  formState = null;
}

function readForm() {
  return {
    name: formDom.name.value.trim(),
    base_url: formDom.url.value.trim(),
    username: formDom.username.value.trim(),
    namespace: formDom.namespace.value.trim(),
  };
}

function missingFields(fields, needPassword) {
  const labels = { name: "Name", base_url: "URL", username: "Username", namespace: "Namespace" };
  const missing = Object.keys(labels).filter((key) => !fields[key]).map((key) => labels[key]);
  if (needPassword && !formDom.password.value) missing.push("Password");
  return missing;
}

// Edit: only the fields that differ, plus the password if one was typed.
function editChanges(fields) {
  const changes = {};
  for (const key of ["name", "base_url", "username", "namespace"]) {
    if (fields[key] !== formState.instance[key]) changes[key] = fields[key];
  }
  if (formDom.password.value) changes.password = formDom.password.value;
  return changes;
}

function failureDetail(result, fallback) {
  return (result && result.handler_result && result.handler_result.detail) || (result && result.detail) || fallback;
}

async function handleFormTest(event) {
  event.preventDefault();
  if (!formState || formState.done) return;
  clearFormTest();
  const { token, mode } = formState;
  const fields = readForm();
  const missing = missingFields(fields, mode === "add");
  if (missing.length) {
    showFormError(`Required: ${missing.join(", ")}.`);
    return;
  }
  // Edit: the backend's dry run validates the update, including one that
  // changes nothing (it re-checks the connection only when that changes).
  const changes = mode === "edit" ? editChanges(fields) : null;

  setFormBusy(true, mode === "add" ? "Testing connection…" : "Checking the update with the backend (dry run)…");
  try {
    if (mode === "add") {
      // /instances/test takes only the connection fields (no name).
      const { name: _name, ...connection } = fields;
      const check = await IrisApi.testInstanceConnection({ ...connection, password: formDom.password.value });
      if (token !== dialogToken) return;
      renderCheck(formDom.testResult, check);
      formState.tested = check.status === "compatible";
    } else {
      const preview = await IrisApi.updateInstance(formState.instance.id, changes, true, true);
      if (token !== dialogToken) return;
      const handlerResult = preview && preview.handler_result;
      const check = handlerResult && handlerResult.data && handlerResult.data.check;
      formState.tested = preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success";
      if (check) renderCheck(formDom.testResult, check);
      if (formState.tested) {
        const note = document.createElement("p");
        note.className = "ns-hint";
        note.textContent = check
          ? handlerResult.detail
          : `${handlerResult.detail} No connection re-check is needed for this change.`;
        formDom.testResult.append(note);
        formDom.testResult.hidden = false;
      } else {
        showFormError(failureDetail(preview, "This update could not be validated."));
      }
    }
    formDom.ack.hidden = !formState.tested;
  } catch (err) {
    if (token !== dialogToken) return;
    showFormError(errorMessage(err, "An unexpected error occurred while testing the connection."));
  } finally {
    if (token === dialogToken) setFormBusy(false);
  }
}

async function submitForm() {
  if (!formState || !formState.tested || !formDom.ackCheckbox.checked || formState.done) return;
  const { token, mode } = formState;
  const fields = readForm();
  const instanceId = mode === "edit" ? formState.instance.id : null;
  showFormError("");
  setFormBusy(true, mode === "add" ? "Adding instance…" : "Updating instance…");
  try {
    const result = mode === "add"
      ? await IrisApi.createInstance({ ...fields, password: formDom.password.value }, true, false)
      : await IrisApi.updateInstance(instanceId, editChanges(fields), true, false);
    // Refresh even if the dialog was closed meanwhile: the change happened.
    if (result.status === "success" || result.status === "verification_failed") loadInstances();
    if (token !== dialogToken) return;
    renderOperationResult(formDom.resultList, result);
    formDom.result.hidden = false;
    if (result.status === "success") {
      formState.done = true;
      formDom.password.value = "";
      for (const input of formDom.form.querySelectorAll("input")) input.disabled = true;
      formDom.ack.hidden = true;
      formDom.testButton.hidden = true;
      formDom.submitButton.hidden = true;
      formDom.cancelButton.textContent = "Close";
    } else {
      // Not changed (or not verified): the user can fix the fields and test again.
      formState.tested = false;
      formDom.ack.hidden = true;
      formDom.ackCheckbox.checked = false;
    }
  } catch (err) {
    if (token !== dialogToken) return;
    showFormError(errorMessage(err, "An unexpected error occurred while saving the instance."));
  } finally {
    if (token === dialogToken) setFormBusy(false);
  }
}

// --- Activate / Deactivate / Delete ---

function updateConfirmEnabled(busy = false) {
  confirmDom.confirmButton.disabled =
    busy || !confirmState || confirmState.done || !confirmState.previewed || !confirmDom.ackCheckbox.checked;
}

function showConfirmError(message) {
  confirmDom.errorText.textContent = message || "";
  confirmDom.error.hidden = !message;
}

function setConfirmBusy(busy, text = "") {
  confirmDom.loading.hidden = !busy;
  confirmDom.loadingText.textContent = text;
  confirmDom.cancelButton.disabled = busy;
  updateConfirmEnabled(busy);
}

function runConfirmAction(state, dryRun) {
  const { action, instance } = state;
  return action === "delete"
    ? IrisApi.deleteInstance(instance.id, true, dryRun)
    : IrisApi.setInstanceActive(instance.id, action === "activate", true, dryRun);
}

async function openConfirm(action, instance) {
  const config = CONFIRM_ACTIONS[action];
  dialogToken += 1;
  confirmState = { action, instance, previewed: false, done: false, token: dialogToken };
  const { token } = confirmState;

  confirmDom.title.textContent = config.title;
  confirmDom.heading.textContent = config.heading;
  confirmDom.message.textContent = config.message;
  confirmDom.banner.className = `banner inst-confirm-banner ${config.banner}`;
  confirmDom.target.replaceChildren();
  addInfoRows(confirmDom.target, [
    ["Instance", `${instance.name} (${instance.id})`],
    ["URL", instance.base_url],
  ]);
  confirmDom.ackLabel.textContent = config.ack;
  confirmDom.ackCheckbox.checked = false;
  confirmDom.ack.hidden = true;
  confirmDom.preview.hidden = true;
  confirmDom.result.hidden = true;
  confirmDom.confirmButton.hidden = false;
  confirmDom.confirmButton.textContent = config.button;
  confirmDom.confirmButton.className = `btn ${config.buttonClass}`;
  confirmDom.cancelButton.textContent = "Cancel";
  showConfirmError("");
  confirmDom.backdrop.hidden = false;
  confirmDom.drawer.hidden = false;

  setConfirmBusy(
    true,
    action === "activate"
      ? "Checking the instance with the backend (dry run, live compatibility check)…"
      : "Checking with the backend (dry run)…",
  );
  try {
    const preview = await runConfirmAction(confirmState, true);
    if (token !== dialogToken) return;
    const handlerResult = preview && preview.handler_result;
    if (preview.status === "dry_run" && handlerResult && handlerResult.outcome === "success") {
      confirmState.previewed = true;
      confirmDom.preview.textContent = handlerResult.detail;
      confirmDom.preview.hidden = false;
      confirmDom.ack.hidden = false;
    } else {
      showConfirmError(failureDetail(preview, "This change could not be validated."));
    }
  } catch (err) {
    if (token !== dialogToken) return;
    showConfirmError(errorMessage(err, "An unexpected error occurred while checking this change."));
  } finally {
    if (token === dialogToken) setConfirmBusy(false);
  }
}

function closeConfirm() {
  dialogToken += 1;
  confirmDom.backdrop.hidden = true;
  confirmDom.drawer.hidden = true;
  confirmState = null;
}

async function submitConfirm() {
  if (!confirmState || !confirmState.previewed || !confirmDom.ackCheckbox.checked || confirmState.done) return;
  const { token } = confirmState;
  showConfirmError("");
  setConfirmBusy(true, CONFIRM_ACTIONS[confirmState.action].running);
  try {
    const result = await runConfirmAction(confirmState, false);
    if (result.status === "success" || result.status === "verification_failed") loadInstances();
    if (token !== dialogToken) return;
    renderOperationResult(confirmDom.resultList, result);
    confirmDom.result.hidden = false;
    confirmState.done = true;
    confirmDom.ack.hidden = true;
    confirmDom.preview.hidden = true;
    confirmDom.confirmButton.hidden = true;
    confirmDom.cancelButton.textContent = "Close";
  } catch (err) {
    if (token !== dialogToken) return;
    showConfirmError(errorMessage(err, "An unexpected error occurred while applying this change."));
  } finally {
    if (token === dialogToken) setConfirmBusy(false);
  }
}

// --- Check (saved as last_check) ---

async function openCheck(instance) {
  dialogToken += 1;
  const token = dialogToken;
  checkDom.subtitle.textContent = `${instance.name} (${instance.id}) · ${instance.base_url}`;
  checkDom.result.hidden = true;
  checkDom.result.replaceChildren();
  checkDom.error.hidden = true;
  checkDom.loading.hidden = false;
  checkDom.backdrop.hidden = false;
  checkDom.drawer.hidden = false;
  checkDom.doneButton.focus();
  try {
    const view = await IrisApi.checkInstance(instance.id);
    loadInstances();
    if (token !== dialogToken) return;
    if (view && view.last_check) renderCheck(checkDom.result, view.last_check);
  } catch (err) {
    if (token !== dialogToken) return;
    checkDom.errorText.textContent = errorMessage(err, "An unexpected error occurred while checking the instance.");
    checkDom.error.hidden = false;
  } finally {
    if (token === dialogToken) checkDom.loading.hidden = true;
  }
}

function closeCheck() {
  dialogToken += 1;
  checkDom.backdrop.hidden = true;
  checkDom.drawer.hidden = true;
}

export function initInstancesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadInstances();
  });
  dom.addButton.addEventListener("click", () => openForm("add"));

  // One delegated listener for every row's action buttons.
  dom.tableBody.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button || button.disabled) return;
    const instance = findInstance(button.dataset.instanceId);
    if (!instance) return;
    const { action } = button.dataset;
    if (action === "check") openCheck(instance);
    else if (action === "edit" && !instance.primary && !instance.docker_managed) openForm("edit", instance);
    else if (CONFIRM_ACTIONS[action] && !instance.primary && !(action === "delete" && instance.docker_managed)) {
      openConfirm(action, instance);
    }
  });

  formDom.form.addEventListener("submit", handleFormTest);
  formDom.form.addEventListener("input", (event) => {
    if (event.target !== formDom.ackCheckbox) clearFormTest();
  });
  formDom.ackCheckbox.addEventListener("change", () => updateFormSubmitEnabled());
  formDom.submitButton.addEventListener("click", () => {
    handleSubmitClick();
  });
  formDom.passwordToggle.addEventListener("click", () => {
    setPasswordVisible(formDom.password.type === "password");
  });
  formDom.cancelButton.addEventListener("click", closeForm);
  formDom.close.addEventListener("click", closeForm);
  formDom.backdrop.addEventListener("click", closeForm);

  confirmDom.ackCheckbox.addEventListener("change", () => updateConfirmEnabled());
  confirmDom.confirmButton.addEventListener("click", () => {
    submitConfirm();
  });
  confirmDom.cancelButton.addEventListener("click", closeConfirm);
  confirmDom.close.addEventListener("click", closeConfirm);
  confirmDom.backdrop.addEventListener("click", closeConfirm);

  checkDom.doneButton.addEventListener("click", closeCheck);
  checkDom.close.addEventListener("click", closeCheck);
  checkDom.backdrop.addEventListener("click", closeCheck);

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (!formDom.drawer.hidden) closeForm();
    if (!confirmDom.drawer.hidden) closeConfirm();
    if (!checkDom.drawer.hidden) closeCheck();
  });
}
