// API Capability Explorer view: fetches GET /api/iris/capabilities ONLY
// (via IrisApi.getCapabilities) and renders it. No other endpoint is
// called from this module, and no mutating HTTP method is used anywhere
// in it.
//
// Unlike investigation.js, filtering here never re-fetches from the
// backend: the full capability list is small and static (see
// backend/app/capabilities.py), so it is fetched once per view-open/
// Refresh click and then searched/filtered entirely client-side, the same
// list already cached in `allCapabilities` below.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  loadingState: document.getElementById("capabilities-loading-state"),
  errorBanner: document.getElementById("capabilities-error-banner"),
  errorBannerText: document.getElementById("capabilities-error-banner-text"),
  refreshButton: document.getElementById("capabilities-refresh-button"),
  summary: document.getElementById("capabilities-summary"),
  countLabel: document.getElementById("capabilities-count"),
  filterForm: document.getElementById("capabilities-filter-form"),
  filterSearch: document.getElementById("capabilities-filter-search"),
  filterVerification: document.getElementById("capabilities-filter-verification"),
  filterAvailable: document.getElementById("capabilities-filter-available"),
  tableWrapper: document.getElementById("capabilities-table-wrapper"),
  tableBody: document.getElementById("capabilities-table-body"),
  empty: document.getElementById("capabilities-empty"),
};

// The full list from the last successful fetch — filters below only ever
// re-render a subset of this, never re-fetch it.
let allCapabilities = [];

function setLoading(isLoading) {
  dom.loadingState.hidden = !isLoading;
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

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function makeCell(text) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

// Same badge convention already used by observability.js's execution
// traces table (status-badge / status-badge--ok / status-badge--neutral).
function makeBadge(label, isPositive) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${isPositive ? "status-badge--ok" : "status-badge--neutral"}`;
  badge.textContent = label;
  return badge;
}

function makeBadgeCell(label, isPositive, title) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  cell.append(makeBadge(label, isPositive));
  if (title) cell.title = title;
  return cell;
}

function matchesFilters(entry, filters) {
  if (filters.verification && entry.verification_status !== filters.verification) return false;
  if (filters.available === "true" && entry.available !== true) return false;
  if (filters.available === "false" && entry.available !== false) return false;
  if (filters.search) {
    const haystack = `${entry.capability} ${entry.endpoint} ${entry.notes}`.toLowerCase();
    if (!haystack.includes(filters.search)) return false;
  }
  return true;
}

function collectFilters() {
  return {
    search: dom.filterSearch.value.trim().toLowerCase(),
    verification: dom.filterVerification.value,
    available: dom.filterAvailable.value,
  };
}

function renderRows(entries) {
  dom.tableBody.replaceChildren();

  if (entries.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.empty.hidden = true;
  dom.tableWrapper.hidden = false;
  dom.countLabel.textContent = `Showing ${entries.length} of ${allCapabilities.length} capabilities`;

  for (const entry of entries) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(entry.capability)),
      makeCell(textOrPlaceholder(entry.endpoint)),
      makeCell(textOrPlaceholder(entry.method)),
      makeCell(textOrPlaceholder(entry.required_privilege)),
      makeBadgeCell(
        textOrPlaceholder(entry.verification_status),
        entry.verification_status === "Verified",
      ),
      makeBadgeCell(
        entry.available ? "Available" : "Not available",
        entry.available === true,
        entry.command_center_path
          ? `${entry.command_center_method || ""} ${entry.command_center_path}`.trim()
          : "Not exposed as its own Command Center route",
      ),
      makeCell(textOrPlaceholder(entry.notes)),
    );
    dom.tableBody.append(row);
  }
}

/** Re-renders from the already-fetched `allCapabilities` list using the
 * current filter values — never triggers a network request. */
function applyFilters() {
  const filters = collectFilters();
  renderRows(allCapabilities.filter((entry) => matchesFilters(entry, filters)));
}

function renderSummary() {
  const verifiedCount = allCapabilities.filter((c) => c.verification_status === "Verified").length;
  const availableCount = allCapabilities.filter((c) => c.available).length;
  dom.summary.textContent =
    `${allCapabilities.length} capabilities documented · ` +
    `${verifiedCount} verified · ${availableCount} available in this Command Center`;
}

/**
 * Fetches GET /api/iris/capabilities and renders it. This is the ONLY
 * network call this module makes — no mutating request exists anywhere in
 * this file.
 */
export async function loadCapabilities() {
  setLoading(true);
  setErrorBanner(null);

  let response;
  try {
    response = await IrisApi.getCapabilities();
  } catch (err) {
    const message =
      err instanceof ApiError
        ? "Could not load capability data. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading capability data.";
    setErrorBanner(message);
    allCapabilities = [];
    dom.summary.textContent = "";
    renderRows([]);
    setLoading(false);
    return;
  }

  allCapabilities = Array.isArray(response.capabilities) ? response.capabilities : [];
  renderSummary();
  applyFilters();
  setLoading(false);
}

export function initCapabilitiesControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadCapabilities();
  });
  // Filtering is client-side and instant — no network request, so every
  // input re-renders immediately rather than waiting for a submit/click.
  dom.filterSearch.addEventListener("input", applyFilters);
  dom.filterVerification.addEventListener("change", applyFilters);
  dom.filterAvailable.addEventListener("change", applyFilters);
  // Pressing Enter in the search field would otherwise submit this <form>
  // and reload the page; filtering already happens live via the "input"
  // listener above, so submitting just needs to be a harmless no-op.
  dom.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
  });
}
