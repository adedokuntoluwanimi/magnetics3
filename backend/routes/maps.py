from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.services.container import get_maps_service

router = APIRouter(prefix="/api/maps", tags=["maps"])


@router.get("/key")
def get_maps_key(service=Depends(get_maps_service)) -> dict:
    return service.get_api_key()
