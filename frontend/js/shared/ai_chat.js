/**
 * Shared AI chat component.
 *
 * Usage:
 *   const chat = initAIChat(bodyEl, inputEl, sendEl, { location: "preview" });
 *   await chat.autoLoad();                   // fires initial analysis on screen load
 *   chat.autoLoad("What are the risks?");   // initial analysis with a specific question
 */

import {askAurora} from "../api.js";
import {appState} from "../state.js";

export function initAIChat(bodyEl, inputEl, sendEl, {location}) {
  let busy = false;

  async function _call(question) {
    if (busy || !appState.project || !appState.task) return;
    busy = true;
    inputEl.disabled = true;
    sendEl.disabled = true;

    const thinking = _appendBubble(bodyEl, "ai", "Thinking…", true);
    bodyEl.scrollTop = bodyEl.scrollHeight;

    try {
      const res = await askAurora({
        project_id: appState.project.id,
        task_id: appState.task.id,
        location,
        question: question || null,
      });
      thinking.remove();
      _appendBubble(bodyEl, "ai", res.summary);
      for (const h of res.highlights || []) {
        _appendHighlight(bodyEl, h);
      }
    } catch {
      thinking.remove();
      _appendBubble(bodyEl, "ai", "AI service unavailable. Check connectivity and try again.");
    } finally {
      busy = false;
      inputEl.disabled = false;
      sendEl.disabled = false;
      bodyEl.scrollTop = bodyEl.scrollHeight;
    }
  }

  function _send() {
    const q = inputEl.value.trim();
    if (!q) return;
    _appendBubble(bodyEl, "user", q);
    inputEl.value = "";
    _call(q);
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
          "<div class='amsg'>Open a project and task to enable AI analysis.</div>";
        return;
      }
      bodyEl.innerHTML = "";
      await _call(initialQuestion || null);
    },

    clear() {
      bodyEl.innerHTML = "";
    },
  };
}

function _appendBubble(container, role, text, isThinking = false) {
  const el = document.createElement("div");
  if (role === "user") {
    el.className = "chat-user";
  } else if (isThinking) {
    el.className = "chat-ai chat-thinking";
  } else {
    el.className = "chat-ai";
  }
  el.textContent = text;
  container.appendChild(el);
  return el;
}

function _appendHighlight(container, text) {
  const el = document.createElement("div");
  el.className = "ahi";
  el.style.marginTop = "8px";
  el.textContent = text;
  container.appendChild(el);
  return el;
}
