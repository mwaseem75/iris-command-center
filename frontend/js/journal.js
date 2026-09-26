// Journal page: read-only view of the journal settings (one call to
// GET /api/iris/journal/settings). Changing PurgeArchived is done from the
// Operations page, not here.
//
// FileSizeLimit and targwijsz come back as MB integers; everything else is
// shown as IRIS returns it.

import { IrisApi, ApiError } from "./api.js";
import { navigateTo } from "./nav.js";

const PLACEHOLDER = "—"; // shown for empty values

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
  kpiPurgeArchived: document.getElementById("journal-kpi-purge-archived"),
  kpiDaysBeforePurge: document.getElementById("journal-kpi-days-before-purge"),
  kpiBackupsBeforePurge: document.getElementById("journal-kpi-backups-before-purge"),
  kpiFileSizeLimit: document.getElementById("journal-kpi-file-size-limit"),
  kpiCompressFiles: document.getElementById("journal-kpi-compress-files"),
  kpiFreezeOnError: document.getElementById("journal-kpi-freeze-on-error"),
  openOperationsButton: document.getElementById("journal-open-operations-button"),
  openInvestigationButton: document.getElementById("journal-open-investigation-button"),
};

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
  // Disable right away so a double click doesn't fire two requests.
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

// Show a boolean setting as a Yes/No badge.
function makeBooleanBadge(value) {
  if (typeof value !== "boolean") {
    const span = document.createElement("span");
    span.textContent = PLACEHOLDER;
    return span;
  }
  // Green for on, gray for off; neither value is "bad" here.
  const badge = document.createElement("span");
  badge.className = `status-badge ${value ? "status-badge--ok" : "status-badge--neutral"}`;
  badge.textContent = value ? "Yes" : "No";
  return badge;
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

// Fill the KPI cards (null resets them to the placeholder).
function renderKpis(settings) {
  const s = settings && typeof settings === "object" ? settings : {};
  dom.kpiPurgeArchived.textContent = formatBoolean(s.PurgeArchived);
  dom.kpiDaysBeforePurge.textContent = textOrPlaceholder(s.DaysBeforePurge);
  dom.kpiBackupsBeforePurge.textContent =
    s.BackupsBeforePurge === undefined || s.BackupsBeforePurge === null
      ? ""
      : `backups before purge: ${textOrPlaceholder(s.BackupsBeforePurge)}`;
  dom.kpiFileSizeLimit.textContent = formatMegabytes(s.FileSizeLimit);
  dom.kpiCompressFiles.textContent = formatBoolean(s.CompressFiles);
  dom.kpiFreezeOnError.textContent = formatBoolean(s.FreezeOnError);
}

function renderSettings(settings) {
  renderKpis(settings);
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
    // Booleans get a badge, everything else is plain text.
    if (format === formatBoolean) {
      dd.append(makeBooleanBadge(settings[key]));
    } else {
      dd.textContent = format(settings[key]);
    }

    row.append(dt, dd);
    dom.settingsList.append(row);
  }
}

/** Load the journal settings and render the page. */
export async function loadJournal() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…", "");

  let response;
  try {
    response = await IrisApi.getJournalSettings();
  } catch (err) {
    // ApiError messages are already safe to show (see api.js).
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
    // IRIS returned warnings in status.errors.
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
  // These buttons just switch pages.
  dom.openOperationsButton.addEventListener("click", () => navigateTo("operations"));
  dom.openInvestigationButton.addEventListener("click", () => navigateTo("investigation"));
}
