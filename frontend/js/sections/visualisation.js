import {fetchTask, fetchTaskResults} from "../api.js";
import {renderWorkflowProgress} from "./progress.js";
import {appState, setActiveVisualisation, setTask} from "../state.js";
import {formatNumber} from "../shared/format.js";
import {loadScript} from "../shared/loaders.js";
import {renderStationMap} from "./maps.js";

let plotlyPromise = null;

async function ensurePlotly() {
  if (window.Plotly) {
    return window.Plotly;
  }
  if (!plotlyPromise) {
    plotlyPromise = loadScript("https://cdn.plot.ly/plotly-2.35.2.min.js").then(() => window.Plotly);
  }
  return plotlyPromise;
}

function getResults() {
  return appState.task?.results?.data || null;
}

function getRoots() {
  const screen = document.getElementById("screen-visualisation");
  return {
    screen,
    mapBox: screen.querySelector(".mapbox"),
    layerBar: screen.querySelector("div[style*='margin-top:9px']"),
    statsRows: screen.querySelectorAll("div[style*='padding:13px 15px'] .srow .sv"),
    scaleLabels: screen.querySelectorAll("div[style*='font-family:\\'JetBrains Mono\\''] span"),
    headerBadgeWrap: screen.querySelector("div[style*='margin-left:auto']"),
  };
}

function ensureHost() {
  let host = document.getElementById("visRenderHost");
  if (!host) {
    host = document.createElement("div");
    host.id = "visRenderHost";
    host.style.width = "100%";
    host.style.height = "100%";
    getRoots().mapBox.innerHTML = "";
    getRoots().mapBox.appendChild(host);
  }
  return host;
}

function renderStats(results) {
  const stats = results?.stats || {};
  const roots = getRoots();
  const rows = [
    formatNumber(stats.mean),
    formatNumber(stats.std),
    String(stats.anomaly_count || 0),
    formatNumber(stats.min),
    formatNumber(stats.max),
  ];
  roots.statsRows.forEach((node, index) => {
    if (rows[index] !== undefined) {
      node.textContent = rows[index];
    }
  });
  if (roots.scaleLabels[0]) {
    roots.scaleLabels[0].textContent = formatNumber(stats.min);
  }
  if (roots.scaleLabels[1]) {
    roots.scaleLabels[1].textContent = formatNumber(stats.mean);
  }
  if (roots.scaleLabels[2]) {
    roots.scaleLabels[2].textContent = formatNumber(stats.max);
  }
}

const ADD_ON_LABELS = {rtp: "RTP", analytic_signal: "Analytic signal", emag2: "EMAG2", uncertainty: "Uncertainty"};
const MODEL_DISPLAY = {kriging: "Kriging", ml: "Machine learning", hybrid: "Hybrid"};

function renderLayerBar(results) {
  const task = appState.task || {};
  const layers = [
    "<span style=\"font-size:10px;font-weight:700;color:var(--text4);letter-spacing:1px\">LAYERS</span>",
    "<span class=\"badge bg\">TMF grid</span>",
  ];
  (task.analysis_config?.add_ons || []).forEach((addOn) => {
    const label = ADD_ON_LABELS[addOn] || addOn;
    layers.push(`<span class="badge ba">${label}</span>`);
  });
  const modelLabel = MODEL_DISPLAY[results?.model_used] || results?.model_used || "";
  if (modelLabel) {
    layers.push(`<span style="font-size:10px;color:var(--text4);margin-left:auto">${modelLabel}</span>`);
  }
  getRoots().layerBar?.innerHTML && (getRoots().layerBar.innerHTML = layers.join(""));
}

function renderHeader(results) {
  const modelLabel = MODEL_DISPLAY[results?.model_used] || results?.model_used || "";
  const wrap = getRoots().headerBadgeWrap;
  if (!wrap) return;
  wrap.innerHTML = `
    <span class="badge bgr">${results.stats?.point_count || 0} points</span>
    ${modelLabel ? `<span class="badge" style="background:var(--amber-bg);color:var(--amber)">${modelLabel}</span>` : ""}
    <button class="btn btn-sm btn-out" onclick="go(document.querySelector('[data-s=export]'))">Export ↗</button>
  `;
}

