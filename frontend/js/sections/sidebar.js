import {listProjects, listTasks, renameProject, deleteProject, renameTask, deleteTask} from "../api.js";
import {appState, clearProcessingRun, clearProject, clearTask, setProject, setTask} from "../state.js";
import {renderWorkflowProgress} from "./progress.js";
import {showConfirm, showAlert} from "../shared/modal.js";

// Track collapsed project ids.
const collapsedProjects = new Set();

/* Helpers */

function lifecycleDot(task, active) {
  if (active) return "d-active";
  if (task?.lifecycle === "completed") return "d-done";
  return "d-idle";
}

function lifecycleBadgeClass(lc) {
  return {completed: "bg-done", running: "bb", queued: "ba", failed: "br",
          configured: "bg", preview_ready: "bg"}[lc] || "bgr";
}

function fmtDate(iso) {
  if (!iso) return "";
  try { return new Date(iso).toLocaleDateString(undefined, {year:"numeric",month:"short",day:"numeric"}); }
  catch { return ""; }
}

function syncContext(project = appState.project) {
  const ctxText = document.getElementById("ctxTxt");
  const ctxBadge = document.getElementById("ctxBadge");
  if (ctxText) ctxText.textContent = project?.name || "New project";
  if (ctxBadge) ctxBadge.style.display = project ? "flex" : "none";
}

function wireProjectNewBtn() {
  const btn = document.getElementById("sb-new-project");
  if (btn && !btn.dataset.bound) {
    btn.dataset.bound = "true";
    btn.addEventListener("click", () => {
      window.beginNewProjectFlow?.();
      window.openProjectSetup?.();
    });
  }
}

/* Inline rename */
function startRename(nameEl, currentName, onSave) {
  const input = document.createElement("input");
  input.className = "sb-rename-input";
  input.value = currentName;
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  let saved = false;
  async function commit() {
    if (saved) return;
    saved = true;
    const newName = input.value.trim();
    if (newName && newName !== currentName && newName.length >= 3) {
      try {
        await onSave(newName);
        input.replaceWith(nameEl); // restore after success (nameEl.textContent set by onSave)
      } catch {
        input.replaceWith(nameEl);
      }
    } else {
      input.replaceWith(nameEl);
    }
  }
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); commit(); }
    if (e.key === "Escape") { saved = true; input.replaceWith(nameEl); }
  });
  input.addEventListener("blur", commit);
}

