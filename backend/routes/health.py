from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.config import get_settings
from backend.services.container import get_maps_service, get_store

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.service_name,
        "infraProjectId": settings.infra_project_id,
        "aiProjectId": settings.ai_project_id,
        "region": settings.region,
    }


@router.get("/health/dependencies")
def dependency_health(store=Depends(get_store), maps_service=Depends(get_maps_service)) -> dict:
    settings = get_settings()
    projects_ok = True
    maps_ok = True
    maps_message = "configured"
    try:
        _ = store.list_projects()
    except Exception:
        projects_ok = False
    try:
        maps_key = maps_service.get_api_key()["apiKey"]
        maps_ok = bool(maps_key)
        maps_message = "configured" if maps_ok else "missing key"
    except Exception as exc:
        maps_ok = False
        maps_message = str(exc)

    return {
        "status": "ok" if projects_ok and maps_ok else "degraded",
        "service": settings.service_name,
        "dependencies": {
            "firestore": {
                "ok": projects_ok,
                "message": "reachable" if projects_ok else "unavailable",
            },
            "storage": {
                "ok": settings.ready_for_storage,
                "message": "configured" if settings.ready_for_storage else "missing bucket configuration",
            },
            "processing": {
                "ok": settings.ready_for_processing,
                "message": "configured" if settings.ready_for_processing else "missing processing configuration",
            },
            "exports": {
                "ok": settings.ready_for_exports,
                "message": "configured" if settings.ready_for_exports else "missing export configuration",
            },
            "aurora": {
                "ok": settings.ready_for_ai,
                "message": settings.aurora_model or "missing model configuration",
            },
            "maps": {
                "ok": maps_ok,
                "message": maps_message,
            },
        },
    }
