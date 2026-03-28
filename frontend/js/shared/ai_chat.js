/**
 * Shared AI chat component.
 *
 * Usage:
 *   const chat = initAIChat(bodyEl, inputEl, sendEl, { location: "preview" });
 *   await chat.autoLoad("What does this survey show?");   // initial load
 *   // User can then type follow-up questions freely
 */

import {askAurora} from "../api.js";
import {appState} from "../state.js";

export function initAIChat(bodyEl, inputEl, sendEl, {location}) {
  let busy = false;
  // Each entry: { role: "user" | "assistant", content: "..." }
  let history = [];

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

      thinking.remove();

      // The full conversational text lives in `message`; fall back to `summary`
      const fullText = (res.message && res.message.trim()) ? res.message : res.summary;

      _appendAIMessage(bodyEl, fullText);

      // Persist conversation for follow-up context
      if (question) {
        history.push({role: "user", content: question});
      }
      history.push({role: "assistant", content: fullText});

      // Cap history to last 20 messages to avoid ever-growing payloads
      if (history.length > 20) {
        history = history.slice(history.length - 20);
      }
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
    const q = inputEl.value.trim();
    if (!q || busy) return;
    _appendUserMessage(bodyEl, q);
    inputEl.value = "";
    _call(q);
  }

  function _setInputDisabled(disabled) {
    inputEl.disabled = disabled;
    sendEl.disabled = disabled;
  }

  sendEl.addEventListener("click", _send);
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      _send();
    }
  });

  return {
    async autoLoad(initialQuestion) {
      if (!appState.project || !appState.task) {
        bodyEl.innerHTML =
          "<div class='chat-empty'>Open a project and task to enable AI analysis.</div>";
        return;
      }
      // Reset history and UI for a fresh context (e.g. layer change)
      history = [];
      bodyEl.innerHTML = "";
      await _call(initialQuestion || null);
    },

    clear() {
      history = [];
      bodyEl.innerHTML = "";
    },
  };
}

// ── DOM helpers ───────────────────────────────────────────────────────────────

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
  el.innerHTML =
    '<span class="chat-dot"></span><span class="chat-dot"></span><span class="chat-dot"></span>';
  container.appendChild(el);
  return el;
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
// Handles: bold, bullet lists, numbered lists, headers, paragraphs.
// Uses textContent for all user data paths (no XSS risk from Claude output,
// but we sanitize anyway by building DOM nodes, not innerHTML from raw text).

function _escape(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function _renderInline(text) {
  // **bold**
  return _escape(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function _renderMarkdown(text) {
  if (!text) return "";

  const lines = text.split("\n");
  const html = [];
  let inList = false;
  let listType = "";

  function _closeList() {
    if (inList) {
      html.push(`</${listType}>`);
      inList = false;
      listType = "";
    }
  }

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      _closeList();
      html.push("<br>");
      continue;
    }

    // ### Heading 3
    if (/^###\s+/.test(trimmed)) {
      _closeList();
      html.push(`<div class="chat-h3">${_renderInline(trimmed.replace(/^###\s+/, ""))}</div>`);
      continue;
    }

    // ## Heading 2
    if (/^##\s+/.test(trimmed)) {
      _closeList();
      html.push(`<div class="chat-h2">${_renderInline(trimmed.replace(/^##\s+/, ""))}</div>`);
      continue;
    }

    // # Heading 1
    if (/^#\s+/.test(trimmed)) {
      _closeList();
      html.push(`<div class="chat-h1">${_renderInline(trimmed.replace(/^#\s+/, ""))}</div>`);
      continue;
    }

    // Numbered list: 1. item
    const numMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
    if (numMatch) {
      if (!inList || listType !== "ol") {
        _closeList();
        html.push("<ol class='chat-ol'>");
        inList = true;
        listType = "ol";
      }
      html.push(`<li>${_renderInline(numMatch[2])}</li>`);
      continue;
    }

    // Unordered list: -, *, •
    if (/^[-\*\•]\s+/.test(trimmed)) {
      if (!inList || listType !== "ul") {
        _closeList();
        html.push("<ul class='chat-ul'>");
        inList = true;
        listType = "ul";
      }
      html.push(`<li>${_renderInline(trimmed.replace(/^[-\*\•]\s+/, ""))}</li>`);
      continue;
    }

    // Regular paragraph line
    _closeList();
    html.push(`<p class="chat-p">${_renderInline(trimmed)}</p>`);
  }

  _closeList();
  return html.join("");
}