/* Project overview screen */
function renderProjectScreen(project, tasks) {
  const titleEl = document.getElementById("proj-title");
  if (!titleEl) return;

  document.getElementById("proj-title").textContent = project.name;
  document.getElementById("proj-sub").textContent =
    `${tasks.length} task${tasks.length !== 1 ? "s" : ""} - Created ${fmtDate(project.created_at)}`;
  const contextEl = document.getElementById("proj-context");
  if (contextEl) contextEl.textContent = project.context || "No description provided.";

  // Wire delete project button
  const delBtn = document.getElementById("projDeleteBtn");
  if (delBtn) {
    delBtn.onclick = () => {
      showConfirm(`Delete project "<strong>${project.name}</strong>" and all its tasks? This cannot be undone.`, {
        title: "Delete project",
        confirmLabel: "Delete",
        danger: true,
        onConfirm: async () => {
          try {
            await deleteProject(project.id);
            clearProject();
            clearTask();
            clearProcessingRun();
            syncContext(null);
            await refreshSidebar();
            renderWorkflowProgress();
            await openProjectsList();
          } catch (err) { showAlert(err.message || "Delete failed."); }
        },
      });
    };
  }

  // Wire edit context button
  const editCtxBtn = document.getElementById("projEditContextBtn");
  if (editCtxBtn && contextEl) {
    editCtxBtn.onclick = () => {
      if (contextEl.querySelector("textarea")) return; // already editing
      const currentText = contextEl.textContent.trim();
      const ta = document.createElement("textarea");
      ta.className = "ftxt";
      ta.rows = 5;
      ta.value = currentText === "No description provided." ? "" : currentText;
      ta.style.marginTop = "4px";
      contextEl.textContent = "";
      contextEl.appendChild(ta);
      editCtxBtn.textContent = "Save";
      ta.focus();

      editCtxBtn.onclick = async () => {
        const newCtx = ta.value.trim();
        if (newCtx.length < 10) { showAlert("Context must be at least 10 characters."); return; }
        try {
          await renameProject(project.id, undefined, newCtx);
          project.context = newCtx;
          contextEl.textContent = newCtx;
          editCtxBtn.textContent = "Edit";
          renderProjectScreen(project, tasks);
        } catch (err) {
          showAlert(err.message || "Save failed.");
        }
      };
    };
  }

  const countEl = document.getElementById("proj-task-count");
  if (countEl) countEl.textContent = `${tasks.length} task${tasks.length !== 1 ? "s" : ""}`;

  const taskList = document.getElementById("proj-task-list");
  if (!taskList) return;
  taskList.innerHTML = "";

  if (!tasks.length) {
    taskList.innerHTML = `<div class="card" style="text-align:center;padding:32px;color:var(--text4)">
      <div style="font-size:13px;font-weight:700;color:var(--text3);margin-bottom:4px">No tasks yet</div>
      <div style="font-size:12px">Add a task to begin processing this project.</div>
    </div>`;
    return;
  }

  tasks.forEach((task) => {
    const active = task.id === appState.task?.id;
    const lc = task.lifecycle || "draft";
    const mode = task.processing_mode === "multi" ? "Multi-line" : "Single-line";
    const files = (task.survey_files || []).length;
    const scenario = task.scenario ? task.scenario.charAt(0).toUpperCase() + task.scenario.slice(1) : "";
    const platform = task.platform ? task.platform.charAt(0).toUpperCase() + task.platform.slice(1) : "";

    const card = document.createElement("div");
    card.className = `card proj-task-card${active ? " card-active" : ""}`;
    card.style.marginBottom = "10px";
    card.innerHTML = `
      <div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:8px">
        <div class="sdot ${lifecycleDot(task, active)}" style="width:9px;height:9px;flex-shrink:0;margin-top:3px"></div>
        <div style="flex:1">
          <div style="font-size:13.5px;font-weight:700;color:var(--text)" class="ptask-name">${task.name}</div>
          <div style="font-size:11.5px;color:var(--text3);margin-top:2px;line-height:1.5">${task.description || ""}</div>
        </div>
        <span class="badge ${lifecycleBadgeClass(lc)}" style="flex-shrink:0">${lc}</span>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:12px">
        ${platform ? `<span class="badge bgr">${platform}</span>` : ""}
        <span class="badge bgr">${mode}</span>
        ${scenario ? `<span class="badge bgr">${scenario}</span>` : ""}
        <span class="badge bgr">${files} file${files !== 1 ? "s" : ""}</span>
        ${task.created_at ? `<span class="badge bgr">Created ${fmtDate(task.created_at)}</span>` : ""}
      </div>
      <div style="display:flex;gap:7px;flex-wrap:wrap">
        <button class="btn btn-g btn-xs ptask-open">Open task →</button>
        <button class="btn btn-out btn-xs ptask-edit">Edit setup</button>
        <button class="btn btn-out btn-xs ptask-rename">Rename</button>
        <button class="btn btn-out btn-xs ptask-del" style="color:var(--red);border-color:var(--red-bg)">Delete</button>
      </div>
    `;

    card.querySelector(".ptask-open").addEventListener("click", () => {
      setTask(task);
      clearProcessingRun();
      syncContext(project);
      renderWorkflowProgress();
      window.go?.(document.querySelector("[data-s=analysis]"));
    });

    const nameEl = card.querySelector(".ptask-name");
    card.querySelector(".ptask-rename").addEventListener("click", async () => {
      startRename(nameEl, task.name, async (newName) => {
        await renameTask(project.id, task.id, newName);
        task.name = newName;
        nameEl.textContent = newName;
        if (appState.task?.id === task.id) {
          appState.task.name = newName;
          syncContext(project);
        }
        await refreshSidebar();
      });
    });

    card.querySelector(".ptask-edit").addEventListener("click", () => {
      window.loadTaskForEdit?.(task, project);
    });

    card.querySelector(".ptask-del").addEventListener("click", () => {
      showConfirm(`Delete task "<strong>${task.name}</strong>"? This cannot be undone.`, {
        title: "Delete task",
        confirmLabel: "Delete",
        danger: true,
        onConfirm: async () => {
          try {
            await deleteTask(project.id, task.id);
            if (appState.task?.id === task.id) clearTask();
            const updatedTasks = await listTasks(project.id);
            if (updatedTasks.length) setTask(updatedTasks[0]);
            renderProjectScreen(project, updatedTasks);
            await refreshSidebar();
            renderWorkflowProgress();
          } catch (err) { showAlert(err.message || "Delete failed."); }
        },
      });
    });

    taskList.appendChild(card);
  });
}

