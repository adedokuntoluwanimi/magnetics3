import {appState} from "../state.js";

function ensureProgressNode() {
  let node = document.getElementById("workflowProgress");
  if (node) {
    return node;
  }
  const target = document.querySelector(".nav-right");
  node = document.createElement("div");
  node.id = "workflowProgress";
  node.style.display = "none";
  node.style.minWidth = "150px";
  node.style.padding = "6px 10px";
  node.style.border = "1px solid var(--border)";
  node.style.borderRadius = "14px";
  node.style.background = "var(--bg2)";
  node.style.boxShadow = "var(--shadow)";
  target.prepend(node);
  return node;
}

function getProgressState() {
  const task = appState.task;
  const run = appState.processingRun;
  if (!task) {
    return null;
  }
  if (run?.status === "running") {
    const completed = (run.steps || []).filter((step) => step.status === "completed").length;
    const total = (run.steps || []).length || 1;
    const active = run.steps?.find((step) => step.status === "running")?.name || "processing";
    return {
      label: "Processing",
      detail: `${completed}/${total} pipeline steps`,
      percent: Math.max(8, Math.round((completed / total) * 100)),
      accent: "var(--amber)",
      note: active.replace(/_/g, " "),
    };
  }
  if (run?.status === "failed" || task.lifecycle === "failed") {
    return {
      label: "Attention",
      detail: "Processing failed",
      percent: 100,
      accent: "var(--red)",
      note: "check logs",
    };
  }
  if (task.lifecycle === "completed") {
    const latestExport = (task.export_jobs || []).slice(-1)[0];
    if (latestExport?.status === "completed") {
      return {
        label: "Export Ready",
        detail: `${(latestExport.details?.artifacts || []).length} live files ready`,
        percent: 100,
        accent: "var(--g500)",
        note: "download available",
      };
    }
    return {
      label: "Results Ready",
      detail: "Processing complete",
      percent: 100,
      accent: "var(--g500)",
      note: "open visualisation",
    };
  }
  if (task.analysis_config?.model) {
    return {
      label: "Configured",
      detail: "Ready for preview and processing",
      percent: 55,
      accent: "var(--blue)",
      note: task.analysis_config.model,
    };
  }
  return {
    label: "Setup",
    detail: "Task created",
    percent: 25,
    accent: "var(--blue)",
    note: task.processing_mode,
  };
}

export function renderWorkflowProgress() {
  const node = ensureProgressNode();
  const state = getProgressState();
  if (!state) {
    node.style.display = "none";
    return;
  }
  node.style.display = "block";
  node.innerHTML = `
  <div style="display:flex;align-items:center;gap:8px">
    <div style="font-size:10px;font-weight:700;letter-spacing:0.8px;color:var(--text4);text-transform:uppercase;white-space:nowrap">${state.label}</div>
    <div style="flex:1;height:5px;border-radius:999px;background:var(--bg3);overflow:hidden"><div style="height:100%;width:${state.percent}%;background:${state.accent};border-radius:999px"></div></div>
    <div style="font-size:10px;color:${state.accent};font-weight:700">${state.percent}%</div>
  </div>
  <div style="font-size:10px;color:var(--text4);margin-top:3px;text-transform:capitalize;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${state.note}</div>
`;
}

export function initWorkflowProgress() {
  renderWorkflowProgress();
}
