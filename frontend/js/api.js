async function parseResponse(response) {
  if (response.ok) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      return response.json();
    }
    return response.text();
  }

  let detail = `Request failed with status ${response.status}`;
  try {
    const payload = await response.json();
    if (Array.isArray(payload.detail)) {
      detail = payload.detail.map((e) => e.msg || String(e)).join("; ");
    } else {
      detail = payload.detail || detail;
    }
  } catch (_error) {
    detail = (await response.text()) || detail;
  }
  throw new Error(detail);
}

async function request(path, options = {}) {
  const response = await fetch(path, options);
  return parseResponse(response);
}

export function createProject(payload) {
  return request("/api/projects", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}

export function fetchDependencyStatus() {
  return request("/api/health/dependencies");
}

export function listProjects() {
  return request("/api/projects");
}

export function listTasks(projectId) {
  return request(`/api/projects/${projectId}/tasks`);
}

export function createTask(projectId, formData) {
  return request(`/api/projects/${projectId}/tasks`, {
    method: "POST",
    body: formData,
  });
}

export function saveAnalysis(projectId, taskId, payload) {
  return request(`/api/projects/${projectId}/tasks/${taskId}/analysis`, {
    method: "PUT",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}

export function fetchPreview(projectId, taskId) {
  return request(`/api/projects/${projectId}/tasks/${taskId}/preview`);
}

export function fetchTask(projectId, taskId) {
  return request(`/api/projects/${projectId}/tasks/${taskId}`);
}

export function startProcessing(taskId) {
  return request(`/api/processing/tasks/${taskId}/runs`, {method: "POST"});
}

export function fetchProcessingRun(runId) {
  return request(`/api/processing/runs/${runId}`);
}

export function createExport(taskId, payload) {
  return request(`/api/exports/tasks/${taskId}`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}

export function askAurora(payload) {
  return request("/api/ai/respond", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}

export function fetchMapsKey() {
  return request("/api/maps/key");
}

export function renameProject(projectId, name, context) {
  const body = {};
  if (name !== undefined) body.name = name;
  if (context !== undefined) body.context = context;
  return request(`/api/projects/${projectId}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(body),
  });
}

export function deleteProject(projectId) {
  return request(`/api/projects/${projectId}`, {method: "DELETE"});
}

export function renameTask(projectId, taskId, name) {
  return request(`/api/projects/${projectId}/tasks/${taskId}`, {
    method: "PATCH",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name}),
  });
}

export function deleteTask(projectId, taskId) {
  return request(`/api/projects/${projectId}/tasks/${taskId}`, {method: "DELETE"});
}
