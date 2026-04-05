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
import {waitForAuth, signOutUser, getCurrentUser} from "./auth.js";

window.addEventListener("DOMContentLoaded", async () => {
  const user = await waitForAuth();
  if (!user) {
    window.location.replace("/login");
    return;
  }

  // Wire sign-out
  window.signOut = async () => {
    await signOutUser();
    window.location.replace("/login");
  };

  // Show user display name if element exists
  const userDisplay = document.getElementById("userDisplay");
  if (userDisplay) userDisplay.textContent = user.displayName || user.email || "";

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
      const hash = location.hash.replace("#", "");
      const saved = localStorage.getItem("gaiaCurrentScreen");
      const validScreens = ["setup", "analysis", "preview", "processing", "visualisation", "export", "project", "projects"];
      const target = (hash && validScreens.includes(hash)) ? hash : (saved && validScreens.includes(saved)) ? saved : null;
      if (target) {
        await window.go(target);
      }
    })
    .catch((error) => console.error(error));
});
