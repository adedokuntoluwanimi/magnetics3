from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.routes.ai import router as ai_router
from backend.routes.exports import router as exports_router
from backend.routes.health import router as health_router
from backend.routes.maps import router as maps_router
from backend.routes.processing import router as processing_router
from backend.routes.projects import router as projects_router
from backend.routes.storage import router as storage_router
from backend.routes.tasks import router as tasks_router

settings = get_settings()
app = FastAPI(title="GAIA Magnetics", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(processing_router)
app.include_router(ai_router)
app.include_router(exports_router)
app.include_router(storage_router)
app.include_router(maps_router)

frontend_dir = Path(settings.frontend_dir)
app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")


@app.on_event("startup")
def startup_checks() -> None:
    from backend.services.container import get_ai_service

    get_ai_service().run_startup_checks()


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")
