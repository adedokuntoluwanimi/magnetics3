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
