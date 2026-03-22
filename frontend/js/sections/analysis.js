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
  "EMAG2 comparison": "emag2",
  "Uncertainty quantification": "uncertainty",
};

const MODEL_MAP = {
  "Kriging": "kriging",
  "Machine learning": "ml",
  "Hybrid": "hybrid",
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

  const runPrediction = document.getElementById("predModelToggle")?.checked !== false;
  return {corrections, filter_type: filterType, model, add_ons: addOns, run_prediction: runPrediction};
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
export function loadAnalysis(task) {
  if (!task?.analysis_config) return;
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
    }
  });

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

  // Expose save-then-navigate function for the "Preview →" button
  window.saveAndPreview = async () => {
    if (!appState.project || !appState.task) {
      showGlobalNotice("Complete project setup first before configuring analysis.");
      return;
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
