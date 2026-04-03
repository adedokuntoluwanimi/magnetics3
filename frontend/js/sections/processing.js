import {fetchProcessingRun, fetchTask, startProcessing} from "../api.js";
import {renderWorkflowProgress} from "./progress.js";
import {appState, clearTaskResults, setProcessingRun, setTask} from "../state.js";
import {ensureElement} from "../shared/dom.js";
import {formatNumber, titleCase} from "../shared/format.js";

let pollHandle = null;
let startPromise = null;
const IDLE_STEPS = [
  {name: "Load and validate", detail: "Waiting for you to start processing."},
  {name: "Clean and standardize", detail: "Queued"},
  {name: "Line-domain corrections", detail: "Queued"},
  {name: "Leveling and crossover", detail: "Queued"},
  {name: "Prediction target preparation", detail: "Queued"},
  {name: "Modelling and interpolation", detail: "Queued"},
  {name: "Grid-domain transforms", detail: "Queued"},
  {name: "Uncertainty synthesis", detail: "Queued"},
  {name: "QA report", detail: "Queued"},
  {name: "Save results", detail: "Queued"},
];

// Approximate ETA per step in seconds (shown while queued/running)
const STEP_ETA = [6, 5, 8, 10, 8, 45, 12, 8, 5, 6];

const CORRECTION_LABELS = {
  diurnal: "Diurnal correction", igrf: "IGRF removal",
  filtering: "Filtering", lag: "Lag correction", heading: "Heading correction",
};
const ADD_ON_LABELS = {
  rtp: "RTP",
  analytic_signal: "Analytic signal",
  first_vertical_derivative: "First vertical derivative",
  horizontal_derivative: "Horizontal derivative",
  emag2: "Regional field + residual",
  uncertainty: "Uncertainty",
};
const MODEL_LABELS = {kriging: "Kriging", ml: "Machine learning", hybrid: "Hybrid", none: "No modelling"};
const EXECUTION_ETA = {
  "validate inputs": 6,
  "standardize dataset": 5,
  "diurnal correction": 8,
  "igrf removal": 8,
  "lag correction": 8,
  "heading correction": 8,
  "filtering": 8,
  "leveling and crossover": 10,
  "prediction target preparation": 8,
  "kriging modelling": 45,
  "machine learning modelling": 45,
  "hybrid modelling": 45,
  "regional field + residual": 12,
  "rtp": 12,
  "analytic signal": 12,
  "first vertical derivative": 12,
  "horizontal derivative": 12,
  "uncertainty": 8,
  "qa report": 5,
  "save results": 6,
};

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

