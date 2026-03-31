import {fetchPreview} from "../api.js";
import {persistAnalysis} from "./analysis.js";
import {renderWorkflowProgress} from "./progress.js";
import {appState, setPredictedMarkerColor, setSurveyMarkerColor, setBaseStationMarkerColor, setTask} from "../state.js";
import {titleCase} from "../shared/format.js";
import {showGlobalNotice} from "../shared/notice.js";
import {renderStationMap, recolorSurveyMarkers, recolorPredictedMarkers, recolorBaseStationMarkers} from "./maps.js";
import {initAIChat} from "../shared/ai_chat.js";

let _previewChat = null;

// Human-readable labels for normalized backend IDs
const CORRECTION_LABELS = {
  diurnal: "Diurnal",
  igrf: "IGRF removal",
  filtering: "Filtering",
  lag: "Lag correction",
  heading: "Heading correction",
};

const ADD_ON_LABELS = {
  rtp: "RTP",
  analytic_signal: "Analytic signal",
  first_vertical_derivative: "First vertical derivative",
  horizontal_derivative: "Horizontal derivative",
  emag2: "Regional residual",
  uncertainty: "Uncertainty",
};

const MODEL_LABELS = {
  kriging: "Kriging",
  ml: "Machine learning",
  hybrid: "Hybrid",
};

function setVal(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text ?? "—";
}

function ensurePreviewMapHost() {
  const existing = document.getElementById("previewMapCanvas");
  if (existing) return existing;
  const legacy = document.getElementById("previewMap");
  const host = document.createElement("div");
  host.id = "previewMapCanvas";
  host.style.width = "100%";
  host.style.height = "100%";
  legacy.replaceWith(host);
  return host;
}


function renderPreview(payload) {
  const project = payload.project;
  const task = payload.task;
  const config = task.analysis_config || {};
  const points = payload.preview_points || task.results?.data?.points || [];

  setTask(task);
  renderWorkflowProgress();

  // Project & task card
  setVal("pv-project", project.name);
  setVal("pv-task", task.name);
  setVal("pv-points", points.length ? String(points.length) : "—");
  setVal("pv-traverses", payload.traverse_count ? String(payload.traverse_count) : "—");
  setVal("pv-pred-traverses", payload.predicted_traverse_count ? String(payload.predicted_traverse_count) : "—");
  setVal("pv-platform", task.platform ? titleCase(task.platform) : "—");
  setVal("pv-scenario", task.scenario ? titleCase(task.scenario) : "Optional / automatic");
  const lineMode = task.line_interpolation === false ? "grid" : (window.state?.lineMode || "line");
  const gridRows = window.state?.gridRows || "—";
  const gridCols = window.state?.gridCols || "—";
  if (task.scenario === "sparse") {
    setVal("pv-interp", lineMode === "grid" ? "Full grid" : "Along lines");
    setVal("pv-grid", lineMode === "grid" ? `${gridRows} × ${gridCols}` : "—");
  } else {
    setVal("pv-interp", "—");
    setVal("pv-grid", "—");
  }
  setVal("pv-mode", task.processing_mode ? titleCase(task.processing_mode) : "—");
  setVal("pv-basemap", task.basemap_file?.file_name || "None");

  // Analysis card
  const corrections = (config.corrections || [])
    .map((id) => CORRECTION_LABELS[id] || id)
    .join(", ") || "None";
  const addOns = (config.add_ons || [])
    .map((id) => ADD_ON_LABELS[id] || id)
    .join(", ") || "None";
  const model = MODEL_LABELS[config.model] || config.model || "Not set";
  const estRuntime = points.length
    ? `~${Math.max(2, Math.ceil(points.length / 1500))} min`
    : "—";

  setVal("pv-corrections", corrections);
  setVal("pv-model", model);
  setVal("pv-addons", addOns);
  setVal("pv-runtime", estRuntime);

  const legendPred = document.getElementById("leg-pred");
  if (legendPred) legendPred.style.display = "none";

  return points;
}

function setPreviewLoading(on, label = "Loading preview...") {
  const overlay = document.getElementById("pvLoadingOverlay");
  const lbl = document.getElementById("pvLoadingLabel");
  if (!overlay) return;
  if (lbl) lbl.textContent = label;
  overlay.style.display = on ? "flex" : "none";
}

