// Demo Activity: the UI for the backend's controlled rehearsal
// (POST /api/iris/demo/rehearsal, backend/app/execution/demo_rehearsal.py).
//
// The backend runs existing, registered operations through the existing
// authorization -> confirmation -> execution -> verification framework and
// restores every temporary change itself. This file only:
//   1. opens a drawer that explains what will happen (opening never runs
//      anything, and nothing runs on page load),
//   2. sends `confirmed: true` ONLY from the drawer's own Confirm & Run
//      button click handler,
//   3. renders the backend's own step results — nothing is invented, and
//      no trace or activity data is created here — and
//   4. asks the caller (app.js) to refresh the views that read the real
//      traces afterwards.
// It is not a registered operation and never touches the operation
// registry.

import { IrisApi, ApiError } from "./api.js";

const PLACEHOLDER = "—"; // em dash — matches the app's existing empty-value convention

const dom = {
  backdrop: document.getElementById("demo-activity-backdrop"),
  drawer: document.getElementById("demo-activity-drawer"),
  close: document.getElementById("demo-activity-close"),
  intro: document.getElementById("demo-activity-intro"),
  confirmButton: document.getElementById("demo-activity-confirm-button"),
  cancelButton: document.getElementById("demo-activity-cancel-button"),
  running: document.getElementById("demo-activity-running"),
  result: document.getElementById("demo-activity-result"),
  resultStatus: document.getElementById("demo-activity-result-status"),
  resultDetail: document.getElementById("demo-activity-result-detail"),
  steps: document.getElementById("demo-activity-steps"),
  doneButton: document.getElementById("demo-activity-done-button"),
  error: document.getElementById("demo-activity-error"),
  errorText: document.getElementById("demo-activity-error-text"),
};

const OVERALL = {
  completed: ["Completed", "status-badge--ok"],
  stopped: ["Stopped", "status-badge--warning"],
  restore_failed: ["Restore failed", "status-badge--error"],
};

const STEP_BADGE = {
  success: "status-badge--ok",
  dry_run: "status-badge--neutral",
  skipped: "status-badge--neutral",
  not_needed: "status-badge--neutral",
  failed: "status-badge--error",
};

// Friendly labels for the backend's own step ids (unknown ids are shown as-is).
const STEP_LABEL = {
  "journal.read": "Read journal setting",
  "journal.change": "Change journal setting",
  "journal.restore": "Restore journal setting",
  "web_app.select": "Select web application",
  "web_app.read": "Read web app description",
  "web_app.change": "Change web app description",
  "web_app.restore": "Restore web app description",
  "database.select": "Read databases",
  "database.dry_run": "Mount database (dry run)",
  "task.select": "Read tasks",
  "task.dry_run": "Run task now (dry run)",
};

let running = false;
let onCompleted = null;
let onOpenTrace = null;

function textOrPlaceholder(value) {
  if (value === null || value === undefined) return PLACEHOLDER;
  const str = String(value);
  return str === "" ? PLACEHOLDER : str;
}

function makeBadge(text, variant) {
  const badge = document.createElement("span");
  badge.className = `status-badge ${variant}`;
  badge.textContent = text;
  return badge;
}

function showStage(stage) {
  dom.intro.hidden = stage !== "intro";
  dom.running.hidden = stage !== "running";
  dom.result.hidden = stage !== "result";
  dom.error.hidden = stage !== "error";
  const busy = stage === "running";
  dom.close.disabled = busy;
  dom.confirmButton.disabled = busy;
}

/** Opens the drawer at its explanation stage. Never sends a request. */
export function openDemoActivity() {
  if (running) return; // a run in progress keeps showing its own stage
  showStage("intro");
  dom.backdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.confirmButton.focus();
}

function closeDemoActivity() {
  if (running) return; // never hide an in-flight rehearsal's outcome
  dom.backdrop.hidden = true;
  dom.drawer.hidden = true;
}

function renderSteps(steps) {
  dom.steps.replaceChildren();
  for (const step of Array.isArray(steps) ? steps : []) {
    const item = document.createElement("li");
    item.className = "demo-step";
    item.dataset.status = textOrPlaceholder(step.status);

    const head = document.createElement("div");
    head.className = "demo-step__head";
    const title = document.createElement("span");
    title.className = "demo-step__title";
    title.textContent = STEP_LABEL[step.step] || textOrPlaceholder(step.step);
    head.append(
      title,
      makeBadge(textOrPlaceholder(step.status).replace(/_/g, " "), STEP_BADGE[step.status] || "status-badge--neutral"),
    );

    const detail = document.createElement("p");
    detail.className = "demo-step__detail";
    detail.textContent = textOrPlaceholder(step.detail);

    item.append(head, detail);

    const meta = document.createElement("div");
    meta.className = "demo-step__meta";
    if (step.target) {
      const target = document.createElement("span");
      target.className = "demo-step__target";
      target.textContent = step.target;
      meta.append(target);
    }
    if (step.trace_id && onOpenTrace) {
      const link = document.createElement("button");
      link.type = "button";
      link.className = "dash-panel__link";
      link.textContent = `Trace ${String(step.trace_id).slice(0, 8)} →`;
      link.title = `Open trace ${step.trace_id} in Observability`;
      link.addEventListener("click", () => {
        closeDemoActivity();
        onOpenTrace(step.trace_id);
      });
      meta.append(link);
    }
    if (meta.childElementCount) item.append(meta);
    dom.steps.append(item);
  }
}

function renderResult(result) {
  const [label, variant] = OVERALL[result && result.status] || [textOrPlaceholder(result && result.status), "status-badge--neutral"];
  dom.resultStatus.replaceChildren(makeBadge(label, variant));
  dom.resultDetail.textContent = textOrPlaceholder(result && result.detail);
  renderSteps(result && result.steps);
  showStage("result");
}

/**
 * The ONLY place that calls IrisApi.runDemoRehearsal — reachable only via
 * the Confirm & Run button's click handler below, never on load.
 */
async function runConfirmed() {
  if (running) return;
  running = true;
  showStage("running");
  try {
    const result = await IrisApi.runDemoRehearsal(true);
    running = false;
    renderResult(result);
  } catch (err) {
    running = false;
    dom.errorText.textContent =
      err instanceof ApiError && err.status === 409
        ? "A demo rehearsal is already running. Wait for it to finish, then check Recent Operations."
        : err instanceof ApiError
          ? "Could not run the rehearsal — the Command Center backend may be unreachable."
          : "An unexpected error occurred while running the rehearsal.";
    showStage("error");
  } finally {
    // Whatever happened, the real traces may have changed — let the views
    // that read them refresh from the backend.
    if (onCompleted) onCompleted();
  }
}

/**
 * `onCompleted()` is called after every attempt (success or not) so the
 * caller can refresh the views that read real traces. `onOpenTrace(id)`
 * opens a trace in the existing Observability detail view.
 */
export function initDemoActivity({ onCompleted: completed, onOpenTrace: openTrace } = {}) {
  onCompleted = typeof completed === "function" ? completed : null;
  onOpenTrace = typeof openTrace === "function" ? openTrace : null;

  document.querySelectorAll("[data-demo-activity-open]").forEach((button) => {
    button.addEventListener("click", () => openDemoActivity());
  });
  dom.close.addEventListener("click", () => closeDemoActivity());
  dom.cancelButton.addEventListener("click", () => closeDemoActivity());
  dom.doneButton.addEventListener("click", () => closeDemoActivity());
  dom.backdrop.addEventListener("click", () => closeDemoActivity());
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeDemoActivity();
  });
  dom.confirmButton.addEventListener("click", () => {
    runConfirmed();
  });
}
