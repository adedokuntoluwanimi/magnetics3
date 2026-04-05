from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.auth import verify_token
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

# Health routes are public (used by Cloud Run health checks)
app.include_router(health_router)

# All other API routes require a valid Firebase ID token
_auth = [Depends(verify_token)]
app.include_router(projects_router, dependencies=_auth)
app.include_router(tasks_router, dependencies=_auth)
app.include_router(processing_router, dependencies=_auth)
app.include_router(ai_router, dependencies=_auth)
app.include_router(exports_router, dependencies=_auth)
app.include_router(storage_router, dependencies=_auth)
app.include_router(maps_router, dependencies=_auth)

frontend_dir = Path(settings.frontend_dir)
app.mount("/frontend", StaticFiles(directory=frontend_dir), name="frontend")


@app.on_event("startup")
def startup_checks() -> None:
    from backend.auth import _get_firebase_app
    from backend.services.container import get_ai_service

    _get_firebase_app()
    get_ai_service().run_startup_checks()


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/login", include_in_schema=False)
def login_page() -> FileResponse:
    return FileResponse(frontend_dir / "login.html")