function renderProjectsDirectory(projects, tasksByProject = {}) {
  const count = document.getElementById("projectsListCount");
  const host = document.getElementById("projectsListHost");
  if (!host) return;
  if (count) {
    count.textContent = `${projects.length} project${projects.length === 1 ? "" : "s"}`;
  }
  if (!projects.length) {
    host.innerHTML = `
      <div class="card" style="text-align:center;padding:34px">
        <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:6px">No projects yet</div>
        <div style="font-size:12px;color:var(--text3);margin-bottom:16px">Start a new project to begin your first GAIA workflow.</div>
        <button class="btn btn-g btn-sm" onclick="window.beginNewProjectFlow?.();window.openProjectSetup?.()">Create project</button>
      </div>
    `;
    return;
  }

  host.innerHTML = projects.map((project) => {
    const tasks = tasksByProject[project.id] || [];
    const previewTask = tasks[0];
    return `
      <div class="card" style="margin-bottom:12px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px">
          <div style="flex:1">
            <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:3px">${project.name}</div>
            <div style="font-size:11px;color:var(--text4);font-weight:700;letter-spacing:0.5px">${tasks.length} task${tasks.length === 1 ? "" : "s"}  -  Updated ${fmtDate(project.updated_at || project.created_at)}</div>
          </div>
          <span class="badge ${project.id === appState.project?.id ? "bg" : "bgr"}">${project.id === appState.project?.id ? "Active" : "Project"}</span>
        </div>
        <div style="font-size:12px;color:var(--text2);line-height:1.7;margin-bottom:12px">${project.context || "No project context yet."}</div>
        ${previewTask ? `<div style="font-size:11px;color:var(--text3);margin-bottom:12px">Latest task: <strong style="color:var(--text)">${previewTask.name}</strong></div>` : `<div style="font-size:11px;color:var(--text3);margin-bottom:12px">No tasks created yet.</div>`}
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button class="btn btn-g btn-xs" onclick="window.openProjectFromDirectory?.('${project.id}')">Open project</button>
          <button class="btn btn-out btn-xs" onclick="window.editProjectFromDirectory?.('${project.id}')">Edit project</button>
          <button class="btn btn-out btn-xs" onclick="window.beginNewTaskForProject?.('${project.id}')">+ New task</button>
        </div>
      </div>
    `;
  }).join("");
}

