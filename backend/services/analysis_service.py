from __future__ import annotations

from datetime import datetime, timezone

from backend.models import AnalysisConfig


class AnalysisService:
    def __init__(self, store) -> None:
        self._store = store

    def save_analysis(self, task_id: str, payload: AnalysisConfig) -> dict:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")

        suggestions = []
        if task.get("data_state") == "corrected":
            existing = set(task.get("corrected_corrections", []))
            for recommendation in ["diurnal", "igrf"]:
                if recommendation not in existing and recommendation not in payload.corrections:
                    suggestions.append(recommendation)

        updated = payload.model_copy(update={"missing_correction_suggestions": suggestions})
        return self._store.update_task(
            task_id,
            {
                "analysis_config": updated.model_dump(mode="json"),
                "lifecycle": "configured",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
