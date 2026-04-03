import {fetchTask, fetchTaskResults} from "../api.js";
import {renderWorkflowProgress} from "./progress.js";
import {
  appState,
  setActiveResultLayer,
  setActiveTraverseFilter,
  setActiveVisualisation,
  setStackProfiles,
  setTask,
  setTaskResults,
} from "../state.js";
import {initAIChat} from "../shared/ai_chat.js";

let _visChat = null;
import {formatNumber, titleCase} from "../shared/format.js";
import {loadScript} from "../shared/loaders.js";
import {renderStationMap} from "./maps.js";

let plotlyPromise = null;
const _customPalettes = {};

function themeValue(token, fallback = "") {
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  return value || fallback;
}

function getPlotTheme() {
  return {
    text: themeValue("--text3", "#5f6d64"),
    grid: themeValue("--border2", "rgba(0,0,0,0.12)"),
    contourLine: themeValue("--border3", "rgba(20,30,24,0.28)"),
  };
}

function getLayerPalette(layer) {
  const custom = _customPalettes[layer.id];
  if (custom?.length >= 2) return custom;
  return layer.palette;
}

const LAYER_META = {
  magnetic: {
    label: "Corrected magnetic field",
    shortLabel: "TMF",
    key: "surface",
    unit: "nT",
    tone: "Core field",
    description: "Main corrected magnetic surface used for modelling and interpretation.",
    palette: ["#1a2980", "#0a9396", "#94d2bd", "#e9c46a", "#c0392b"],
  },
  filtered_surface: {
    label: "Filtered surface",
    shortLabel: "Filtered",
    key: "filtered_surface",
    unit: "nT",
    tone: "Correction",
    description: "Filter output using the processing option selected in Analysis.",
    palette: ["#113b57", "#1f6f9e", "#62b9dd", "#d8f2fb"],
  },
  rtp_surface: {
    label: "Reduction to pole",
    shortLabel: "RTP",
    key: "rtp_surface",
    unit: "nT",
    tone: "Add-on",
    description: "Pole-reduced surface when inclination/declination are available; QA will flag any fallback path.",
    palette: ["#1c3567", "#2d5ab3", "#79a8f2", "#e2edff"],
  },
  analytic_signal: {
    label: "Analytic signal",
    shortLabel: "Analytic",
    key: "analytic_signal",
    unit: "nT/m",
    tone: "Derivative",
    description: "Edge-enhancement layer highlighting source boundaries and contacts.",
    palette: ["#5d2f0a", "#ba6412", "#efae55", "#fff0cf"],
  },
  first_vertical_derivative: {
    label: "First vertical derivative",
    shortLabel: "FVD",
    key: "first_vertical_derivative",
    unit: "nT/m",
    tone: "Derivative",
    description: "Sharper near-surface enhancement that suppresses regional trends.",
    palette: ["#5a1b1b", "#b43737", "#ef7b68", "#ffe0d6"],
  },
  horizontal_derivative: {
    label: "Horizontal derivative",
    shortLabel: "HD",
    key: "horizontal_derivative",
    unit: "nT/m",
    tone: "Derivative",
    description: "Horizontal gradient magnitude for delineating lateral edges and structures.",
    palette: ["#3f2d14", "#8e6528", "#d6a55c", "#f9ebca"],
  },
  regional_field: {
    label: "Regional field",
    shortLabel: "Regional",
    key: "regional_field",
    unit: "nT",
    tone: "Trend",
    description: "Regional magnetic trend separated from the corrected field; single traverses use a line-fit trend and broader surfaces fall back to grid smoothing.",
    palette: ["#133b54", "#2f6e8f", "#7bb4c9", "#e0f3fa"],
  },
  emag2_residual: {
    label: "Regional residual",
    shortLabel: "Residual",
    key: "emag2_residual",
    unit: "nT",
    tone: "Comparison",
    description: "Residual magnetic field after subtracting the regional field from the corrected data.",
    palette: ["#3e1847", "#8b3e91", "#cf7ad7", "#f3def8"],
  },
  uncertainty: {
    label: "Uncertainty",
    shortLabel: "Uncertainty",
    key: "uncertainty",
    unit: "%",
    tone: "Confidence",
    description: "Estimated model uncertainty combining distance from data support and variance.",
    palette: ["#4f2c00", "#936100", "#d29a16", "#fbe7ab"],
  },
};

const VISUALISATION_TAB_LABELS = {
  Surface: "Contour map",
  Heatmap: "Contour map",
  Contour: "Contour map",
  "3D": "3D surface",
  Map: "Map overlay",
  "Line Profiles": "Line profiles",
};

function getTraverseFilterOptions(displayData) {
  return [
    {value: "all", label: "All traverses"},
    ...displayData.traverses.map((traverse) => ({value: traverse.label, label: traverse.label})),
  ];
}

function filterDisplayData(displayData) {
  const filterValue = appState.activeTraverseFilter || "all";
  if (filterValue === "all") return displayData;
  const traverses = displayData.traverses.filter((traverse) => traverse.label === filterValue);
  const keys = new Set(traverses.map((traverse) => traverse.key));
  return {
    measured: displayData.measured.filter((point) => keys.has(point.traverse_key)),
    predicted: displayData.predicted.filter((point) => keys.has(point.traverse_key)),
    traverses,
  };
}

async function ensurePlotly() {
  if (window.Plotly) {
    return window.Plotly;
  }
  if (!plotlyPromise) {
    plotlyPromise = loadScript("https://cdn.plot.ly/plotly-2.35.2.min.js").then(() => window.Plotly);
  }
  return plotlyPromise;
}

