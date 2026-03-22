from __future__ import annotations

from typing import Any

from backend.config import Settings
from backend.gcp.clients import firestore_client


class FirestoreStore:
    def __init__(self, settings: Settings) -> None:
        self._client = firestore_client(settings)
        self._projects = self._client.collection("gaia_projects")
        self._tasks = self._client.collection("gaia_tasks")
        self._runs = self._client.collection("gaia_processing_runs")
        self._exports = self._client.collection("gaia_export_jobs")

    def list_projects(self) -> list[dict[str, Any]]:
        docs = self._projects.order_by("updated_at", direction="DESCENDING").stream()
        return [doc.to_dict() for doc in docs]

    def create_project(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._projects.document(payload["id"]).set(payload)
        return payload

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        doc = self._projects.document(project_id).get()
        return doc.to_dict() if doc.exists else None

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._tasks.document(payload["id"]).set(payload)
        self._projects.document(payload["project_id"]).update({"updated_at": payload["updated_at"]})
        return payload

    def update_task(self, task_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._tasks.document(task_id).update(fields)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        doc = self._tasks.document(task_id).get()
        return doc.to_dict() if doc.exists else None

    def list_tasks(self, project_id: str) -> list[dict[str, Any]]:
        docs = self._tasks.where("project_id", "==", project_id).stream()
        items = [doc.to_dict() for doc in docs]
        return sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)

    def create_processing_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._runs.document(payload["id"]).set(payload)
        return payload

    def get_processing_run(self, run_id: str) -> dict[str, Any] | None:
        doc = self._runs.document(run_id).get()
        return doc.to_dict() if doc.exists else None

    def update_processing_run(self, run_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._runs.document(run_id).update(fields)
        return self.get_processing_run(run_id)

    def update_project(self, project_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._projects.document(project_id).update(fields)
        return self.get_project(project_id)

    def delete_project(self, project_id: str) -> None:
        tasks = self.list_tasks(project_id)
        for task in tasks:
            self._tasks.document(task["id"]).delete()
        self._projects.document(project_id).delete()

    def delete_task(self, task_id: str) -> None:
        self._tasks.document(task_id).delete()

    def create_export_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._exports.document(payload["id"]).set(payload)
        return payload

    def get_export_job(self, export_job_id: str) -> dict[str, Any] | None:
        doc = self._exports.document(export_job_id).get()
        return doc.to_dict() if doc.exists else None

    def update_export_job(self, export_job_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        self._exports.document(export_job_id).update(fields)
        return self.get_export_job(export_job_id)
