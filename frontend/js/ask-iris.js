// Ask IRIS: a side panel with read-only answers about one context (Processes,
// Databases, Web Apps, Tasks or the detected issues). Questions go to the
// existing Copilot (POST /api/iris/copilot/ask) for the selected instance;
// its deterministic provider answers from the read-only context it reads
// there. There is no LLM, and this panel never plans, authorizes or runs a
// change: a change request gets a read-only reply and links to the pages
// where changes are made.
//
// One panel (`.ns-drawer`, so detail-workspace.js gives it the modal
// behaviour), opened by any `[data-ask-iris="<context>"]` button: the page
// headers, the Dashboard cards and a process's detail drawer.
// All DOM is built with createElement/textContent, no innerHTML.

import { ApiError, IrisApi } from "./api.js";
import { getInstanceContext, selectedInstanceId } from "./instance-context.js";
import { navigateTo } from "./nav.js";

// Each context: its title, suggested prompts, the words that make a question
// about it (to name the source), its source, the page it lives on and the
// next steps. Prompts only ask what the Copilot's context can answer.
export const CONTEXTS = {
  processes: {
    title: "Processes",
    prompts: [
      "Summarize process activity",
      "Show processes by state",
      "Show processes by namespace",
      "Which processes have the highest cumulative CPU time?",
      "Are there any active issues?",
    ],
    words: /\bprocess(es)?\b|\bpid\b/i,
    source: "GET /v2/processes",
    page: "processes",
    steps: ["investigation", "processes", "issue-resolver"],
  },
  databases: {
    title: "Databases",
    prompts: [
      "Summarize database status",
      "Which databases need attention?",
      "Show dismounted databases",
      "Explain the current database status",
    ],
    words: /\bdatabases?\b/i,
    source: "GET /v2/databases, with the Issue Resolver's detection",
    page: "databases",
    steps: ["databases", "issue-resolver"],
  },
  "web-apps": {
    title: "Web Applications",
    prompts: [
      "Summarize web applications",
      "Which web apps are disabled?",
      "Show web apps by namespace",
      "Do any web apps point to a missing namespace?",
    ],
    words: /\bweb\s*apps?\b|\bweb\s+applications?\b/i,
    source: "GET /v2/web-apps, with the Issue Resolver's detection",
    page: "web-apps",
    steps: ["web-apps", "issue-resolver"],
  },
  tasks: {
    title: "Tasks",
    prompts: [
      "Which tasks are suspended?",
      "Are there task errors?",
      "Explain the current task status",
      "Summarize task schedules",
    ],
    words: /\btasks?\b/i,
    source: "GET /v2/tasks, with each task's info and details",
    page: "tasks",
    steps: ["tasks", "issue-resolver"],
  },
  // Like the Dashboard's Issues panel, for the Primary instance only.
  issues: {
    title: "Detected Issues",
    prompts: [
      "Are there any active issues?",
      "Which issues need attention?",
      "Which issue checks could not run?",
    ],
    words: null,
    source: "Issue Resolver detection (read-only)",
    page: "issue-resolver",
    steps: ["issue-resolver"],
    primaryOnly: true,
  },
};

// Next steps: view -> [label, hint]. They only open existing pages.
const STEPS = {
  investigation: ["Open Investigation", "Audit trail for this instance"],
  processes: ["View Processes", "Refresh the process list"],
  databases: ["View Databases", "Database details and status"],
  "web-apps": ["View Web Apps", "Application settings and REST endpoints"],
  tasks: ["View Tasks", "Schedules and run state"],
  "issue-resolver": ["Open Issue Resolver", "Check for related issues"],
  operations: ["Open Operations", "Changes, with confirmation"],
};

const READ_ONLY_REPLY =
  "Ask IRIS is read-only and doesn't make changes. Changes go through the existing operation workflows, " +
  "which check your privileges, ask for explicit confirmation and verify the result, on the Primary instance only.";

