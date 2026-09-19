// AI Assistant view: connects the existing chat shell to the backend's
// read-only GET /api/iris/assistant/query endpoint via IrisApi.queryAssistant
// — the ONLY network call this module makes. No other endpoint is ever
// called from here, and no mutating HTTP method is used anywhere in this
// file. IRIS is never called directly from the browser: the backend does
// all IRIS communication and natural-language interpretation (see
// backend/app/routes/assistant.py); this module only sends the user's
// text and renders the reply it gets back.
//
// This assistant is read-only by construction — it has no way to trigger
// any mutating operation (e.g. journal.update_purge_archived): the backend
// route it calls never executes one, and this file contains no execution
// control of any kind.

import { ApiError, IrisApi } from "./api.js";

const dom = {
  messages: document.getElementById("ai-chat-messages"),
  suggestions: document.getElementById("ai-chat-suggestions"),
  composer: document.getElementById("ai-chat-composer"),
  input: document.getElementById("ai-chat-input"),
  sendButton: document.getElementById("ai-chat-send-button"),
};

// Messages are always appended via document.createElement + .textContent —
// never innerHTML — so user-typed text or a reply containing HTML-special
// characters can never be interpreted as markup.
function appendMessage(role, text) {
  const message = document.createElement("div");
  message.className = `chat__message chat__message--${role}`;

  const paragraph = document.createElement("p");
  paragraph.className = "chat__message-text";
  paragraph.textContent = text;

  message.append(paragraph);
  dom.messages.append(message);
  dom.messages.scrollTop = dom.messages.scrollHeight;
}

function setSending(isSending) {
  // Disabling synchronously, before any await, is what makes a second
  // rapid Send click a no-op — the same in-flight-request guard used by
  // every Refresh button elsewhere in this app.
  dom.sendButton.disabled = isSending;
  dom.input.disabled = isSending;
}

async function sendMessage(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return;

  appendMessage("user", trimmed);
  setSending(true);

  try {
    const response = await IrisApi.queryAssistant(trimmed);
    const reply =
      response && typeof response.reply === "string" && response.reply
        ? response.reply
        : "I didn't get a usable answer for that — please try again.";
    appendMessage("assistant", reply);
  } catch (err) {
    // ApiError messages are already generic (see api.js) — never a stack
    // trace, header, or credential value.
    const message =
      err instanceof ApiError
        ? "I couldn't reach the Command Center backend to answer that."
        : "Something went wrong while answering that.";
    appendMessage("assistant", message);
  } finally {
    setSending(false);
    dom.input.focus();
  }
}

export function initAiAssistantControls() {
  dom.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    const text = dom.input.value;
    dom.input.value = "";
    sendMessage(text);
  });

  dom.suggestions.querySelectorAll(".chat__suggestion").forEach((button) => {
    button.addEventListener("click", () => {
      sendMessage(button.dataset.prompt || button.textContent);
    });
  });
}
