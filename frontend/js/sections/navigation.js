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

let cachedProjects = null;
let cachedProjectsAt = 0;

async function getProjectsCached() {
  const now = Date.now();
  if (cachedProjects && now - cachedProjectsAt < 15000) {
    return cachedProjects;
  }
  const projects = await listProjects();
  cachedProjects = projects;
  cachedProjectsAt = now;
  return projects;
}

async function openProjsDropdown() {
  const dropdown = document.getElementById("projsDropdown");
  const list = document.getElementById("projsDropList");
  const btn = document.getElementById("projsDropBtn");
  const rect = btn.getBoundingClientRect();
  dropdown.style.top = (rect.bottom + 4) + "px";
  dropdown.style.right = (window.innerWidth - rect.right) + "px";
  dropdown.style.display = "block";
  list.innerHTML = `<div style="padding:10px 13px;font-size:11px;color:var(--text3)">Loading...</div>`;
  try {
    const projects = await getProjectsCached();
    if (!projects.length) {
      list.innerHTML = `
        <div style="padding:8px 13px">
          <button class="btn btn-out btn-xs" style="width:100%;justify-content:center" onclick="window.openProjectsList?.();window.closeProjsDropdown?.()">View full project list</button>
        </div>
        <div style="padding:10px 13px;font-size:11px;color:var(--text3)">No projects yet.</div>
      `;
      return;
    }
    list.innerHTML = `
      <div style="padding:8px 13px;border-bottom:1px solid var(--border)">
        <button class="btn btn-out btn-xs" style="width:100%;justify-content:center" onclick="window.openProjectsList?.();window.closeProjsDropdown?.()">View full project list</button>
      </div>
    ` + projects.map((p) => `
      <div data-proj-id="${p.id}" style="display:flex;align-items:center;gap:8px;padding:8px 13px;font-size:12px;font-weight:600;color:var(--text2);cursor:pointer;transition:background 0.1s" onmouseenter="this.style.background='var(--bg3)'" onmouseleave="this.style.background=''" onclick="window.loadProjectFromDropdown('${p.id}')">
        <div style="width:6px;height:6px;border-radius:50%;background:var(--g400);flex-shrink:0"></div>
        <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${p.name}</span>
      </div>
    `).join("") + `<div style="border-top:1px solid var(--border);margin:4px 0"></div>
      <div style="padding:8px 13px;font-size:11.5px;font-weight:700;color:var(--g500);cursor:pointer" onmouseenter="this.style.background='var(--g50)'" onmouseleave="this.style.background=''" onclick="window.beginNewProjectFlow?.();window.openProjectSetup?.();window.closeProjsDropdown?.()">+ New project</div>`;
  } catch {
    list.innerHTML = `<div style="padding:10px 13px;font-size:11px;color:var(--red)">Could not load projects.</div>`;
  }
}

export function initNavigation() {
  const legacyToggleFS = window.toggleFS.bind(window);
  getProjectsCached().catch(() => null);

  window.addEventListener("popstate", (e) => {
    const screen = e.state?.screen;
    if (screen) window.go(screen);
  });

  window.goHome = () => window.go(document.querySelector("[data-s=home]"));
  window.openProjectSetup = () => {
    document.getElementById("sidebar")?.classList.remove("off");
    window.go("setup");
    window.restoreSetupFromState?.();
  };
  window.openTaskSetup = () => {
    document.getElementById("sidebar")?.classList.remove("off");
    window.go("setup");
    window.restoreSetupFromState?.();
  };
  window.openProjectsHub = async () => {
    const {openProjectsList} = await import("./sidebar.js");
    await openProjectsList();
  };
  window.startProject = () => window.openProjectsHub?.();
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
      } else if (active === "screen-visualisation" && appState.task?.results?.artifacts?.length) {
        await loadVisualisation();
      }
    } catch (error) {
      console.error(error);
    }
  };
  window.toggleFS = () => legacyToggleFS();

  window.toggleSidebar = () => {
    const sidebar = document.getElementById("sidebar");
    if (!sidebar) return;
    // Complete collapse with no residual expand button.
    sidebar.classList.toggle("collapsed");
    // Always hide the expand button (full collapse, no half-visible indicator)
    document.getElementById("sbExpandBtn")?.style.setProperty("display", "none");
    document.getElementById("sbCollapseBtn")?.style.setProperty("display", "flex");
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
      const {selectProject} = await import("./sidebar.js");
      await selectProject(project);
    } catch (err) {
      showGlobalNotice(err.message || "Could not load project.");
    }
  };

  let _goInProgress = false;
  window.go = async (element) => {
    let target = typeof element === "string" ? element : element?.dataset?.s;
    if (!target) {
      return null;
    }
    // Prevent re-entrant calls (e.g. setup callbacks calling window.go("setup"))
    if (_goInProgress && target === window.cur) {
      return target;
    }
    if (target === "projects") {
      const {openProjectsList} = await import("./sidebar.js");
      await openProjectsList();
      return "projects";
    }
    const workflowScreens = ["analysis", "preview", "processing", "visualisation", "export", "project"];
    if (workflowScreens.includes(target) && !appState.project) {
      target = "projects";
      element = document.querySelector("[data-s=projects]");
      const {openProjectsList} = await import("./sidebar.js");
      await openProjectsList();
      return "projects";
    }
    document.querySelectorAll(".screen").forEach((node) => node.classList.remove("active"));
    document.getElementById(`screen-${target}`)?.classList.add("active");
    document.querySelectorAll(".nlnk").forEach((node) => node.classList.remove("active"));
    document.querySelector(`[data-s=${target}]`)?.classList.add("active");
    document.getElementById("sidebar")?.classList.toggle("off", target === "home" || target === "preview");
    const contextBadge = document.getElementById("ctxBadge");
    if (contextBadge) {
      contextBadge.style.display = target !== "home" && appState.project ? "flex" : "none";
    }
    window.cur = target;
    try {
      if (history.state?.screen !== target) {
        history.pushState({screen: target}, "", "#" + target);
      }
      localStorage.setItem("gaiaCurrentScreen", target);
    } catch {}
    if (typeof window.setStatus === "function" && Array.isArray(window.sorder)) {
      window.setStatus(window.smap?.[target] || "Ready", window.sorder.indexOf(target) - 1);
    }
    _goInProgress = true;
    try {
      hideGlobalNotice();
      if (target === "analysis") {
        if (appState.task) loadAnalysis(appState.task);
      } else if (target === "setup") {
        window.restoreSetupFromState?.();
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
    } finally {
      _goInProgress = false;
    }
    return target;
  };
}