const $ = (id) => document.getElementById(id);
const dom = {
  backdrop: $("ask-iris-backdrop"),
  drawer: $("ask-iris-drawer"),
  close: $("ask-iris-close"),
  title: $("ask-iris-title"),
  instance: $("ask-iris-instance"),
  screen: $("ask-iris-screen"),
  readAt: $("ask-iris-read-at"),
  prompts: $("ask-iris-prompts"),
  form: $("ask-iris-form"),
  input: $("ask-iris-input"),
  send: $("ask-iris-send"),
  loading: $("ask-iris-loading"),
  loadingText: $("ask-iris-loading-text"),
  error: $("ask-iris-error"),
  errorText: $("ask-iris-error-text"),
  result: $("ask-iris-result"),
};

let context = CONTEXTS.processes;  // the open panel's context
let selectedPid = null;  // the process the panel was opened for, if any
let busy = false;
let latest = 0;  // numbers each question; an answer to an older one is dropped

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function instanceLabel() {
  const instance = getInstanceContext().instance;
  if (!instance || instance.primary) return "Primary";
  return instance.connection ? `${instance.name} (${instance.connection})` : instance.name;
}

function fmtTime(date) {
  return date.toLocaleString([], { dateStyle: "medium", timeStyle: "medium" });
}

function renderPrompts() {
  const prompts = selectedPid === null ? context.prompts : [`Explain PID ${selectedPid}`, ...context.prompts];
  dom.prompts.replaceChildren(
    ...prompts.map((prompt) => {
      const button = el("button", "explain-chip", prompt);
      button.type = "button";
      button.dataset.prompt = prompt;
      return button;
    }),
  );
}

function setBusy(isBusy) {
  busy = isBusy;
  dom.send.disabled = isBusy;
  dom.input.disabled = isBusy;
  dom.prompts.querySelectorAll("button").forEach((button) => {
    button.disabled = isBusy;
  });
  dom.loading.hidden = !isBusy;
}

const aboutContext = (question) => Boolean(context.words && context.words.test(question));

function sourceOf(question, intent) {
  if (intent === "issue_investigation") return CONTEXTS.issues.source;
  if (aboutContext(question)) return context.source;
  return "Copilot read-only context (system, databases, processes, web apps, tasks, issues)";
}

function stepsFor(question, intent) {
  if (intent === "resolution_request") return [...new Set(["operations", context.page])];
  if (intent === "issue_investigation") return ["issue-resolver", "investigation"];
  if (intent === "read_only_query" && aboutContext(question)) return context.steps;
  return [context.page];
}

function nextSteps(views) {
  const section = el("section", "explain-card");
  section.append(el("h4", "explain-card__title", "What you can do next"));
  const row = el("div", "ask-iris__steps");
  for (const view of views) {
    const [label, hint] = STEPS[view];
    const button = el("button", "explain-chip ask-iris__step");
    button.type = "button";
    button.dataset.view = view;
    button.append(el("strong", "", label), el("span", "ask-iris__step-hint", hint));
    row.append(button);
  }
  section.append(row);
  return section;
}

function metaRow(label, value) {
  const row = el("div");
  row.append(el("dt", "", label), el("dd", "", value));
  return row;
}

/** The answer, then (set apart) the evidence it rests on, then next steps. */
function renderAnswer(question, response, instance, readAt) {
  const answer = el("section", "explain-card ask-iris__answer");
  answer.append(el("h4", "explain-card__title", "Answer"), el("p", "ask-iris__question", question));
  if (response.intent === "resolution_request") {
    // Read-only: a proposal from the Copilot isn't shown, let alone offered.
    answer.append(el("p", "ask-iris__answer-text", READ_ONLY_REPLY));
    return [answer, nextSteps(stepsFor(question, response.intent))];
  }
  answer.append(el("p", "ask-iris__answer-text", response.answer));

  const evidence = el("section", "explain-card ask-iris__evidence");
  evidence.append(el("h4", "explain-card__title", "Evidence"));
  const observations = (Array.isArray(response.observations) ? response.observations : [])
    .filter((item) => typeof item === "string" && item);
  if (observations.length) {
    const list = el("ul", "ask-iris__observations");
    observations.forEach((item) => list.append(el("li", "", item)));
    evidence.append(list);
  } else {
    evidence.append(el("p", "explain-card__text", "No further observations for this answer."));
  }
  const meta = el("dl", "ask-iris__meta");
  meta.append(
    metaRow("Source", sourceOf(question, response.intent)),
    metaRow("Instance", instance),
    metaRow("Read at", fmtTime(readAt)),
  );
  evidence.append(meta);
  return [answer, evidence, nextSteps(stepsFor(question, response.intent))];
}

