from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from .common import GaiaModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuroraRequest(GaiaModel):
    project_id: str
    task_id: str
    location: str
    question: str | None = None


class AuroraResponse(GaiaModel):
    location: str
    summary: str
    highlights: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=utc_now)
