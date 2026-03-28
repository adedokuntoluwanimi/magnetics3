from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.models import AuroraRequest
from backend.services.container import get_ai_service

router = APIRouter(prefix="/api/ai", tags=["ai"])


@router.post("/preview")
def preview_ai(payload: AuroraRequest, service=Depends(get_ai_service)) -> dict:
    try:
        return service.generate_preview(payload.project_id, payload.task_id).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/respond")
def respond_ai(payload: AuroraRequest, service=Depends(get_ai_service)) -> dict:
    try:
        return service.generate_response(
            payload.project_id,
            payload.task_id,
            location=payload.location,
            question=payload.question,
            history=payload.history or [],
        ).model_dump(mode="json")
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