function getRoots() {
  return {
    screen: document.getElementById("screen-visualisation"),
    mapBox: document.querySelector("#screen-visualisation .mapbox"),
    headerActions: document.getElementById("visHeaderActions"),
    headerLayerBar: document.getElementById("visLayerBar"),
    statsTitle: document.getElementById("visStatsTitle"),
    statMeanLabel: document.getElementById("visStatMeanLabel"),
    statMeanValue: document.getElementById("visStatMeanValue"),
    statStdLabel: document.getElementById("visStatStdLabel"),
    statStdValue: document.getElementById("visStatStdValue"),
    statAnomalyLabel: document.getElementById("visStatAnomalyLabel"),
    statAnomalyValue: document.getElementById("visStatAnomalyValue"),
    statMinLabel: document.getElementById("visStatMinLabel"),
    statMinValue: document.getElementById("visStatMinValue"),
    statMaxLabel: document.getElementById("visStatMaxLabel"),
    statMaxValue: document.getElementById("visStatMaxValue"),
    scaleBar: document.getElementById("visScaleBar"),
    scaleMin: document.getElementById("visScaleMin"),
    scaleMid: document.getElementById("visScaleMid"),
    scaleMax: document.getElementById("visScaleMax"),
    layerToggles: document.getElementById("visLayerToggles"),
    interpretation: document.getElementById("visInterpretation"),
  };
}

function ensureHost() {
  let host = document.getElementById("visRenderHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "visRenderHost";
    host.style.width = "100%";
    host.style.height = "100%";
    const mapBox = getRoots().mapBox;
    mapBox.innerHTML = "";
    mapBox.appendChild(host);
  }
  return host;
}

function resetVisualisationHost() {
  const host = ensureHost();
  if (window.Plotly) {
    try {
      window.Plotly.purge(host);
    } catch (_error) {
      // Ignore cleanup errors and continue with a fresh host.
    }
  }
  host.innerHTML = "";
  return host;
}

function syncVisualisationTabs(mode) {
  const activeLabel = VISUALISATION_TAB_LABELS[mode] || VISUALISATION_TAB_LABELS.Surface;
  document.querySelectorAll("#screen-visualisation .vt").forEach((node) => {
    node.classList.toggle("on", node.textContent.trim() === activeLabel);
  });
}

function syncVisualisationMapControls(show) {
  const toolbar = document.getElementById("visMapToolbar");
  if (toolbar) {
    toolbar.style.display = show ? "flex" : "none";
  }
}

function matrixify(values) {
  if (!Array.isArray(values)) {
    return [];
  }
  if (!values.length) {
    return [];
  }
  return Array.isArray(values[0]) ? values : [values];
}

function flattenFinite(values) {
  return matrixify(values)
    .flat()
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value));
}

function axisFromGrid(grid, axis) {
  const matrix = matrixify(grid);
  if (!matrix.length) {
    return [];
  }
  if (axis === "x") {
    return (matrix[0] || []).map((value) => Number(value));
  }
  return matrix.map((row) => Number((row || [])[0]));
}

function buildPlotSurface(results, surfaceValues) {
  const z = matrixify(surfaceValues).map((row) => row.map((value) => Number(value)));
  let x = axisFromGrid(results.grid_x, "x");
  let y = axisFromGrid(results.grid_y, "y");

  if (!z.length || !z[0]?.length) {
    return {x: [], y: [], z: []};
  }
  if (!x.length) {
    x = Array.from({length: z[0].length}, (_, index) => index + 1);
  }
  if (!y.length) {
    y = Array.from({length: z.length}, (_, index) => index + 1);
  }
  if (z.length === 1) {
    const delta = Math.max(Math.abs((x[x.length - 1] || 1) - (x[0] || 0)) * 0.015, 0.0001);
    const y0 = Number.isFinite(y[0]) ? y[0] : 0;
    return {x, y: [y0 - delta, y0 + delta], z: [z[0], z[0]]};
  }
  if (z[0].length === 1) {
    const delta = Math.max(Math.abs((y[y.length - 1] || 1) - (y[0] || 0)) * 0.015, 0.0001);
    const x0 = Number.isFinite(x[0]) ? x[0] : 0;
    return {x: [x0 - delta, x0 + delta], y, z: z.map((row) => [row[0], row[0]])};
  }
  return {x, y, z};
}

function computeLayerStats(layer) {
  const values = flattenFinite(layer.surface);
  if (!values.length) {
    return {min: null, max: null, mean: null, std: null, anomalyCount: 0, pointCount: 0, range: null};
  }
  const mean = values.reduce((sum, value) => sum + value, 0) / values.length;
  const variance = values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length;
  const std = Math.sqrt(variance);
  const min = Math.min(...values);
  const max = Math.max(...values);
  return {
    min,
    max,
    mean,
    std,
    anomalyCount: values.filter((value) => value > mean + std).length,
    pointCount: values.length,
    range: max - min,
  };
}

function paletteToCss(palette) {
  return `linear-gradient(90deg, ${palette.join(",")})`;
}

function paletteToPlotly(palette) {
  if (!palette?.length) {
    return "Viridis";
  }
  return palette.map((color, index) => [index / Math.max(palette.length - 1, 1), color]);
}

