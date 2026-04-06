import {saveAnalysis} from "../api.js";
import {appState} from "../state.js";
import {showGlobalNotice} from "../shared/notice.js";

// Display label → backend ID maps
const CORRECTION_MAP = {
  "Diurnal correction": "diurnal",
  "IGRF removal": "igrf",
  "Filtering": "filtering",
  "Lag correction": "lag",
  "Heading correction": "heading",
};

const ADD_ON_MAP = {
  "Reduction to Pole (RTP)": "rtp",
  "Analytic signal": "analytic_signal",
  "First Vertical Derivative": "first_vertical_derivative",
  "Second Vertical Derivative": "second_vertical_derivative",
  "Horizontal Derivative": "horizontal_derivative",
  "Total Horizontal Gradient": "thg",
  "Tilt Derivative": "tilt_derivative",
  "Regional residual": "emag2",
};

const MODEL_MAP = {
  "Kriging": "kriging",
  "Machine learning": "ml",
  "Hybrid": "hybrid",
};

const REGIONAL_METHOD_HELP = {
  polynomial: "Fits a low-order polynomial trend to station distance. Suitable for removing broad tilts in the corrected field. Single-line: profile polynomial. Multi-line: 2D trend surface.",
  trend: "Represents the broad background field using a smooth large-scale spatial trend. Similar to polynomial but fitted over 2D space.",
  lowpass: "Retains long-wavelength content as the regional field. Applied per-line for single-line surveys; grid low-pass for multi-line. Cutoff tied to smoothing scale.",
  igrf_context: "Uses the IGRF geomagnetic reference as a long-wavelength background context. Not a local trend fit — more appropriate as a reference check than a local regional estimate.",
};

// Reverse maps for restoring saved state to the UI
const REV_MODEL = Object.fromEntries(Object.entries(MODEL_MAP).map(([k, v]) => [v, k]));

export function collectAnalysisConfig() {
  const checkedLabels = Array.from(
    document.querySelectorAll("#screen-analysis .chk.on .chk-t"),
  ).map((n) => n.textContent.trim());

  const corrections = checkedLabels
    .filter((l) => CORRECTION_MAP[l])
    .map((l) => CORRECTION_MAP[l]);

  const addOns = checkedLabels
    .filter((l) => ADD_ON_MAP[l])
    .map((l) => ADD_ON_MAP[l]);

  const modelLabel =
    document.querySelector("#screen-analysis .mc.on .mc-name")?.textContent.trim() ||
    "Machine learning";
  const model = MODEL_MAP[modelLabel] || "ml";

  const filterType = document.getElementById("filt-low")?.classList.contains("selected")
    ? "low-pass"
    : document.getElementById("filt-high")?.classList.contains("selected")
      ? "high-pass"
      : null;

  // Filter cutoff: half-wavelength in stations
  const filterCutoffRaw = parseInt(document.getElementById("filter-cutoff")?.value || "20", 10);
  const filterCutoffStations = Number.isFinite(filterCutoffRaw) && filterCutoffRaw >= 2 ? filterCutoffRaw : 20;

  // IGRF survey date (ISO date string, e.g. "2024-03-15")
  const igrfDateVal = document.getElementById("igrf-survey-date")?.value || "";
  const surveyDate = igrfDateVal ? `${igrfDateVal}T00:00:00Z` : null;

  // SVD pre-smoothing
  const svdPreSmooth = document.getElementById("svd-smooth-toggle")?.checked !== false;

  const runPrediction = document.getElementById("predModelToggle")?.checked !== false;
  const regionalResidualEnabled = document.getElementById("regionalResidualToggle")?.checked
    || addOns.includes("emag2")
    || false;
  const regionalMethod = document.getElementById("regionalMethodSelect")?.value || "lowpass";
  const regionalDegree = Number(document.getElementById("regionalDegreeInput")?.value || 1);
  const regionalScale = Number(document.getElementById("regionalScaleInput")?.value || 2.5);

  return {
    corrections,
    filter_type: filterType,
    filter_cutoff_stations: filterCutoffStations,
    survey_date: surveyDate,
    svd_pre_smooth: svdPreSmooth,
    model,
    add_ons: addOns,
    run_prediction: runPrediction,
    regional_residual_enabled: Boolean(regionalResidualEnabled),
    regional_method: regionalMethod,
    regional_polynomial_degree: Number.isFinite(regionalDegree) ? regionalDegree : 1,
    regional_filter_scale: Number.isFinite(regionalScale) ? regionalScale : 2.5,
    output_regional_residual_visuals: Boolean(regionalResidualEnabled),
  };
}

