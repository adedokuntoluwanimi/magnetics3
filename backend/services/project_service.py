from __future__ import annotations

from datetime import datetime, timezone

from backend.models import ProjectCreate, ProjectRecord


class ProjectService:
    def __init__(self, store) -> None:
        self._store = store

    def list_projects(self) -> list[dict]:
        return self._store.list_projects()

    def create_project(self, payload: ProjectCreate) -> dict:
        project = ProjectRecord(**payload.model_dump())
        return self._store.create_project(project.model_dump(mode="json"))

    def get_project(self, project_id: str) -> dict | None:
        return self._store.get_project(project_id)

    def rename_project(self, project_id: str, name: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return self._store.update_project(project_id, {"name": name, "updated_at": now})

    def delete_project(self, project_id: str) -> None:
        self._store.delete_project(project_id)