function _showPalettePickerFor(layerId, currentPalette) {
  let picker = document.getElementById("_visPalPicker");
  if (!picker) {
    picker = document.createElement("div");
    picker.id = "_visPalPicker";
    picker.style.cssText = "position:fixed;z-index:9999;background:#fff;border:1px solid #d0d5d1;border-radius:10px;padding:14px 16px;box-shadow:0 4px 20px rgba(0,0,0,0.14);font-family:'Manrope',sans-serif;font-size:12px;min-width:190px";
    document.body.appendChild(picker);
    document.addEventListener("mousedown", (e) => {
      if (!picker.contains(e.target) && !e.target.closest("#visScaleBar")) picker.style.display = "none";
    }, true);
  }
  const cold = currentPalette[0] || "#1a2980";
  const hot = currentPalette[currentPalette.length - 1] || "#c0392b";
  picker.innerHTML = `
    <div style="font-weight:700;color:#071a0b;margin-bottom:10px;font-size:12px">Colour scale</div>
    <div style="display:flex;flex-direction:column;gap:9px">
      <label style="display:flex;align-items:center;justify-content:space-between;gap:10px">
        <span style="color:#5a8264">Cold (low)</span>
        <input type="color" value="${cold}" oninput="window._setVisLayerPalCold('${layerId}',this.value)" style="width:34px;height:26px;border:1px solid #d0d5d1;border-radius:5px;cursor:pointer;padding:2px">
      </label>
      <label style="display:flex;align-items:center;justify-content:space-between;gap:10px">
        <span style="color:#5a8264">Hot (high)</span>
        <input type="color" value="${hot}" oninput="window._setVisLayerPalHot('${layerId}',this.value)" style="width:34px;height:26px;border:1px solid #d0d5d1;border-radius:5px;cursor:pointer;padding:2px">
      </label>
      <div style="display:flex;gap:6px;margin-top:2px">
        <button onclick="window._resetVisLayerPal('${layerId}')" style="flex:1;padding:5px;border:1px solid #ccc;border-radius:6px;background:#f5f5f5;cursor:pointer;font-size:11px">Reset</button>
        <button onclick="document.getElementById('_visPalPicker').style.display='none'" style="flex:1;padding:5px;border:1px solid #ccc;border-radius:6px;background:#f5f5f5;cursor:pointer;font-size:11px">Close</button>
      </div>
    </div>
  `;
  const scaleBar = document.getElementById("visScaleBar");
  if (scaleBar) {
    const rect = scaleBar.getBoundingClientRect();
    const top = Math.min(rect.bottom + 6, window.innerHeight - 180);
    picker.style.left = `${Math.min(rect.left, window.innerWidth - 210)}px`;
    picker.style.top = `${top}px`;
  }
  picker.style.display = "block";
}

function renderStats(layer, stats) {
  const roots = getRoots();
  const pal = getLayerPalette(layer);
  if (roots.statsTitle) {
    roots.statsTitle.textContent = `${layer.shortLabel} statistics`;
  }
  if (roots.statMeanLabel) roots.statMeanLabel.textContent = `Mean ${layer.shortLabel}`;
  if (roots.statStdLabel) roots.statStdLabel.textContent = "Std dev";
  if (roots.statAnomalyLabel) roots.statAnomalyLabel.textContent = "High anomalies";
  if (roots.statMinLabel) roots.statMinLabel.textContent = `Min ${layer.unit}`;
  if (roots.statMaxLabel) roots.statMaxLabel.textContent = `Max ${layer.unit}`;
  if (roots.statMeanValue) roots.statMeanValue.textContent = formatNumber(stats.mean);
  if (roots.statStdValue) roots.statStdValue.textContent = formatNumber(stats.std);
  if (roots.statAnomalyValue) roots.statAnomalyValue.textContent = String(stats.anomalyCount || 0);
  if (roots.statMinValue) roots.statMinValue.textContent = formatNumber(stats.min);
  if (roots.statMaxValue) roots.statMaxValue.textContent = formatNumber(stats.max);
  if (roots.scaleBar) {
    roots.scaleBar.style.background = paletteToCss(pal);
    roots.scaleBar.style.cursor = "pointer";
    roots.scaleBar.title = "Click to customise colour scale";
    roots.scaleBar.setAttribute("data-layer-id", layer.id);
    roots.scaleBar.onclick = () => _showPalettePickerFor(layer.id, pal);
  }
  if (roots.scaleMin) roots.scaleMin.textContent = formatNumber(stats.min);
  if (roots.scaleMid) roots.scaleMid.textContent = formatNumber(stats.mean);
  if (roots.scaleMax) roots.scaleMax.textContent = formatNumber(stats.max);
}

function renderHeader(results, layer, stats) {
  const roots = getRoots();
  if (!roots.headerActions) return;
  const modelLabel = {
    kriging: "Kriging",
    hybrid: "Hybrid",
    machine_learning: "Machine learning",
    ml: "Machine learning",
    none: "No modelling",
  }[results?.model_used] || titleCase(results?.model_used || "");
  roots.headerActions.innerHTML = `
    <span class="badge bgr">${results?.points?.length || 0} measured points</span>
    ${(results?.predicted_points?.length || 0) ? `<span class="badge bb">${results.predicted_points.length} predicted</span>` : ""}
    <span class="badge bg">${layer.shortLabel}</span>
    ${modelLabel ? `<span class="badge" style="background:var(--amber-bg);color:var(--amber)">${modelLabel}</span>` : ""}
    ${stats.range != null ? `<span class="badge bgr">Range ${formatNumber(stats.range)} ${layer.unit}</span>` : ""}
    <button class="btn btn-sm btn-out" onclick="go(document.querySelector('[data-s=export]'))">Export →</button>
  `;
}

function renderLayerBar(layers, activeLayer) {
  const roots = getRoots();
  if (!roots.headerLayerBar) return;
  roots.headerLayerBar.innerHTML = `
    <span style="font-size:10px;font-weight:700;color:var(--text4);letter-spacing:1px">ACTIVE RESULTS</span>
    ${layers.map((layer) => `<span class="badge ${layer.id === activeLayer.id ? "bg" : "bgr"}">${layer.shortLabel}</span>`).join("")}
    <span style="font-size:10px;color:var(--text4);margin-left:auto">${activeLayer.tone}</span>
  `;
}

