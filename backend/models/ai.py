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
    # Conversation history: list of {role: "user"|"assistant", content: "..."}
    history: list[dict] = Field(default_factory=list)
    ui_context: dict = Field(default_factory=dict)


class AuroraResponse(GaiaModel):
    location: str
    summary: str
    highlights: list[str] = Field(default_factory=list)
    # Full conversational text (used by the chat UI)
    message: str = ""
    # Structured report data from export report generation (PDF/DOCX/PPTX only)
    report_data: dict | None = None
    generated_at: datetime = Field(default_factory=utc_now)