/* Sidebar task sub-list */
function renderTaskSubList(tasks, projectId, container) {
  container.querySelector(".sb-task-sublist")?.remove();

  const subList = document.createElement("div");
  subList.className = "sb-task-sublist";
  subList.style.cssText = "margin:2px 0 4px 16px;padding-left:8px;border-left:1.5px solid var(--border2)";

  tasks.forEach((task) => {
    const active = task.id === appState.task?.id;
    const item = document.createElement("div");
    item.className = `sbi sb-item-task${active ? " active" : ""}`;
    item.style.cssText = "padding:5px 10px;font-size:11.5px;gap:6px";

    const dot = document.createElement("div");
    dot.className = `sdot ${lifecycleDot(task, active)}`;
    dot.style.cssText = "width:5px;height:5px;flex-shrink:0";

    const nameEl = document.createElement("span");
    nameEl.className = "sb-name";
    nameEl.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1";
    nameEl.textContent = task.name;

    const dotsWrap = document.createElement("div");
    dotsWrap.className = "sb-dots-wrap";
    const dotsBtn = document.createElement("button");
    dotsBtn.className = "sb-dots-btn";
    dotsBtn.textContent = "⋮";
    dotsBtn.title = "Actions";
    const dropdown = document.createElement("div");
    dropdown.className = "sb-dropdown";
    dropdown.innerHTML = `
      <div class="sb-dd-item" data-act="open">Open task</div>
      <div class="sb-dd-item" data-act="edit">Edit task setup</div>
      <div class="sb-dd-item" data-act="rename">Rename</div>
      <div class="sb-dd-sep"></div>
      <div class="sb-dd-item danger" data-act="delete">Delete</div>
    `;
    dotsWrap.append(dotsBtn, dropdown);

    dotsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = dropdown.classList.toggle("open");
      if (open) {
        const rect = dotsBtn.getBoundingClientRect();
        dropdown.style.top = rect.bottom + 2 + "px";
        dropdown.style.left = rect.left + "px";
        const close = () => { dropdown.classList.remove("open"); document.removeEventListener("click", close); };
        setTimeout(() => document.addEventListener("click", close), 0);
      }
    });

    item.append(dot, nameEl, dotsWrap);

    // Click on item: select task and navigate to analysis.
    item.addEventListener("click", (e) => {
      if (e.target.closest(".sb-dots-wrap")) return;
      e.stopPropagation();
      setTask(task);
      clearProcessingRun();
      syncContext(appState.project);
      const parent = container;
      const currentTasks = tasks.map((t) => (t.id === task.id ? {...t} : t));
      renderTaskSubList(currentTasks, projectId, parent);
      renderWorkflowProgress();
      window.go?.(document.querySelector("[data-s=analysis]"));
    });

    dropdown.querySelector("[data-act=open]").addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.remove("open");
      setTask(task);
      clearProcessingRun();
      syncContext(appState.project);
      renderWorkflowProgress();
      window.go?.(document.querySelector("[data-s=analysis]"));
    });

    dropdown.querySelector("[data-act=edit]").addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.remove("open");
      setTask(task);
      syncContext(appState.project);
      window.loadTaskForEdit?.(task, appState.project);
    });

    dropdown.querySelector("[data-act=rename]").addEventListener("click", async (e) => {
      e.stopPropagation();
      dropdown.classList.remove("open");
      startRename(nameEl, task.name, async (newName) => {
        await renameTask(projectId, task.id, newName);
        task.name = newName;
        nameEl.textContent = newName;
        if (appState.task?.id === task.id) {
          appState.task.name = newName;
          syncContext(appState.project);
        }
      });
    });

    dropdown.querySelector("[data-act=delete]").addEventListener("click", (e) => {
      e.stopPropagation();
      dropdown.classList.remove("open");
      showConfirm(`Delete task "<strong>${task.name}</strong>"? This cannot be undone.`, {
        title: "Delete task", confirmLabel: "Delete", danger: true,
        onConfirm: async () => {
          try {
            await deleteTask(projectId, task.id);
            if (appState.task?.id === task.id) clearTask();
            await refreshSidebar(); renderWorkflowProgress();
          } catch (err) { showAlert(err.message || "Delete failed."); }
        },
      });
    });

    subList.appendChild(item);
  });

  // New task button
  const newBtn = document.createElement("div");
  newBtn.className = "sbi";
  newBtn.style.cssText = "padding:5px 10px;font-size:11.5px;color:var(--g500)";
  newBtn.innerHTML = `<div class="sdot d-new" style="width:5px;height:5px;flex-shrink:0"></div><span>New task...</span>`;
  newBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    window.beginNewTaskFlow?.();
    window.openTaskSetup?.();
  });
  subList.appendChild(newBtn);

  container.appendChild(subList);
}

