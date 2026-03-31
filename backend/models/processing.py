from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import Field

from .common import ExportStatus, GaiaModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AnalysisConfig(GaiaModel):
    corrections: list[str] = Field(default_factory=list)
    filter_type: str | None = None
    model: str
    add_ons: list[str] = Field(default_factory=list)
    run_prediction: bool = True
    missing_correction_suggestions: list[str] = Field(default_factory=list)
    fft_cutoff_low: float | None = None
    fft_cutoff_high: float | None = None
    rtp_inclination: float | None = None
    rtp_declination: float | None = None
    survey_date: datetime | None = None
    upward_continuation_height: float | None = None
    downward_continuation_height: float | None = None


class MetricSummary(GaiaModel):
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None
    point_count: int = 0
    affected_count: int = 0


class ProcessingFallbackEvent(GaiaModel):
    stage: str
    requested: str
    actual: str
    reason: str
    severity: str = "warning"
    timestamp: datetime = Field(default_factory=utc_now)


class ValidationIssue(GaiaModel):
    code: str
    severity: str
    message: str
    count: int = 0


class ValidationSummary(GaiaModel):
    status: str = "unknown"
    row_count: int = 0
    valid_row_count: int = 0
    dropped_row_count: int = 0
    coordinate_system: str | None = None
    utm_zone: int | None = None
    utm_hemisphere: str | None = None
    survey_date: datetime | None = None
    line_count: int = 0
    base_station_count: int = 0
    duplicate_timestamp_count: int = 0
    non_monotonic_line_count: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProcessingStageSummary(GaiaModel):
    name: str
    status: str
    detail: str
    metrics: MetricSummary | None = None
    warnings: list[str] = Field(default_factory=list)
    fallbacks: list[ProcessingFallbackEvent] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QAReport(GaiaModel):
    status: str = "unknown"
    warnings: list[str] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)
    validation: ValidationSummary | None = None
    fallback_events: list[ProcessingFallbackEvent] = Field(default_factory=list)
    correction_path: list[str] = Field(default_factory=list)
    crossover: dict[str, Any] = Field(default_factory=dict)
    lag: dict[str, Any] = Field(default_factory=dict)
    heading: dict[str, Any] = Field(default_factory=dict)
    model: dict[str, Any] = Field(default_factory=dict)
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    derived_layers: dict[str, Any] = Field(default_factory=dict)
    integrity: dict[str, Any] = Field(default_factory=dict)
    quality_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineStep(GaiaModel):
    name: str
    status: str
    detail: str


class PipelineRun(GaiaModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    status: str
    steps: list[PipelineStep] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    job_execution_name: str | None = None
    pubsub_message_id: str | None = None
    logs: list[dict[str, Any]] = Field(default_factory=list)
    qa_status: str | None = None
    validation_summary: ValidationSummary | None = None
    qa_report: QAReport | None = None
    stage_reports: list[ProcessingStageSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class ExportRequest(GaiaModel):
    formats: list[str]
    aurora_sections: list[str] = Field(default_factory=list)


class ExportJob(GaiaModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    task_id: str
    formats: list[str]
    status: ExportStatus = ExportStatus.queued
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    details: dict[str, Any] = Field(default_factory=dict)
