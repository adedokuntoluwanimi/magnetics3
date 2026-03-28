from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.models import AnalysisConfig, ColumnMapping, TaskCreatePayload
from backend.models.common import DataState, Platform, ProcessingMode, Scenario
from backend.services.container import get_analysis_service, get_preview_service, get_task_service, get_storage_backend


class TaskRename(BaseModel):
    name: str

router = APIRouter(prefix="/api/projects/{project_id}/tasks", tags=["tasks"])


def _build_task_payload(
    *,
    name: str,
    description: str,
    platform: str,
    data_state: str,
    scenario: str,
    processing_mode: str,
    station_spacing: float | None,
    station_spacing_unit: str | None,
    line_interpolation: str | None,
    grid_rows: int | None,
    grid_cols: int | None,
    corrected_corrections: str,
    column_mapping: str,
    metadata: str,
) -> TaskCreatePayload:
    line_interp_val = True
    if line_interpolation is not None:
        line_interp_val = str(line_interpolation).lower() in {"1", "true", "yes", "y"}
    return TaskCreatePayload(
        name=name,
        description=description,
        platform=Platform(platform),
        data_state=DataState(data_state),
        scenario=Scenario(scenario),
        processing_mode=ProcessingMode(processing_mode),
        station_spacing=station_spacing,
        station_spacing_unit=station_spacing_unit,
        line_interpolation=line_interp_val,
        grid_rows=grid_rows,
        grid_cols=grid_cols,
        corrected_corrections=json.loads(corrected_corrections or "[]"),
        column_mapping=ColumnMapping(**json.loads(column_mapping)),
        metadata=json.loads(metadata or "{}"),
    )


@router.get("")
def list_tasks(project_id: str, service=Depends(get_task_service)) -> list[dict]:
    return service.list_tasks(project_id)


@router.post("")
async def create_task(
    project_id: str,
    name: str = Form(...),
    description: str = Form(...),
    platform: str = Form(...),
    data_state: str = Form(...),
    scenario: str = Form(...),
    processing_mode: str = Form(...),
    station_spacing: float | None = Form(None),
    station_spacing_unit: str | None = Form(None),
    line_interpolation: str | None = Form(None),
    grid_rows: int | None = Form(None),
    grid_cols: int | None = Form(None),
    corrected_corrections: str = Form("[]"),
    column_mapping: str = Form(...),
    metadata: str = Form("{}"),
    survey_files: list[UploadFile] = File(...),
    basemap_file: UploadFile | None = File(None),
    service=Depends(get_task_service),
) -> dict:
    try:
        payload = _build_task_payload(
            name=name,
            description=description,
            platform=platform,
            data_state=data_state,
            scenario=scenario,
            processing_mode=processing_mode,
            station_spacing=station_spacing,
            station_spacing_unit=station_spacing_unit,
            line_interpolation=line_interpolation,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            corrected_corrections=corrected_corrections,
            column_mapping=column_mapping,
            metadata=metadata,
        )
        survey_payloads = [
            (upload.filename, upload.content_type or "text/csv", await upload.read())
            for upload in survey_files
        ]
        basemap_payload = None
        if basemap_file and basemap_file.filename:
            basemap_payload = (
                basemap_file.filename,
                basemap_file.content_type or "application/octet-stream",
                await basemap_file.read(),
            )
        return service.create_task(
            project_id=project_id,
            payload=payload,
            survey_files=survey_payloads,
            basemap_file=basemap_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{task_id}")
async def update_task(
    project_id: str,
    task_id: str,
    name: str = Form(...),
    description: str = Form(...),
    platform: str = Form(...),
    data_state: str = Form(...),
    scenario: str = Form(...),
    processing_mode: str = Form(...),
    station_spacing: float | None = Form(None),
    station_spacing_unit: str | None = Form(None),
    line_interpolation: str | None = Form(None),
    grid_rows: int | None = Form(None),
    grid_cols: int | None = Form(None),
    corrected_corrections: str = Form("[]"),
    column_mapping: str = Form(...),
    metadata: str = Form("{}"),
    survey_files: list[UploadFile] | None = File(None),
    basemap_file: UploadFile | None = File(None),
    service=Depends(get_task_service),
) -> dict:
    task = service.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    try:
        payload = _build_task_payload(
            name=name,
            description=description,
            platform=platform,
            data_state=data_state,
            scenario=scenario,
            processing_mode=processing_mode,
            station_spacing=station_spacing,
            station_spacing_unit=station_spacing_unit,
            line_interpolation=line_interpolation,
            grid_rows=grid_rows,
            grid_cols=grid_cols,
            corrected_corrections=corrected_corrections,
            column_mapping=column_mapping,
            metadata=metadata,
        )
        survey_payloads = [
            (upload.filename, upload.content_type or "text/csv", await upload.read())
            for upload in (survey_files or [])
            if upload and upload.filename
        ]
        basemap_payload = None
        if basemap_file and basemap_file.filename:
            basemap_payload = (
                basemap_file.filename,
                basemap_file.content_type or "application/octet-stream",
                await basemap_file.read(),
            )
        return service.update_task(
            task_id=task_id,
            payload=payload,
            survey_files=survey_payloads or None,
            basemap_file=basemap_payload,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{task_id}")
def get_task(project_id: str, task_id: str, service=Depends(get_task_service)) -> dict:
    task = service.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@router.put("/{task_id}/analysis")
def save_analysis(
    project_id: str,
    task_id: str,
    payload: AnalysisConfig,
    service=Depends(get_analysis_service),
) -> dict:
    try:
        return service.save_analysis(task_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{task_id}")
def rename_task(project_id: str, task_id: str, payload: TaskRename, service=Depends(get_task_service)) -> dict:
    task = service.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    name = payload.name.strip()
    if len(name) < 3:
        raise HTTPException(status_code=422, detail="Task name must be at least 3 characters.")
    return service.rename_task(task_id, name)


@router.delete("/{task_id}")
def delete_task(project_id: str, task_id: str, service=Depends(get_task_service)) -> dict:
    task = service.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    service.delete_task(task_id)
    return {"deleted": True}


@router.get("/{task_id}/preview")
def get_preview(project_id: str, task_id: str, service=Depends(get_preview_service)) -> dict:
    try:
        return service.build_preview(project_id, task_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{task_id}/results")
def get_task_results(
    project_id: str,
    task_id: str,
    service=Depends(get_task_service),
    storage=Depends(get_storage_backend),
) -> dict:
    task = service.get_task(task_id)
    if not task or task["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="Task not found.")
    artifacts = (task.get("results") or {}).get("artifacts") or []
    results_artifact = next(
        (a for a in artifacts if a.get("file_name") == "results.json"), None
    )
    if not results_artifact:
        raise HTTPException(status_code=404, detail="Results not available yet. Run processing first.")
    data = storage.download_bytes(results_artifact["bucket"], results_artifact["object_name"])
    return json.loads(data)
