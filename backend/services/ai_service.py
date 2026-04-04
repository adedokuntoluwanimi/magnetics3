from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from typing import Any

from backend.models import AuroraResponse

logger = logging.getLogger(__name__)

_EXPORT_SYSTEM_PROMPT = """You are a senior geophysicist, technical report writer, and presentation designer.
Generate client-ready DOCX, PDF, and PPTX deliverables from processed magnetic survey results.
Use only the provided project data, processed outputs, QA, configuration, and uploaded-file summaries.

Design intent:
- the report and slides must feel premium, deliberate, and presentation-ready
- avoid plain filler text and generic section names where a stronger title is justified
- write for a professional client audience with crisp hierarchy and compelling visual callouts
- slide content should feel like a real consulting deck: clear storyline, punchy bullets, useful speaker notes
- every visual_ref should correspond to a meaningful figure or layer that can be shown prominently

Content rules:
- stay grounded in the actual outputs and metadata
- do not invent layers, corrections, or findings
- if prediction was off, say so clearly
- if QA or fallbacks matter, surface them clearly but professionally

Return only valid JSON in the required schema. Do not add markdown fences or prose outside the JSON."""


class AIService:
    _MAX_REF_CHARS = 6000
    _MAX_CHAT_CONTEXT_CHARS = 6000
    _MAX_UPLOAD_SNIPPET_CHARS = 2000

    def __init__(self, store, chat_client, export_client, storage_backend=None) -> None:
        self._store = store
        self._chat_client = chat_client
        self._export_client = export_client
        self._storage = storage_backend

    def generate_preview(self, project_id: str, task_id: str) -> AuroraResponse:
        return self.generate_response(project_id, task_id, location="preview")

    def generate_response(
        self,
        project_id: str,
        task_id: str,
        *,
        location: str,
        question: str | None = None,
        history: list[dict] | None = None,
        extra_results: dict | None = None,
    ) -> AuroraResponse:
        project = self._store.get_project(project_id)
        task = self._store.get_task(task_id)
        if not project or not task:
            raise ValueError("Project or task not found.")

        outputs = extra_results or self._load_full_results(task) or task.get("results", {}).get("data", {})
        stats = outputs.get("stats") or {}
        config = task.get("analysis_config") or {}
        system_prompt = self._build_chat_system_prompt(project, task, config, outputs, stats, location)

        messages: list[dict[str, str]] = []
        for msg in (history or [])[-20:]:
            role = msg.get("role", "user")
            content = (msg.get("content") or "").strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": question or "Provide the most helpful guidance for this screen."})

        try:
            text = self._chat_client.generate(system_prompt=system_prompt, messages=messages, max_tokens=1200)
        except Exception as exc:
            logger.exception("Aurora chat generation failed", extra={"location": location, "task_id": task_id, "project_id": project_id, "error": str(exc)})
            try:
                compact_prompt = self._build_compact_chat_system_prompt(project, task, config, outputs, stats, location)
                text = self._chat_client.generate(system_prompt=compact_prompt, messages=messages[-6:], max_tokens=800)
            except Exception:
                text = self._fallback_text(project, task, outputs, location, question)
        return self._parse_chat_response(text, location)

    def generate_export_report(self, project_id: str, task_id: str, full_results: dict) -> AuroraResponse:
        project = self._store.get_project(project_id)
        task = self._store.get_task(task_id)
        if not project or not task:
            raise ValueError("Project or task not found.")

        config = task.get("analysis_config") or {}
        stats = full_results.get("stats") or {}
        upload_context = self._collect_uploaded_file_context(task)
        user_prompt = self._build_export_data_prompt(project, task, config, full_results, stats, upload_context)

        try:
            text = self._export_client.generate(
                system_prompt=_EXPORT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=4000,
            )
            report_data = self._parse_export_json(text)
        except Exception as exc:
            logger.exception("Aurora export report generation failed", extra={"task_id": task_id, "project_id": project_id, "error": str(exc)})
            report_data = None

        if not report_data:
            try:
                compact_prompt = self._build_export_data_prompt(
                    project,
                    task,
                    config,
                    full_results,
                    stats,
                    (upload_context or "")[:1200],
                )
                text = self._export_client.generate(
                    system_prompt=_EXPORT_SYSTEM_PROMPT,
                    user_prompt=compact_prompt,
                    max_tokens=2500,
                )
                report_data = self._parse_export_json(text)
            except Exception as exc:
                logger.exception("Aurora export retry failed", extra={"task_id": task_id, "project_id": project_id, "error": str(exc)})
                report_data = None

        if report_data:
            report = report_data.get("report", {})
            highlights = []
            for layer in (report.get("results_interpretation") or [])[:5]:
                obs = layer.get("observations", "")
                if obs:
                    highlights.append(f"{layer.get('layer', 'Layer')}: {obs[:120]}")
            recommendations = report.get("recommendations", "")
            if recommendations:
                highlights.append(f"Recommendation: {recommendations[:200]}")
            summary = report_data.get("executive_summary", "")
            return AuroraResponse(
                location="export",
                summary=summary,
                highlights=highlights,
                message=summary,
                report_data=report_data,
            )

        fallback_report = self._build_fallback_report_data(project, task, config, full_results, stats, upload_context)
        fallback_summary = fallback_report.get("executive_summary", "")
        return AuroraResponse(
            location="export",
            summary=fallback_summary,
            highlights=fallback_report.get("report", {}).get("recommendations", "").splitlines()[:4],
            message=fallback_summary,
            report_data=fallback_report,
        )

    def _parse_chat_response(self, text: str, location: str) -> AuroraResponse:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        summary = lines[0] if lines else text
        highlights = []
        for line in lines[1:]:
            clean = re.sub(r"^[-*•]+\s*", "", line).strip()
            if clean and len(clean) > 10:
                highlights.append(clean)
                if len(highlights) >= 6:
                    break
        return AuroraResponse(location=location, summary=summary, highlights=highlights, message=text)

    def _parse_export_json(self, text: str) -> dict | None:
        fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        json_str = fence_match.group(1) if fence_match else text.strip()
        brace_match = re.search(r"\{[\s\S]+\}", json_str)
        if brace_match:
            json_str = brace_match.group(0)
        try:
            data = json.loads(json_str)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        if "report" not in data and "executive_summary" not in data:
            return None
        return data

    def _build_chat_system_prompt(
        self,
        project: dict,
        task: dict,
        config: dict,
        outputs: dict,
        stats: dict,
        location: str,
    ) -> str:
        corrections = ", ".join(config.get("corrections") or []) or "none"
        add_ons = ", ".join(config.get("add_ons") or []) or "none"
        scenario = task.get("scenario") or "off"
        model = config.get("model") or "not specified"
        prompt = (
            "You are Aurora AI, a practical magnetic-survey assistant. "
            "Keep answers direct, plain-language, and grounded in the actual task data. "
            "Do not add geology interpretation unless the user explicitly asks.\n\n"
            "--- PROJECT CONTEXT ---\n"
            f"Project: {project.get('name', '')} - {project.get('context', '')}\n"
            f"Task: {task.get('name', '')} - {task.get('description', '')}\n"
            f"Platform: {task.get('platform', 'not specified')} | Scenario: {scenario} | Model: {model}\n"
            f"Corrections: {corrections}\n"
            f"Add-ons: {add_ons}\n"
        )
        if stats:
            prompt += (
                f"Magnetic stats: mean={stats.get('mean', 0):.2f} nT, std={stats.get('std', 0):.2f} nT, "
                f"min={stats.get('min', 0):.2f}, max={stats.get('max', 0):.2f}, "
                f"points={stats.get('point_count', 0)}, anomalies={stats.get('anomaly_count', 0)}\n"
            )
        validation = outputs.get("validation_summary") or {}
        base_station_count = self._resolved_base_station_count(outputs)
        if validation:
            prompt += (
                f"Validation status: {validation.get('status', 'unknown')}; "
                f"rows={validation.get('row_count', 0)}; base-station readings recognised={base_station_count}; warnings={len(validation.get('warnings') or [])}\n"
            )
        qa_report = outputs.get("qa_report") or {}
        if qa_report:
            prompt += (
                f"QA status: {qa_report.get('status', 'unknown')}; "
                f"quality={qa_report.get('quality_score', 'n/a')}; "
                f"fallback events={len(qa_report.get('fallback_events') or [])}\n"
            )
        correction_path = qa_report.get("correction_path") or []
        if correction_path:
            prompt += "Applied correction path: " + " | ".join(correction_path[:8]) + "\n"
        layers = self._list_available_layers(outputs)
        if layers:
            prompt += "Available layers: " + ", ".join(layers) + "\n"
        sample_points = (outputs.get("points") or [])[:20]
        if sample_points:
            prompt += "Sample stations (lat, lon, magnetic nT):\n"
            for point in sample_points:
                latitude = self._to_float(point.get("latitude"))
                longitude = self._to_float(point.get("longitude"))
                magnetic = self._point_value_for_context(point)
                if latitude is None or longitude is None or magnetic is None:
                    continue
                prompt += f"  {latitude:.5f}, {longitude:.5f}, {magnetic:.2f}\n"
        uploaded_context = self._collect_uploaded_file_context(task)
        if uploaded_context:
            prompt += "\n--- UPLOADED FILES ---\n" + uploaded_context[: self._MAX_CHAT_CONTEXT_CHARS] + "\n"
        results_context = self._build_results_context(outputs)
        if results_context:
            prompt += "\n--- PROCESSED OUTPUTS ---\n" + results_context[: self._MAX_CHAT_CONTEXT_CHARS] + "\n"
        prompt += f"\n--- CURRENT SCREEN: {location.upper()} ---\n"
        return prompt

    def _build_compact_chat_system_prompt(
        self,
        project: dict,
        task: dict,
        config: dict,
        outputs: dict,
        stats: dict,
        location: str,
    ) -> str:
        return (
            "You are Aurora AI, a practical magnetic-survey assistant. "
            "Answer directly in plain language using only the project/task/results summary below. Never expose raw field names, internal keys, or code-style identifiers.\n"
            f"Project: {project.get('name', '')}\n"
            f"Task: {task.get('name', '')}\n"
            f"Screen: {location}\n"
            f"Scenario: {task.get('scenario') or 'off'}\n"
            f"Corrections: {', '.join(config.get('corrections') or []) or 'none'}\n"
            f"Outputs: {', '.join(config.get('add_ons') or []) or 'none'}\n"
            f"Stats: mean={stats.get('mean', 0):.2f} nT, range={float(stats.get('max', 0) or 0) - float(stats.get('min', 0) or 0):.2f} nT, points={stats.get('point_count', 0)}\n"
            f"Base-station readings recognised: {self._resolved_base_station_count(outputs)}\n"
            f"Available layers: {', '.join(self._list_available_layers(outputs)) or 'TMF only'}\n"
        )

    def _build_export_data_prompt(
        self,
        project: dict,
        task: dict,
        config: dict,
        full_results: dict,
        stats: dict,
        upload_context: str | None,
    ) -> str:
        corrections = config.get("corrections") or []
        add_ons = config.get("add_ons") or []
        scenario = task.get("scenario") or "automatic"
        model = config.get("model") or "not specified"
        selected_add_ons = full_results.get("selected_add_ons") or add_ons
        layer_map = {
            "rtp": "Reduction to Pole (RTP)",
            "analytic_signal": "Analytic Signal",
            "first_vertical_derivative": "First Vertical Derivative (FVD)",
            "horizontal_derivative": "Horizontal Derivative",
            "tilt_derivative": "Tilt Derivative",
            "total_gradient": "Total Gradient",
            "emag2": "Regional Residual",
            "uncertainty": "Uncertainty Surface",
        }
        derived_layers = [layer_map.get(key, key) for key in selected_add_ons]
        sample_lines = []
        for point in (full_results.get("points") or [])[:30]:
            latitude = self._to_float(point.get("latitude"))
            longitude = self._to_float(point.get("longitude"))
            magnetic = self._point_value_for_context(point)
            if latitude is None or longitude is None or magnetic is None:
                continue
            sample_lines.append(f"{latitude:.5f}, {longitude:.5f}, {magnetic:.2f} nT")

        qa_report = full_results.get("qa_report") or {}
        model_meta = full_results.get("model_metadata") or {}
        validation = full_results.get("validation_summary") or {}
        data = {
            "project_name": project.get("name", ""),
            "project_context": project.get("context", ""),
            "task_name": task.get("name", ""),
            "task_description": task.get("description", ""),
            "platform": task.get("platform", "not specified"),
            "scenario": scenario,
            "processing_mode": task.get("processing_mode", "not specified"),
            "corrections_applied": corrections,
            "correction_report": self._build_export_correction_report(full_results, corrections),
            "model": model,
            "model_diagnostics": {
                "model_used": full_results.get("model_used", model),
                "algorithm": model_meta.get("algorithm"),
                "rmse": model_meta.get("rmse", stats.get("rmse")),
                "mae": model_meta.get("mae"),
                "r2": model_meta.get("r2"),
                "support_fraction": model_meta.get("support_fraction"),
                "observed_points": len([p for p in (full_results.get("points") or []) if not p.get("is_predicted")]),
                "predicted_points": len(full_results.get("predicted_points") or []),
            },
            "base_station_readings": int((validation or {}).get("base_station_count", 0)),
            "add_ons_enabled": add_ons,
            "derived_layers": derived_layers,
            "all_layers": ["Total Magnetic Field (TMF)"] + derived_layers,
            "available_visualisations": ["Magnetic Surface (heatmap + contour)", "Map overlay", "Line profiles"] + derived_layers,
            "stats": {
                "mean_nT": round(float(stats.get("mean", 0)), 3),
                "std_nT": round(float(stats.get("std", 0)), 3),
                "min_nT": round(float(stats.get("min", 0)), 3),
                "max_nT": round(float(stats.get("max", 0)), 3),
                "range_nT": round(float(stats.get("max", 0)) - float(stats.get("min", 0)), 3),
                "point_count": stats.get("point_count", 0),
                "anomaly_count": stats.get("anomaly_count", 0),
            },
            "validation_summary": validation,
            "qa_report": qa_report,
            "processing_quality_score": qa_report.get("quality_score", 1.0),
            "run_status": qa_report.get("status", "completed"),
            "sample_stations_lat_lon_nT": sample_lines,
            "uploaded_files_summary": upload_context[: self._MAX_UPLOAD_SNIPPET_CHARS] if upload_context else None,
        }
        return (
            "INPUT DATA - use this to generate the dynamic technical deliverable:\n\n"
            + json.dumps(data, indent=2)
            + "\n\nReturn only the JSON structure described in the system prompt."
        )

    def _build_export_correction_report(self, full_results: dict, corrections: list[str]) -> dict[str, Any]:
        qa_report = full_results.get("qa_report") or {}
        fallback_events = qa_report.get("fallback_events") or []
        report = {}
        for correction in corrections:
            report[correction] = "Applied or configured"
        for event in fallback_events:
            requested = event.get("requested")
            if requested:
                report[requested] = {
                    "requested": requested,
                    "actual": event.get("actual"),
                    "reason": event.get("reason"),
                    "severity": event.get("severity"),
                }
        if qa_report.get("lag"):
            report["lag"] = qa_report.get("lag")
        if qa_report.get("heading"):
            report["heading"] = qa_report.get("heading")
        if qa_report.get("crossover"):
            report["leveling"] = qa_report.get("crossover")
        return report

    def _load_full_results(self, task: dict) -> dict:
        if not self._storage:
            return {}
        artifacts = (task.get("results") or {}).get("artifacts") or []
        results_artifact = next((a for a in artifacts if a.get("file_name") == "results.json"), None)
        if not results_artifact:
            return {}
        try:
            data = self._storage.download_bytes(results_artifact["bucket"], results_artifact["object_name"])
            return json.loads(data)
        except Exception:
            return {}

    def _collect_uploaded_file_context(self, task: dict) -> str | None:
        if not self._storage:
            return None
        sections = []
        seen_objects: set[str] = set()
        for artifact in list(task.get("survey_files") or []) + [task.get("basemap_file")]:
            if not artifact:
                continue
            object_name = artifact.get("object_name")
            if not object_name or object_name in seen_objects:
                continue
            seen_objects.add(object_name)
            summary = self._summarize_uploaded_artifact(artifact)
            if summary:
                sections.append(summary)
        if not sections:
            return None
        return "\n\n".join(sections)[: self._MAX_REF_CHARS]

    def _summarize_uploaded_artifact(self, artifact: dict) -> str | None:
        try:
            raw = self._storage.download_bytes(artifact["bucket"], artifact["object_name"])
        except Exception:
            return None
        file_name = artifact.get("file_name") or "uploaded file"
        content = self._extract_text_from_bytes(raw, file_name.lower())
        if not content:
            return f"File: {file_name}\nCould not extract readable text, but the file is attached to the task."
        return f"File: {file_name}\n{content[: self._MAX_UPLOAD_SNIPPET_CHARS]}"

    def _extract_text_from_bytes(self, raw: bytes, file_name: str) -> str | None:
        try:
            if file_name.endswith(".csv"):
                return self._summarize_csv(raw)
            if file_name.endswith(".txt"):
                return raw.decode("utf-8", errors="replace")
            if file_name.endswith((".json", ".geojson")):
                data = json.loads(raw.decode("utf-8", errors="replace"))
                if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                    features = data.get("features") or []
                    lines = [f"GeoJSON FeatureCollection with {len(features)} features."]
                    for feature in features[:10]:
                        props = feature.get("properties") or {}
                        geom_type = (feature.get("geometry") or {}).get("type", "unknown")
                        lines.append(f"{geom_type}: {props}")
                    return "\n".join(lines)
                return json.dumps(data, indent=2)[: self._MAX_UPLOAD_SNIPPET_CHARS]
            if file_name.endswith(".kml"):
                import xml.etree.ElementTree as ET

                root = ET.fromstring(raw.decode("utf-8", errors="replace"))
                names = [el.text for el in root.iter() if el.tag.endswith("name") and el.text]
                descs = [el.text for el in root.iter() if el.tag.endswith("description") and el.text]
                lines = ["KML file contents:"]
                if names:
                    lines.append("Names: " + ", ".join(names[:20]))
                if descs:
                    lines.append("Descriptions:")
                    lines.extend(descs[:5])
                return "\n".join(lines)
            if file_name.endswith((".kmz", ".zip")):
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    text_parts = []
                    for name in archive.namelist():
                        lower_name = name.lower()
                        if lower_name.endswith((".txt", ".csv", ".json", ".geojson", ".kml")):
                            extracted = self._extract_text_from_bytes(archive.read(name), lower_name)
                            if extracted:
                                text_parts.append(f"Embedded file: {name}\n{extracted[:1500]}")
                    return "\n\n".join(text_parts) if text_parts else None
            if file_name.endswith(".pdf"):
                try:
                    from pdfminer.high_level import extract_text as pdf_extract

                    return pdf_extract(io.BytesIO(raw))
                except Exception:
                    text = raw.decode("latin-1", errors="replace")
                    lines = [
                        line
                        for line in text.splitlines()
                        if len(line) > 10 and sum(32 <= ord(char) < 127 for char in line) / max(len(line), 1) > 0.8
                    ]
                    return "\n".join(lines[:80])
            if file_name.endswith(".docx"):
                from docx import Document as DocxDocument

                doc = DocxDocument(io.BytesIO(raw))
                return "\n".join(paragraph.text for paragraph in doc.paragraphs if paragraph.text.strip())
        except Exception:
            return None
        return None

    def _summarize_csv(self, raw: bytes) -> str | None:
        text = raw.decode("utf-8", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = []
        try:
            for _, row in zip(range(6), reader):
                rows.append(row)
        except Exception:
            return None
        if not rows:
            return None
        lines = [f"CSV with columns: {', '.join(rows[0][:20]) or 'unknown'}"]
        if len(rows) > 1:
            lines.append("Sample rows:")
            for row in rows[1:6]:
                lines.append(", ".join((cell or "").strip()[:40] for cell in row[:8]))
        return "\n".join(lines)

    def _build_results_context(self, outputs: dict) -> str:
        if not outputs:
            return ""
        lines = []
        validation = outputs.get("validation_summary") or {}
        qa_report = outputs.get("qa_report") or {}
        model_metadata = outputs.get("model_metadata") or {}
        uncertainty_metadata = outputs.get("uncertainty_metadata") or {}
        base_station_count = self._resolved_base_station_count(outputs)
        if validation:
            lines.append(
                "Validation summary: "
                f"status={validation.get('status', 'unknown')}, "
                f"rows={validation.get('row_count', 0)}, "
                f"base-station readings={base_station_count}, "
                f"warnings={len(validation.get('warnings') or [])}"
            )
        if qa_report:
            lines.append(
                "QA report: "
                f"status={qa_report.get('status', 'unknown')}, "
                f"quality={qa_report.get('quality_score', 'n/a')}, "
                f"fallbacks={len(qa_report.get('fallback_events') or [])}"
            )
        if model_metadata:
            lines.append(
                "Model metadata: "
                f"algorithm={model_metadata.get('algorithm') or 'not specified'}, "
                f"rmse={model_metadata.get('rmse')}, "
                f"mae={model_metadata.get('mae')}, "
                f"r2={model_metadata.get('r2')}"
            )
        if uncertainty_metadata:
            lines.append(
                "Uncertainty metadata: "
                f"algorithm={uncertainty_metadata.get('algorithm') or 'not specified'}, "
                f"detail={uncertainty_metadata.get('detail') or 'n/a'}"
            )
        layer_summaries = []
        for label in self._list_available_layers(outputs):
            key = self._output_key_for_layer(label)
            summary = self._summarize_numeric_grid(outputs.get(key))
            if summary:
                layer_summaries.append(f"{label}: {summary}")
        if layer_summaries:
            lines.append("Layer summaries:")
            lines.extend(layer_summaries[:10])
        return "\n".join(lines)

    def _resolved_base_station_count(self, outputs: dict) -> int:
        points = outputs.get("points") or []
        counted = sum(1 for point in points if point.get("is_base_station"))
        if counted:
            return int(counted)
        validation = outputs.get("validation_summary") or {}
        return int(validation.get("base_station_count", 0) or 0)

    def _list_available_layers(self, outputs: dict) -> list[str]:
        layer_map = {
            "surface": "Total Magnetic Field (TMF)",
            "corrected_field": "Corrected Magnetic Field",
            "filtered_surface": "Filtered Surface",
            "rtp_surface": "Reduction to Pole (RTP)",
            "analytic_signal": "Analytic Signal",
            "first_vertical_derivative": "First Vertical Derivative (FVD)",
            "horizontal_derivative": "Horizontal Derivative",
            "regional_field": "Regional Field",
            "regional_surface": "Regional Field",
            "regional_residual": "Regional Residual",
            "residual_surface": "Regional Residual",
            "emag2_residual": "Regional Residual",
            "uncertainty": "Uncertainty Surface",
            "tilt_derivative": "Tilt Derivative",
            "total_gradient": "Total Gradient",
        }
        labels = []
        for key, label in layer_map.items():
            if outputs.get(key) is not None and label not in labels:
                labels.append(label)
        return labels

    def _output_key_for_layer(self, label: str) -> str:
        reverse = {
            "Total Magnetic Field (TMF)": "surface",
            "Corrected Magnetic Field": "corrected_field",
            "Filtered Surface": "filtered_surface",
            "Reduction to Pole (RTP)": "rtp_surface",
            "Analytic Signal": "analytic_signal",
            "First Vertical Derivative (FVD)": "first_vertical_derivative",
            "Horizontal Derivative": "horizontal_derivative",
            "Regional Field": "regional_field",
            "Regional Residual": "regional_residual",
            "Uncertainty Surface": "uncertainty",
            "Tilt Derivative": "tilt_derivative",
            "Total Gradient": "total_gradient",
        }
        return reverse.get(label, "")

    def _build_fallback_report_data(
        self,
        project: dict,
        task: dict,
        config: dict,
        full_results: dict,
        stats: dict,
        upload_context: str | None,
    ) -> dict:
        qa_report = full_results.get("qa_report") or {}
        validation = full_results.get("validation_summary") or {}
        layers = self._list_available_layers(full_results)
        corrections = ", ".join(config.get("corrections") or []) or "None"
        add_ons = ", ".join(config.get("add_ons") or []) or "None"
        recommendations = [
            "Review the QA warnings and fallback events before treating the export as final.",
            "Use the regional/residual and derivative layers together when comparing shallow versus broad responses.",
            "Verify any interpretation against survey geometry, support coverage, and uncertainty before drilling or engineering decisions.",
        ]
        if int(validation.get("base_station_count", 0) or 0) == 0:
            recommendations.insert(0, "This run did not recognise base-station readings, so diurnal correction fell back and should be reviewed.")
        executive_summary = (
            f"{task.get('name', 'Task')} for project {project.get('name', 'Project')} processed "
            f"{stats.get('point_count', 0)} points with {qa_report.get('status', 'unknown')} QA status. "
            f"Configured corrections were {corrections}; configured add-ons were {add_ons}."
        )
        return {
            "executive_summary": executive_summary,
            "report": {
                "survey_context": {
                    "project_name": project.get("name", ""),
                    "project_context": project.get("context", ""),
                    "task_name": task.get("name", ""),
                    "task_description": task.get("description", ""),
                    "platform": task.get("platform"),
                    "scenario": task.get("scenario") or "automatic",
                    "processing_mode": task.get("processing_mode"),
                    "configured_corrections": config.get("corrections") or [],
                    "configured_add_ons": config.get("add_ons") or [],
                    "configured_model": config.get("model") or "not specified",
                },
                "project_overview": f"Project: {project.get('name', '')}. Context: {project.get('context', '')}",
                "data_description": f"Task: {task.get('name', '')}. Description: {task.get('description', '')}. Uploaded context: {(upload_context or 'No uploaded-file summary was available.')[:1200]}",
                "processing_workflow": {
                    "project_and_task": f"Platform={task.get('platform')}, scenario={task.get('scenario') or 'automatic'}, processing_mode={task.get('processing_mode')}",
                    "configured_pipeline": f"Corrections={corrections}. Model={config.get('model') or 'not specified'}. Add-ons={add_ons}.",
                    "regional_residual": json.dumps(
                        {
                            "regional_method_used": full_results.get("regional_method_used"),
                            "regional_scale_or_degree": full_results.get("regional_scale_or_degree"),
                            "residual_definition": full_results.get("residual_definition"),
                            "regional_vs_residual_summary": full_results.get("regional_vs_residual_summary"),
                        },
                        indent=2,
                    ),
                    "qa_and_fallbacks": json.dumps(
                        {
                            "qa_status": qa_report.get("status"),
                            "fallback_events": qa_report.get("fallback_events") or [],
                            "warnings": qa_report.get("warnings") or [],
                        },
                        indent=2,
                    ),
                },
                "results_interpretation": [
                    {
                        "layer": layer,
                        "description": (
                            "Broadly corrected magnetic field carried forward from the correction and modelling workflow."
                            if layer == "Corrected Magnetic Field"
                            else "Broad regional magnetic trend representing long-wavelength field behaviour."
                            if layer == "Regional Field"
                            else "Residual magnetic field isolating local anomaly expression after subtracting the regional field."
                            if layer == "Regional Residual"
                            else f"{layer} was generated for this run."
                        ),
                        "observations": f"Overall range: {stats.get('min', 0):.2f} to {stats.get('max', 0):.2f} nT across {stats.get('point_count', 0)} points.",
                        "interpretation": "Interpretation should be tied to the actual QA status, fallback path, and survey support shown in the processing outputs.",
                        "implication": "Use this layer alongside uncertainty and QA metadata before drawing operational conclusions.",
                    }
                    for layer in layers[:6]
                ],
                "modelling": json.dumps(full_results.get("model_metadata") or {}, indent=2),
                "data_quality": json.dumps(
                    {
                        "validation": validation,
                        "qa_report": qa_report,
                    },
                    indent=2,
                ),
                "conclusions": (
                    f"QA status: {qa_report.get('status', 'unknown')}\n"
                    f"Base-station readings recognised: {validation.get('base_station_count', 0)}\n"
                    f"Available layers: {', '.join(layers) or 'TMF only'}"
                ),
                "recommendations": "\n".join(recommendations),
            },
        }

    def _summarize_numeric_grid(self, values: Any) -> str | None:
        if not isinstance(values, list) or not values:
            return None
        flattened = []
        for row in values:
            if isinstance(row, list):
                flattened.extend(value for value in row if isinstance(value, (int, float)))
            elif isinstance(row, (int, float)):
                flattened.append(row)
        if not flattened:
            return None
        return (
            f"min={min(flattened):.2f}, max={max(flattened):.2f}, "
            f"mean={sum(flattened) / len(flattened):.2f}, cells={len(flattened)}"
        )

    def _point_value_for_context(self, point: dict) -> float | None:
        for key in ("magnetic", "corrected_magnetic", "predicted_magnetic", "value"):
            value = self._to_float(point.get(key))
            if value is not None:
                return value
        return None

    def _to_float(self, value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _fallback_text(self, project: dict, task: dict, outputs: dict, location: str, question: str | None) -> str:
        layer_names = ", ".join(self._list_available_layers(outputs)[:4]) or "saved outputs"
        if location == "export":
            return (
                "Aurora export drafting is temporarily unavailable, so the document package was generated from the saved task data only. "
                f"Available outputs for this task include {layer_names}."
            )
        question_text = f"Your message was: {question}" if question else "Try asking again in a moment."
        return (
            "Aurora is temporarily unavailable, but your saved task and processing results are still loaded. "
            f"The current screen has access to {layer_names}. {question_text}"
        )
