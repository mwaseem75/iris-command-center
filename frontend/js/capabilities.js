// API Capability Explorer: GET /api/iris/capabilities, shown as a searchable
// table.
//
// The list is small and static, so it's fetched once per visit/Refresh and
// filtered in the browser (unlike Investigation, which searches on the
// server).
//
// Instance-aware (instance selector): the selected instance's last
// compatibility check (its last_check in GET /api/iris/instances: status,
// product, versions, Management API, and which of the required endpoints
// answered) is shown, and each capability is marked Answered / Missing on it,
// or Not checked when the check doesn't cover that endpoint. Nothing is
// inferred beyond that check; an instance with none recorded says so.

import { IrisApi, ApiError } from "./api.js";
import { getInstanceContext } from "./instance-context.js";
import { navigateTo } from "./nav.js";
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
  filterInstance: document.getElementById("capabilities-filter-instance"),
  instanceColumn: document.getElementById("capabilities-instance-column"),
  instanceSummary: document.getElementById("capabilities-instance-summary"),
  instanceFacts: document.getElementById("capabilities-instance-facts"),
  openInstances: document.getElementById("capabilities-open-instances"),
};

// The last fetched list; filtering only re-renders part of it.
let allCapabilities = [];
// The selected instance's last compatibility check (null: none recorded),
// or undefined when it couldn't be loaded.
let instanceCheck = undefined;

const ADMIN_PREFIX = "/api/admin";
const ON_INSTANCE = {
  answered: ["Answered", "status-badge--ok"],
  missing: ["Missing", "status-badge--error"],
  not_checked: ["Not checked", "status-badge--neutral"],
};

function viewedName() {
  const instance = getInstanceContext().instance;
  return instance ? instance.name : "Primary";
}

// Whether the last check got as far as probing the endpoints. A check that
// failed earlier (unreachable, auth_failed, not IRIS...) records none.
function endpointsChecked() {
  return Boolean(instanceCheck)
    && (instanceCheck.endpoints_ok || []).length + (instanceCheck.endpoints_missing || []).length > 0;
}

// What the selected instance's last check found for this capability's endpoint.
function onInstance(entry) {
  if (!endpointsChecked()) return null;
  const path = typeof entry.endpoint === "string" ? entry.endpoint.replace(ADMIN_PREFIX, "") : "";
  if ((instanceCheck.endpoints_ok || []).includes(path)) return "answered";
  if ((instanceCheck.endpoints_missing || []).includes(path)) return "missing";
  return "not_checked";
}

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
  if (filters.instance && onInstance(entry) !== filters.instance) return false;
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
    instance: dom.filterInstance.value,
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
      onInstanceCell(entry),
      makeCell(textOrPlaceholder(entry.notes)),
    );
    dom.tableBody.append(row);
  }
}

function onInstanceCell(entry) {
  const state = onInstance(entry);
  if (!state) {
    return makeCell(PLACEHOLDER);
  }
  const [label, variant] = ON_INSTANCE[state];
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = label;
  cell.append(badge);
  cell.title = state === "not_checked"
    ? "The compatibility check covers the verified GET endpoints Command Center reads; this one isn't among them."
    : `In ${viewedName()}'s last compatibility check`;
  return cell;
}

function addFact(label, value) {
  const row = document.createElement("div");
  row.className = "info-list__row";
  const dt = document.createElement("dt");
  dt.textContent = label;
  const dd = document.createElement("dd");
  dd.className = "info-list__value";
  dd.textContent = textOrPlaceholder(value);
  row.append(dt, dd);
  dom.instanceFacts.append(row);
}

// The selected instance's last compatibility check, as recorded.
function renderInstance() {
  const ctx = getInstanceContext();
  const name = viewedName();
  dom.instanceColumn.textContent = `On ${name}`;
  dom.instanceFacts.replaceChildren();
  if (instanceCheck === undefined) {
    dom.instanceSummary.textContent = `Could not load ${name}'s compatibility information.`;
    return;
  }
  if (instanceCheck === null) {
    const primary = !ctx.instance || ctx.instance.primary;
    dom.instanceSummary.textContent = `No compatibility check is recorded for ${name}${primary ? " since the backend started" : ""}. ` +
      "Run Check on the Instances screen to record which APIs it offers.";
    return;
  }
  const ok = (instanceCheck.endpoints_ok || []).length;
  const missing = (instanceCheck.endpoints_missing || []).length;
  dom.instanceSummary.textContent = endpointsChecked()
    ? `${name}'s last compatibility check: ${ok} of ${ok + missing} required System ` +
      `Administration API endpoints answered${missing ? `, ${missing} missing` : ""}.`
    : `${name}'s last compatibility check ended before its API endpoints were checked ` +
      `(result: ${String(instanceCheck.status || "unknown").replace(/_/g, " ")}).` +
      `${instanceCheck.detail ? ` ${instanceCheck.detail}` : ""} Run Check again on the Instances screen.`;
  const checkedAt = new Date(instanceCheck.checked_at);
  addFact("Check result", String(instanceCheck.status || "").replace(/_/g, " "));
  addFact("Checked", Number.isNaN(checkedAt.getTime()) ? instanceCheck.checked_at : checkedAt.toLocaleString());
  addFact("Product", instanceCheck.product);
  addFact("Server version", instanceCheck.server_version);
  addFact("API version", instanceCheck.api_version);
  addFact("Management API (/api/mgmnt)", typeof instanceCheck.mgmnt_api_available === "boolean"
    ? (instanceCheck.mgmnt_api_available ? "Available" : "Not available") : null);
  if (instanceCheck.detail) addFact("Detail", instanceCheck.detail);
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
  const answered = allCapabilities.filter((c) => onInstance(c) === "answered").length;
  dom.summary.textContent =
    `${allCapabilities.length} capabilities documented · ` +
    `${verifiedCount} verified · ${availableCount} available in this Command Center` +
    (endpointsChecked() ? ` · ${answered} answered on ${viewedName()}` : "");
  renderOverview();
}

/** Load GET /api/iris/capabilities and the selected instance's check, and render them. */
export async function loadCapabilities() {
  setLoading(true);
  setErrorBanner(null);

  const instanceId = getInstanceContext().instanceId;
  const [capabilities, registry] = await Promise.allSettled([IrisApi.getCapabilities(), IrisApi.getInstances()]);
  const listed = registry.status === "fulfilled" && Array.isArray(registry.value?.instances)
    ? registry.value.instances.find((instance) => instance.id === instanceId) : undefined;
  instanceCheck = listed ? listed.last_check || null : undefined;
  renderInstance();

  let response;
  try {
    if (capabilities.status === "rejected") throw capabilities.reason;
    response = capabilities.value;
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
  dom.filterInstance.addEventListener("change", applyFilters);
  dom.openInstances.addEventListener("click", () => navigateTo("instances"));
  // Stop Enter from submitting the form and reloading the page; filtering
  // already happens on input.
  dom.filterForm.addEventListener("submit", (event) => {
    event.preventDefault();
  });
}
