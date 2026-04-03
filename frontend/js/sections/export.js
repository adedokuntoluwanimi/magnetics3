import {createExport, fetchTask} from "../api.js";
import {renderWorkflowProgress} from "./progress.js";
import {appState, setTask} from "../state.js";
import {formatBytes} from "../shared/format.js";
const CARD_TO_FORMAT = {
  "ec-pdf": "pdf",
  "ec-pptx": "pptx",
  "ec-word": "word",
  "ec-geojson": "geojson",
  "ec-kml": "kmz",
  "ec-csv": "csv",
  "ec-gdb": "gdb",
  "ec-png": "png",
};

function getRoots() {
  return {
    screen: document.getElementById("screen-export"),
    count: document.getElementById("exCnt"),
    progress: document.getElementById("exportProg"),
    done: document.getElementById("exportDone"),
  };
}

function getSelectedFormats() {
  return Array.from(document.querySelectorAll("#screen-export .ec.on"))
    .map((card) => CARD_TO_FORMAT[card.id])
    .filter(Boolean);
}

function renderSelectionCount() {
  const formats = getSelectedFormats();
  getRoots().count.textContent = `${formats.length} format${formats.length === 1 ? "" : "s"} selected`;
}

function renderProgress(formats, artifacts = []) {
  const roots = getRoots();
  roots.progress.style.display = "block";
  const card = roots.progress.querySelector(".card");
  card.innerHTML = formats.map((format) => {
    const artifact = artifacts.find((item) => item.file_name.toLowerCase().includes(format.replace("kmz", "km")));
    return `
      <div class="eprow">
        <div class="epname">${format.toUpperCase()}</div>
        <div class="epbar"><div class="epfill" style="width:${artifact ? "100%" : "55%"};background:${artifact ? "var(--g500)" : "var(--amber)"}"></div></div>
        <div class="epsize">${artifact ? formatBytes(artifact.size_bytes) : "Building..."}</div>
        <span class="badge ${artifact ? "bg" : "bgr"}">${artifact ? "Completed" : "Running"}</span>
      </div>
    `;
  }).join("");
}

function renderDownloads(job) {
  const roots = getRoots();
  const artifacts = job?.details?.artifacts || [];
  roots.done.style.display = artifacts.length ? "block" : "none";
  roots.done.innerHTML = artifacts.length ? `
    <div class="sep">Download links</div>
    <div class="card card-g">
      <div style="display:flex;flex-direction:column;gap:12px">
        ${artifacts.map((artifact, index) => `
          <div style="${index ? "border-top:1px solid var(--g100);padding-top:11px;" : ""}display:flex;align-items:center;justify-content:space-between;gap:10px">
            <div>
              <div style="font-size:12.5px;font-weight:700;color:var(--text)">${artifact.file_name}</div>
              <div style="font-size:10.5px;color:var(--text3);margin-top:2px;font-family:'JetBrains Mono',monospace">${formatBytes(artifact.size_bytes)}  -  ${artifact.gcs_uri}</div>
            </div>
            <a class="btn btn-g btn-sm" href="${artifact.signed_url}" target="_blank" rel="noreferrer">Download</a>
          </div>
        `).join("")}
      </div>
    </div>
  ` : "";
}

export async function loadExportView() {
  renderSelectionCount();
  document.querySelectorAll("#screen-export .ec .badge.bgr").forEach((badge) => {
    if (/\d/.test(badge.textContent)) {
      badge.remove();
    }
  });
  const sizeNodes = document.querySelectorAll("#exportProg .epsize");
  sizeNodes.forEach((node) => {
    node.textContent = "—";
  });
  if (!appState.project || !appState.task) {
    getRoots().done.style.display = "none";
    getRoots().progress.style.display = "none";
    throw new Error("Run a processed task before opening Export.");
  }
  const task = await fetchTask(appState.project.id, appState.task.id);
  setTask(task);
  renderWorkflowProgress();
  const latestJob = (task.export_jobs || []).slice(-1)[0];
  if (latestJob) {
    renderProgress(latestJob.formats || [], latestJob.details?.artifacts || []);
    renderDownloads(latestJob);
  } else {
    getRoots().progress.style.display = "none";
    getRoots().done.style.display = "none";
  }
}

export async function runExport() {
  if (!appState.task) {
    throw new Error("Run processing before creating exports.");
  }
  const formats = getSelectedFormats();
  renderProgress(formats, []);
  const sections = Array.from(document.querySelectorAll("#screen-export .chk.on .chk-t")).map((node) => node.textContent.trim());
  const job = await createExport(appState.task.id, {formats, aurora_sections: sections});
  setTask({...appState.task, export_jobs: [...(appState.task.export_jobs || []), job]});
  renderWorkflowProgress();
  renderProgress(formats, job.details?.artifacts || []);
  renderDownloads(job);
}

export function initExport() {
  renderSelectionCount();
  getRoots().done.style.display = "none";
  getRoots().progress.style.display = "none";
  window.toggleEx = (card) => {
    card.classList.toggle("on");
    renderSelectionCount();
  };
  window.runExport = runExport;
}
