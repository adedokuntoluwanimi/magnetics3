import {initAnalysis} from "./sections/analysis.js";
import {initExport, loadExportView} from "./sections/export.js";
import {initNavigation} from "./sections/navigation.js";
import {loadPreview} from "./sections/preview.js";
import {initProcessing, loadProcessingView} from "./sections/processing.js";
import {initWorkflowProgress, renderWorkflowProgress} from "./sections/progress.js";
import {initSidebar, refreshSidebar} from "./sections/sidebar.js";
import {initSetup} from "./sections/setup.js";
import {loadVisualisation, initVisualisation} from "./sections/visualisation.js";
import {appState} from "./state.js";

window.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initSidebar();
  initSetup();
  initAnalysis();
  initProcessing();
  initVisualisation();
  initExport();
  initWorkflowProgress();
  refreshSidebar()
    .then(async () => {
      if (document.querySelector("[data-s=preview]")?.classList.contains("active")) {
        await loadPreview();
      }
      if (appState.task) {
        await loadProcessingView();
        renderWorkflowProgress();
      }
      if (appState.task?.results?.data) {
        await loadVisualisation();
        await loadExportView();
      }
    })
    .catch((error) => console.error(error));
});