function buildAvailableLayers(results, task) {
  const config = task?.analysis_config || {};
  const selectedAddOns = new Set(config.add_ons || []);
  const selectedCorrections = new Set(config.corrections || []);
  const layers = [];

  const pushLayer = (id, enabled = true) => {
    const meta = LAYER_META[id];
    if (!meta || !enabled) return;
    const surface = results?.[meta.key];
    if (!Array.isArray(surface) || !matrixify(surface).length) return;
    layers.push({...meta, id, surface});
  };

  pushLayer("magnetic", true);
  pushLayer("filtered_surface", selectedCorrections.has("filtering"));
  pushLayer("rtp_surface", selectedAddOns.has("rtp"));
  pushLayer("analytic_signal", selectedAddOns.has("analytic_signal"));
  pushLayer("first_vertical_derivative", selectedAddOns.has("first_vertical_derivative"));
  pushLayer("horizontal_derivative", selectedAddOns.has("horizontal_derivative"));
  pushLayer("regional_field", selectedAddOns.has("emag2"));
  pushLayer("emag2_residual", selectedAddOns.has("emag2"));
  pushLayer("uncertainty", selectedAddOns.has("uncertainty"));
  return layers;
}

function getActiveLayer(layers) {
  const fallback = layers[0] || {...LAYER_META.magnetic, id: "magnetic", surface: []};
  const active = layers.find((layer) => layer.id === appState.activeResultLayer) || fallback;
  if (active.id !== appState.activeResultLayer) {
    setActiveResultLayer(active.id);
  }
  return active;
}

function buildSurfaceSampler(results, layer) {
  const z = matrixify(layer.surface);
  const gx = matrixify(results.grid_x);
  const gy = matrixify(results.grid_y);
  const nodes = [];
  for (let row = 0; row < z.length; row += 1) {
    for (let col = 0; col < (z[row] || []).length; col += 1) {
      const value = Number(z[row][col]);
      const lon = Number((gx[row] || [])[col]);
      const lat = Number((gy[row] || [])[col]);
      if (Number.isFinite(value) && Number.isFinite(lat) && Number.isFinite(lon)) {
        nodes.push({lat, lon, value});
      }
    }
  }
  return (latitude, longitude) => {
    if (!nodes.length) return null;
    let best = nodes[0];
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const node of nodes) {
      const distance = ((node.lat - latitude) ** 2) + ((node.lon - longitude) ** 2);
      if (distance < bestDistance) {
        bestDistance = distance;
        best = node;
      }
    }
    return best?.value ?? null;
  };
}

function deriveGrouping(points) {
  const coords = points.filter((point) => Number.isFinite(Number(point.latitude)) && Number.isFinite(Number(point.longitude)));
  if (!coords.length) {
    return {groupByLat: true, axisKey: "longitude", transverseKey: "latitude", step: 0.001};
  }
  const lats = coords.map((point) => Number(point.latitude));
  const lons = coords.map((point) => Number(point.longitude));
  const latRange = Math.max(...lats) - Math.min(...lats);
  const lonRange = Math.max(...lons) - Math.min(...lons);
  const groupByLat = latRange < lonRange;
  const stepBase = (groupByLat ? latRange : lonRange) / Math.max(Math.sqrt(coords.length / 5), 1);
  return {
    groupByLat,
    axisKey: groupByLat ? "longitude" : "latitude",
    transverseKey: groupByLat ? "latitude" : "longitude",
    step: Math.max(stepBase || 0, 0.0001),
  };
}

function buildDisplayDatasets(results, layer) {
  const measured = (results?.points || []).filter((point) => Number.isFinite(Number(point.latitude)) && Number.isFinite(Number(point.longitude)));
  const predicted = (results?.predicted_points || []).filter((point) => Number.isFinite(Number(point.latitude)) && Number.isFinite(Number(point.longitude)));
  const sampler = buildSurfaceSampler(results, layer);
  const grouping = deriveGrouping([...measured, ...predicted]);
  const all = [];

  const measuredDisplay = measured.map((point) => {
    const sampled = sampler(Number(point.latitude), Number(point.longitude));
    const directLayerValue = Number(point[layer.key]);
    const displayValue = layer.id === "magnetic" && Number.isFinite(Number(point.raw_magnetic ?? point.magnetic))
      ? Number(point.raw_magnetic ?? point.magnetic)
      : Number.isFinite(directLayerValue)
        ? directLayerValue
      : sampled;
    const item = {
      ...point,
      display_value: Number.isFinite(displayValue) ? displayValue : null,
      display_label: layer.shortLabel,
      display_unit: layer.unit,
      point_kind: point.is_base_station ? "Measured base station" : "Measured data",
      value_type: "measured",
    };
    all.push(item);
    return item;
  });

  const predictedDisplay = predicted.map((point) => {
    const directLayerValue = Number(point[layer.key]);
    const displayValue = layer.id === "magnetic" && Number.isFinite(Number(point.raw_magnetic ?? point.predicted_magnetic ?? point.magnetic))
      ? Number(point.raw_magnetic ?? point.predicted_magnetic ?? point.magnetic)
      : Number.isFinite(directLayerValue)
        ? directLayerValue
      : sampler(Number(point.latitude), Number(point.longitude));
    const item = {
      ...point,
      display_value: Number.isFinite(displayValue) ? displayValue : null,
      display_label: layer.shortLabel,
      display_unit: layer.unit,
      point_kind: "Predicted data",
      value_type: "predicted",
    };
    all.push(item);
    return item;
  });

  const traverseMap = new Map();
  all.forEach((point) => {
    const key = point.traverse_label
      ? `predicted-${point.traverse_label}`
      : point.line_id != null
      ? `line-${point.line_id}`
      : `group-${Math.round(Number(point[grouping.transverseKey]) / grouping.step)}`;
    if (!traverseMap.has(key)) traverseMap.set(key, []);
    traverseMap.get(key).push(point);
  });

  const orderedTraverses = [...traverseMap.entries()]
    .sort(([, a], [, b]) => Number(a[0]?.[grouping.transverseKey] || 0) - Number(b[0]?.[grouping.transverseKey] || 0))
    .map(([key, points], index) => {
      const sorted = [...points].sort((a, b) => Number(a[grouping.axisKey]) - Number(b[grouping.axisKey]));
      const origin = sorted[0]
        ? {lat: Number(sorted[0].latitude), lon: Number(sorted[0].longitude)}
        : {lat: 0, lon: 0};
      const traverseLabel = sorted.find((point) => point.traverse_label)?.traverse_label || `Traverse ${index + 1}`;
      sorted.forEach((point, stationIndex) => {
        point.station_number = stationIndex + 1;
        const dLat = (Number(point.latitude) - origin.lat) * 111320;
        const dLon = (Number(point.longitude) - origin.lon) * 111320 * Math.cos(origin.lat * Math.PI / 180);
        point.distance_along = Math.sqrt((dLat ** 2) + (dLon ** 2));
        point.traverse_label = traverseLabel;
        point.traverse_key = key;
      });
      return {
        key,
        label: traverseLabel,
        points: sorted,
      };
    });

  return {
    measured: measuredDisplay,
    predicted: predictedDisplay,
    traverses: orderedTraverses,
  };
}

