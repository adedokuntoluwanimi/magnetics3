const storedSurveyColor = localStorage.getItem("gaiaSurveyColor") || "#2daa52";
const storedPredictedColor = localStorage.getItem("gaiaPredictedColor") || "#5ba8d4";
const storedBaseStationColor = localStorage.getItem("gaiaBaseStationColor") || "#e07b14";

export const appState = {
  project: null,
  task: null,
  processingRun: null,
  surveyFiles: [],
  basemapFile: null,
  headers: [],
  mapsApiKey: null,
  activeVisualisation: "Heatmap",
  activeResultLayer: "magnetic",
  stackProfiles: false,
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
  appState.task = task;
}

export function clearTask() {
  appState.task = null;
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
}

export function setActiveResultLayer(layerId) {
  appState.activeResultLayer = layerId;
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
