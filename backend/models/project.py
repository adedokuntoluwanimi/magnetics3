from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import Field

from .common import DataState, GaiaModel, MapBounds, Platform, ProcessingMode, Scenario, TaskLifecycle


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ColumnMapping(GaiaModel):
    latitude: str
    longitude: str
    magnetic_field: str
    # Time columns (raw data diurnal correction)
    hour: str | None = None
    minute: str | None = None
    second: str | None = None
    # Coordinate system
    coordinate_system: str = "wgs84"  # "wgs84" or "utm"
    utm_zone: int | None = None
    utm_hemisphere: str | None = None  # "N" or "S"


class ArtifactRecord(GaiaModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    file_name: str
    content_type: str
    bucket: str
    object_name: str
    gcs_uri: str
    signed_url: str | None = None
    kind: str
    size_bytes: int
    created_at: datetime = Field(default_factory=utc_now)


class DatasetProfile(GaiaModel):
    headers: list[str]
    total_rows: int
    files_count: int
    column_mapping: ColumnMapping
    preview_points: list[dict[str, float]] = Field(default_factory=list)
    bounds: MapBounds = Field(default_factory=MapBounds)
    magnetic_min: float | None = None
    magnetic_max: float | None = None
    magnetic_mean: float | None = None


class ProjectCreate(GaiaModel):
    name: str = Field(min_length=3, max_length=160)
    context: str = Field(min_length=10, max_length=12000)


class ProjectRecord(ProjectCreate):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class TaskCreatePayload(GaiaModel):
    name: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=10, max_length=4000)
    platform: Platform
    data_state: DataState
    scenario: Scenario
    processing_mode: ProcessingMode
    station_spacing: float | None = None
    station_spacing_unit: str | None = None
    corrected_corrections: list[str] = Field(default_factory=list)
    column_mapping: ColumnMapping
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskSummary(GaiaModel):
    id: str
    project_id: str
    name: str
    lifecycle: TaskLifecycle
    updated_at: datetime


class TaskRecord(TaskCreatePayload):
    id: str = Field(default_factory=lambda: uuid4().hex)
    project_id: str
    lifecycle: TaskLifecycle = TaskLifecycle.draft
    dataset_profile: DatasetProfile
    survey_files: list[ArtifactRecord]
    basemap_file: ArtifactRecord | None = None
    analysis_config: dict[str, Any] = Field(default_factory=dict)
    processing_run_id: str | None = None
    export_jobs: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