function renderLayerControls(layers, activeLayer, mode) {
  const roots = getRoots();
  if (!roots.layerToggles) return;
  const fullDisplayData = buildDisplayDatasets(appState.taskResults || {}, activeLayer);
  const displayData = filterDisplayData(fullDisplayData);
  const traverseOptions = getTraverseFilterOptions(fullDisplayData);
  roots.layerToggles.innerHTML = `
    <div style="font-size:10px;font-weight:700;color:var(--text4);letter-spacing:0.8px;text-transform:uppercase;margin-bottom:10px">Selected processing outputs</div>
    <div style="display:flex;flex-direction:column;gap:6px">
      ${layers.map((layer) => {
        const active = layer.id === activeLayer.id;
        return `
          <button
            type="button"
            onclick="window.switchResultLayer('${layer.id}')"
            style="display:flex;align-items:flex-start;gap:10px;text-align:left;padding:9px 10px;border-radius:8px;border:1px solid ${active ? "var(--g300)" : "var(--border)"};background:${active ? "var(--g50)" : "var(--bg)"};cursor:pointer"
          >
            <span style="width:10px;height:10px;border-radius:50%;background:${layer.palette[1]};margin-top:4px;flex-shrink:0"></span>
            <span style="flex:1">
              <span style="display:block;font-size:12px;font-weight:${active ? "700" : "600"};color:${active ? "var(--g600)" : "var(--text)"}">${layer.label}</span>
              <span style="display:block;font-size:10px;color:var(--text3);margin-top:2px">${layer.description}</span>
            </span>
          </button>
        `;
      }).join("")}
    </div>
    <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">
      <div style="font-size:10px;font-weight:700;color:var(--text4);letter-spacing:0.8px;text-transform:uppercase;margin-bottom:8px">Traverse view</div>
      <select class="fsel" style="font-size:11px" onchange="window.setTraverseFilter(this.value)">
        ${traverseOptions.map((option) => `<option value="${option.value}"${option.value === (appState.activeTraverseFilter || "all") ? " selected" : ""}>${option.label}</option>`).join("")}
      </select>
      <div style="font-size:10px;color:var(--text3);margin-top:6px;line-height:1.6">Showing ${displayData.traverses.length} traverse${displayData.traverses.length === 1 ? "" : "s"} in the current view.</div>
    </div>
    ${mode === "Line Profiles" ? `
      <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">
        <label style="display:flex;align-items:center;justify-content:space-between;gap:10px">
          <span style="font-size:11px;color:var(--text2)">Horizontal axis max (m)</span>
          <input id="visXAxisMax" type="number" min="0" step="1" value="${Number.isFinite(Number(appState.visXAxisMax)) ? Number(appState.visXAxisMax) : ""}" placeholder="auto" style="width:92px">
        </label>
        <label style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:8px">
          <span style="font-size:11px;color:var(--text2)">Vertical axis min</span>
          <input id="visYAxisMin" type="number" step="0.01" value="${Number.isFinite(Number(appState.visYAxisMin)) ? Number(appState.visYAxisMin) : ""}" placeholder="auto" style="width:92px">
        </label>
        <label style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-top:8px">
          <span style="font-size:11px;color:var(--text2)">Vertical axis max</span>
          <input id="visYAxisMax" type="number" step="0.01" value="${Number.isFinite(Number(appState.visYAxisMax)) ? Number(appState.visYAxisMax) : ""}" placeholder="auto" style="width:92px">
        </label>
        <div style="display:flex;gap:8px;margin-top:10px">
          <button type="button" class="btn btn-white btn-sm" onclick="window.applyProfileAxes()">Apply axes</button>
          <button type="button" class="btn btn-white btn-sm" onclick="window.resetProfileAxes()">Auto</button>
        </div>
      </div>
      <div style="margin-top:14px;padding-top:12px;border-top:1px solid var(--border)">
        <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer">
          <input type="checkbox" ${appState.stackProfiles ? "checked" : ""} onchange="window.toggleProfileStacking(this.checked)" style="width:14px;height:14px;accent-color:var(--g500);margin-top:2px">
          <span>
            <span style="display:block;font-size:12px;font-weight:700;color:var(--text)">Stack profiles</span>
            <span style="display:block;font-size:10px;color:var(--text3);margin-top:2px">Offset each traverse vertically for easier comparison. Hover shows station number only when stacking is on.</span>
          </span>
        </label>
      </div>
    ` : ""}
  `;
}