export async function persistAnalysis() {
  if (!appState.project || !appState.task) return null;
  const config = collectAnalysisConfig();
  const updated = await saveAnalysis(appState.project.id, appState.task.id, config);
  // Persist back into state so Preview picks it up immediately
  if (updated) appState.task = updated;
  return updated;
}

/**
 * Restore the analysis UI from a previously saved analysis_config on a task.
 */
function applyDataStateRestrictions(task) {
  const isCorrected = task?.data_state === "corrected";
  document.querySelectorAll("#screen-analysis .chk").forEach((el) => {
    const label = el.querySelector(".chk-t")?.textContent.trim();
    if (label === "Diurnal correction") {
      if (isCorrected) {
        el.style.opacity = "0.4";
        el.style.pointerEvents = "none";
        el.classList.remove("on");
        const box = el.querySelector(".chk-box");
        if (box) { box.classList.remove("on"); box.textContent = ""; }
      } else {
        el.style.opacity = "";
        el.style.pointerEvents = "";
      }
    }
  });
}

function renderDiurnalInfo(task) {
  const badges = document.getElementById("diurnalInfoBadges");
  const note = document.getElementById("diurnalInfoNote");
  if (!badges || !note) return;
  const validation = task?.results?.data?.validation_summary || task?.results?.validation_summary || {};
  const baseCount = Number(validation.base_station_count || 0);
  const items = [];
  if (baseCount > 0) {
    items.push({text: "Base station data detected", color: "var(--g500)", bg: "var(--g100)"});
  } else {
    items.push({text: "Fallback diurnal mode likely", color: "var(--amber)", bg: "var(--amber-bg)"});
  }
  items.push({text: "Interval-based diurnal correction", color: "var(--blue)", bg: "var(--bg2)"});
  badges.innerHTML = items.map((item) => `<span class="badge" style="background:${item.bg};color:${item.color}">${item.text}</span>`).join("");
  if (baseCount === 1) {
    note.style.display = "block";
    note.textContent = "Only one base station reading detected. Constant-base correction may be used.";
  } else {
    note.style.display = "none";
    note.textContent = "";
  }
}

function syncRegionalResidualUI() {
  const card = document.getElementById("regionalSettingsCard");
  const toggle = document.getElementById("regionalResidualToggle");
  const select = document.getElementById("regionalMethodSelect");
  const degreeRow = document.getElementById("regionalDegreeRow");
  const scaleRow = document.getElementById("regionalScaleRow");
  const help = document.getElementById("regionalMethodHelp");
  const note = document.getElementById("regionalMethodNote");
  const regionalCard = Array.from(document.querySelectorAll("#screen-analysis .chk .chk-t"))
    .find((node) => node.textContent.trim() === "Regional residual")
    ?.closest(".chk");
  const enabled = Boolean(toggle?.checked || regionalCard?.classList.contains("on"));
  if (toggle) toggle.checked = enabled;
  if (card) card.style.display = enabled ? "block" : "none";
  const method = select?.value || "lowpass";
  if (degreeRow) degreeRow.style.display = method === "polynomial" || method === "trend" ? "block" : "none";
  if (scaleRow) scaleRow.style.display = method === "lowpass" ? "block" : "none";
  if (help) help.textContent = REGIONAL_METHOD_HELP[method] || "";
  if (note) {
    if (method === "igrf_context") {
      note.style.display = "block";
      note.textContent = "IGRF context is a background reference mode, not the same as polynomial detrending or local profile smoothing.";
    } else {
      note.style.display = "none";
      note.textContent = "";
    }
  }
}

function syncFilterUI() {
  const highWarn = document.getElementById("filter-highpass-warn");
  if (!highWarn) return;
  const isHigh = document.getElementById("filt-high")?.classList.contains("selected");
  highWarn.style.display = isHigh ? "block" : "none";
}

