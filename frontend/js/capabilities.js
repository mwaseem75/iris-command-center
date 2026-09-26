// API Capability Explorer: GET /api/iris/capabilities, shown as a searchable
// table.
//
// The list is small and static, so it's fetched once per visit/Refresh and
// filtered in the browser (unlike Investigation, which searches on the
// server).

import { IrisApi, ApiError } from "./api.js";
import { countBy, renderDonut } from "./viz.js";

const PLACEHOLDER = "—";  // shown for empty values

const dom = {
  loadingState: document.getElementById("capabilities-loading-state"),
  errorBanner: document.getElementById("capabilities-error-banner"),
  errorBannerText: document.getElementById("capabilities-error-banner-text"),
  refreshButton: document.getElementById("capabilities-refresh-button"),
  summary: document.getElementById("capabilities-summary"),
  overview: document.getElementById("capabilities-overview"),
  vizVerification: document.getElementById("capabilities-viz-verification"),
  vizAvailability: document.getElementById("capabilities-viz-availability"),
  countLabel: document.getElementById("capabilities-count"),
  filterForm: document.getElementById("capabilities-filter-form"),
  filterSearch: document.getElementById("capabilities-filter-search"),
  filterVerification: document.getElementById("capabilities-filter-verification"),
  filterAvailable: document.getElementById("capabilities-filter-available"),
  tableWrapper: document.getElementById("capabilities-table-wrapper"),
  tableBody: document.getElementById("capabilities-table-body"),
  empty: document.getElementById("capabilities-empty"),
};

// The last fetched list; filtering only re-renders part of it.
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

// Same badge classes as the Observability traces table.
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

/** Re-render from `allCapabilities` with the current filters (no request). */
function applyFilters() {
  const filters = collectFilters();
  renderRows(allCapabilities.filter((entry) => matchesFilters(entry, filters)));
}

/**
 * Two donuts over the whole list (not the filtered rows), like the summary
 * text. Hidden when there's nothing to show.
 */
function renderOverview() {
  if (allCapabilities.length === 0) {
    dom.overview.hidden = true;
    return;
  }
  dom.overview.hidden = false;
  renderDonut(dom.vizVerification, countBy(allCapabilities, (c) => c.verification_status || "Unknown"), {
    size: 76,
    centerValue: allCapabilities.length,
    centerLabel: "total",
  });
  renderDonut(
    dom.vizAvailability,
    countBy(allCapabilities, (c) => (c.available ? "Available" : "Not available")),
    { size: 76, centerValue: allCapabilities.length, centerLabel: "total" },
  );
}

function renderSummary() {
  const verifiedCount = allCapabilities.filter((c) => c.verification_status === "Verified").length;
  const availableCount = allCapabilities.filter((c) => c.available).length;
  dom.summary.textContent =
    `${allCapabilities.length} capabilities documented · ` +
    `${verifiedCount} verified · ${availableCount} available in this Command Center`;
  renderOverview();
}

/** Load GET /api/iris/capabilities and render it. */
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
    dom.overview.hidden = true;
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
  // Filtering is local, so update on every keystroke.
  dom.filterSearch.addEventListener("input", applyFilters);
  dom.filterVerification.addEventListener("change", applyFilters);
  dom.filterAvailable.addEventListener("change", applyFilters);
  // Stop Enter from submitting the form and reloading the page; filtering
  // already happens on input.
  dom.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
  });
}
