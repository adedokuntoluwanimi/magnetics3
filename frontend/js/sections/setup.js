import {createProject, createTask} from "../api.js";
import {renderWorkflowProgress} from "./progress.js";
import {renameProject, updateTask} from "../api.js";
import {refreshSidebar} from "./sidebar.js";
import {
  appState,
  clearProcessingRun,
  clearProject,
  clearTask,
  setBasemapFile,
  setHeaders,
  setProject,
  setSurveyFiles,
  setTask,
} from "../state.js";
import {clearFlash, setFlash} from "../shared/dom.js";
import {showConfirm} from "../shared/modal.js";

let setupFlow = "new-project";
let taskFlow = "new-task";

function splitCsvHeader(text) {
  const first = (text || "").split(/\r?\n/, 1)[0] || "";
  return first.split(",").map((v) => v.trim()).filter(Boolean);
}

function pickDefault(headers, keywords) {
  const lc = keywords.map((k) => k.toLowerCase());
  return headers.find((h) => lc.some((k) => h.toLowerCase().includes(k))) || headers[0] || "";
}

function getEl(id) {
  return document.getElementById(id);
}

function median(values) {
  const sorted = values.filter((value) => Number.isFinite(value)).sort((a, b) => a - b);
  if (!sorted.length) return NaN;
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function toNumeric(value) {
  if (typeof value === "number") return value;
  const normalized = String(value ?? "").trim().replace(/,/g, "");
  if (!normalized) return NaN;
  return Number(normalized);
}

function toRadians(value) {
  return value * (Math.PI / 180);
}

function haversineMeters(lat1, lon1, lat2, lon2) {
  const earthRadius = 6371000;
  const dLat = toRadians(lat2 - lat1);
  const dLon = toRadians(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(toRadians(lat1)) * Math.cos(toRadians(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * earthRadius * Math.asin(Math.sqrt(a));
}

async function readSurveyRows(file) {
  if (!window.XLSX) {
    throw new Error("Spreadsheet parser not loaded yet. Please try again.");
  }
  let workbook;
  if (/\.xlsx?$/i.test(file.name)) {
    workbook = window.XLSX.read(await file.arrayBuffer(), {type: "array"});
  } else {
    workbook = window.XLSX.read(await file.text(), {type: "string"});
  }
  const sheet = workbook.Sheets[workbook.SheetNames[0]];
  const rows = window.XLSX.utils.sheet_to_json(sheet, {defval: ""});
  const headers = Object.keys(rows[0] || {});
  return {headers, rows};
}

function detectCoordinateOutliers(rows, mapping, coordSystem) {
  const latKey = mapping.latitude;
  const lonKey = mapping.longitude;
  const isUtm = coordSystem === "utm";
  const invalidWgs84 = new Set();
  const coords = rows.map((row, index) => {
    const rawLat = toNumeric(row[latKey]);
    const rawLon = toNumeric(row[lonKey]);
    if (!isUtm && Number.isFinite(rawLat) && Number.isFinite(rawLon) && (Math.abs(rawLat) > 90 || Math.abs(rawLon) > 180)) {
      invalidWgs84.add(index);
      return null;
    }
    return {index, rawLat, rawLon};
  }).filter((row) => row && Number.isFinite(row.rawLat) && Number.isFinite(row.rawLon));

  if (coords.length < 6) {
    return {
      outlierIndices: invalidWgs84,
      threshold: NaN,
      samples: [...invalidWgs84].slice(0, 5).map((index) => ({
        latitude: toNumeric(rows[index]?.[latKey]),
        longitude: toNumeric(rows[index]?.[lonKey]),
        distance: NaN,
      })),
    };
  }

  const centerLat = median(coords.map((row) => row.rawLat));
  const centerLon = median(coords.map((row) => row.rawLon));
  const distances = coords.map((row) => {
    const distance = isUtm
      ? Math.hypot(row.rawLat - centerLat, row.rawLon - centerLon)
      : haversineMeters(row.rawLat, row.rawLon, centerLat, centerLon);
    return {...row, distance};
  });

  const medianDistance = median(distances.map((row) => row.distance));
  const mad = median(distances.map((row) => Math.abs(row.distance - medianDistance)));
  const threshold = Math.max(
    medianDistance + Math.max(mad * 6, 250),
    medianDistance * 4,
    1000,
  );
  const outliers = distances.filter((row) => row.distance > threshold);
  const combinedOutliers = new Set([...invalidWgs84, ...outliers.map((row) => row.index)]);
  if (!combinedOutliers.size || combinedOutliers.size > Math.max(8, Math.floor(Math.max(distances.length, 1) * 0.25))) {
    return {outlierIndices: invalidWgs84, threshold, samples: []};
  }

  return {
    outlierIndices: combinedOutliers,
    threshold,
    samples: [...invalidWgs84].map((index) => ({
      latitude: toNumeric(rows[index]?.[latKey]),
      longitude: toNumeric(rows[index]?.[lonKey]),
      distance: NaN,
    })).concat(outliers.slice(0, 5).map((row) => ({
      latitude: row.rawLat,
      longitude: row.rawLon,
      distance: row.distance,
    }))).slice(0, 5),
  };
}

function csvEscape(value) {
  const text = String(value ?? "");
  if (!/[",\r\n]/.test(text)) return text;
  return `"${text.replace(/"/g, "\"\"")}"`;
}

function buildFilteredCsvFile(file, headers, rows, outlierIndices) {
  const kept = rows.filter((_, index) => !outlierIndices.has(index));
  const csv = [
    headers.map((header) => csvEscape(header)).join(","),
    ...kept.map((row) => headers.map((header) => csvEscape(row[header])).join(",")),
  ].join("\r\n");
  const fileName = file.name.replace(/\.[^.]+$/, "") + "-filtered.csv";
  return new File([csv], fileName, {type: "text/csv"});
}

async function reviewCoordinateOutliers(files, mapping, coordSystem) {
  const analyses = await Promise.all(files.map(async (file) => {
    const parsed = await readSurveyRows(file);
    const detection = detectCoordinateOutliers(parsed.rows, mapping, coordSystem);
    return {file, ...parsed, ...detection};
  }));

  const flagged = analyses.filter((item) => item.outlierIndices.size);
  if (!flagged.length) {
    return files;
  }

  const totalOutliers = flagged.reduce((sum, item) => sum + item.outlierIndices.size, 0);
  const sampleItems = flagged.flatMap((item) => item.samples.map((sample) => `
    <li><strong>${item.file.name}</strong>: ${sample.latitude}, ${sample.longitude}${Number.isFinite(sample.distance) ? ` (${Math.round(sample.distance)} m from survey cluster)` : " (invalid coordinate range)"}</li>
  `)).slice(0, 5).join("");

  const discard = await new Promise((resolve) => {
    showConfirm(`
      GAIA found <strong>${totalOutliers}</strong> coordinate outlier${totalOutliers === 1 ? "" : "s"} far from the main survey cluster.
      <div style="margin-top:10px;font-size:12px;color:var(--text3)">These points can stretch the preview and distort the map.</div>
      ${sampleItems ? `<ul style="margin-top:10px;padding-left:18px;font-size:12px;color:var(--text2);line-height:1.7">${sampleItems}</ul>` : ""}
    `, {
      title: "Distant coordinates detected",
      confirmLabel: "Discard outliers",
      cancelLabel: "Keep all",
      onConfirm: () => resolve(true),
      onCancel: () => resolve(false),
    });
  });

  if (!discard) {
    return files;
  }

  return analyses.map((item) => (
    item.outlierIndices.size
      ? buildFilteredCsvFile(item.file, item.headers, item.rows, item.outlierIndices)
      : item.file
  ));
}

function flash() {
  return getEl("setupFlash");
}

function syncProjectInputs(project = appState.project) {
  const pName = getEl("projectNameInput");
  const pCtx = getEl("projectContextInput");
  if (pName) pName.value = project?.name || "";
  if (pCtx) pCtx.value = project?.context || "";
}

function updateSetupActionLabels() {
  const projectBtn = getEl("setupToTaskBtn");
  const taskBtn = getEl("setupSaveBtn");
  if (projectBtn) {
    projectBtn.textContent = setupFlow === "new-project"
      ? "Save project and continue to Task setup →"
      : "Save project changes and continue to Task setup →";
  }
  if (taskBtn) {
    taskBtn.textContent = taskFlow === "edit-task"
      ? "Save task changes and continue to Analysis →"
      : "Save task and continue to Analysis →";
  }
}

async function saveProjectDetails() {
  clearFlash(flash());
  if (!validateProject()) {
    return false;
  }

  const name = (getEl("projectNameInput")?.value || "").trim();
  const context = (getEl("projectContextInput")?.value || "").trim();
  setFlash(
    flash(),
    setupFlow === "new-project" ? "Saving new project..." : "Saving project changes...",
    "info",
  );
  getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});

  try {
    let project = appState.project;
    if (setupFlow === "new-project" || !project) {
      project = await createProject({name, context});
    } else {
      project = await renameProject(project.id, name, context);
    }
    setProject(project);
    setupFlow = "existing-project";
    syncProjectInputs(project);
    updateSetupActionLabels();
    await refreshSidebar();
    renderWorkflowProgress();
    setFlash(flash(), "Project saved. Continue with task setup.", "success");
    setStep(2);
    return true;
  } catch (error) {
    setFlash(flash(), error.message || "Could not save project.", "error");
    return false;
  }
}

function hydrateTaskFormFromRecord(task) {
  const headers = task?.dataset_profile?.headers || task?.metadata?.headers || [];
  if (headers.length) {
    setHeaders(headers);
    populateColumnMapping(headers);
    if (isRawMode()) {
      populateTimeMapping(headers);
    }
    syncBaseStationSection(headers, task?.survey_files?.[0]?.file_name || "");
  } else {
    setHeaders([]);
    resetColumnMapping();
    resetTimeMapping();
    syncBaseStationSection([], "");
  }

  const mapping = task?.column_mapping || {};
  if (getEl("latSelect")) getEl("latSelect").value = mapping.latitude || "";
  if (getEl("lonSelect")) getEl("lonSelect").value = mapping.longitude || "";
  if (getEl("magSelect")) getEl("magSelect").value = mapping.magnetic_field || "";
  if (getEl("hourSelect")) getEl("hourSelect").value = mapping.hour || "";
  if (getEl("minuteSelect")) getEl("minuteSelect").value = mapping.minute || "";
  if (getEl("secondSelect")) getEl("secondSelect").value = mapping.second || "";
}

function buildUploadRow(name, meta, onRemove) {
  const div = document.createElement("div");
  div.className = "upload-item";
  div.innerHTML = `
    <div style="width:8px;height:8px;border-radius:50%;background:var(--g400);flex-shrink:0"></div>
    <div style="flex:1">
      <div class="upload-item-name"></div>
      <div class="upload-item-info"></div>
    </div>
    <button class="upload-item-rm" type="button">×</button>
  `;
  div.querySelector(".upload-item-name").textContent = name;
  div.querySelector(".upload-item-info").textContent = meta;
  div.querySelector(".upload-item-rm").addEventListener("click", onRemove);
  return div;
}

function setStep(step) {
  const pp = getEl("setupProjectPane");
  const tp = getEl("setupTaskPane");
  const sProject = getEl("setupStepProject");
  const sTask = getEl("setupStepTask");
  if (!pp || !tp) return;
  if (step === 1) {
    pp.style.display = "block";
    tp.style.display = "none";
    sProject.className = "si active";
    sProject.innerHTML = `<div class="snum active">1</div>Project details`;
    sTask.className = "si";
    sTask.innerHTML = `<div class="snum">2</div>Task setup`;
  } else {
    pp.style.display = "none";
    tp.style.display = "block";
    sProject.className = "si done";
    sProject.innerHTML = `<div class="snum done">✓</div>Project details`;
    sTask.className = "si active";
    sTask.innerHTML = `<div class="snum active">2</div>Task setup`;
  }
  const screen = getEl("screen-setup");
  if (screen) screen.dataset.setupStep = String(step);
  getEl("setupScroll")?.scrollTo(0, 0);
}

function updateUploadZone(mode) {
  const zone = getEl("surveyUpzone");
  const addBtn = getEl("addUploadBtn");
  if (!zone) return;
  if (mode === "single") {
    zone.innerHTML = `
      <div style="font-size:13px;font-weight:700;color:var(--text2);margin-bottom:4px">Click to upload CSV</div>
      <div style="font-size:11px;color:var(--text3)">Single survey line · .csv format</div>
    `;
    if (addBtn) addBtn.style.display = "none";
  } else {
    zone.innerHTML = `
      <div style="font-size:13px;font-weight:700;color:var(--text2);margin-bottom:4px">Click to add CSV files</div>
      <div style="font-size:11px;color:var(--text3)">Multi-line survey · one CSV per line · .csv format</div>
    `;
    if (addBtn) addBtn.style.display = "flex";
  }
}

function renderSurveyFiles() {
  const list = getEl("uploadList");
  if (!list) return;
  list.innerHTML = "";
  appState.surveyFiles.forEach((file, idx) => {
    const meta = `${(file.size / 1024).toFixed(1)} KB`;
    list.appendChild(
      buildUploadRow(file.name, meta, () => {
        const updated = appState.surveyFiles.filter((_, i) => i !== idx);
        setSurveyFiles(updated);
        renderSurveyFiles();
        if (!updated.length) resetColumnMapping();
      })
    );
  });
}

function renderBasemap() {
  const zone = getEl("basemapZone");
  const done = getEl("basemapDone");
  if (!zone || !done) return;
  if (!appState.basemapFile) {
    zone.style.display = "block";
    done.style.display = "none";
    done.innerHTML = "";
    return;
  }
  zone.style.display = "none";
  done.style.display = "block";
  done.innerHTML = "";
  done.appendChild(
    buildUploadRow(
      appState.basemapFile.name,
      `${(appState.basemapFile.size / 1024).toFixed(1)} KB`,
      () => {
        setBasemapFile(null);
        renderBasemap();
      }
    )
  );
}

function populateColumnMapping(headers) {
  const lat = getEl("latSelect");
  const lon = getEl("lonSelect");
  const mag = getEl("magSelect");
  if (!lat || !lon || !mag) return;
  [lat, lon, mag].forEach((sel) => {
    sel.innerHTML = "";
    headers.forEach((h) => {
      const opt = document.createElement("option");
      opt.value = h;
      opt.textContent = h;
      sel.appendChild(opt);
    });
  });
  lat.value = pickDefault(headers, ["lat", "northing", "y"]);
  lon.value = pickDefault(headers, ["lon", "long", "easting", "x"]);
  mag.value = pickDefault(headers, ["mag", "tmf", "field", "nt"]);
  const placeholder = getEl("mappingPlaceholder");
  const selects = getEl("mappingSelects");
  if (placeholder) placeholder.style.display = "none";
  if (selects) selects.style.display = "block";
}

function resetColumnMapping() {
  const placeholder = getEl("mappingPlaceholder");
  const selects = getEl("mappingSelects");
  if (placeholder) placeholder.style.display = "block";
  if (selects) selects.style.display = "none";
}

function isRawMode() {
  return !getEl("state-corr")?.classList.contains("selected");
}

function syncRawDataSection() {
  const section = getEl("rawDataSection");
  if (section) section.style.display = isRawMode() ? "block" : "none";
}

function syncBaseStationSection(headers, fileName) {
  const isXlsx = /\.xlsx?$/i.test(fileName || "");
  const xlsxNote = getEl("bsXlsxNote");
  const csvSection = getEl("bsCsvSection");
  const noFile = getEl("bsNoFile");
  if (xlsxNote) xlsxNote.style.display = isXlsx ? "block" : "none";
  if (csvSection) csvSection.style.display = (!isXlsx && headers.length) ? "block" : "none";
  if (noFile) noFile.style.display = headers.length ? "none" : "block";
  if (!isXlsx && headers.length) {
    const bsSel = getEl("bsColumnSelect");
    if (bsSel) {
      bsSel.innerHTML = `<option value="">— none —</option>` + headers.map((h) => `<option value="${h}">${h}</option>`).join("");
      bsSel.onchange = () => {
        const vRow = getEl("bsValueRow");
        if (vRow) vRow.style.display = bsSel.value ? "block" : "none";
      };
    }
  }
}

function populateTimeMapping(headers) {
  const hour = getEl("hourSelect");
  const min = getEl("minuteSelect");
  const sec = getEl("secondSelect");
  if (!hour || !min || !sec) return;
  const empty = `<option value="">— none —</option>`;
  [hour, min, sec].forEach((sel) => {
    sel.innerHTML = empty + headers.map((h) => `<option value="${h}">${h}</option>`).join("");
  });
  hour.value = pickDefault(headers, ["hour", "hh", "h"]) || "";
  min.value = pickDefault(headers, ["min", "minute", "mm", "m"]) || "";
  sec.value = pickDefault(headers, ["sec", "second", "ss", "s"]) || "";
  const ph = getEl("timeMappingPlaceholder");
  const ts = getEl("timeMappingSelects");
  if (ph) ph.style.display = "none";
  if (ts) ts.style.display = "block";
}

function resetTimeMapping() {
  const ph = getEl("timeMappingPlaceholder");
  const ts = getEl("timeMappingSelects");
  if (ph) ph.style.display = "block";
  if (ts) ts.style.display = "none";
}


async function readFileHeaders(file) {
  const isXlsx = /\.xlsx?$/i.test(file.name);
  if (isXlsx) {
    if (!window.XLSX) throw new Error("xlsx parser not loaded yet — try again in a moment.");
    const ab = await file.arrayBuffer();
    const wb = window.XLSX.read(ab, {type: "array"});
    const ws = wb.Sheets[wb.SheetNames[0]];
    const rows = window.XLSX.utils.sheet_to_json(ws, {header: 1, defval: ""});
    const headers = (rows[0] || []).map((h) => String(h).trim()).filter(Boolean);
    if (!headers.length) throw new Error("Excel file has no readable header row.");
    return headers;
  }
  const text = await file.text();
  const headers = splitCsvHeader(text);
  if (!headers.length) throw new Error("File has no readable header row.");
  return headers;
}

async function handleFiles(fileList) {
  const arr = Array.from(fileList || []);
  if (!arr.length) return;
  const mode = window.state?.mode || "single";
  if (mode === "single") {
    setSurveyFiles([arr[0]]);
  } else {
    setSurveyFiles([...appState.surveyFiles, ...arr]);
  }
  renderSurveyFiles();
  try {
    const headers = await readFileHeaders(appState.surveyFiles[0]);
    setHeaders(headers);
    populateColumnMapping(headers);
    if (isRawMode()) {
      populateTimeMapping(headers);
    }
    syncBaseStationSection(headers, appState.surveyFiles[0]?.name);
    clearFlash(flash());
  } catch (e) {
    setFlash(flash(), e.message || "Could not read file headers.", "error");
  }
}

function validateProject() {
  const name = (getEl("projectNameInput")?.value || "").trim();
  const context = (getEl("projectContextInput")?.value || "").trim();
  if (!name) {
    setFlash(flash(), "Project name is required.", "error");
    return false;
  }
  if (name.length < 3) {
    setFlash(flash(), "Project name must be at least 3 characters.", "error");
    return false;
  }
  if (!context) {
    setFlash(flash(), "Project context is required.", "error");
    return false;
  }
  if (context.length < 10) {
    setFlash(flash(), "Project context must be at least 10 characters — describe the survey area and objectives.", "error");
    return false;
  }
  return true;
}

async function submitTaskFlow() {
  clearFlash(flash());

  if (!appState.project) {
    const savedProject = await saveProjectDetails();
    if (!savedProject) {
      setStep(1);
      return;
    }
  }

  const taskName = (getEl("taskNameInput")?.value || "").trim();
  const taskDesc = (getEl("taskDescInput")?.value || "").trim();
  if (!taskName || taskName.length < 3) {
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    setFlash(flash(), "Task name must be at least 3 characters.", "error");
    return;
  }
  if (!taskDesc || taskDesc.length < 10) {
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    setFlash(flash(), "Task description must be at least 10 characters.", "error");
    return;
  }
  const isEditingTask = taskFlow === "edit-task" && appState.task?.id;
  if (!appState.surveyFiles.length && !isEditingTask) {
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    setFlash(flash(), "Upload at least one survey CSV file.", "error");
    return;
  }
  const mapping = {
    latitude: getEl("latSelect")?.value || "",
    longitude: getEl("lonSelect")?.value || "",
    magnetic_field: getEl("magSelect")?.value || "",
  };
  if (!mapping.latitude || !mapping.longitude || !mapping.magnetic_field) {
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    setFlash(flash(), "Column mapping is incomplete — upload a CSV file and map all three fields.", "error");
    return;
  }
  const isRaw = isRawMode();
  if (isRaw) {
    mapping.hour = getEl("hourSelect")?.value || "";
    mapping.minute = getEl("minuteSelect")?.value || "";
    mapping.second = getEl("secondSelect")?.value || "";
    const bsCol = getEl("bsColumnSelect")?.value || "";
    const bsVal = getEl("bsValueInput")?.value?.trim() || "";
    if (bsCol) {
      mapping.base_station_column = bsCol;
      mapping.base_station_value = bsVal || "1";
    }
  }
  // Coordinate system should always be sent for preview conversion.
  const coordSys = window.state?.coordSystem || "wgs84";
  mapping.coordinate_system = coordSys;
  if (coordSys === "utm") {
    const zone = parseInt(getEl("utmZoneInput")?.value || "0", 10);
    if (zone >= 1 && zone <= 60) mapping.utm_zone = zone;
    mapping.utm_hemisphere = getEl("utmHemisphere")?.value || "N";
  }

  try {
    const preparedSurveyFiles = appState.surveyFiles.length
      ? await reviewCoordinateOutliers(appState.surveyFiles, mapping, coordSys)
      : [];
    setFlash(
      flash(),
      isEditingTask ? "Saving task changes..." : "Creating task and uploading files...",
      "info",
    );
    // Scroll to top so the user can see the progress flash
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});

    const fd = new FormData();
    fd.set("name", taskName);
    fd.set("description", taskDesc);
    fd.set("platform", window.state?.platform || "ground");
    fd.set("data_state", getEl("state-corr")?.classList.contains("selected") ? "corrected" : "raw");
    fd.set("scenario", window.state?.scenario || "explicit");
    fd.set("processing_mode", window.state?.mode || "single");
    fd.set("corrected_corrections", JSON.stringify([]));
    fd.set("column_mapping", JSON.stringify(mapping));
    fd.set("metadata", JSON.stringify({headers: appState.headers}));
    const spacingVal = (getEl("spacingInput")?.value || "").trim();
    if (spacingVal) fd.set("station_spacing", spacingVal);
    const spacingUnit = getEl("spacingUnit")?.value;
    if (spacingUnit) fd.set("station_spacing_unit", spacingUnit);
    const ptList = window.state?.predictedTraverses || [];
    fd.set("predicted_traverses_json", JSON.stringify(ptList));
    preparedSurveyFiles.forEach((f) => fd.append("survey_files", f, f.name));
    if (appState.basemapFile) fd.append("basemap_file", appState.basemapFile, appState.basemapFile.name);

    const task = isEditingTask
      ? await updateTask(appState.project.id, appState.task.id, fd)
      : await createTask(appState.project.id, fd);
    setTask(task);
    taskFlow = "edit-task";
    await refreshSidebar();
    renderWorkflowProgress();
    setFlash(flash(), isEditingTask ? "Task updated." : "Task saved.", "success");
    window.go(document.querySelector("[data-s=analysis]"));
  } catch (err) {
    setFlash(flash(), err.message || "Save failed. Please try again.", "error");
  }
}

function fullReset({preserveProject = false} = {}) {
  clearFlash(flash());
  clearProcessingRun();
  setSurveyFiles([]);
  setBasemapFile(null);
  setHeaders([]);
  const taskName = getEl("taskNameInput");
  const taskDesc = getEl("taskDescInput");
  if (taskName) taskName.value = "";
  if (taskDesc) taskDesc.value = "";
  if (!preserveProject) {
    clearProject();
    syncProjectInputs(null);
  }
  clearTask();
  renderSurveyFiles();
  renderBasemap();
  resetColumnMapping();
  resetTimeMapping();

  syncRawDataSection();
  syncBaseStationSection([], "");
  updateUploadZone(window.state?.mode || "single");
  if (preserveProject) {
    syncProjectInputs(appState.project);
  }
  taskFlow = "new-task";
  updateSetupActionLabels();
  setStep(preserveProject ? 2 : 1);
}

export function initSetup() {
  renderBasemap();
  renderSurveyFiles();
  resetColumnMapping();
  resetTimeMapping();

  syncRawDataSection();
  updateUploadZone(window.state?.mode || "single");
  updateSetupActionLabels();
  setStep(1);

  // Create hidden file inputs once
  let surveyInput = getEl("surveyFilesInput");
  if (!surveyInput) {
    surveyInput = document.createElement("input");
    surveyInput.type = "file";
    surveyInput.id = "surveyFilesInput";
    surveyInput.accept = ".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
    surveyInput.multiple = true;
    surveyInput.style.display = "none";
    document.getElementById("screen-setup").appendChild(surveyInput);
  }

  let basemapInput = getEl("basemapInput");
  if (!basemapInput) {
    basemapInput = document.createElement("input");
    basemapInput.type = "file";
    basemapInput.id = "basemapInput";
    basemapInput.accept = ".kmz,.kml,.zip,.geojson,.json,.pdf,.doc,.docx,.txt";
    basemapInput.style.display = "none";
    document.getElementById("screen-setup").appendChild(basemapInput);
  }

  // Wire file input events
  surveyInput.addEventListener("change", async (e) => {
    await handleFiles(e.target.files);
    surveyInput.value = "";
  });
  basemapInput.addEventListener("change", (e) => {
    const f = Array.from(e.target.files || [])[0] || null;
    setBasemapFile(f);
    renderBasemap();
    basemapInput.value = "";
  });
  // Wire upload zone and add-file button
  getEl("surveyUpzone")?.addEventListener("click", () => surveyInput.click());
  getEl("addUploadBtn")?.addEventListener("click", () => surveyInput.click());
  getEl("basemapZone")?.addEventListener("click", () => basemapInput.click());

  // Step buttons
  getEl("setupToTaskBtn")?.addEventListener("click", async () => {
    await saveProjectDetails();
  });
  getEl("setupBackBtn")?.addEventListener("click", () => {
    clearFlash(flash());
    setStep(1);
  });
  getEl("setupSaveBtn")?.addEventListener("click", submitTaskFlow);

  // Override legacy inline setState to show/hide raw data section
  const legacySetState = window.setState?.bind(window);
  window.setState = (s) => {
    legacySetState?.(s);
    syncRawDataSection();
    // If headers already loaded, populate/clear time mapping
    if (appState.headers?.length) {
      if (isRawMode()) {
        populateTimeMapping(appState.headers);
      } else {
        resetTimeMapping();
      }
    }
  };

  // Override legacy inline setMode to also update upload zone
  const legacySetMode = window.setMode?.bind(window);
  window.setMode = (m) => {
    legacySetMode?.(m);
    updateUploadZone(m);
    if (m === "single" && appState.surveyFiles.length > 1) {
      setSurveyFiles(appState.surveyFiles.slice(0, 1));
      renderSurveyFiles();
    }
  };

  // Global hooks
  window.setCoordSystem = (cs) => {
    if (!window.state) window.state = {};
    window.state.coordSystem = cs;
    getEl("cs-wgs84")?.classList.toggle("selected", cs === "wgs84");
    getEl("cs-utm")?.classList.toggle("selected", cs === "utm");
    const zoneRow = getEl("utm-zone-row");
    if (zoneRow) zoneRow.style.display = cs === "utm" ? "block" : "none";
  };
  window.addBasemap = () => basemapInput.click();
  window.removeBasemap = () => {
    setBasemapFile(null);
    renderBasemap();
  };
  window.goSetupProjectStep = () => setStep(1);
  window.goSetupTaskStep = async () => {
    await saveProjectDetails();
  };
  window.beginNewProjectFlow = () => {
    setupFlow = "new-project";
    taskFlow = "new-task";
    fullReset();
    refreshSidebar();
  };
  window.beginEditProjectFlow = () => {
    setupFlow = "existing-project";
    taskFlow = "new-task";
    fullReset({preserveProject: true});
    syncProjectInputs(appState.project);
    updateSetupActionLabels();
    setStep(1);
  };
  window.beginNewTaskFlow = () => {
    setupFlow = "existing-project";
    taskFlow = "new-task";
    fullReset({preserveProject: true});
    syncProjectInputs(appState.project);
    refreshSidebar();
  };
  window.submitTaskFlow = submitTaskFlow;

  window.loadTaskForEdit = (task, project) => {
    setupFlow = "existing-project";
    taskFlow = "edit-task";
    if (project) setProject(project);
    setTask(task);
    syncProjectInputs(project);
    setSurveyFiles([]);
    renderSurveyFiles();
    setBasemapFile(null);
    renderBasemap();
    hydrateTaskFormFromRecord(task);
    updateSetupActionLabels();
    setStep(2);
    const tName = getEl("taskNameInput");
    const tDesc = getEl("taskDescInput");
    if (tName) tName.value = task.name || "";
    if (tDesc) tDesc.value = task.description || "";
    window.setMode?.(task.processing_mode || "single");
    const platform = task.platform || "ground";
    window.setPlatform?.(platform);
    if (window.state) window.state.platform = platform;
    const scenario = task.scenario || "explicit";
    window.setScenario?.(scenario);
    if (window.state) window.state.scenario = scenario;
    if (scenario === "sparse") {
      const pts = task.predicted_traverses || [];
      window.state.predictedTraverses = pts;
      renderPredictedTraverseList();
    }
    const dataState = task.data_state === "corrected" ? "corr" : "raw";
    window.setState?.(dataState);
    const mapping = task.column_mapping || {};
    if (mapping.coordinate_system) window.setCoordSystem?.(mapping.coordinate_system);
    if (mapping.utm_zone) { const z = getEl("utmZoneInput"); if (z) z.value = mapping.utm_zone; }
    const spacingEl = getEl("spacingInput");
    if (spacingEl && task.station_spacing) spacingEl.value = task.station_spacing;
    const unitEl = getEl("spacingUnit");
    if (unitEl && task.station_spacing_unit) unitEl.value = task.station_spacing_unit;
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    window.go?.("setup");
  };

  // Wire "Start Project" buttons from the home screen
  document.querySelectorAll("button").forEach((btn) => {
    if (/start project/i.test(btn.textContent || "") && btn.getAttribute("onclick")?.includes("startProject")) {
      btn.onclick = () => {
        window.beginNewProjectFlow?.();
        window.startProject?.();
      };
    }
  });
}

// Predicted traverse management (sparse scenario)
window.state = window.state || {};
window.state.predictedTraverses = window.state.predictedTraverses || [];

window.addPredictedTraverse = function(type) {
  if (!window.state) window.state = {};
  if (!window.state.predictedTraverses) window.state.predictedTraverses = [];
  const idx = window.state.predictedTraverses.length;
  const label = `Predicted Traverse ${idx + 1}`;
  const t = {
    type: type || "offset",
    label,
    spacing: 10,
    spacing_unit: "Metres",
    distance: 50,
    distance_unit: "Metres",
    direction: 90,
  };
  window.state.predictedTraverses.push(t);
  renderPredictedTraverseList();
};

window.removePredictedTraverse = function(idx) {
  if (!window.state?.predictedTraverses) return;
  window.state.predictedTraverses.splice(idx, 1);
  // Re-label remaining traverses
  window.state.predictedTraverses.forEach((t, i) => { t.label = `Predicted Traverse ${i + 1}`; });
  renderPredictedTraverseList();
};

window.updatePredictedTraverse = function(idx, field, value) {
  if (!window.state?.predictedTraverses?.[idx]) return;
  window.state.predictedTraverses[idx][field] = value;
};

function renderPredictedTraverseList() {
  const container = document.getElementById("predictedTraverseList");
  if (!container) return;
  const list = window.state?.predictedTraverses || [];
  if (list.length === 0) {
    container.innerHTML = `<div style="font-size:11px;color:var(--text4);padding:6px 0">No predicted traverses added yet.</div>`;
    return;
  }
  container.innerHTML = list.map((t, i) => `
    <div class="card" style="margin-bottom:8px;padding:10px 12px;position:relative">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
        <span style="font-size:12px;font-weight:700;color:var(--text1)">${t.label}</span>
        <button onclick="window.removePredictedTraverse(${i})" style="background:none;border:none;color:var(--text3);cursor:pointer;font-size:13px;padding:0 4px" title="Remove">✕</button>
      </div>
      <div style="display:flex;gap:8px;margin-bottom:8px">
        <button onclick="window.setPTType(${i},'offset')" class="pt-type-btn${t.type==='offset'?' selected':''}" style="flex:1;padding:4px;font-size:10.5px;border-radius:5px;border:1px solid var(--border);background:${t.type==='offset'?'var(--accent)':'var(--card)'};color:${t.type==='offset'?'#fff':'var(--text2)'};cursor:pointer">Offset traverse</button>
        <button onclick="window.setPTType(${i},'infill')" class="pt-type-btn${t.type==='infill'?' selected':''}" style="flex:1;padding:4px;font-size:10.5px;border-radius:5px;border:1px solid var(--border);background:${t.type==='infill'?'var(--accent)':'var(--card)'};color:${t.type==='infill'?'#fff':'var(--text2)'};cursor:pointer">Infill spacing</button>
      </div>
      ${t.type === 'offset' ? `
        <div class="g2" style="margin-bottom:6px">
          <div>
            <label class="fl" style="font-size:10.5px">Distance</label>
            <div class="g2">
              <input class="fi" type="number" min="1" value="${t.distance||50}" oninput="window.updatePredictedTraverse(${i},'distance',+this.value)" style="font-size:11px">
              <select class="fsel" onchange="window.updatePredictedTraverse(${i},'distance_unit',this.value)" style="font-size:11px">
                <option${t.distance_unit==='Metres'?' selected':''}>Metres</option>
                <option${t.distance_unit==='Kilometres'?' selected':''}>Kilometres</option>
                <option${t.distance_unit==='Feet'?' selected':''}>Feet</option>
              </select>
            </div>
          </div>
          <div>
            <label class="fl" style="font-size:10.5px">Direction (bearing °)</label>
            <input class="fi" type="number" min="0" max="359" value="${t.direction||90}" oninput="window.updatePredictedTraverse(${i},'direction',+this.value)" style="font-size:11px" placeholder="0=N 90=E 180=S 270=W">
          </div>
        </div>
      ` : ''}
      <div>
        <label class="fl" style="font-size:10.5px">Station spacing</label>
        <div class="g2">
          <input class="fi" type="number" min="0.1" step="0.1" value="${t.spacing||10}" oninput="window.updatePredictedTraverse(${i},'spacing',+this.value)" style="font-size:11px">
          <select class="fsel" onchange="window.updatePredictedTraverse(${i},'spacing_unit',this.value)" style="font-size:11px">
            <option${t.spacing_unit==='Metres'?' selected':''}>Metres</option>
            <option${t.spacing_unit==='Kilometres'?' selected':''}>Kilometres</option>
            <option${t.spacing_unit==='Feet'?' selected':''}>Feet</option>
          </select>
        </div>
      </div>
    </div>
  `).join("");
}

window.setPTType = function(idx, type) {
  if (!window.state?.predictedTraverses?.[idx]) return;
  window.state.predictedTraverses[idx].type = type;
  renderPredictedTraverseList();
};
