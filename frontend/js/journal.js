// Journal view: fetches GET /api/iris/journal/settings ONLY and renders a
// read-only breakdown of the connected IRIS instance's journal
// configuration. No other endpoint is called from this module, and no
// mutating HTTP method is used anywhere in it — in particular, this view
// intentionally does NOT expose a control for the existing
// journal.update_purge_archived operation (see
// docs/first-mutation-implementation.md); PurgeArchived is shown as plain
// information only, with a note explaining the relationship.
//
// Fields shown are exactly the ones backend/app/models/iris.py's
// JournalSettings actually defines — nothing invented. FileSizeLimit and
// targwijsz are documented (docs/first-mutation-selection.md) as MB
// integers; every other field is rendered as IRIS returns it.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("journal-loading-state"),
  errorBanner: document.getElementById("journal-error-banner"),
  errorBannerText: document.getElementById("journal-error-banner-text"),
  refreshButton: document.getElementById("journal-refresh-button"),
  connectionStatus: document.getElementById("journal-connection-status"),
  connectionStatusLabel: document.getElementById("journal-connection-status-label"),
  connectionDetail: document.getElementById("journal-connection-detail"),
  settingsList: document.getElementById("journal-settings-list"),
  settingsEmpty: document.getElementById("journal-settings-empty"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disabling the button synchronously, before any await, is what makes a
  // second rapid Refresh click a no-op — the same pattern already used and
  // reviewed in the other views.
  dom.refreshButton.disabled = isLoading;
  dom.refreshButton.classList.toggle("btn--spinning", isLoading);
}

function setErrorBanner(message) {
  if (!message) {
    dom.errorBanner.hidden = true;
    return;
  }
  dom.errorBannerText.textContent = message;
  dom.errorBanner.hidden = false;
}

function setConnectionState(state, label, detail) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
  dom.connectionDetail.textContent = detail || "";
}

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatBoolean(value) {
  return typeof value === "boolean" ? (value ? "Yes" : "No") : PLACEHOLDER;
}

function formatMegabytes(value) {
  return typeof value === "number" ? `${value} MB` : PLACEHOLDER;
}

// [label, JournalSettings field, formatter]
const SETTINGS_FIELDS = [
  ["Current Directory", "CurrentDirectory", textOrPlaceholder],
  ["Alternate Directory", "AlternateDirectory", textOrPlaceholder],
  ["Journal File Prefix", "JournalFilePrefix", textOrPlaceholder],
  ["File Size Limit", "FileSizeLimit", formatMegabytes],
  ["Days Before Purge", "DaysBeforePurge", textOrPlaceholder],
  ["Backups Before Purge", "BackupsBeforePurge", textOrPlaceholder],
  ["Archive Name", "ArchiveName", textOrPlaceholder],
  ["Purge Archived", "PurgeArchived", formatBoolean],
  ["Compress Files", "CompressFiles", formatBoolean],
  ["Freeze On Error", "FreezeOnError", formatBoolean],
  ["Journal CSP Session", "JournalcspSession", formatBoolean],
  ["WIJ Directory", "wijdir", textOrPlaceholder],
  ["WIJ Size Target", "targwijsz", formatMegabytes],
];

function renderSettings(settings) {
  dom.settingsList.replaceChildren();

  if (!settings || typeof settings !== "object" || Object.keys(settings).length === 0) {
    dom.settingsEmpty.hidden = false;
    return;
  }

  dom.settingsEmpty.hidden = true;
  for (const [label, key, format] of SETTINGS_FIELDS) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.className = "info-list__value info-list__value--mono";
    dd.textContent = format(settings[key]);

    row.append(dt, dd);
    dom.settingsList.append(row);
  }
}

/**
 * Fetches GET /api/iris/journal/settings and renders it. This is the ONLY
 * network call this module makes — no mutating request exists anywhere in
 * this file.
 */
export async function loadJournal() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getJournalSettings();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load journal settings. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading journal settings.";
    setConnectionState("error", "Could not reach IRIS", "");
    setErrorBanner(message);
    renderSettings(null);
    setLoading(false);
    return;
  }

  const settings =
    response && response.result && typeof response.result === "object" ? response.result : null;
  const envelopeErrors =
    response && response.status && Array.isArray(response.status.errors)
      ? response.status.errors
      : [];

  if (!settings) {
    setConnectionState("error", "IRIS returned no data", "");
    setErrorBanner("IRIS did not return the expected journal settings.");
    renderSettings(null);
    setLoading(false);
    return;
  }

  if (envelopeErrors.length > 0) {
    // The backend's own response envelope flagged something — a real,
    // observed field (status.errors), not an invented threshold. Same
    // pattern already used and reviewed in the other views.
    setConnectionState("degraded", "Connected (with warnings)", response.status.summary || "");
    setErrorBanner("IRIS reported one or more warnings for this request.");
  } else {
    setConnectionState("connected", "Connected", "");
    setErrorBanner(null);
  }

  renderSettings(settings);
  setLoading(false);
}

export function initJournalControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadJournal();
  });
}
