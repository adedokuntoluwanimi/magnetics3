import {fetchDependencyStatus} from "../api.js";
import {showGlobalNotice} from "../shared/notice.js";

function ensureStatusPanel() {
  let panel = document.getElementById("serviceStatusPanel");
  if (panel) {
    return panel;
  }
  panel = document.createElement("div");
  panel.id = "serviceStatusPanel";
  panel.className = "hsec";
  const homeScroll = document.querySelector("#screen-home .home-scroll");
  homeScroll.insertBefore(panel, homeScroll.children[1]);
  return panel;
}

export async function loadHomeStatus() {
  const panel = ensureStatusPanel();
  try {
    const payload = await fetchDependencyStatus();
    const entries = Object.entries(payload.dependencies || {});
    panel.innerHTML = `
      <div class="hslabel">System</div>
      <div class="hstitle">Live service status</div>
      <div class="cap-grid">
        ${entries.map(([name, state]) => `
          <div class="cap-card">
            <div class="cap-t">${name.charAt(0).toUpperCase() + name.slice(1)}</div>
            <div class="cap-d">${state.ok ? "Ready" : "Attention needed"} · ${state.message}</div>
          </div>
        `).join("")}
      </div>
    `;
  } catch (error) {
    panel.innerHTML = `
      <div class="hslabel">System</div>
      <div class="hstitle">Live service status</div>
      <div class="cap-card">
        <div class="cap-t">Status unavailable</div>
        <div class="cap-d">Unable to load dependency health right now.</div>
      </div>
    `;
    showGlobalNotice(error.message || "Unable to load service status.");
  }
}
