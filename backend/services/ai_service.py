from __future__ import annotations

from statistics import mean

from backend.models import AuroraResponse


class AIService:
    def __init__(self, store, vertex_client) -> None:
        self._store = store
        self._vertex = vertex_client

    def generate_preview(self, project_id: str, task_id: str) -> AuroraResponse:
        return self.generate_response(project_id, task_id, location="preview")

    def generate_response(
        self,
        project_id: str,
        task_id: str,
        *,
        location: str,
        question: str | None = None,
    ) -> AuroraResponse:
        project = self._store.get_project(project_id)
        task = self._store.get_task(task_id)
        if not project or not task:
            raise ValueError("Project or task not found.")

        system_prompt = (
            "You are Aurora, a senior geophysical magnetics analyst. "
            "Ground your response in the provided project context, survey configuration, "
            "and magnetic workflow choices. Be practical, concise, and domain aware."
        )
        outputs = task.get("results", {}).get("data", {})
        user_prompt = (
            f"Project context:\n{project['context']}\n\n"
            f"Task description:\n{task['description']}\n\n"
            f"Task configuration:\n{task}\n\n"
            f"Available outputs:\n{outputs}\n\n"
            f"Location in app: {location}\n"
            f"User question: {question or 'Provide the most helpful contextual guidance for this screen.'}\n\n"
            "Return a short assessment with likely outputs or interpretation, key risks, and one "
            "operational recommendation. Use bullet-like short lines."
        )
        try:
            text = self._vertex.generate(system_prompt=system_prompt, user_prompt=user_prompt)
        except Exception:
            text = self._fallback_text(project, task, outputs, location, question)
        lines = [line.strip("- ").strip() for line in text.splitlines() if line.strip()]
        summary = lines[0] if lines else text
        highlights = lines[1:4] if len(lines) > 1 else []
        return AuroraResponse(location=location, summary=summary, highlights=highlights)

    def _fallback_text(self, project: dict, task: dict, outputs: dict, location: str, question: str | None) -> str:
        stats = outputs.get("stats") or {}
        point_count = stats.get("point_count") or task.get("dataset_profile", {}).get("total_rows") or 0
        magnetic_mean = stats.get("mean")
        magnetic_range = None
        if stats.get("min") is not None and stats.get("max") is not None:
            magnetic_range = float(stats["max"]) - float(stats["min"])
        corrections = ", ".join(task.get("analysis_config", {}).get("corrections") or []) or "no explicit corrections"
        add_ons = ", ".join(task.get("analysis_config", {}).get("add_ons") or []) or "no add-ons"
        project_context = project.get("context", "").strip()
        project_sentence = project_context.split(".")[0].strip() if project_context else "Project context is available."
        lines = [
            f"{project_sentence} This {location} assessment is grounded in {point_count} magnetic observations and a {task.get('analysis_config', {}).get('model', 'configured')} workflow.",
            f"Configured corrections are {corrections}; selected add-ons are {add_ons}.",
        ]
        if magnetic_mean is not None:
            lines.append(f"Processed magnetic response centres around {float(magnetic_mean):.2f} nT with a working spread of about {float(magnetic_range or 0):.2f} nT.")
        if location == "preview":
            lines.append("Watch for sparse edge control near survey boundaries because interpolation uncertainty typically rises there.")
        elif location == "visualisation":
            lines.append("Prioritise coherent amplitude highs, strong analytic-signal ridges, and consistent spatial clustering before inferring structure.")
        elif location == "export":
            lines.append("Keep the delivery focused on the chosen model assumptions, uncertainty surface, and any correction limitations so the interpretation remains auditable.")
        if question:
            lines.append(f"Question focus: {question}")
        return "\n".join(lines)