async function ask(raw) {
  const question = (raw || "").trim();
  if (!question || busy) return;
  const id = ++latest;
  // The instance is fixed per question: the backend reads that instance or
  // fails; it never answers from the Primary instead.
  const instance = instanceLabel();
  dom.loadingText.textContent = `Reading live IRIS data from ${instance}…`;
  dom.error.hidden = true;
  dom.result.replaceChildren();
  setBusy(true);
  try {
    const response = await IrisApi.askCopilot(question, selectedInstanceId());
    if (id !== latest) return;
    if (!response || typeof response.answer !== "string" || !response.answer) {
      throw new Error("No usable answer");
    }
    const readAt = new Date();
    dom.readAt.textContent = fmtTime(readAt);
    dom.result.replaceChildren(...renderAnswer(question, response, instance, readAt));
  } catch (err) {
    if (id !== latest) return;
    dom.errorText.textContent = err instanceof ApiError
      ? `Couldn't read IRIS data from ${instance}. The Command Center backend or this IRIS instance ` +
        "may be unreachable; no other instance was used. Try again."
      : "Something went wrong while answering that. Try again.";
    dom.error.hidden = false;
  } finally {
    if (id === latest) setBusy(false);
  }
}

/**
 * Opens the panel for `key` (one of CONTEXTS). `screen` names where it was
 * opened from (default: the context's own page); with a `pid` (Processes),
 * it asks about that process right away. A Primary-only context doesn't
 * open while another instance is selected.
 */
export function openAskIris(key, { pid = null, screen = null } = {}) {
  const next = CONTEXTS[key];
  if (!next || (next.primaryOnly && selectedInstanceId())) return;
  context = next;
  selectedPid = pid;
  dom.title.textContent = `Ask IRIS · ${context.title}`;
  dom.instance.textContent = instanceLabel();
  dom.screen.textContent = screen ? `${screen} · ${context.title}` : context.title;
  dom.readAt.textContent = "Not read yet";
  dom.error.hidden = true;
  dom.result.replaceChildren();
  dom.input.value = "";
  renderPrompts();
  dom.backdrop.hidden = false;
  dom.drawer.hidden = false;
  dom.drawer.scrollTop = 0;
  if (pid !== null) ask(`Explain PID ${pid}`);
  else dom.input.focus();
}

function closeAskIris() {
  latest += 1;  // an answer still on its way is dropped
  setBusy(false);
  dom.backdrop.hidden = true;
  dom.drawer.hidden = true;
}

export function initAskIris() {
  // Every entry point is a [data-ask-iris] button. On the Dashboard they sit
  // beside the cards, not inside them, so a card click still opens its page.
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-ask-iris]");
    if (button) openAskIris(button.dataset.askIris, { screen: button.dataset.askIrisScreen || null });
  });
  dom.close.addEventListener("click", closeAskIris);
  dom.backdrop.addEventListener("click", closeAskIris);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dom.drawer.hidden) closeAskIris();
  });
  dom.form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = dom.input.value;
    dom.input.value = "";
    ask(question);
  });
  dom.prompts.addEventListener("click", (event) => {
    const button = event.target.closest("[data-prompt]");
    if (button) ask(button.dataset.prompt);
  });
  // Next steps only switch pages, like the other cross-page links.
  dom.result.addEventListener("click", (event) => {
    const button = event.target.closest("[data-view]");
    if (!button) return;
    closeAskIris();
    navigateTo(button.dataset.view);
  });
}
