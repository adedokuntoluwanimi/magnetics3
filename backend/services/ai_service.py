from __future__ import annotations

import io
import json
import zipfile

from backend.models import AuroraResponse


class AIService:
    def __init__(self, store, vertex_client, storage_backend=None) -> None:
        self._store = store
        self._vertex = vertex_client
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
        extra_results: dict | None = None,
    ) -> AuroraResponse:
        project = self._store.get_project(project_id)
        task = self._store.get_task(task_id)
        if not project or not task:
            raise ValueError("Project or task not found.")

        system_prompt = (
            "You are a senior geophysical magnetics analyst with expertise in survey QC, "
            "potential-field interpretation, and Kriging/ML-based magnetic modelling. "
            "Ground every response in the provided project context, survey configuration, "
            "and magnetic workflow choices. Be practical, precise, and domain aware. "
            "Do not refer to yourself by any product name."
        )

        # Prefer the richer GCS-loaded results when supplied (export path),
        # otherwise fall back to the lightweight Firestore copy.
        outputs = extra_results or task.get("results", {}).get("data", {})
        stats = outputs.get("stats") or {}
        config = task.get("analysis_config") or {}

        is_export = location == "export"
        max_tokens = 3000 if is_export else 1500

        # Build a focused, structured context block instead of dumping the whole task dict
        context_block = (
            f"Project name: {project.get('name', '')}\n"
            f"Project context: {project.get('context', '')}\n\n"
            f"Task name: {task.get('name', '')}\n"
            f"Task description: {task.get('description', '')}\n\n"
            f"Survey platform: {task.get('platform', 'not specified')}\n"
            f"Scenario: {task.get('scenario', 'not specified')}\n"
            f"Processing mode: {task.get('processing_mode', 'not specified')}\n\n"
            f"Corrections applied: {', '.join(config.get('corrections') or []) or 'none'}\n"
            f"Prediction model: {config.get('model') or 'not specified'}\n"
            f"Processing add-ons: {', '.join(config.get('add_ons') or []) or 'none'}\n\n"
        )

        if stats:
            context_block += (
                f"Processed magnetic statistics:\n"
                f"  Mean field: {stats.get('mean', 'n/a'):.2f} nT\n"
                f"  Std deviation: {stats.get('std', 'n/a'):.2f} nT\n"
                f"  Min / Max: {stats.get('min', 'n/a'):.2f} / {stats.get('max', 'n/a'):.2f} nT\n"
                f"  Points processed: {stats.get('point_count', 'n/a')}\n"
                f"  Anomaly count (>mean+1σ): {stats.get('anomaly_count', 0)}\n"
                f"  Model used: {outputs.get('model_used', 'n/a')}\n\n"
            )

        # Include a sample of measured station values for spatial context
        sample_points = (outputs.get("points") or [])[:30]
        if sample_points:
            context_block += "Sample measured stations (lat, lon, magnetic nT):\n"
            for p in sample_points:
                context_block += f"  {p.get('latitude', ''):.5f}, {p.get('longitude', ''):.5f}, {p.get('magnetic', ''):.2f}\n"
            context_block += "\n"

        # Inject reference file text if available
        ref_text = self._extract_reference_text(task)
        if ref_text:
            context_block += f"Reference document uploaded by user:\n{ref_text}\n\n"

        if is_export:
            detail_instruction = (
                "Produce a structured geophysical interpretation suitable for a professional deliverable. "
                "Format your response with these clearly labelled sections:\n"
                "EXECUTIVE SUMMARY: One paragraph summary of survey outcomes.\n"
                "KEY FINDINGS: 3 to 5 bullet points describing anomaly observations with spatial context where available.\n"
                "MODELLING NOTES: Brief notes on assumptions and limitations of the chosen model and corrections.\n"
                "RECOMMENDATIONS: One or two actionable follow-up recommendations.\n"
                "Write in clear, client-facing language. Be specific to the data provided."
            )
        else:
            detail_instruction = (
                "Return a short assessment with likely outputs or interpretation, key risks, and one "
                "operational recommendation. Use bullet-like short lines."
            )

        user_prompt = (
            f"{context_block}"
            f"Location in app: {location}\n"
            f"User question: {question or 'Provide the most helpful contextual guidance for this screen.'}\n\n"
            f"{detail_instruction}"
        )
        try:
            text = self._vertex.generate(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=max_tokens)
        except Exception:
            text = self._fallback_text(project, task, outputs, location, question)

        return self._parse_response(text, location, is_export)

    def _parse_response(self, text: str, location: str, is_export: bool) -> AuroraResponse:
        """
        For export: extract labelled sections and map them to summary + highlights.
        For other locations: first non-empty line is summary, next lines are highlights.
        """
        if is_export:
            sections = {
                "executive_summary": "",
                "key_findings": [],
                "modelling_notes": "",
                "recommendations": "",
            }
            current = None
            for line in text.splitlines():
                stripped = line.strip()
                low = stripped.lower()
                if low.startswith("executive summary"):
                    current = "executive_summary"
                    rest = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
                    if rest:
                        sections["executive_summary"] = rest
                elif low.startswith("key findings"):
                    current = "key_findings"
                elif low.startswith("modelling notes") or low.startswith("modeling notes"):
                    current = "modelling_notes"
                    rest = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
                    if rest:
                        sections["modelling_notes"] = rest
                elif low.startswith("recommendation"):
                    current = "recommendations"
                    rest = stripped.split(":", 1)[1].strip() if ":" in stripped else ""
                    if rest:
                        sections["recommendations"] = rest
                elif stripped and current:
                    if current == "executive_summary" and not sections["executive_summary"]:
                        sections["executive_summary"] = stripped
                    elif current == "executive_summary":
                        sections["executive_summary"] += " " + stripped
                    elif current == "key_findings":
                        clean = stripped.lstrip("•-*").strip()
                        if clean:
                            sections["key_findings"].append(clean)
                    elif current == "modelling_notes":
                        sections["modelling_notes"] += (" " + stripped) if sections["modelling_notes"] else stripped
                    elif current == "recommendations":
                        sections["recommendations"] += (" " + stripped) if sections["recommendations"] else stripped

            summary = sections["executive_summary"] or text.splitlines()[0].strip()
            highlights = sections["key_findings"]
            if sections["modelling_notes"]:
                highlights.append(f"Modelling: {sections['modelling_notes']}")
            if sections["recommendations"]:
                highlights.append(f"Recommendation: {sections['recommendations']}")
            return AuroraResponse(location=location, summary=summary, highlights=highlights)

        # Non-export: keep existing simple format
        lines = [line.strip("- •*").strip() for line in text.splitlines() if line.strip()]
        summary = lines[0] if lines else text
        highlights = lines[1:6] if len(lines) > 1 else []
        return AuroraResponse(location=location, summary=summary, highlights=highlights)

    # ── Reference file extraction ────────────────────────────────────────────

    _MAX_REF_CHARS = 6000  # cap to avoid overloading the context window

    def _extract_reference_text(self, task: dict) -> str | None:
        """
        Download the reference file stored as task.basemap_file from GCS and
        extract readable text from it. Returns None if no file exists, the
        storage backend is unavailable, or extraction fails.

        Supported formats: .txt, .json, .geojson, .kml, .pdf, .docx, .kmz, .zip
        """
        if not self._storage:
            return None
        ref = task.get("basemap_file")
        if not ref or not ref.get("bucket") or not ref.get("object_name"):
            return None

        try:
            raw = self._storage.download_bytes(ref["bucket"], ref["object_name"])
        except Exception:
            return None

        file_name = (ref.get("file_name") or "").lower()
        try:
            if file_name.endswith(".txt"):
                text = raw.decode("utf-8", errors="replace")

            elif file_name.endswith((".json", ".geojson")):
                data = json.loads(raw.decode("utf-8", errors="replace"))
                # Summarise GeoJSON rather than dumping the whole thing
                if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                    features = data.get("features") or []
                    lines = [f"GeoJSON FeatureCollection with {len(features)} features."]
                    for f in features[:10]:
                        props = f.get("properties") or {}
                        geom_type = (f.get("geometry") or {}).get("type", "unknown")
                        lines.append(f"  {geom_type}: {props}")
                    text = "\n".join(lines)
                else:
                    text = json.dumps(data, indent=2)[:self._MAX_REF_CHARS]

            elif file_name.endswith(".kml"):
                import xml.etree.ElementTree as ET
                root = ET.fromstring(raw.decode("utf-8", errors="replace"))
                ns = {"k": "http://www.opengis.net/kml/2.2"}
                names = [el.text for el in root.iter() if el.tag.endswith("name") and el.text]
                descs = [el.text for el in root.iter() if el.tag.endswith("description") and el.text]
                text = "KML file contents:\n"
                if names:
                    text += "Names: " + ", ".join(names[:20]) + "\n"
                if descs:
                    text += "Descriptions:\n" + "\n".join(descs[:5])

            elif file_name.endswith(".kmz") or file_name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    # Look for a KML or text file inside
                    text_parts = []
                    for name in zf.namelist():
                        if name.lower().endswith(".kml"):
                            kml_bytes = zf.read(name)
                            import xml.etree.ElementTree as ET
                            root = ET.fromstring(kml_bytes.decode("utf-8", errors="replace"))
                            names = [el.text for el in root.iter() if el.tag.endswith("name") and el.text]
                            descs = [el.text for el in root.iter() if el.tag.endswith("description") and el.text]
                            if names:
                                text_parts.append("KML names: " + ", ".join(names[:20]))
                            if descs:
                                text_parts.append("KML descriptions: " + "; ".join(descs[:5]))
                        elif name.lower().endswith(".txt"):
                            text_parts.append(zf.read(name).decode("utf-8", errors="replace")[:2000])
                    text = "\n".join(text_parts) if text_parts else None

            elif file_name.endswith(".pdf"):
                try:
                    from pdfminer.high_level import extract_text as pdf_extract
                    text = pdf_extract(io.BytesIO(raw))
                except Exception:
                    # Fallback: try raw byte decode for simple PDFs
                    text = raw.decode("latin-1", errors="replace")
                    # Strip binary garbage — keep only printable ASCII lines
                    lines = [
                        ln for ln in text.splitlines()
                        if len(ln) > 10 and sum(32 <= ord(c) < 127 for c in ln) / max(len(ln), 1) > 0.8
                    ]
                    text = "\n".join(lines[:80])

            elif file_name.endswith(".docx"):
                from docx import Document as DocxDoc
                doc = DocxDoc(io.BytesIO(raw))
                text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())

            else:
                # Unknown binary format — skip
                return None

            if not text:
                return None
            # Trim to token-safe length
            return text[:self._MAX_REF_CHARS]

        except Exception:
            return None

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
