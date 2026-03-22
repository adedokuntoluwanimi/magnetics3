from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.models import ExportRequest
from backend.services.container import get_export_service

router = APIRouter(prefix="/api/exports", tags=["exports"])


@router.post("/tasks/{task_id}")
def create_export(task_id: str, payload: ExportRequest, service=Depends(get_export_service)) -> dict:
    try:
        return service.create_export(task_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
