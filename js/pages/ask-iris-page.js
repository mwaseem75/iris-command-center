// Ask IRIS — the Vector Search + LLM/LangChain bonus feature's UI. A chat
// grounded entirely in this app's own documentation: every answer is
// generated only from chunks IRIS's native SQL Vector Search retrieves
// (see docs/ask-iris.md), never from the model's general knowledge alone,
// and every answer carries the sources it was grounded in.

import { getStatus, askQuestion, reindex as reindexApi } from '../api/ask-iris-api.js';
import { performAction } from '../utils/perform-action.js';
import { loadingRow, errorState, actionButton, emptyCard } from '../utils/dom-helpers.js';
import { config } from '../config.js';

let destroyed = false;

export function render(container) {
  destroyed = false;
  container.replaceChildren();

  const heading = document.createElement('h1');
  heading.className = 'page-title';
  heading.textContent = 'Ask IRIS';

  const subtitle = document.createElement('p');
  subtitle.className = 'metric-card__subtitle';
  subtitle.textContent =
    "A grounded assistant that answers questions about this portal using IRIS Vector Search over its own documentation — never from general knowledge alone.";

  const statusArea = document.createElement('div');
  const mainArea = document.createElement('div');

  container.append(heading, subtitle, statusArea, mainArea);

  async function loadStatus() {
    statusArea.replaceChildren(loadingRow('Checking Ask IRIS status…'));
    mainArea.replaceChildren();
    try {
      const status = await getStatus();
      if (destroyed) return;
      if (status === null) {
        statusArea.replaceChildren();
        mainArea.replaceChildren(cancelledNote());
        return;
      }
      renderStatus(status);
    } catch (err) {
      if (destroyed) return;
      statusArea.replaceChildren();
      mainArea.replaceChildren(errorState(err, loadStatus));
    }
  }

  function renderStatus(status) {
    statusArea.replaceChildren();
    const bar = document.createElement('div');
    bar.className = 'dashboard-controls';
    const label = document.createElement('span');
    label.className = 'metric-card__subtitle';
    label.textContent = status.configured
      ? `Index: ${status.indexedChunks} chunk${status.indexedChunks === 1 ? '' : 's'} from this app's own docs.`
      : 'Not configured yet.';
    bar.appendChild(label);
    if (status.configured) {
      bar.appendChild(actionButton('Rebuild index', 'button--ghost', doReindex));
    }
    statusArea.appendChild(bar);

    if (!status.configured) {
      mainArea.replaceChildren(notConfiguredCard(status.detail));
      return;
    }
    if (status.indexedChunks === 0) {
      mainArea.replaceChildren(emptyIndexCard());
      return;
    }
    mainArea.replaceChildren(buildChat());
  }

  async function doReindex() {
    const ok = await performAction({
      title: 'Rebuild Ask IRIS index',
      message:
        "This re-embeds this app's entire docs corpus via the configured LLM provider and replaces the existing index. Conversation history in this session is unaffected.",
      request: { method: 'POST', path: 'reindex', basePath: config.askIrisApiBaseUrl },
      execute: () => reindexApi(),
      activityLabel: 'Rebuild Ask IRIS index',
    });
    if (ok && !destroyed) loadStatus();
  }

  function notConfiguredCard(detail) {
    return emptyCard(
      "Ask IRIS isn't configured yet",
      detail || 'Create the OpenAI API key wallet secret to enable this feature. See docs/ask-iris.md.'
    );
  }

  function emptyIndexCard() {
    const card = emptyCard('Index is empty', "The docs corpus hasn't been indexed yet.");
    card.appendChild(actionButton('Rebuild index', 'button--primary', doReindex));
    return card;
  }

  function cancelledNote() {
    const note = document.createElement('p');
    note.className = 'empty-state__body';
    note.textContent = 'Skipped — Basic authentication is required for this endpoint.';
    return note;
  }

  function buildChat() {
    const chatWrapper = document.createElement('div');
    chatWrapper.className = 'ask-iris';

    const history = document.createElement('div');
    history.className = 'ask-iris__history';
    history.setAttribute('aria-live', 'polite');

    const form = document.createElement('form');
    form.className = 'ask-iris__form';
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'text-input ask-iris__input';
    input.placeholder = 'Ask a question about this portal…';
    input.setAttribute('aria-label', 'Question');
    const submitButton = document.createElement('button');
    submitButton.type = 'submit';
    submitButton.className = 'button button--primary';
    submitButton.textContent = 'Ask';
    form.append(input, submitButton);

    chatWrapper.append(history, form);

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const question = input.value.trim();
      if (!question) return;
      input.value = '';
      submitButton.disabled = true;
      input.disabled = true;

      history.appendChild(buildTurn('question', question));
      const pending = loadingRow('Thinking…');
      history.appendChild(pending);
      pending.scrollIntoView({ block: 'nearest' });

      try {
        const result = await askQuestion(question);
        if (destroyed) return;
        pending.remove();
        history.appendChild(
          result === null ? buildTurn('note', 'Skipped — authentication was cancelled.') : buildAnswerTurn(result)
        );
      } catch (err) {
        if (destroyed) return;
        pending.remove();
        history.appendChild(buildTurn('error', err?.message || 'The question could not be answered.'));
      } finally {
        if (!destroyed) {
          submitButton.disabled = false;
          input.disabled = false;
          input.focus();
        }
      }
    });

    return chatWrapper;
  }

  function buildTurn(kind, text) {
    const el = document.createElement('div');
    el.className = `ask-iris__turn ask-iris__turn--${kind}`;
    el.textContent = text;
    return el;
  }

  function buildAnswerTurn(result) {
    const el = document.createElement('div');
    el.className = 'ask-iris__turn ask-iris__turn--answer';
    const answer = document.createElement('p');
    answer.textContent = result.answer;
    el.appendChild(answer);

    if (result.sources?.length) {
      const sourcesEl = document.createElement('div');
      sourcesEl.className = 'ask-iris__sources';
      const label = document.createElement('span');
      label.className = 'ask-iris__sources-label';
      label.textContent = 'Sources:';
      sourcesEl.appendChild(label);
      result.sources.forEach((source, index) => {
        const badge = document.createElement('span');
        badge.className = 'ask-iris__source';
        badge.textContent = `[${index + 1}] ${source.source} — ${source.heading} (${Math.round(source.score * 100)}%)`;
        sourcesEl.appendChild(badge);
      });
      el.appendChild(sourcesEl);
    }
    return el;
  }

  loadStatus();
}

export function destroy() {
  destroyed = true;
}
