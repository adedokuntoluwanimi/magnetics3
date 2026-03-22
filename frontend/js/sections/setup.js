import {createProject, createTask} from "../api.js";
import {renderWorkflowProgress} from "./progress.js";
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

function flash() {
  return getEl("setupFlash");
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

  const name = (getEl("projectNameInput")?.value || "").trim();
  const context = (getEl("projectContextInput")?.value || "").trim();
  if (!name || name.length < 3) {
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    setFlash(flash(), "Project name must be at least 3 characters.", "error");
    setStep(1);
    return;
  }
  if (!context || context.length < 10) {
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    setFlash(flash(), "Project context must be at least 10 characters.", "error");
    setStep(1);
    return;
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
  if (!appState.surveyFiles.length) {
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
    setFlash(flash(), "Creating project and uploading files…", "info");
    // Scroll to top so the user can see the progress flash
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});

    if (!appState.project) {
      const project = await createProject({name, context});
      setProject(project);
      await refreshSidebar();
    }

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
    appState.surveyFiles.forEach((f) => fd.append("survey_files", f, f.name));
    if (appState.basemapFile) fd.append("basemap_file", appState.basemapFile, appState.basemapFile.name);

    const task = await createTask(appState.project.id, fd);
    setTask(task);
    await refreshSidebar();
    renderWorkflowProgress();
    setFlash(flash(), "Project and task saved.", "success");
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
    const pName = getEl("projectNameInput");
    const pCtx = getEl("projectContextInput");
    if (pName) pName.value = "";
    if (pCtx) pCtx.value = "";
  }
  clearTask();
  renderSurveyFiles();
  renderBasemap();
  resetColumnMapping();
  resetTimeMapping();

  syncRawDataSection();
  syncBaseStationSection([], "");
  updateUploadZone(window.state?.mode || "single");
  setStep(preserveProject ? 2 : 1);
}

export function initSetup() {
  renderBasemap();
  renderSurveyFiles();
  resetColumnMapping();
  resetTimeMapping();

  syncRawDataSection();
  updateUploadZone(window.state?.mode || "single");
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
  getEl("setupToTaskBtn")?.addEventListener("click", () => {
    if (validateProject()) {
      clearFlash(flash());
      setStep(2);
    }
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
  window.goSetupTaskStep = () => {
    if (validateProject()) setStep(2);
  };
  window.beginNewProjectFlow = () => {
    fullReset();
    refreshSidebar();
  };
  window.beginNewTaskFlow = () => {
    fullReset({preserveProject: true});
    refreshSidebar();
  };
  window.submitTaskFlow = submitTaskFlow;

  window.loadTaskForEdit = (task, project) => {
    if (project) setProject(project);
    setTask(task);
    const pName = getEl("projectNameInput");
    const pCtx = getEl("projectContextInput");
    if (pName) pName.value = project?.name || "";
    if (pCtx) pCtx.value = project?.context || "";
    setStep(2);
    const tName = getEl("taskNameInput");
    const tDesc = getEl("taskDescInput");
    if (tName) tName.value = task.name || "";
    if (tDesc) tDesc.value = task.description || "";
    window.setMode?.(task.processing_mode || "single");
    const platform = task.platform || "ground";
    document.querySelectorAll(".plt-opt").forEach((el) => el.classList.toggle("selected", el.id === `plt-${platform}`));
    if (window.state) window.state.platform = platform;
    const scenario = task.scenario || "explicit";
    document.querySelectorAll(".radio-opt[id^='sc-']").forEach((el) => el.classList.toggle("selected", el.id === `sc-${scenario}`));
    if (window.state) window.state.scenario = scenario;
    const dataState = task.data_state || "corrected";
    document.querySelectorAll(".radio-opt[id^='state-']").forEach((el) => el.classList.toggle("selected", el.id === `state-${dataState}`));
    const mapping = task.column_mapping || {};
    if (mapping.coordinate_system) window.setCoordSystem?.(mapping.coordinate_system);
    if (mapping.utm_zone) { const z = getEl("utmZoneInput"); if (z) z.value = mapping.utm_zone; }
    const spacingEl = getEl("spacingInput");
    if (spacingEl && task.station_spacing) spacingEl.value = task.station_spacing;
    const unitEl = getEl("spacingUnit");
    if (unitEl && task.station_spacing_unit) unitEl.value = task.station_spacing_unit;
    getEl("setupScroll")?.scrollTo({top: 0, behavior: "smooth"});
    window.go?.(document.querySelector("[data-s=setup]"));
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