export async function loadPreview() {
  if (!appState.project || !appState.task) {
    throw new Error("Create a project and task before opening Preview.");
  }
  setPreviewLoading(true, "Loading preview...");
  try {
    try {
      await persistAnalysis();
    } catch (error) {
      console.warn("Could not persist analysis before loading preview:", error);
      showGlobalNotice("Preview loaded with the last saved analysis settings because the latest analysis changes could not be saved.");
    }
    setPreviewLoading(true, "Fetching survey data...");
    const preview = await fetchPreview(appState.project.id, appState.task.id);
    const points = renderPreview(preview);
    const predictedPoints = preview.predicted_points || [];

    // Show/hide predicted legend item
    const legPred = document.getElementById("leg-pred");
    if (legPred) legPred.style.display = predictedPoints.length ? "flex" : "none";

    // Show/hide base station legend item
    const legendBase = document.getElementById("leg-base");
    const hasBasePoints = points.some((p) => p.is_base_station);
    if (legendBase) legendBase.style.display = hasBasePoints ? "flex" : "none";

    setPreviewLoading(true, "Rendering map...");
    const host = ensurePreviewMapHost();
    await renderStationMap(host, points, {predictedPoints, showLines: false});
    recolorSurveyMarkers(appState.mapColors.survey);
    recolorPredictedMarkers(appState.mapColors.predicted);

    const legend = document.getElementById("mapLegend");
    if (legend) legend.style.zIndex = "2";

    // Show color picker and wire up setMapColor
    const colorPicker = document.getElementById("mapColorPicker");
    if (colorPicker) colorPicker.style.display = "block";
    // Show predicted colour row only if there are predicted points
    const predColorLabel = document.getElementById("predColorLabel");
    const predColorSwatches = document.getElementById("predColorSwatches");
    if (predColorLabel) predColorLabel.style.display = predictedPoints.length ? "block" : "none";
    if (predColorSwatches) predColorSwatches.style.display = predictedPoints.length ? "flex" : "none";

    window.setMapColor = (color, swatchEl) => {
      recolorSurveyMarkers(color);
      setSurveyMarkerColor(color);
      document.querySelectorAll(".mcp-swatch-survey").forEach((s) => s.classList.remove("active"));
      swatchEl?.classList.add("active");
      const legDot = document.getElementById("leg-measured-dot");
      if (legDot) legDot.style.background = color;
    };
    window.setPredictedColor = (color, swatchEl) => {
      recolorPredictedMarkers(color);
      setPredictedMarkerColor(color);
      document.querySelectorAll(".mcp-swatch-pred").forEach((s) => s.classList.remove("active"));
      swatchEl?.classList.add("active");
      const legDot = document.getElementById("leg-pred-dot");
      if (legDot) {
        legDot.style.background = color;
        legDot.style.border = color === "#ffffff" ? "1px solid #1a5f8c" : "1px solid rgba(0,0,0,0.2)";
      }
    };
    window.setBaseStationColor = (color, swatchEl) => {
      recolorBaseStationMarkers(color);
      setBaseStationMarkerColor(color);
      document.querySelectorAll(".mcp-swatch-bs").forEach((s) => s.classList.remove("active"));
      swatchEl?.classList.add("active");
      const legDot = document.getElementById("leg-base-dot");
      if (legDot) { legDot.style.background = color; legDot.style.borderColor = color; }
    };
    document.querySelectorAll(".mcp-swatch-survey").forEach((swatch) => {
      swatch.classList.toggle("active", swatch.dataset.color?.toLowerCase() === appState.mapColors.survey.toLowerCase());
    });
    document.querySelectorAll(".mcp-swatch-pred").forEach((swatch) => {
      swatch.classList.toggle("active", swatch.dataset.color?.toLowerCase() === appState.mapColors.predicted.toLowerCase());
    });
    const legMeasuredDot = document.getElementById("leg-measured-dot");
    if (legMeasuredDot) legMeasuredDot.style.background = appState.mapColors.survey;
    const legPredDot = document.getElementById("leg-pred-dot");
    if (legPredDot) {
      legPredDot.style.background = appState.mapColors.predicted;
      legPredDot.style.border = appState.mapColors.predicted.toLowerCase() === "#ffffff" ? "1px solid #1a5f8c" : "1px solid rgba(0,0,0,0.2)";
    }

    const attribution = document.querySelector("#screen-preview .map-attribution");
    if (attribution && points.length) {
      const lats = points.map((p) => Number(p.latitude));
      const lons = points.map((p) => Number(p.longitude));
      const minLat = Math.min(...lats).toFixed(4);
      const maxLat = Math.max(...lats).toFixed(4);
      const minLon = Math.min(...lons).toFixed(4);
      const maxLon = Math.max(...lons).toFixed(4);
      attribution.textContent = `Google Maps · ${minLat}, ${minLon} → ${maxLat}, ${maxLon}`;
    }
    // Fire AI analysis after map loads (non-blocking)
    _loadPreviewAI();
  } finally {
    setPreviewLoading(false);
  }
}

function _loadPreviewAI() {
  const bodyEl = document.getElementById("previewAIBody");
  const inputEl = document.getElementById("previewAIInput");
  const sendEl = document.getElementById("previewAISend");
  if (!bodyEl || !inputEl || !sendEl) return;
  if (!_previewChat) {
    _previewChat = initAIChat(bodyEl, inputEl, sendEl, {location: "preview"});
  }
}

window.drawPreviewMap = async () => {
  if (appState.project && appState.task) {
    await loadPreview();
  }
};
