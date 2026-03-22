import {loadAnalysis} from "./analysis.js";
import {loadExportView} from "./export.js";
import {loadPreview} from "./preview.js";
import {loadProcessingView} from "./processing.js";
import {appState} from "../state.js";
import {loadVisualisation} from "./visualisation.js";
import {hideGlobalNotice, showGlobalNotice} from "../shared/notice.js";

export function initNavigation() {
  const legacyToggleFS = window.toggleFS.bind(window);

  window.goHome = () => window.go(document.querySelector("[data-s=home]"));
  window.startProject = () => {
    document.getElementById("sidebar")?.classList.remove("off");
    window.go(document.querySelector("[data-s=setup]"));
  };
  window.toggleDark = async () => {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
    const button = document.getElementById("dmBtn");
    if (button) {
      button.textContent = dark ? "\u2600" : "\u263D";
    }
    try {
      const active = document.querySelector(".screen.active")?.id;
      if (active === "screen-preview" && appState.project && appState.task) {
        await loadPreview();
      } else if (active === "screen-visualisation" && appState.task?.results?.data) {
        await loadVisualisation();
      }
    } catch (error) {
      console.error(error);
    }
  };
  window.toggleFS = () => legacyToggleFS();

  window.go = async (element) => {
    const target = element?.dataset?.s;
    if (!target) {
      return null;
    }
    document.querySelectorAll(".screen").forEach((node) => node.classList.remove("active"));
    document.getElementById(`screen-${target}`)?.classList.add("active");
    document.querySelectorAll(".nlnk").forEach((node) => node.classList.remove("active"));
    document.querySelector(`[data-s=${target}]`)?.classList.add("active");
    document.getElementById("sidebar")?.classList.toggle("off", target === "home");
    const contextBadge = document.getElementById("ctxBadge");
    if (contextBadge) {
      contextBadge.style.display = target !== "home" && appState.project ? "flex" : "none";
    }
    window.cur = target;
    if (typeof window.setStatus === "function" && Array.isArray(window.sorder)) {
      window.setStatus(window.smap?.[target] || "Ready", window.sorder.indexOf(target) - 1);
    }
    try {
      hideGlobalNotice();
      if (target === "analysis") {
        if (appState.task) loadAnalysis(appState.task);
      } else if (target === "preview") {
        await loadPreview();
      } else if (target === "processing") {
        await loadProcessingView();
      } else if (target === "visualisation") {
        await loadVisualisation();
      } else if (target === "export") {
        await loadExportView();
      }
    } catch (error) {
      console.error(error);
      showGlobalNotice(error.message || "That screen could not load.");
    }
    return target;
  };
}
