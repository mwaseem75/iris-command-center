// AI Assistant view: a purely client-side chat shell. No backend or IRIS
// endpoint is called from this module — there is no fetch anywhere in this
// file, and IrisApi is never imported here. Send and the suggested prompts
// only append messages to the local, in-memory chat log and show a fixed
// "AI integration coming next" reply; no LLM is connected, and no IRIS
// operation (read or mutating) is ever executed from this view.

const ASSISTANT_REPLY =
  "AI integration coming next. This assistant isn't connected to a live model yet, and it never executes IRIS operations.";

const dom = {
  messages: document.getElementById("ai-chat-messages"),
  suggestions: document.getElementById("ai-chat-suggestions"),
  composer: document.getElementById("ai-chat-composer"),
  input: document.getElementById("ai-chat-input"),
};

// Messages are always appended via document.createElement + .textContent —
// never innerHTML — so user-typed text can never be interpreted as markup.
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

function sendMessage(text) {
  const trimmed = (text || "").trim();
  if (!trimmed) return;

  appendMessage("user", trimmed);
  appendMessage("assistant", ASSISTANT_REPLY);
}

export function initAiAssistantControls() {
  dom.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(dom.input.value);
    dom.input.value = "";
    dom.input.focus();
  });

  dom.suggestions.querySelectorAll(".chat__suggestion").forEach((button) => {
    button.addEventListener("click", () => {
      sendMessage(button.dataset.prompt || button.textContent);
      dom.input.focus();
    });
  });
}