async function renderBaseStationDrift(host, baseStations) {
  if (!host) return;
  const series = (baseStations || [])
    .filter((point) => Number.isFinite(Number(point.time_s)) && Number.isFinite(Number(point.magnetic ?? point.display_value)))
    .sort((a, b) => Number(a.time_s) - Number(b.time_s));
  if (!series.length) {
    host.innerHTML = "";
    return;
  }
  const Plotly = await ensurePlotly();
  host.innerHTML = "";
  await Plotly.newPlot(host, [{
    x: series.map((point) => Number(point.time_s) / 3600),
    y: series.map((point) => Number(point.magnetic ?? point.display_value)),
    type: "scatter",
    mode: "lines+markers",
    line: {color: appState.mapColors.baseStation, width: 2},
    marker: {color: appState.mapColors.baseStation, size: 6},
    hovertemplate: "Time %{x:.2f} h<br>Base %{y:.2f} nT<extra></extra>",
  }], {
    margin: {t: 8, r: 8, b: 34, l: 42},
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: {color: getPlotTheme().text, size: 10},
    xaxis: {title: "Time (hours)", gridcolor: getPlotTheme().grid},
    yaxis: {title: "Base station (nT)", gridcolor: getPlotTheme().grid},
    showlegend: false,
  }, {displayModeBar: false, responsive: true});
}

function renderInterpretation(layer, stats, displayData) {
  const roots = getRoots();
  if (!roots.interpretation) return;

  // Ensure persistent sub-containers exist. Only the layer/base cards are replaced on each call.
  let layerCard = document.getElementById("visLayerCard");
  let baseCard = document.getElementById("visBaseCard");
  if (!layerCard) {
    layerCard = document.createElement("div");
    layerCard.id = "visLayerCard";
    roots.interpretation.appendChild(layerCard);
  }
  if (!baseCard) {
    baseCard = document.createElement("div");
    baseCard.id = "visBaseCard";
    baseCard.style.marginTop = "10px";
    roots.interpretation.appendChild(baseCard);
  }

  layerCard.innerHTML = `
    <div style="font-size:10px;font-weight:700;color:var(--text3);letter-spacing:0.6px;text-transform:uppercase;margin-bottom:8px">Current layer</div>
    <div class="card card-sm" style="padding:12px">
      <div style="font-size:12px;font-weight:700;color:var(--text);margin-bottom:6px">${layer.label}</div>
      <div style="font-size:11px;color:var(--text2);line-height:1.75;margin-bottom:10px">${layer.description}</div>
      <div style="font-size:11px;color:var(--text3);line-height:1.8">
        <div style="display:flex;justify-content:space-between"><span>Measured points</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700">${displayData.measured.length}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Predicted points</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700">${displayData.predicted.length}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Traverses</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700">${displayData.traverses.length}</span></div>
        <div style="display:flex;justify-content:space-between"><span>Range</span><span style="font-family:'JetBrains Mono',monospace;font-weight:700">${formatNumber(stats.range)} ${layer.unit}</span></div>
      </div>
    </div>
  `;
  const baseStations = displayData.measured.filter((point) => point.is_base_station);
  if (baseStations.length) {
    baseCard.innerHTML = `
      <div style="font-size:10px;font-weight:700;color:var(--text3);letter-spacing:0.6px;text-transform:uppercase;margin-bottom:8px">Base-station drift</div>
      <div class="card card-sm" style="padding:12px">
        <div style="font-size:11px;color:var(--text2);line-height:1.7;margin-bottom:10px">${baseStations.length} detected base-station revisit${baseStations.length === 1 ? "" : "s"} are shown here so drift through time can be checked against the diurnal correction.</div>
        <div id="visBaseDriftChart" style="height:180px"></div>
      </div>
    `;
    renderBaseStationDrift(document.getElementById("visBaseDriftChart"), baseStations);
  } else {
    baseCard.innerHTML = "";
  }
}

async function renderLineProfiles(results, layer, stats) {
  const Plotly = await ensurePlotly();
  const host = resetVisualisationHost();
  const displayData = filterDisplayData(buildDisplayDatasets(results, layer));
  const traverses = displayData.traverses.filter((traverse) => traverse.points.some((point) => Number.isFinite(point.display_value)));

  if (!traverses.length) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">No profile points are available for ${layer.label.toLowerCase()}.</div>`;
    return displayData;
  }

  const offsetStep = appState.stackProfiles
    ? Math.max((stats.range || 0) * 0.25, stats.std || 0, 1)
    : 0;
  const traces = [];
  traverses.slice(0, 24).forEach((traverse, index) => {
    const measured = traverse.points.filter((point) => point.value_type === "measured" && Number.isFinite(point.display_value));
    const predicted = traverse.points.filter((point) => point.value_type === "predicted" && Number.isFinite(point.display_value));
    const offset = appState.stackProfiles ? index * offsetStep : 0;

    const makeCustom = (points) => points.map((point) => [point.station_number, point.display_value, point.value_type]);
    const hoverTemplate = appState.stackProfiles
      ? "Station #%{customdata[0]}<extra>%{fullData.name}</extra>"
      : `Station #%{customdata[0]}<br>${layer.shortLabel}: %{customdata[1]:.2f} ${layer.unit}<extra>%{fullData.name}</extra>`;

    if (measured.length) {
      traces.push({
        x: measured.map((point) => point.distance_along),
        y: measured.map((point) => Number(point.display_value) + offset),
        customdata: makeCustom(measured),
        type: "scatter",
        mode: "lines+markers",
        name: `${traverse.label} - measured`,
        line: {color: appState.mapColors.survey, width: 1.8},
        marker: {color: appState.mapColors.survey, size: 6},
        hovertemplate: hoverTemplate,
        legendgroup: traverse.key,
      });
    }
    if (predicted.length) {
      traces.push({
        x: predicted.map((point) => point.distance_along),
        y: predicted.map((point) => Number(point.display_value) + offset),
        customdata: makeCustom(predicted),
        type: "scatter",
        mode: "markers",
        name: `${traverse.label} - predicted`,
        marker: {
          color: appState.mapColors.predicted,
          size: 7,
          symbol: "circle-open",
          line: {color: appState.mapColors.predicted, width: 1.8},
        },
        hovertemplate: hoverTemplate,
        legendgroup: traverse.key,
      });
    }
  });

  const plotTheme = getPlotTheme();
  const xMax = Number(appState.visXAxisMax);
  const yMin = Number(appState.visYAxisMin);
  const yMax = Number(appState.visYAxisMax);
  await Plotly.newPlot(host, traces, {
    margin: {t: 20, r: 12, b: 48, l: 56},
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: {color: plotTheme.text, size: 11},
    xaxis: {
      title: "Distance along traverse (m)",
      gridcolor: plotTheme.grid,
      range: Number.isFinite(xMax) && xMax > 0 ? [0, xMax] : undefined,
    },
    yaxis: {
      title: appState.stackProfiles ? `${layer.shortLabel} (${layer.unit}) - stacked` : `${layer.shortLabel} (${layer.unit})`,
      gridcolor: plotTheme.grid,
      range: Number.isFinite(yMin) && Number.isFinite(yMax) && yMax > yMin ? [yMin, yMax] : undefined,
    },
    showlegend: true,
    legend: {font: {size: 9}},
    hovermode: "closest",
  }, {displayModeBar: false, responsive: true});

  return displayData;
}