function renderLayerToggles(results) {
  const container = document.getElementById("visLayerToggles");
  if (!container) return;
  const mode = appState.activeVisualisation || "Map";
  const hasPoints = (results?.points?.length || 0) > 0;
  const hasSurface = hasSurfaceGrid(results);
  const layers = [
    {id: "Map", label: "Map overlay", desc: "Survey stations on interactive map", available: hasPoints},
    {id: "Line Profiles", label: "Line profiles", desc: "Distance vs magnetic field", available: hasPoints},
    {id: "Heatmap", label: "Heatmap", desc: "Interpolated 2D colour map", available: hasSurface},
    {id: "Contour", label: "Contour", desc: "Magnetic field contour lines", available: hasSurface},
    {id: "Surface", label: "3D surface", desc: "Interactive 3D terrain model", available: hasSurface},
  ].filter((l) => l.available);
  if (!layers.length) {
    container.innerHTML = `<div style="font-size:11px;color:var(--text3);padding:4px 0">No layers available.</div>`;
    return;
  }
  container.innerHTML = layers.map((layer) => {
    const isActive = mode === layer.id;
    return `
      <div onclick="window.switchVisLayer('${layer.id}')" style="display:flex;align-items:flex-start;gap:9px;padding:8px 10px;border-radius:6px;cursor:pointer;margin-bottom:3px;background:${isActive ? "var(--g50)" : "transparent"};border:1px solid ${isActive ? "var(--g200)" : "transparent"};transition:background 0.1s">
        <div style="width:8px;height:8px;border-radius:50%;background:${isActive ? "var(--g500)" : "var(--g300)"};flex-shrink:0;margin-top:4px"></div>
        <div>
          <div style="font-size:12px;font-weight:${isActive ? "700" : "600"};color:${isActive ? "var(--g600)" : "var(--text2)"}">${layer.label}</div>
          <div style="font-size:10px;color:var(--text3);margin-top:1px">${layer.desc}</div>
        </div>
      </div>
    `;
  }).join("");
  const interp = document.getElementById("visInterpretation");
  if (interp && results?.stats) {
    const s = results.stats;
    const range = Number.isFinite(s.max) && Number.isFinite(s.min) ? s.max - s.min : null;
    interp.innerHTML = `
      <div style="font-size:10px;font-weight:700;color:var(--text3);letter-spacing:0.5px;text-transform:uppercase;margin-bottom:8px">Summary</div>
      <div style="font-size:11px;color:var(--text2);line-height:1.8">
        <div style="display:flex;justify-content:space-between;margin-bottom:2px"><span style="color:var(--text3)">Points</span><span style="font-weight:600;font-family:'JetBrains Mono',monospace">${s.point_count || 0}</span></div>
        ${range !== null ? `<div style="display:flex;justify-content:space-between;margin-bottom:2px"><span style="color:var(--text3)">Field range</span><span style="font-weight:600;font-family:'JetBrains Mono',monospace">${formatNumber(range)} nT</span></div>` : ""}
        ${s.anomaly_count ? `<div style="display:flex;justify-content:space-between"><span style="color:var(--text3)">Anomalies</span><span style="font-weight:600;font-family:'JetBrains Mono',monospace">${s.anomaly_count}</span></div>` : ""}
      </div>
    `;
  }
}

async function renderLineProfiles(results) {
  const Plotly = await ensurePlotly();
  const host = ensureHost();
  const points = results.points || [];
  if (!points.length) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">No point data available for line profiles.</div>`;
    return;
  }
  // Group points into traverses by rounding the perpendicular coordinate
  const lats = points.map((p) => Number(p.latitude));
  const lons = points.map((p) => Number(p.longitude));
  const latRange = Math.max(...lats) - Math.min(...lats);
  const lonRange = Math.max(...lons) - Math.min(...lons);
  const groupByLat = latRange < lonRange; // E-W survey: group by lat, vary along lon
  const step = (groupByLat ? latRange : lonRange) / Math.max(Math.sqrt(points.length / 5), 1);
  const groups = new Map();
  points.forEach((p) => {
    const key = Math.round((groupByLat ? Number(p.latitude) : Number(p.longitude)) / (step || 0.001)) * (step || 0.001);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  });
  const traces = [];
  [...groups.entries()].sort(([a], [b]) => a - b).slice(0, 20).forEach(([key, pts]) => {
    const sorted = pts.sort((a, b) => (groupByLat ? Number(a.longitude) - Number(b.longitude) : Number(a.latitude) - Number(b.latitude)));
    const origin = {lat: Number(sorted[0].latitude), lon: Number(sorted[0].longitude)};
    const distances = sorted.map((p) => {
      const dlat = (Number(p.latitude) - origin.lat) * 111320;
      const dlon = (Number(p.longitude) - origin.lon) * 111320 * Math.cos(origin.lat * Math.PI / 180);
      return Math.sqrt(dlat * dlat + dlon * dlon);
    });
    traces.push({
      x: distances,
      y: sorted.map((p) => Number(p.magnetic || 0)),
      type: "scatter",
      mode: "lines",
      name: `Line ${(groupByLat ? key.toFixed(4) + "°N" : key.toFixed(4) + "°E")}`,
      line: {width: 1.5},
    });
  });
  const commonLayout = {
    margin: {t: 20, r: 12, b: 48, l: 56},
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: {color: "#5f6d64", size: 11},
    xaxis: {title: "Distance along traverse (m)", gridcolor: "rgba(0,0,0,0.06)"},
    yaxis: {title: "Magnetic field (nT)", gridcolor: "rgba(0,0,0,0.06)"},
    showlegend: traces.length <= 8,
    legend: {font: {size: 9}},
  };
  await Plotly.newPlot(host, traces, commonLayout, {displayModeBar: false, responsive: true});
}

function hasSurfaceGrid(results) {
  if (!results?.surface || !results?.grid_x || !results?.grid_y) return false;
  if (!Array.isArray(results.surface) || !Array.isArray(results.grid_y)) return false;
  return results.surface.length > 1 && results.grid_y.length > 1;
}

