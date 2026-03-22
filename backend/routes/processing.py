from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from backend.logging_utils import log_event
from backend.services.container import get_jobs_backend, get_processing_service

router = APIRouter(prefix="/api/processing", tags=["processing"])


@router.post("/tasks/{task_id}/runs")
def start_processing(
    task_id: str,
    background_tasks: BackgroundTasks,
    service=Depends(get_processing_service),
    jobs=Depends(get_jobs_backend),
) -> dict:
    try:
        run = service.start_run(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Attempt to dispatch via Cloud Run Job (fire-and-forget).
    # Fall back to an in-process background thread if the job cannot be reached
    # (e.g. during local development or before the job has been created).
    try:
        jobs.run_processing_job({"GAIA_RUN_ID": run["id"]})
        log_event("INFO", "Processing job dispatched", action="processing.dispatch", run_id=run["id"], task_id=task_id)
    except Exception as exc:
        log_event(
            "WARNING",
            "Cloud Run Job dispatch failed — falling back to background thread",
            action="processing.dispatch_fallback",
            run_id=run["id"],
            task_id=task_id,
            error=str(exc),
        )
        background_tasks.add_task(service.execute_run, run["id"])

    return run


@router.get("/runs/{run_id}")
def get_processing_run(run_id: str, service=Depends(get_processing_service)) -> dict:
    run = service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Processing run not found.")
    return run