/* Sidebar project list */
function renderProjectList(projects, tasksForActive = []) {
  const projectList = document.getElementById("sb-project-list");
  if (!projectList) return;

  projectList.innerHTML = projects.length
    ? ""
    : `<div class="sbi"><div class="sdot d-idle"></div><span style="flex:1">No projects yet</span></div>`;

  projects.forEach((project) => {
    const active = project.id === appState.project?.id;
    const collapsed = collapsedProjects.has(project.id);
    const wrapper = document.createElement("div");

    const item = document.createElement("div");
    item.className = `sbi sb-item-project${active ? " active" : ""}`;

    // Collapse/expand chevron
    const chev = document.createElement("button");
    chev.className = "sb-chev";
    chev.title = collapsed ? "Expand" : "Collapse";
    chev.textContent = collapsed ? "›" : "▾";
    chev.addEventListener("click", (e) => {
      e.stopPropagation();
      if (collapsedProjects.has(project.id)) {
        collapsedProjects.delete(project.id);
      } else {
        collapsedProjects.add(project.id);
      }
      const nowCollapsed = collapsedProjects.has(project.id);
      chev.textContent = nowCollapsed ? "›" : "▾";
      chev.title = nowCollapsed ? "Expand" : "Collapse";
      if (active) {
        wrapper.querySelector(".sb-task-sublist")?.remove();
        if (!nowCollapsed) renderTaskSubList(tasksForActive, project.id, wrapper);
      }
    });

    const dot = document.createElement("div");
    dot.className = `sdot ${active ? "d-active" : "d-idle"}`;

    const nameEl = document.createElement("span");
    nameEl.className = "sb-name";
    nameEl.style.cssText = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1";
    nameEl.textContent = project.name;

    const countBadge = document.createElement("span");
    countBadge.className = "sb-count";
    countBadge.style.display = (active && tasksForActive.length) ? "" : "none";
    if (active && tasksForActive.length) countBadge.textContent = tasksForActive.length;

    // 3-dots dropdown for project actions
    const projDotsWrap = document.createElement("div");
    projDotsWrap.className = "sb-dots-wrap";
    const projDotsBtn = document.createElement("button");
    projDotsBtn.className = "sb-dots-btn";
    projDotsBtn.textContent = "⋮";
    projDotsBtn.title = "Project actions";
    const projDropdown = document.createElement("div");
    projDropdown.className = "sb-dropdown";
    projDropdown.innerHTML = `
      <div class="sb-dd-item" data-act="view">View project</div>
      <div class="sb-dd-item" data-act="newtask">+ New task</div>
      <div class="sb-dd-item" data-act="rename">Rename</div>
      <div class="sb-dd-sep"></div>
      <div class="sb-dd-item danger" data-act="delete">Delete project</div>
    `;
    projDotsWrap.append(projDotsBtn, projDropdown);

    projDotsBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      const open = projDropdown.classList.toggle("open");
      if (open) {
        const rect = projDotsBtn.getBoundingClientRect();
        projDropdown.style.top = rect.bottom + 2 + "px";
        projDropdown.style.left = rect.left + "px";
        const close = () => { projDropdown.classList.remove("open"); document.removeEventListener("click", close); };
        setTimeout(() => document.addEventListener("click", close), 0);
      }
    });

    item.append(chev, dot, nameEl, countBadge, projDotsWrap);

    // Click row: select project and navigate to the project screen.
    item.addEventListener("click", async (e) => {
      if (e.target.closest(".sb-dots-wrap") || e.target.closest(".sb-chev")) return;
      collapsedProjects.delete(project.id);
      await selectProject(project);
    });

    projDropdown.querySelector("[data-act=view]").addEventListener("click", async (e) => {
      e.stopPropagation();
      projDropdown.classList.remove("open");
      await selectProject(project);
    });

    projDropdown.querySelector("[data-act=newtask]").addEventListener("click", (e) => {
      e.stopPropagation();
      projDropdown.classList.remove("open");
      if (appState.project?.id !== project.id) setProject(project);
      window.beginNewTaskFlow?.();
      window.openTaskSetup?.();
    });

    projDropdown.querySelector("[data-act=rename]").addEventListener("click", async (e) => {
      e.stopPropagation();
      projDropdown.classList.remove("open");
      startRename(nameEl, project.name, async (newName) => {
        await renameProject(project.id, newName);
        project.name = newName;
        nameEl.textContent = newName;
        if (appState.project?.id === project.id) {
          appState.project.name = newName;
          syncContext(appState.project);
          const ptitle = document.getElementById("proj-title");
          if (ptitle) ptitle.textContent = newName;
        }
      });
    });

    projDropdown.querySelector("[data-act=delete]").addEventListener("click", (e) => {
      e.stopPropagation();
      projDropdown.classList.remove("open");
      showConfirm(`Delete project "<strong>${project.name}</strong>" and all its tasks? This cannot be undone.`, {
        title: "Delete project",
        confirmLabel: "Delete",
        danger: true,
        onConfirm: async () => {
          try {
            await deleteProject(project.id);
            if (appState.project?.id === project.id) {
              clearProject();
              clearTask();
              clearProcessingRun();
              syncContext(null);
            }
            await refreshSidebar();
            renderWorkflowProgress();
            await openProjectsList();
          } catch (err) { showAlert(err.message || "Delete failed."); }
        },
      });
    });

    wrapper.appendChild(item);

    if (active && !collapsed) {
      renderTaskSubList(tasksForActive, project.id, wrapper);
    }

    projectList.appendChild(wrapper);
  });
}

/* selectProject */
export async function selectProject(project) {
  setProject(project);
  clearTask();
  clearProcessingRun();
  const tasks = await listTasks(project.id);
  if (tasks.length) setTask(tasks[0]);
  syncContext(appState.project);
  const projects = await listProjects();
  renderProjectList(projects, tasks);
  document.getElementById("sidebar")?.classList.remove("off");
  renderProjectScreen(project, tasks);
  window.goProjectScreen?.();
  renderWorkflowProgress();
}

