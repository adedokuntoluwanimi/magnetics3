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

// Approximate ETA per step in seconds (shown while queued/running)
const STEP_ETA = [5, 4, 6, 8, 45, 12, 6];

const CORRECTION_LABELS = {
  diurnal: "Diurnal correction", igrf: "IGRF removal",
  filtering: "Filtering", lag: "Lag correction", heading: "Heading correction",
};
const ADD_ON_LABELS = {
  rtp: "RTP",
  analytic_signal: "Analytic signal",
  first_vertical_derivative: "First vertical derivative",
  horizontal_derivative: "Horizontal derivative",
  emag2: "EMAG2 comparison",
  uncertainty: "Uncertainty",
};
const MODEL_LABELS = {kriging: "Kriging", ml: "Machine learning", hybrid: "Hybrid", none: "No modelling"};

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
  const runPrediction = appState.task?.analysis_config?.run_prediction !== false;
  const roots = getRoots();
  const visibleSteps = (run?.steps || [])
    .map((step, originalIndex) => ({...step, originalIndex}))
    .filter((step) => runPrediction || step.name?.toLowerCase() !== "modelling");
  roots.pipeWrap.innerHTML = visibleSteps.map((step, displayIndex) => {
    const isRunning = step.status === "running";
    const etaSec = STEP_ETA[step.originalIndex] || 10;
    const etaLabel = etaSec >= 60 ? `~${Math.round(etaSec / 60)} min` : `~${etaSec}s`;
    const etaHtml = step.status === "queued"
      ? `<div style="font-size:10px;color:var(--text4);margin-top:3px">Est. ${etaLabel}</div>`
      : "";
    const progressBar = isRunning
      ? `<div class="prog-bar" style="margin-top:8px;width:100%;max-width:220px"><div class="prog-fill" style="width:60%;animation:progPulse 2s ease-in-out infinite"></div></div>`
      : "";
    return `
    <div class="pipe-card ${step.status === "completed" ? "done" : ""}${isRunning ? " running" : ""}">
      <div class="pipe-card-inner">
        <div class="pipe-icon-wrap" style="font-size:12px;font-weight:700;font-family:'Roboto',sans-serif;color:var(--g600)">${String(displayIndex + 1).padStart(2, "0")}</div>
        <div class="pipe-text">
          <div class="pipe-name">${titleCase(step.name)}</div>
          <div class="pipe-detail">${step.detail || titleCase(step.status)}</div>
          ${etaHtml}
          ${progressBar}
        </div>
        <div class="pipe-status">${statusBadge(step.status)}</div>
      </div>
    </div>
  `;
  }).join("");
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


function renderConfigSummary(task) {
  const screen = document.getElementById("screen-processing");
  let card = document.getElementById("procConfigCard");
  if (!card) {
    card = document.createElement("div");
    card.id = "procConfigCard";
    card.style.cssText = "margin-bottom:16px";
    const pipeWrap = document.getElementById("pipeWrap");
    pipeWrap?.parentNode?.insertBefore(card, pipeWrap);
  }
  const config = task?.analysis_config || {};
  const corrections = (config.corrections || []).map((c) => CORRECTION_LABELS[c] || c);
  const addOns = (config.add_ons || []).map((a) => ADD_ON_LABELS[a] || a);
  const model = MODEL_LABELS[config.model] || config.model || "Machine learning";
  const scenario = task?.scenario || "sparse";
  const spacing = task?.station_spacing
    ? `${task.station_spacing} ${task.station_spacing_unit || "m"}`
    : null;
  const runPrediction = config.run_prediction !== false;

  const badge = (text, color) =>
    `<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10.5px;font-weight:700;background:var(--${color}-bg,var(--bg2));color:var(--${color},var(--text2));margin:2px 3px 2px 0">${text}</span>`;

  const rows = [
    ["Scenario", badge(titleCase(scenario), "g5")],
    ...(spacing ? [["Grid spacing", badge(spacing, "blue")]] : []),
    ["Model", badge(model, runPrediction ? "amber" : "text4")],
    corrections.length ? ["Corrections", corrections.map((c) => badge(c, "g5")).join("")] : null,
    addOns.length ? ["Add-ons", addOns.map((a) => badge(a, "blue")).join("")] : null,
  ].filter(Boolean);

  card.innerHTML = `
    <div class="sep first">Your configuration</div>
    <div class="card card-sm" style="padding:10px 14px">
      ${rows.map(([k, v]) => `
        <div style="display:flex;align-items:flex-start;gap:10px;padding:6px 0;border-bottom:1px solid var(--g100)">
          <div style="font-size:11px;color:var(--text3);font-weight:500;min-width:100px;padding-top:3px">${k}</div>
          <div style="flex:1;line-height:1.6">${v}</div>
        </div>`).join("")}
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
  renderConfigSummary(appState.task);
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