export function loadAnalysis(task) {
  if (!task?.analysis_config) {
    applyDataStateRestrictions(task);
    renderDiurnalInfo(task);
    syncRegionalResidualUI();
    return;
  }
  const config = task.analysis_config;
  const savedCorrections = new Set(config.corrections || []);
  const savedAddOns = new Set(config.add_ons || []);

  // Reset all correction/add-on checkboxes first
  document.querySelectorAll("#screen-analysis .chk").forEach((el) => {
    el.classList.remove("on");
    const box = el.querySelector(".chk-box");
    if (box) {
      box.classList.remove("on");
      box.textContent = "";
    }
  });

  // Restore regional settings
  const regionalToggle = document.getElementById("regionalResidualToggle");
  if (regionalToggle) regionalToggle.checked = Boolean(config.regional_residual_enabled || savedAddOns.has("emag2"));
  const regionalMethod = document.getElementById("regionalMethodSelect");
  if (regionalMethod) regionalMethod.value = config.regional_method || "lowpass";
  const regionalDegree = document.getElementById("regionalDegreeInput");
  if (regionalDegree) regionalDegree.value = String(config.regional_polynomial_degree || 1);
  const regionalScale = document.getElementById("regionalScaleInput");
  if (regionalScale) regionalScale.value = String(config.regional_filter_scale || 2.5);

  // Restore IGRF survey date
  const igrfDateInput = document.getElementById("igrf-survey-date");
  if (igrfDateInput && config.survey_date) {
    // config.survey_date is ISO datetime; extract YYYY-MM-DD for the date input
    igrfDateInput.value = String(config.survey_date).slice(0, 10);
  }

  // Restore filter cutoff
  const filterCutoffInput = document.getElementById("filter-cutoff");
  if (filterCutoffInput && config.filter_cutoff_stations) {
    filterCutoffInput.value = String(config.filter_cutoff_stations);
  }

  // Restore SVD pre-smooth
  const svdSmooth = document.getElementById("svd-smooth-toggle");
  if (svdSmooth) svdSmooth.checked = config.svd_pre_smooth !== false;

  // Hide filter sub-options
  const filterOpts = document.getElementById("filter-opts");
  if (filterOpts) filterOpts.style.display = "none";

  // Reset filter radio selection
  ["filt-low", "filt-high"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) {
      el.classList.remove("selected");
      const circle = el.querySelector(".radio-circle");
      if (circle) circle.innerHTML = "";
    }
  });

  // Restore checkboxes based on saved config
  document.querySelectorAll("#screen-analysis .chk").forEach((el) => {
    const label = el.querySelector(".chk-t")?.textContent.trim();
    const corrKey = CORRECTION_MAP[label];
    const addonKey = ADD_ON_MAP[label];
    const shouldOn =
      (corrKey && savedCorrections.has(corrKey)) ||
      (addonKey && savedAddOns.has(addonKey));

    if (shouldOn) {
      el.classList.add("on");
      const box = el.querySelector(".chk-box");
      if (box) {
        box.classList.add("on");
        box.textContent = "✓";
      }
      // Restore filter sub-options if filtering was selected
      if (corrKey === "filtering" && filterOpts) {
        filterOpts.style.display = "block";
        if (config.filter_type === "low-pass") {
          window.setFilter?.("low");
        } else if (config.filter_type === "high-pass") {
          window.setFilter?.("high");
        }
      }
      // Restore SVD sub-options if SVD was selected
      if (addonKey === "second_vertical_derivative") {
        const svdOpts = document.getElementById("svd-opts");
        if (svdOpts) svdOpts.style.display = "block";
      }
    }
  });

  // IGRF opts: show only when IGRF is checked
  const igrfEl = document.getElementById("chk-igrf");
  const igrfOpts = document.getElementById("igrf-opts");
  if (igrfEl && igrfOpts) {
    igrfOpts.style.display = igrfEl.classList.contains("on") ? "block" : "none";
  }

  // Restore prediction modelling toggle
  const toggle = document.getElementById("predModelToggle");
  if (toggle) {
    toggle.checked = config.run_prediction !== false;
    const section = document.getElementById("predModelSection");
    if (section) {
      section.style.opacity = toggle.checked ? "1" : "0.35";
      section.style.pointerEvents = toggle.checked ? "" : "none";
    }
  }

  // Restore model selection
  const savedModelLabel = REV_MODEL[config.model];
  if (savedModelLabel) {
    document.querySelectorAll("#screen-analysis .mc").forEach((el) => {
      const name = el.querySelector(".mc-name")?.textContent.trim();
      const isMatch = name === savedModelLabel;
      el.classList.toggle("on", isMatch);
      const nameEl = el.querySelector(".mc-name");
      if (nameEl) nameEl.style.color = isMatch ? "var(--g600)" : "";
    });
  }

  applyDataStateRestrictions(task);
  renderDiurnalInfo(task);
  syncRegionalResidualUI();
  syncFilterUI();
}

