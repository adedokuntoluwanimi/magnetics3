import {fetchProcessingRun, fetchTask, startProcessing} from "../api.js";
import {renderWorkflowProgress} from "./progress.js";
import {appState, setProcessingRun, setTask} from "../state.js";
import {ensureElement} from "../shared/dom.js";
import {formatNumber, titleCase} from "../shared/format.js";

let pollHandle = null;
let startPromise = null;
const IDLE_STEPS = [
  {name: "Data loading", detail: "Waiting for you to start processing."},
  {name: "Data cleaning", detail: "Queued"},
  {name: "Corrections", detail: "Queued"},
  {name: "Station grid", detail: "Queued"},
  {name: "Modelling", detail: "Queued"},
  {name: "Derived layers", detail: "Queued"},
  {name: "Save results", detail: "Queued"},
];

function getRoots() {
  const screen = document.getElementById("screen-processing");
  const sideRows = screen.querySelectorAll(".srow .sv");
  return {
    screen,
    pipeWrap: document.getElementById("pipeWrap"),
    procEta: document.getElementById("procEta"),
    completeCTA: document.getElementById("completeCTA"),
    sideRows,
  };
}

function statusBadge(status) {
  if (status === "completed") {
    return "<div class=\"pipe-check\">✓</div>";
  }
  if (status === "running") {
    return "<div class=\"pipe-pending-dot\"><div class=\"pipe-pending-inner\"></div></div>";
  }
  if (status === "failed") {
    return "<div class=\"pipe-check\" style=\"background:var(--red-bg);color:var(--red)\">!</div>";
  }
  return "<div class=\"pipe-pending-dot\"><div class=\"pipe-pending-inner\"></div></div>";
}

function renderPipeline(run) {
  const roots = getRoots();
  roots.pipeWrap.innerHTML = (run?.steps || []).map((step, index) => `
    <div class="pipe-card ${step.status === "completed" ? "done" : ""}">
      <div class="pipe-card-inner">
        <div class="pipe-icon-wrap" style="font-size:12px;font-weight:700;font-family:'Roboto',sans-serif;color:var(--g600)">${String(index + 1).padStart(2, "0")}</div>
        <div class="pipe-text">
          <div class="pipe-name">${titleCase(step.name)}</div>
          <div class="pipe-detail">${step.detail || titleCase(step.status)}</div>
        </div>
        <div class="pipe-status">${statusBadge(step.status)}</div>
      </div>
    </div>
  `).join("");
}

function renderIdlePipeline() {
  renderPipeline({
    steps: IDLE_STEPS.map((step) => ({
      ...step,
      status: "queued",
    })),
  });
}

function renderLogs(run) {
  const roots = getRoots();
  const container = ensureElement(roots.screen.querySelector("div[style*='overflow-y:auto']"), "#procLogs", () => {
    const node = document.createElement("div");
    node.id = "procLogs";
    node.style.marginTop = "14px";
    roots.procEta.after(node);
    return node;
  });
  const logs = (run?.logs || []).slice(-12).reverse();
  container.innerHTML = `
    <div class="sep">Logs</div>
    <div class="card card-sm">
      ${logs.length ? logs.map((entry) => `
        <div style="display:flex;gap:10px;align-items:flex-start;padding:8px 0;border-top:1px solid var(--g100)">
          <div style="font-size:10px;color:var(--text4);font-family:'JetBrains Mono',monospace;min-width:60px">${new Date(entry.timestamp).toLocaleTimeString()}</div>
          <div style="font-size:11px;color:var(--text3);flex:1"><strong style="color:var(--text)">${titleCase(entry.step)}</strong> · ${entry.detail}</div>
        </div>
      `).join("") : "<div style='font-size:11px;color:var(--text3)'>No processing logs yet.</div>"}
    </div>
  `;
}


function renderSideStats(task) {
  const roots = getRoots();
  const profile = task?.dataset_profile || {};
  const bounds = profile.bounds || {};
  const rows = [
    String(profile.files_count || 0),
    String(profile.total_rows || 0),
    bounds.min_x !== null ? `${formatNumber(bounds.max_y - bounds.min_y, 4)}° × ${formatNumber(bounds.max_x - bounds.min_x, 4)}°` : "—",
    formatNumber(profile.magnetic_min),
    formatNumber(profile.magnetic_max),
  ];
  roots.sideRows.forEach((node, index) => {
    if (rows[index] !== undefined) {
      node.textContent = rows[index];
    }
  });
}

async function refreshTask() {
  if (!appState.project || !appState.task) {
    return;
  }
  const task = await fetchTask(appState.project.id, appState.task.id);
  setTask(task);
  renderWorkflowProgress();
}

async function pollRun(runId) {
  clearTimeout(pollHandle);
  const run = await fetchProcessingRun(runId);
  setProcessingRun(run);
  renderWorkflowProgress();
  renderPipeline(run);
  renderLogs(run);
  getRoots().procEta.textContent = run.status === "completed"
    ? "Processing complete."
    : run.status === "failed"
      ? `Processing failed: ${run.error || "Check logs."}`
      : "Processing in progress…";

  const cta = getRoots().completeCTA;
  if (run.status === "completed") {
    await refreshTask();
    cta.style.display = "block";
    cta.innerHTML = `
      <div class="complete-cta">
        <div class="cta-text">
          <div class="cta-t">Processing complete ✓</div>
          <div class="cta-d">Results, grids, and surfaces are ready for visualisation.</div>
        </div>
        <button class="btn btn-white" style="flex-shrink:0" onclick="go(document.querySelector('[data-s=visualisation]'))">View visualisations →</button>
      </div>
    `;
    return;
  }
  if (run.status === "failed") {
    cta.style.display = "none";
    return;
  }
  cta.style.display = "none";
  pollHandle = window.setTimeout(() => pollRun(runId), 3000);
}

export async function loadProcessingView() {
  if (!appState.task) {
    throw new Error("Create a task before opening Processing.");
  }
  const roots = getRoots();
  renderSideStats(appState.task);
  if (appState.processingRun?.id) {
    renderPipeline(appState.processingRun);
    renderLogs(appState.processingRun);
    roots.procEta.textContent = titleCase(appState.processingRun.status);
    return;
  }
  if (appState.task?.processing_run_id) {
    await pollRun(appState.task.processing_run_id);
    return;
  }
  renderIdlePipeline();
  renderLogs({logs: []});
  roots.completeCTA.style.display = "none";
  roots.procEta.textContent = "Ready to start processing.";
}

export async function triggerProcessing() {
  if (!appState.task || startPromise) {
    if (!appState.task) {
      throw new Error("Create and configure a task before starting processing.");
    }
    return startPromise;
  }
  startPromise = (async () => {
    const run = appState.task.processing_run_id
      ? await fetchProcessingRun(appState.task.processing_run_id)
      : await startProcessing(appState.task.id);
    setProcessingRun(run);
    renderWorkflowProgress();
    window.procStarted = true;
    await refreshTask();
    await pollRun(run.id);
  })();
  try {
    await startPromise;
  } finally {
    startPromise = null;
  }
}

export function initProcessing() {
  window.startProc = triggerProcessing;
  window.triggerProcessing = triggerProcessing;
}
