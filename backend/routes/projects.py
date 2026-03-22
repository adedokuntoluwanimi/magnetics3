from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.models import ProjectCreate
from backend.services.container import get_project_service

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectPatch(BaseModel):
    name: str | None = None
    context: str | None = None


@router.get("")
def list_projects(service=Depends(get_project_service)) -> list[dict]:
    return service.list_projects()


@router.post("")
def create_project(payload: ProjectCreate, service=Depends(get_project_service)) -> dict:
    return service.create_project(payload)


@router.get("/{project_id}")
def get_project(project_id: str, service=Depends(get_project_service)) -> dict:
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


@router.patch("/{project_id}")
def patch_project(project_id: str, payload: ProjectPatch, service=Depends(get_project_service)) -> dict:
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    fields: dict = {}
    if payload.name is not None:
        name = payload.name.strip()
        if len(name) < 3:
            raise HTTPException(status_code=422, detail="Project name must be at least 3 characters.")
        fields["name"] = name
    if payload.context is not None:
        ctx = payload.context.strip()
        if len(ctx) < 10:
            raise HTTPException(status_code=422, detail="Context must be at least 10 characters.")
        fields["context"] = ctx
    if not fields:
        return project
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    return service._store.update_project(project_id, fields)


@router.delete("/{project_id}")
def delete_project(project_id: str, service=Depends(get_project_service)) -> dict:
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    service.delete_project(project_id)
    return {"deleted": True}