function simplifyProcessingDetail(detail, stepName = "") {
  const raw = String(detail || "").trim();
  if (!raw) return "Working...";
  const step = String(stepName || "").toLowerCase();
  if (step.includes("line-domain corrections")) return "Corrections checked and applied where data support was available.";
  if (step.includes("qa report")) return raw.replace(/^QA status:\s*/i, "QA report prepared with status ");
  if (step.includes("save results")) return raw.replace(/^Saved\s+/i, "Stored ");
  if (/igrf failed|pyigrf unavailable/i.test(raw)) {
    return raw
      .replace(/IGRF FAILED\s*[—-]?\s*/i, "IGRF could not run. ")
      .replace(/\(output not geophysically corrected\)/i, "The data stayed unchanged for that step.")
      .replace(/diurnal correction via base station CubicSpline/gi, "Diurnal correction used base-station interpolation")
      .replace(/low-pass FFT filter/gi, "Low-pass filter")
      .trim();
  }
  if (/requested help:|geologically|configured corrections|selected add-ons/i.test(raw)) return "Aurora AI can explain this screen in plain language if you need it.";
  return raw;
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
  const visibleSteps = buildExecutionSteps(appState.task, run);
  roots.pipeWrap.innerHTML = visibleSteps.map((step, displayIndex) => {
    const isRunning = step.status === "running";
    const etaSec = EXECUTION_ETA[String(step.name || "").toLowerCase()] || STEP_ETA[step.originalIndex] || 10;
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
          <div class="pipe-detail">${simplifyProcessingDetail(step.detail || titleCase(step.status), step.name)}</div>
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
  renderPipeline(null);
}

function buildExecutionSteps(task, run) {
  const config = task?.analysis_config || {};
  const selectedCorrections = (config.corrections || []).map((item) => CORRECTION_LABELS[item] || titleCase(item));
  const selectedAddOns = (config.add_ons || []).map((item) => ADD_ON_LABELS[item] || titleCase(item));
  const runPrediction = config.run_prediction !== false;
  const modelStep = runPrediction ? `${MODEL_LABELS[config.model] || titleCase(config.model || "Machine learning")} modelling` : null;
  const synthetic = [
    {name: "Validate inputs", detail: "Checking uploaded files, mapping, and coordinate fields."},
    {name: "Standardize dataset", detail: "Cleaning rows and preserving supported measured and base-station records."},
    ...selectedCorrections.map((name) => ({name, detail: detailForConfiguredStep(name)})),
    {name: "Leveling and crossover", detail: "Comparing line consistency and applying leveling only if support exists."},
    {name: "Prediction target preparation", detail: "Preparing the exact scenario you selected for modelling or observed-only output."},
    ...(modelStep ? [{name: modelStep, detail: "Generating the model path you selected in Analysis."}] : []),
    ...selectedAddOns.map((name) => ({name, detail: detailForConfiguredStep(name)})),
    {name: "QA report", detail: "Summarising validation, applied paths, warnings, and scientific confidence."},
    {name: "Save results", detail: "Packaging outputs, metadata, and downloadable deliverables."},
  ];
  if (!run?.steps?.length) {
    return synthetic.map((step, index) => ({...step, status: "queued", originalIndex: index}));
  }
  const generic = run.steps || [];
  const completedCount = generic.filter((step) => step.status === "completed").length;
  const runningIndex = generic.findIndex((step) => step.status === "running");
  return synthetic.map((step, index) => {
    let status = "queued";
    if (run.status === "completed") {
      status = "completed";
    } else if (index < completedCount) {
      status = "completed";
    } else if (runningIndex !== -1 && index === runningIndex) {
      status = "running";
    } else if (runningIndex === -1 && index === completedCount && run.status === "running") {
      status = "running";
    } else if (run.status === "failed" && index === Math.max(completedCount, 0)) {
      status = "failed";
    }
    const sourceStep = generic[Math.min(index, generic.length - 1)] || {};
    return {
      ...step,
      status,
      detail: status === "completed" || status === "running"
        ? simplifyProcessingDetail(sourceStep.detail || step.detail, sourceStep.name || step.name)
        : step.detail,
      originalIndex: index,
    };
  });
}

function detailForConfiguredStep(name) {
  const key = String(name || "").toLowerCase();
  const details = {
    "diurnal correction": "Using repeated base-station revisits to correct each time segment between consecutive base readings.",
    "igrf removal": "Removing only the supported regional reference field path and labelling any fallback honestly.",
    "filtering": "Applying the exact filter mode chosen in Analysis to the processed magnetic data.",
    "lag correction": "Checking line timing offsets conservatively before applying any lag shift.",
    "heading correction": "Comparing directional bias between headings and only correcting where support is adequate.",
    "rtp": "Generating reduction-to-pole only when the required magnetic-field parameters support it.",
    "analytic signal": "Computing analytic signal to highlight magnetic source edges and contacts.",
    "first vertical derivative": "Computing first vertical derivative to sharpen shallow responses.",
    "horizontal derivative": "Computing horizontal derivative to emphasise lateral gradients.",
    "regional field + residual": "Separating the broad regional field from the residual magnetic response for comparison.",
    "uncertainty": "Combining support distance and model variance into an uncertainty surface.",
  };
  return details[key] || `${name} will run only where the uploaded data supports it.`;
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
          <div style="font-size:11px;color:var(--text3);flex:1"><strong style="color:var(--text)">${titleCase(entry.step)}</strong> · ${simplifyProcessingDetail(entry.detail, entry.step)}</div>
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
  const runPrediction = config.run_prediction !== false;
  const filterMode = config.filter_type
    ? titleCase(String(config.filter_type).replace(/-/g, " "))
    : null;
  const scenario = task?.scenario ? titleCase(task.scenario) : "Automatic";

  const badge = (text, color) =>
    `<span style="display:inline-block;padding:2px 8px;border-radius:4px;font-size:10.5px;font-weight:700;background:var(--${color}-bg,var(--bg2));color:var(--${color},var(--text2));margin:2px 3px 2px 0">${text}</span>`;

  const rows = [
    ["Prediction modelling", badge(runPrediction ? "On" : "Off", runPrediction ? "amber" : "text4")],
    ["Scenario", badge(scenario, "blue")],
    ["Model", badge(model, runPrediction ? "amber" : "text4")],
    filterMode ? ["Filter mode", badge(filterMode, "blue")] : null,
    ["Corrections", corrections.length ? corrections.map((c) => badge(c, "g5")).join("") : badge("None selected", "text4")],
    ["Add-ons", addOns.length ? addOns.map((a) => badge(a, "blue")).join("") : badge("None selected", "text4")],
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
    clearTaskResults();
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
