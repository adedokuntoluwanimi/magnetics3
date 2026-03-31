const storedSurveyColor = localStorage.getItem("gaiaSurveyColor") || "#2daa52";
const storedPredictedColor = localStorage.getItem("gaiaPredictedColor") || "#5ba8d4";
const storedBaseStationColor = localStorage.getItem("gaiaBaseStationColor") || "#e07b14";

const _VALID_VIS = new Set(["Surface", "3D", "Map", "Line Profiles"]);
const _storedVis = localStorage.getItem("gaiaActiveVis") || "Surface";
const _storedLayer = localStorage.getItem("gaiaActiveLayer") || "magnetic";
const _storedTraverse = localStorage.getItem("gaiaActiveTraverseFilter") || "all";

export const appState = {
  project: null,
  task: null,
  taskResults: null,
  processingRun: null,
  surveyFiles: [],
  basemapFile: null,
  headers: [],
  mapsApiKey: null,
  activeVisualisation: _VALID_VIS.has(_storedVis) ? _storedVis : "Surface",
  activeResultLayer: _storedLayer,
  stackProfiles: false,
  activeTraverseFilter: _storedTraverse,
  mapColors: {
    survey: storedSurveyColor,
    predicted: storedPredictedColor,
    baseStation: storedBaseStationColor,
  },
};

export function setProject(project) {
  appState.project = project;
}

export function clearProject() {
  appState.project = null;
}

export function setTask(task) {
  if (appState.task?.id !== task?.id) {
    appState.taskResults = null;
  }
  appState.task = task;
}

export function clearTask() {
  appState.task = null;
  appState.taskResults = null;
}

export function setTaskResults(results) {
  appState.taskResults = results;
}

export function clearTaskResults() {
  appState.taskResults = null;
}

export function setProcessingRun(run) {
  appState.processingRun = run;
}

export function clearProcessingRun() {
  appState.processingRun = null;
}

export function setSurveyFiles(files) {
  appState.surveyFiles = files;
}

export function setBasemapFile(file) {
  appState.basemapFile = file;
}

export function setHeaders(headers) {
  appState.headers = headers;
}

export function setMapsApiKey(apiKey) {
  appState.mapsApiKey = apiKey;
}

export function setActiveVisualisation(mode) {
  appState.activeVisualisation = mode;
  localStorage.setItem("gaiaActiveVis", mode);
}

export function setActiveResultLayer(layerId) {
  appState.activeResultLayer = layerId;
  localStorage.setItem("gaiaActiveLayer", layerId);
}

export function setStackProfiles(value) {
  appState.stackProfiles = Boolean(value);
}

export function setSurveyMarkerColor(color) {
  appState.mapColors.survey = color;
  localStorage.setItem("gaiaSurveyColor", color);
}

export function setPredictedMarkerColor(color) {
  appState.mapColors.predicted = color;
  localStorage.setItem("gaiaPredictedColor", color);
}

export function setBaseStationMarkerColor(color) {
  appState.mapColors.baseStation = color;
  localStorage.setItem("gaiaBaseStationColor", color);
}
export function setActiveTraverseFilter(value) {
  appState.activeTraverseFilter = value || "all";
  localStorage.setItem("gaiaActiveTraverseFilter", appState.activeTraverseFilter);
}