async function renderPlot(mode, results) {
  const Plotly = await ensurePlotly();
  const host = ensureHost();
  if (!hasSurfaceGrid(results)) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">Surface grid is not available for this task. Try Line profiles or Map overlay.</div>`;
    return;
  }
  const commonLayout = {
    margin: {t: 20, r: 12, b: 42, l: 48},
    paper_bgcolor: "transparent",
    plot_bgcolor: "transparent",
    font: {color: "#5f6d64"},
  };
  if (mode === "Heatmap") {
    await Plotly.newPlot(host, [{
      x: results.grid_x[0],
      y: results.grid_y.map((row) => row[0]),
      z: results.surface,
      type: "heatmap",
      colorscale: "Viridis",
      colorbar: {title: "nT"},
    }], {...commonLayout, xaxis: {title: "Longitude"}, yaxis: {title: "Latitude"}}, {displayModeBar: false, responsive: true});
    return;
  }
  if (mode === "Contour") {
    await Plotly.newPlot(host, [{
      x: results.grid_x[0],
      y: results.grid_y.map((row) => row[0]),
      z: results.surface,
      type: "contour",
      colorscale: "Viridis",
      contours: {showlabels: true},
      colorbar: {title: "nT"},
    }], {...commonLayout, xaxis: {title: "Longitude"}, yaxis: {title: "Latitude"}}, {displayModeBar: false, responsive: true});
    return;
  }
  await Plotly.newPlot(host, [{
    x: results.grid_x[0],
    y: results.grid_y.map((row) => row[0]),
    z: results.surface,
    type: "surface",
    colorscale: "Viridis",
  }], {...commonLayout, scene: {xaxis: {title: "Longitude"}, yaxis: {title: "Latitude"}, zaxis: {title: "nT"}}}, {displayModeBar: false, responsive: true});
}

async function renderMapOverlay(results) {
  const host = ensureHost();
  if (!results?.points?.length) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">No point data available for map overlay.</div>`;
    return;
  }
  await renderStationMap(host, results.points, {
    weighted: true,
    predictedPoints: results.predicted_points || [],
  });
}

function isSurface1D(results) {
  const s = results?.surface;
  // Surface is 1-D when it has only 1 row (sparse along-line output)
  return Array.isArray(s) && s.length <= 1;
}

export async function loadVisualisation() {
  const host = ensureHost();
  if (!appState.project || !appState.task) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">Create and run a task to see visualisations here.</div>`;
    return;
  }
  const task = await fetchTask(appState.project.id, appState.task.id);
  setTask(task);
  renderWorkflowProgress();

  // Lightweight Firestore data tells us if processing ran; full results come from GCS
  if (!task.results?.artifacts?.length) {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">Processing results are not available yet — run the task to generate them.</div>`;
    return;
  }

  let results;
  try {
    results = await fetchTaskResults(appState.project.id, appState.task.id);
  } catch {
    host.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text3);font-size:13px">Could not load results. Please try again.</div>`;
    return;
  }
  // For single-traverse (1-row) surfaces, Line Profiles is the meaningful view
  let mode = appState.activeVisualisation;
  if (isSurface1D(results) && mode !== "Map" && mode !== "Line Profiles") {
    mode = "Line Profiles";
    setActiveVisualisation(mode);
    document.querySelectorAll("#screen-visualisation .vt").forEach((n) => n.classList.remove("on"));
    document.querySelector("#screen-visualisation .vt[onclick*='Line Profiles']")?.classList.add("on");
  }
  try { renderStats(results); } catch (e) { console.warn("renderStats:", e); }
  try { renderLayerBar(results); } catch (e) { console.warn("renderLayerBar:", e); }
  try { renderHeader(results); } catch (e) { console.warn("renderHeader:", e); }
  try { renderLayerToggles(results); } catch (e) { console.warn("renderLayerToggles:", e); }
  if (mode === "Map") {
    await renderMapOverlay(results);
  } else if (mode === "Line Profiles") {
    await renderLineProfiles(results);
  } else {
    await renderPlot(mode, results);
  }
}

export function initVisualisation() {
  window.pickVis = async (element, mode) => {
    document.querySelectorAll("#screen-visualisation .vt").forEach((node) => node.classList.remove("on"));
    element?.classList.add("on");
    setActiveVisualisation(mode);
    await loadVisualisation();
  };
  window.drawVis = async (mode) => {
    setActiveVisualisation(mode);
    await loadVisualisation();
  };
  window.switchVisLayer = async (layerId) => {
    setActiveVisualisation(layerId);
    // Sync the .vt tab buttons if they exist
    document.querySelectorAll("#screen-visualisation .vt").forEach((n) => n.classList.remove("on"));
    document.querySelectorAll("#screen-visualisation .vt").forEach((n) => {
      if (n.getAttribute("onclick")?.includes(`'${layerId}'`) || n.getAttribute("onclick")?.includes(`"${layerId}"`)) {
        n.classList.add("on");
      }
    });
    await loadVisualisation();
  };
}
