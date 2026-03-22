from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict


class GaiaModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)


class Platform(str, Enum):
    ground = "ground"
    airborne = "airborne"


class DataState(str, Enum):
    raw = "raw"
    corrected = "corrected"


class Scenario(str, Enum):
    explicit = "explicit"
    sparse = "sparse"


class ProcessingMode(str, Enum):
    single = "single"
    multi = "multi"


class TaskLifecycle(str, Enum):
    draft = "draft"
    configured = "configured"
    preview_ready = "preview_ready"
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class ExportStatus(str, Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"


class MapBounds(GaiaModel):
    min_x: float | None = None
    min_y: float | None = None
    max_x: float | None = None
    max_y: float | None = None


Metadata = dict[str, Any]
