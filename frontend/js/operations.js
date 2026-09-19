// Operations view: fetches GET /api/iris/operations ONLY — a read-only
// listing of the operations already registered in the backend's
// authorization/execution framework (backend/app/authorization/operations.py).
// No other endpoint is called from this module, and no mutating HTTP
// method is used anywhere in it.
//
// GET /api/iris/operations itself makes NO request to IRIS: it serializes
// the backend's own static OPERATION_REGISTRY. That is why operation
// names, descriptions, required privileges, and confirmation rules are
// never hardcoded here as JavaScript literals — this view only displays
// whatever that single, already-existing source of truth returns.
//
// This view deliberately contains NO execution control, confirmation
// checkbox, or "force"/"bypass" mechanism for journal.update_purge_archived
// or any other mutating operation — it only reviews what is already
// registered. Executing it is out of scope for this step.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention
const REVIEW_OPERATION_NAME = "journal.update_purge_archived";

const dom = {
  loadingState: document.getElementById("operations-loading-state"),
  errorBanner: document.getElementById("operations-error-banner"),
  errorBannerText: document.getElementById("operations-error-banner-text"),
  refreshButton: document.getElementById("operations-refresh-button"),
  connectionStatus: document.getElementById("operations-connection-status"),
  connectionStatusLabel: document.getElementById("operations-connection-status-label"),
  countLabel: document.getElementById("operations-count"),
  tableWrapper: document.getElementById("operations-table-wrapper"),
  tableBody: document.getElementById("operations-table-body"),
  empty: document.getElementById("operations-empty"),
  reviewGrid: document.getElementById("operations-review-grid"),
  reviewList: document.getElementById("operations-review-list"),
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

function setConnectionState(state, label) {
  dom.connectionStatus.dataset.state = state;
  dom.connectionStatusLabel.textContent = label;
}

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function formatKind(kind) {
  if (kind === "mutating") return "Mutating";
  if (kind === "read_only") return "Read-only";
  return textOrPlaceholder(kind);
}

function formatPrivileges(privileges) {
  // required_privileges is an OR-set (the caller needs ANY ONE of them —
  // see OperationDefinition's docstring), so " or " mirrors the backend's
  // own semantics rather than inventing new wording.
  return Array.isArray(privileges) && privileges.length > 0
    ? privileges.join(" or ")
    : PLACEHOLDER;
}

function formatConfirmation(required) {
  return required ? "Yes" : "No";
}

// Cells/rows are always built via document.createElement + .textContent —
// never innerHTML — so an operation name/description containing
// HTML-special characters can never be interpreted as markup.
function makeCell(text) {
  const cell = document.createElement("td");
  cell.className = "data-table__cell";
  cell.textContent = text;
  cell.title = text;
  return cell;
}

function renderTable(operations) {
  dom.tableBody.replaceChildren();

  if (!Array.isArray(operations) || operations.length === 0) {
    dom.tableWrapper.hidden = true;
    dom.empty.hidden = false;
    dom.countLabel.textContent = "";
    return;
  }

  dom.tableWrapper.hidden = false;
  dom.empty.hidden = true;
  dom.countLabel.textContent = `${operations.length} operation${operations.length === 1 ? "" : "s"}`;

  for (const op of operations) {
    const row = document.createElement("tr");
    row.append(
      makeCell(textOrPlaceholder(op.name)),
      makeCell(formatKind(op.kind)),
      makeCell(textOrPlaceholder(op.risk_level)),
      makeCell(formatPrivileges(op.required_privileges)),
      makeCell(formatConfirmation(op.confirmation_required)),
      makeCell(textOrPlaceholder(op.description)),
    );
    dom.tableBody.append(row);
  }
}

function renderReview(operations) {
  dom.reviewList.replaceChildren();

  const operation = Array.isArray(operations)
    ? operations.find((op) => op && op.name === REVIEW_OPERATION_NAME)
    : null;

  if (!operation) {
    dom.reviewGrid.hidden = true;
    return;
  }

  dom.reviewGrid.hidden = false;

  // The row explicitly naming the field execution would change
  // (PurgeArchived) is what satisfies "clearly show what execution
  // changes" — it is real, registry-sourced fact (the operation's own
  // description already names this field), not invented copy.
  const rows = [
    ["Description", textOrPlaceholder(operation.description)],
    ["Kind", formatKind(operation.kind)],
    ["Risk Level", textOrPlaceholder(operation.risk_level)],
    ["Required Privilege", formatPrivileges(operation.required_privileges)],
    ["Confirmation Required", formatConfirmation(operation.confirmation_required)],
    ["Field Changed by Execution", "PurgeArchived"],
  ];

  for (const [label, value] of rows) {
    const row = document.createElement("div");
    row.className = "info-list__row";

    const dt = document.createElement("dt");
    dt.textContent = label;

    const dd = document.createElement("dd");
    dd.className = "info-list__value info-list__value--mono";
    dd.textContent = value;

    row.append(dt, dd);
    dom.reviewList.append(row);
  }
}

/**
 * Fetches GET /api/iris/operations and renders it. This is the ONLY
 * network call this module makes — no mutating request exists anywhere in
 * this file, and nothing here ever calls
 * POST /api/iris/journal/purge-archived (the existing, separate mutating
 * route this view only reviews, never triggers).
 */
export async function loadOperations() {
  setLoading(true);
  setErrorBanner(null);
  setConnectionState("checking", "Checking connection…");

  let response;
  try {
    response = await IrisApi.getOperations();
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "Could not load operations. The Command Center backend may be unreachable."
        : "An unexpected error occurred while loading operations.";
    setConnectionState("error", "Could not reach the backend");
    setErrorBanner(message);
    renderTable(null);
    renderReview(null);
    setLoading(false);
    return;
  }

  const operations = response && Array.isArray(response.operations) ? response.operations : null;

  if (operations === null) {
    setConnectionState("error", "Backend returned no data");
    setErrorBanner("The backend did not return the expected operations list.");
    renderTable(null);
    renderReview(null);
    setLoading(false);
    return;
  }

  setConnectionState("connected", "Connected");
  setErrorBanner(null);
  renderTable(operations);
  renderReview(operations);
  setLoading(false);
}

export function initOperationsControls() {
  dom.refreshButton.addEventListener("click", () => {
    loadOperations();
  });
}