async function renderPlot(mode, results, layer) {
  const Plotly = await ensurePlotly();
  const host = resetVisualisationHost();
  const plotSurface = buildPlotSurface(results, layer.surface);
  if (!plotSurface.z.length) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">No grid data is available for ${layer.label.toLowerCase()}.</div>`;
    return;
  }

  const commonLayout = {
    margin: {t: 20, r: 12, b: 42, l: 48},
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: {color: getPlotTheme().text},
  };
  const colorscale = paletteToPlotly(getLayerPalette(layer));

  if (mode === "Surface" || mode === "Heatmap") {
    await Plotly.newPlot(host, [{
      x: plotSurface.x,
      y: plotSurface.y,
      z: plotSurface.z,
      type: "heatmap",
      colorscale,
      colorbar: {title: layer.unit},
    }, {
      x: plotSurface.x,
      y: plotSurface.y,
      z: plotSurface.z,
      type: "contour",
      colorscale,
      contours: {coloring: "none", showlabels: false},
      line: {width: 1, color: getPlotTheme().contourLine},
      showscale: false,
      hoverinfo: "skip",
    }], {...commonLayout, xaxis: {title: "Longitude"}, yaxis: {title: "Latitude"}}, {displayModeBar: false, responsive: true});
    return;
  }
  if (mode === "Contour") {
    await Plotly.newPlot(host, [{
      x: plotSurface.x,
      y: plotSurface.y,
      z: plotSurface.z,
      type: "contour",
      colorscale,
      contours: {showlabels: true},
      colorbar: {title: layer.unit},
    }], {...commonLayout, xaxis: {title: "Longitude"}, yaxis: {title: "Latitude"}}, {displayModeBar: false, responsive: true});
    return;
  }
  await Plotly.newPlot(host, [{
    x: plotSurface.x,
    y: plotSurface.y,
    z: plotSurface.z,
    type: "surface",
    colorscale,
  }], {...commonLayout, scene: {xaxis: {title: "Longitude"}, yaxis: {title: "Latitude"}, zaxis: {title: layer.unit}}}, {displayModeBar: false, responsive: true});
}

async function renderMapOverlay(results, layer) {
  const host = resetVisualisationHost();
  syncVisualisationMapControls(true);
  const displayData = filterDisplayData(buildDisplayDatasets(results, layer));
  const measured = displayData.measured.map((point) => ({
    ...point,
    hide_value: false,
  }));
  const predicted = displayData.predicted.map((point) => ({
    ...point,
    hide_value: false,
  }));
  if (!measured.length && !predicted.length) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">No map points are available for ${layer.label.toLowerCase()}.</div>`;
    return displayData;
  }
  await renderStationMap(host, measured, {
    weighted: true,
    predictedPoints: predicted,
    mapTypeSelectId: "visMapTypeSelect",
    surveyColor: appState.mapColors.survey,
    predictedColor: appState.mapColors.predicted,
  });
  return displayData;
}

