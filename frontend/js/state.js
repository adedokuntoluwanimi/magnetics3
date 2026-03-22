export const appState = {
  project: null,
  task: null,
  processingRun: null,
  surveyFiles: [],
  basemapFile: null,
  headers: [],
  mapsApiKey: null,
  activeVisualisation: "Heatmap",
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