export function initAnalysis() {
  // Wire prediction modelling toggle
  const predToggle = document.getElementById("predModelToggle");
  const predSection = document.getElementById("predModelSection");
  if (predToggle && predSection) {
    predToggle.addEventListener("change", () => {
      predSection.style.opacity = predToggle.checked ? "1" : "0.35";
      predSection.style.pointerEvents = predToggle.checked ? "" : "none";
    });
  }

  // Regional residual wiring
  document.getElementById("regionalResidualToggle")?.addEventListener("change", () => {
    const enabled = document.getElementById("regionalResidualToggle")?.checked;
    const regionalCard = Array.from(document.querySelectorAll("#screen-analysis .chk .chk-t"))
      .find((node) => node.textContent.trim() === "Regional residual")
      ?.closest(".chk");
    if (regionalCard) {
      regionalCard.classList.toggle("on", Boolean(enabled));
      const box = regionalCard.querySelector(".chk-box");
      if (box) {
        box.classList.toggle("on", Boolean(enabled));
        box.textContent = enabled ? "✓" : "";
      }
    }
    syncRegionalResidualUI();
  });
  document.getElementById("regionalMethodSelect")?.addEventListener("change", syncRegionalResidualUI);
  document.getElementById("regionalDegreeInput")?.addEventListener("input", syncRegionalResidualUI);
  document.getElementById("regionalScaleInput")?.addEventListener("input", syncRegionalResidualUI);

  // Filter type change → sync high-pass warning
  document.getElementById("filt-high")?.addEventListener("click", () => window.setTimeout(syncFilterUI, 0));
  document.getElementById("filt-low")?.addEventListener("click", () => window.setTimeout(syncFilterUI, 0));

  // Keep regional card in sync when checkbox is toggled directly
  document.querySelectorAll("#screen-analysis .chk").forEach((el) => {
    el.addEventListener("click", () => window.setTimeout(syncRegionalResidualUI, 0));
  });

  renderDiurnalInfo(appState.task);
  syncRegionalResidualUI();
  syncFilterUI();

  window.saveAndPreview = async () => {
    if (!appState.project || !appState.task) {
      showGlobalNotice("Complete project setup first before configuring analysis.");
      return;
    }
    // Validate IGRF date if IGRF is enabled
    const igrfEl = document.getElementById("chk-igrf");
    if (igrfEl?.classList.contains("on")) {
      const dateVal = document.getElementById("igrf-survey-date")?.value;
      if (!dateVal) {
        showGlobalNotice("IGRF removal requires a survey date. Please enter a date or disable IGRF removal.");
        return;
      }
    }
    try {
      await persistAnalysis();
    } catch (err) {
      showGlobalNotice(err.message || "Could not save analysis configuration.");
      return;
    }
    window.go?.(document.querySelector("[data-s=preview]"));
  };
}

// ── Toggle helpers exposed to inline HTML onclick ──────────────────────────

window.toggleIGRF = (el) => {
  toggleChk(el);
  const igrfOpts = document.getElementById("igrf-opts");
  if (igrfOpts) {
    igrfOpts.style.display = el.classList.contains("on") ? "block" : "none";
  }
};

window.toggleSVD = (el) => {
  toggleChk(el);
  const svdOpts = document.getElementById("svd-opts");
  if (svdOpts) {
    svdOpts.style.display = el.classList.contains("on") ? "block" : "none";
  }
};