export async function loadVisualisation() {
  const host = ensureHost();
  syncVisualisationMapControls(false);
  if (!appState.project || !appState.task) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">Create and run a task to see visualisations here.</div>`;
    return;
  }

  const task = await fetchTask(appState.project.id, appState.task.id);
  setTask(task);
  renderWorkflowProgress();

  if (!task.results?.artifacts?.length) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">Processing results are not available yet — run the task to generate them.</div>`;
    return;
  }

  let results = appState.taskResults;
  try {
    if (!results) {
      results = await fetchTaskResults(appState.project.id, appState.task.id);
      setTaskResults(results);
    }
  } catch {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">Could not load results. Please try again.</div>`;
    return;
  }

  const layers = buildAvailableLayers(results, task);
  const activeLayer = getActiveLayer(layers);
  const stats = computeLayerStats(activeLayer);
  const mode = appState.activeVisualisation || "Contour";

  // Detect single-traverse to show a hint (never force-redirect — let user choose their tab)
  const _lineIds = new Set((results?.points || []).map((p) => (p.line_id != null ? String(p.line_id) : null)).filter(Boolean));
  const _isSingleTraverse = _lineIds.size <= 1 && (results?.points || []).length > 0;

  syncVisualisationTabs(mode);

  renderStats(activeLayer, stats);
  renderHeader(results, activeLayer, stats);
  renderLayerBar(layers, activeLayer);
  renderLayerControls(layers, activeLayer, mode);

  // Single-traverse hint banner
  const _mapBox = getRoots().mapBox;
  const _existingHint = document.getElementById("_visSingleTraverseHint");
  if (_existingHint) _existingHint.remove();
  if (_isSingleTraverse && (mode === "Surface" || mode === "Heatmap" || mode === "Contour" || mode === "3D")) {
    const _hint = document.createElement("div");
    _hint.id = "_visSingleTraverseHint";
    _hint.style.cssText = `position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:200;background:${themeValue("--amber-bg", "rgba(255,247,230,0.97)")};border:1px solid ${themeValue("--amber", "#e9c46a")};border-radius:8px;padding:7px 14px;font-family:'Manrope',sans-serif;font-size:11px;color:${themeValue("--amber", "#7a5a00")};display:flex;align-items:center;gap:10px;pointer-events:auto;white-space:nowrap`;
    _hint.innerHTML = `<span>Single traverse detected - <button onclick="window.drawVis('Line Profiles')" style="background:none;border:none;color:${themeValue("--g500", "#1a7f4b")};font-weight:700;cursor:pointer;font-size:11px;padding:0;font-family:inherit">Switch to Line Profiles</button> for best view</span><button onclick="this.parentElement.remove()" style="background:none;border:none;cursor:pointer;color:${themeValue("--amber", "#7a5a00")};font-size:13px;line-height:1;padding:0 2px">×</button>`;
    if (_mapBox) { _mapBox.style.position = "relative"; _mapBox.appendChild(_hint); }
  }

  let displayData = {measured: [], predicted: [], traverses: []};
  if (mode === "Map") {
    displayData = await renderMapOverlay(results, activeLayer);
  } else if (mode === "Line Profiles") {
    syncVisualisationMapControls(false);
    displayData = await renderLineProfiles(results, activeLayer, stats);
  } else {
    syncVisualisationMapControls(false);
    await renderPlot(mode, results, activeLayer);
    displayData = filterDisplayData(buildDisplayDatasets(results, activeLayer));
  }
  renderInterpretation(activeLayer, stats, displayData);
  if (_visChat?.refresh) {
    _visChat.refresh();
  }
}

export function initVisualisation() {
  // Initialise the vis AI chat once. visAIBody is created lazily by renderInterpretation
  // so we defer wiring until the DOM is ready.
  const _wireVisChat = () => {
    const inputEl = document.getElementById("visAIInput");
    const sendEl = document.getElementById("visAISend");
    const bodyEl = document.getElementById("visAIBody");
    if (inputEl && sendEl && bodyEl && !_visChat) {
      _visChat = initAIChat(bodyEl, inputEl, sendEl, {location: "visualisation"});
    }
  };
  // Wire immediately if DOM is ready, otherwise retry after first render
  _wireVisChat();
  const _origObserver = new MutationObserver(() => {
    if (!_visChat) _wireVisChat();
    if (_visChat) _origObserver.disconnect();
  });
  const interpEl = document.getElementById("visInterpretation");
  if (interpEl) _origObserver.observe(interpEl, {childList: true});

  window._setVisLayerPalCold = (layerId, color) => {
    const cur = _customPalettes[layerId] || [];
    const hot = cur[cur.length - 1] || (LAYER_META[layerId]?.palette || ["#c0392b"]).at(-1);
    _customPalettes[layerId] = [color, hot];
    loadVisualisation();
  };
  window._setVisLayerPalHot = (layerId, color) => {
    const cur = _customPalettes[layerId] || [];
    const cold = cur[0] || (LAYER_META[layerId]?.palette || ["#1a2980"])[0];
    _customPalettes[layerId] = [cold, color];
    loadVisualisation();
  };
  window._resetVisLayerPal = (layerId) => {
    delete _customPalettes[layerId];
    const picker = document.getElementById("_visPalPicker");
    if (picker) picker.style.display = "none";
    loadVisualisation();
  };
  window.pickVis = async (element, mode) => {
    const resolvedMode = mode === "3D surface" ? "3D" : mode === "Contour map" ? "Contour" : mode;
    document.querySelectorAll("#screen-visualisation .vt").forEach((node) => node.classList.remove("on"));
    element?.classList.add("on");
    setActiveVisualisation(resolvedMode);
    await loadVisualisation();
  };
  window.drawVis = async (mode) => {
    const resolvedMode = mode === "3D surface" ? "3D" : mode === "Contour map" ? "Contour" : mode;
    setActiveVisualisation(resolvedMode);
    syncVisualisationTabs(resolvedMode);
    await loadVisualisation();
  };
  window.switchResultLayer = async (layerId) => {
    setActiveResultLayer(layerId);
    await loadVisualisation();
  };
  window.toggleProfileStacking = async (value) => {
    setStackProfiles(value);
    await loadVisualisation();
  };
  window.applyProfileAxes = async () => {
    appState.visXAxisMax = document.getElementById("visXAxisMax")?.value || "";
    appState.visYAxisMin = document.getElementById("visYAxisMin")?.value || "";
    appState.visYAxisMax = document.getElementById("visYAxisMax")?.value || "";
    await loadVisualisation();
  };
  window.resetProfileAxes = async () => {
    appState.visXAxisMax = "";
    appState.visYAxisMin = "";
    appState.visYAxisMax = "";
    await loadVisualisation();
  };
  window.setTraverseFilter = async (value) => {
    setActiveTraverseFilter(value);
    await loadVisualisation();
  };
}