export async function openProjectsList() {
  const projects = await listProjects();
  const taskPairs = await Promise.all(
    projects.map(async (project) => {
      try {
        return [project.id, await listTasks(project.id)];
      } catch {
        return [project.id, []];
      }
    }),
  );
  const tasksByProject = Object.fromEntries(taskPairs);
  renderProjectsDirectory(projects, tasksByProject);
  document.querySelectorAll(".screen").forEach((node) => node.classList.remove("active"));
  document.getElementById("screen-projects")?.classList.add("active");
  document.querySelectorAll(".nlnk").forEach((node) => node.classList.remove("active"));
  document.querySelector("[data-s=projects]")?.classList.add("active");
  document.getElementById("sidebar")?.classList.add("off");
  document.getElementById("ctxBadge")?.style.setProperty("display", appState.project ? "flex" : "none");
  window.cur = "projects";
  window.setStatus?.("Projects", 0);
}

/* refreshSidebar */
export async function refreshSidebar({bootstrap = false} = {}) {
  wireProjectNewBtn();
  const projects = await listProjects();

  if (!projects.length) {
    clearProject();
    clearTask();
    clearProcessingRun();
    syncContext(null);
    renderProjectList([]);
    renderWorkflowProgress();
    return;
  }

  const selectedProject =
    projects.find((p) => p.id === appState.project?.id) || (bootstrap ? projects[0] : null);

  if (selectedProject) {
    setProject(selectedProject);
  } else {
    clearProject();
  }

  let tasksForActive = [];
  if (selectedProject) {
    const tasks = await listTasks(selectedProject.id);
    const selectedTask =
      tasks.find((t) => t.id === appState.task?.id) || (bootstrap ? tasks[0] || null : appState.task);
    setTask(selectedTask || null);
    tasksForActive = tasks;
  } else {
    clearTask();
  }

  syncContext(selectedProject || null);
  renderProjectList(projects, tasksForActive);
  renderWorkflowProgress();
}

/* initSidebar */
export function initSidebar() {
  wireProjectNewBtn();
  syncContext();
  initSidebarResize();
  window.openProjectsList = openProjectsList;
  window.openProjectFromDirectory = async (projectId) => {
    const project = (await listProjects()).find((item) => item.id === projectId);
    if (project) {
      await selectProject(project);
    }
  };
  window.editProjectFromDirectory = async (projectId) => {
    const project = (await listProjects()).find((item) => item.id === projectId);
    if (!project) return;
    setProject(project);
    syncContext(project);
    window.beginEditProjectFlow?.();
    window.openProjectSetup?.();
  };
  window.beginNewTaskForProject = async (projectId) => {
    const project = (await listProjects()).find((item) => item.id === projectId);
    if (!project) return;
    setProject(project);
    syncContext(project);
    window.beginNewTaskFlow?.();
    window.openTaskSetup?.();
  };
}

function initSidebarResize() {
  const sidebar = document.getElementById("sidebar");
  if (!sidebar) return;

  const saved = parseInt(localStorage.getItem("sidebarWidth") || "0", 10);
  if (saved >= 160 && saved <= 480) sidebar.style.width = saved + "px";

  const EDGE = 6; // px from right edge that triggers resize
  let dragging = false;
  let startX = 0;
  let startW = 0;

  sidebar.addEventListener("mousemove", (e) => {
    const rect = sidebar.getBoundingClientRect();
    sidebar.style.cursor = e.clientX >= rect.right - EDGE ? "col-resize" : "";
  });

  sidebar.addEventListener("mouseleave", () => {
    if (!dragging) sidebar.style.cursor = "";
  });

  sidebar.addEventListener("mousedown", (e) => {
    const rect = sidebar.getBoundingClientRect();
    if (e.clientX < rect.right - EDGE) return;
    dragging = true;
    startX = e.clientX;
    startW = sidebar.offsetWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();

    const onMove = (ev) => {
      if (!dragging) return;
      const w = Math.max(160, Math.min(480, startW + ev.clientX - startX));
      sidebar.style.width = w + "px";
    };
    const onUp = () => {
      dragging = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      localStorage.setItem("sidebarWidth", String(sidebar.offsetWidth));
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  });
}
