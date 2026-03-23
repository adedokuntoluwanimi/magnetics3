import {loadAnalysis} from "./analysis.js";
import {loadExportView} from "./export.js";
import {loadPreview} from "./preview.js";
import {loadProcessingView} from "./processing.js";
import {appState, setProject, setTask, clearTask, clearProcessingRun} from "../state.js";
import {loadVisualisation} from "./visualisation.js";
import {hideGlobalNotice, showGlobalNotice} from "../shared/notice.js";
import {listProjects, listTasks} from "../api.js";

function closeProjsDropdown() {
  document.getElementById("projsDropdown").style.display = "none";
}

async function openProjsDropdown() {
  const dropdown = document.getElementById("projsDropdown");
  const list = document.getElementById("projsDropList");
  const btn = document.getElementById("projsDropBtn");
  const rect = btn.getBoundingClientRect();
  dropdown.style.top = (rect.bottom + 4) + "px";
  dropdown.style.right = (window.innerWidth - rect.right) + "px";
  dropdown.style.display = "block";
  list.innerHTML = `<div style="padding:10px 13px;font-size:11px;color:var(--text3)">Loading…</div>`;
  try {
    const projects = await listProjects();
    if (!projects.length) {
      list.innerHTML = `<div style="padding:10px 13px;font-size:11px;color:var(--text3)">No projects yet.</div>`;
      return;
    }
    list.innerHTML = projects.map((p) => `
      <div data-proj-id="${p.id}" style="display:flex;align-items:center;gap:8px;padding:8px 13px;font-size:12px;font-weight:600;color:var(--text2);cursor:pointer;transition:background 0.1s" onmouseenter="this.style.background='var(--bg3)'" onmouseleave="this.style.background=''" onclick="window.loadProjectFromDropdown('${p.id}')">
        <div style="width:6px;height:6px;border-radius:50%;background:var(--g400);flex-shrink:0"></div>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.name}</span>
      </div>
    `).join("") + `<div style="border-top:1px solid var(--border);margin:4px 0"></div>
      <div style="padding:8px 13px;font-size:11.5px;font-weight:700;color:var(--g500);cursor:pointer" onmouseenter="this.style.background='var(--g50)'" onmouseleave="this.style.background=''" onclick="window.beginNewProjectFlow?.();window.startProject?.();closeProjsDropdown()">+ New project</div>`;
  } catch {
    list.innerHTML = `<div style="padding:10px 13px;font-size:11px;color:var(--red)">Could not load projects.</div>`;
  }
}

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

  window.toggleSidebar = () => {
    const sidebar = document.getElementById("sidebar");
    const expandBtn = document.getElementById("sbExpandBtn");
    if (!sidebar) return;
    const collapsed = sidebar.classList.toggle("collapsed");
    if (expandBtn) expandBtn.style.display = collapsed ? "flex" : "none";
  };

  window.toggleProjectsDropdown = () => {
    const dd = document.getElementById("projsDropdown");
    if (dd.style.display === "none" || !dd.style.display) {
      openProjsDropdown();
    } else {
      closeProjsDropdown();
    }
  };
  window.closeProjsDropdown = closeProjsDropdown;
  document.addEventListener("click", (e) => {
    if (!document.getElementById("projsDropBtn")?.contains(e.target)) {
      closeProjsDropdown();
    }
  });

  window.loadProjectFromDropdown = async (projectId) => {
    closeProjsDropdown();
    try {
      const projects = await listProjects();
      const project = projects.find((p) => p.id === projectId);
      if (!project) return;
      setProject(project);
      clearTask();
      clearProcessingRun();
      const tasks = await listTasks(projectId);
      if (tasks.length) setTask(tasks[0]);
      const ctxTxt = document.getElementById("ctxTxt");
      if (ctxTxt) ctxTxt.textContent = project.name;
      document.getElementById("sidebar")?.classList.remove("off");
      const {refreshSidebar} = await import("./sidebar.js");
      await refreshSidebar();
      // goProjectScreen activates screen-project and deactivates all nav links
      window.goProjectScreen?.();
    } catch (err) {
      showGlobalNotice(err.message || "Could not load project.");
    }
  };

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
