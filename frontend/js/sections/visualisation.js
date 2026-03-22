import {askAurora, fetchTask} from "../api.js";
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
    auroraBody: screen.querySelector(".a-body"),
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
    String(Math.max(0, Math.round((stats.anomaly_count || 0) / 3))),
    String(Math.max(0, Math.round((stats.anomaly_count || 0) / 6))),
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

function renderLayerBar(results) {
  const task = appState.task || {};
  const layers = [
    "<span style=\"font-size:10px;font-weight:700;color:var(--text4);letter-spacing:1px\">LAYERS</span>",
    "<span class=\"badge bg\">TMF grid</span>",
  ];
  (task.analysis_config?.add_ons || []).forEach((addOn) => {
    layers.push(`<span class="badge ba">${addOn}</span>`);
  });
  if (task.basemap_file) {
    layers.push("<span class=\"badge\" style=\"background:var(--amber-bg);color:var(--amber)\">Basemap uploaded</span>");
  }
  layers.push(`<span style="font-size:10px;color:var(--text4);margin-left:auto">${results.model_used} · Google Maps / Plotly</span>`);
  getRoots().layerBar.innerHTML = layers.join("");
}

function renderHeader(results) {
  getRoots().headerBadgeWrap.innerHTML = `
    <span class="badge bgr">${results.stats.point_count} points</span>
    <span class="badge" style="background:var(--amber-bg);color:var(--amber)">${results.model_used}</span>
    <button class="btn btn-sm btn-out" onclick="go(document.querySelector('[data-s=export]'))">Export ↗</button>
  `;
}

async function renderAurora() {
  if (!appState.project || !appState.task) {
    return;
  }
  const aurora = await askAurora({
    project_id: appState.project.id,
    task_id: appState.task.id,
    location: "visualisation",
    question: `Explain the current ${appState.activeVisualisation} view and the main magnetic patterns.`,
  });
  getRoots().auroraBody.innerHTML = `
    <div class="amsg">${aurora.summary}</div>
    ${(aurora.highlights || []).map((item) => `<div class="ahi">${item}</div>`).join("")}
  `;
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

async function renderPlot(mode, results) {
  const Plotly = await ensurePlotly();
  const host = ensureHost();
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
  await renderStationMap(host, results.points, {weighted: true});
}

export async function loadVisualisation() {
  if (!appState.project || !appState.task) {
    throw new Error("Run a task before opening Visualisation.");
  }
  const task = await fetchTask(appState.project.id, appState.task.id);
  setTask(task);
  renderWorkflowProgress();
  const results = getResults();
  if (!results) {
    throw new Error("Processing results are not available yet.");
  }
  renderStats(results);
  renderLayerBar(results);
  renderHeader(results);
  if (appState.activeVisualisation === "Map") {
    await renderMapOverlay(results);
  } else if (appState.activeVisualisation === "Line Profiles") {
    await renderLineProfiles(results);
  } else {
    await renderPlot(appState.activeVisualisation, results);
  }
  await renderAurora();
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
}
