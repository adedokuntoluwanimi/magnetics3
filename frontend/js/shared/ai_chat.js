import {askAurora} from "../api.js";
import {appState} from "../state.js";

function storageKey(location) {
  const projectId = appState.project?.id || "no-project";
  const taskId = appState.task?.id || "no-task";
  return `gaiaAuroraChat:${location}:${projectId}:${taskId}`;
}

function readHistory(location) {
  try {
    const raw = localStorage.getItem(storageKey(location));
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((item) => item?.role && item?.content) : [];
  } catch {
    return [];
  }
}

function writeHistory(location, history) {
  try {
    localStorage.setItem(storageKey(location), JSON.stringify(history.slice(-20)));
  } catch {
    // Ignore storage failures and keep the chat usable.
  }
}

export function initAIChat(bodyEl, inputEl, sendEl, {location}) {
  let busy = false;
  let history = readHistory(location);

  function renderHistory() {
    bodyEl.innerHTML = "";
    if (!history.length) {
      bodyEl.innerHTML = "<div class='chat-empty'>Ask Aurora about this task, the uploaded data, or the processed outputs.</div>";
      return;
    }
    for (const message of history) {
      if (message.role === "user") {
        _appendUserMessage(bodyEl, message.content);
      } else {
        _appendAIMessage(bodyEl, message.content);
      }
    }
    bodyEl.scrollTop = bodyEl.scrollHeight;
  }

  function persist() {
    writeHistory(location, history);
  }

  async function _call(question) {
    if (busy || !appState.project || !appState.task) return;
    busy = true;
    _setInputDisabled(true);
    const thinking = _appendThinking(bodyEl);
    bodyEl.scrollTop = bodyEl.scrollHeight;

    try {
      const res = await askAurora({
        project_id: appState.project.id,
        task_id: appState.task.id,
        location,
        question: question || null,
        history,
      });

      const fullText = (res.message && res.message.trim()) ? res.message : res.summary;
      thinking.remove();
      _appendAIMessage(bodyEl, fullText);
      if (question) {
        history.push({role: "user", content: question});
      }
      history.push({role: "assistant", content: fullText});
      history = history.slice(-20);
      persist();
    } catch {
      thinking.remove();
      _appendAIMessage(bodyEl, "AI service unavailable. Check your connection and try again.");
    } finally {
      busy = false;
      _setInputDisabled(false);
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  }

  function _send() {
    const question = inputEl.value.trim();
    if (!question || busy) return;
    if (!history.length && bodyEl.querySelector(".chat-empty")) {
      bodyEl.innerHTML = "";
    }
    _appendUserMessage(bodyEl, question);
    inputEl.value = "";
    _call(question);
  }

  function _setInputDisabled(disabled) {
    inputEl.disabled = disabled;
    sendEl.disabled = disabled;
  }

  sendEl.addEventListener("click", _send);
  inputEl.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      _send();
    }
  });

  renderHistory();

  return {
    async autoLoad(initialQuestion) {
      history = readHistory(location);
      renderHistory();
      if (!appState.project || !appState.task) {
        bodyEl.innerHTML = "<div class='chat-empty'>Open a project and task to enable Aurora chat.</div>";
        return;
      }
      if (!history.length && initialQuestion) {
        await _call(initialQuestion);
      }
    },

    clear() {
      history = [];
      persist();
      renderHistory();
    },

    refresh() {
      history = readHistory(location);
      renderHistory();
    },
  };
}

function _appendUserMessage(container, text) {
  const el = document.createElement("div");
  el.className = "chat-user";
  el.textContent = text;
  container.appendChild(el);
  return el;
}

function _appendAIMessage(container, text) {
  const el = document.createElement("div");
  el.className = "chat-ai";
  el.innerHTML = _renderMarkdown(text);
  container.appendChild(el);
  return el;
}

function _appendThinking(container) {
  const el = document.createElement("div");
  el.className = "chat-ai chat-thinking";
  el.innerHTML = '<span class="chat-dot"></span><span class="chat-dot"></span><span class="chat-dot"></span>';
  container.appendChild(el);
  return el;
}

function _escape(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _renderInline(text) {
  return _escape(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function _renderMarkdown(text) {
  if (!text) return "";
  const lines = text.split("\n");
  const html = [];
  let inList = false;
  let listType = "";

  function closeList() {
    if (inList) {
      html.push(`</${listType}>`);
      inList = false;
      listType = "";
    }
  }

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      closeList();
      html.push("<br>");
      continue;
    }
    if (/^###\s+/.test(trimmed)) {
      closeList();
      html.push(`<div class="chat-h3">${_renderInline(trimmed.replace(/^###\s+/, ""))}</div>`);
      continue;
    }
    if (/^##\s+/.test(trimmed)) {
      closeList();
      html.push(`<div class="chat-h2">${_renderInline(trimmed.replace(/^##\s+/, ""))}</div>`);
      continue;
    }
    if (/^#\s+/.test(trimmed)) {
      closeList();
      html.push(`<div class="chat-h1">${_renderInline(trimmed.replace(/^#\s+/, ""))}</div>`);
      continue;
    }
    const numberMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
    if (numberMatch) {
      if (!inList || listType !== "ol") {
        closeList();
        html.push("<ol class='chat-ol'>");
        inList = true;
        listType = "ol";
      }
      html.push(`<li>${_renderInline(numberMatch[2])}</li>`);
      continue;
    }
    if (/^[-*•]\s+/.test(trimmed)) {
      if (!inList || listType !== "ul") {
        closeList();
        html.push("<ul class='chat-ul'>");
        inList = true;
        listType = "ul";
      }
      html.push(`<li>${_renderInline(trimmed.replace(/^[-*•]\s+/, ""))}</li>`);
      continue;
    }
    closeList();
    html.push(`<p class="chat-p">${_renderInline(trimmed)}</p>`);
  }

  closeList();
  return html.join("");
}
