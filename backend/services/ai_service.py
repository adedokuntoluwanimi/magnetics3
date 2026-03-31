from __future__ import annotations

import io
import json
import re
import zipfile

from backend.models import AuroraResponse

# ── Export report system prompt ──────────────────────────────────────────────
# Used ONLY for PDF / DOCX / PPTX generation — not the chat panels.
_EXPORT_SYSTEM_PROMPT = """You are a senior geophysicist, technical report writer, and presentation designer.

You are generating client-ready deliverables (DOCX, PDF, PPTX) from processed magnetic survey results.

The outputs must be:
* technically rigorous
* visually structured
* fully grounded in the actual processing configuration and results

# INPUT DATA (MANDATORY USAGE)

You will receive structured data including:
* processing configuration (which corrections and layers were enabled)
* correction_report
* model_diagnostics
* derived_layers (only those actually generated)
* scenario (explicit or sparse)
* processing_quality_score
* run_status
* grid information
* available visualisations (listed by name; figure placeholders required)

You MUST dynamically adapt content based on what is present.

# CORE RULE

Do NOT generate fixed sections.

Instead:
* ONLY include sections for:
  * corrections that were actually applied
  * layers that were actually generated
  * modelling mode that was used

# VISUAL INTEGRATION (CRITICAL)

For EVERY available visualisation listed in the input data:

You MUST:
1. Insert a figure placeholder: [Insert <Layer Name> Map Here]
2. Provide:
   * Figure title
   * Description (what is shown)
   * Interpretation (what it means)
   * Implication (why it matters)

Example:
Figure: RTP Magnetic Map
Description: Displays the magnetic field after reduction to pole transformation
Interpretation: Anomalies are spatially centered over their sources
Implication: Enables clearer identification of structural features

# REPORT GENERATION (DYNAMIC STRUCTURE)

## 1. Project Overview
* Purpose of survey
* Context

## 2. Data Description
* Data type, density, coordinate system
* Scenario type:
  * Explicit → explain missing-value prediction
  * Sparse → explain interpolation/grid logic

## 3. Processing Workflow (ONLY INCLUDE ACTIVE STEPS)

Dynamically generate subsections ONLY for enabled steps:
IF igrf applied → include IGRF section
IF diurnal correction applied → include Diurnal section
IF spike_removal applied → include Spike Removal section
IF heading_correction applied → include Heading Correction section
IF lag_correction applied → include Lag Correction section
IF fft_filter applied → include FFT Filter section

Each subsection must include:
* Purpose of the step
* Method used (from correction_report)
* Effect on data
* Impact on interpretation

## 4. Results & Interpretation (VISUAL-FIRST)

For EACH available layer generate a section:
### <Layer Name>
[Insert <Layer Name> Map Here]
* Description (what is visualised)
* Observations (anomaly patterns, trends, intensity distribution)
* Interpretation (structural meaning, possible geological implications)
* Implication (what this suggests about subsurface features)

Only include layers present in derived_layers.

## 5. Modelling & Prediction

IF scenario == explicit:
* Explain prediction of missing values
* Discuss reliability of inferred values

IF scenario == sparse:
* Explain grid generation
* Discuss interpolation assumptions

Always include:
* RMSE interpretation
* variance interpretation
* prediction distribution

## 6. Data Quality & Reliability

Use processing_quality_score and correction_report.
Explain which corrections were applied or skipped and their impact.
Provide a clear confidence level: low / moderate / high

## 7. Conclusions
* Key findings (based strictly on results)
* Structural interpretation summary

## 8. Recommendations
* Further work
* Survey improvements
* Additional geophysical methods

# PRESENTATION (PPTX — DYNAMIC)

Slides must be generated ONLY for available content.

Each slide must include:
* title
* 3–5 concise bullets
* speaker_notes (detailed explanation)
* visual_ref (layer name for figure, or null)

Required logic:
* If RTP exists → include RTP slide
* If Analytic Signal exists → include slide
* If Tilt derivative exists → include slide
* If leveling applied → include slide explaining improvement
* If modelling exists → include modelling slide
* Do NOT include slides for unavailable layers

Suggested structure:
1. Title
2. Project Overview
3. Data Summary
4. Processing Workflow
5. Magnetic Map (TMF)
6. RTP (if available)
7. Analytic Signal (if available)
8. Structural Interpretation
9. Modelling Results
10. Data Quality
11. Conclusions
12. Recommendations

# EXECUTIVE SUMMARY

Must include:
* What was done
* Key findings
* Confidence level
* Key recommendation

Keep concise but impactful.

# STYLE REQUIREMENTS

* Professional geophysical tone
* Clear and precise language
* No generic filler
* No repetition
* Every statement must tie to actual outputs

# STRICT RULES

* Do NOT include sections for features not used
* Do NOT hallucinate missing data
* Do NOT ignore provided visualisations
* Do NOT produce generic summaries

# OUTPUT FORMAT

Return ONLY valid JSON (no markdown code fences, no explanation text):

{
  "executive_summary": "one concise paragraph",
  "report": {
    "project_overview": "...",
    "data_description": "...",
    "processing_workflow": {
      "<step_name>": "<description of what was done and why>"
    },
    "results_interpretation": [
      {
        "layer": "<Layer Name>",
        "figure_placeholder": "[Insert <Layer Name> Map Here]",
        "description": "...",
        "observations": "...",
        "interpretation": "...",
        "implication": "..."
      }
    ],
    "modelling": "...",
    "data_quality": "...",
    "conclusions": "...",
    "recommendations": "..."
  },
  "slides": [
    {
      "title": "...",
      "bullets": ["...", "...", "..."],
      "speaker_notes": "...",
      "visual_ref": "<layer name or null>"
    }
  ]
}"""


class AIService:
    def __init__(self, store, vertex_client, storage_backend=None) -> None:
        self._store = store
        self._vertex = vertex_client
        self._storage = storage_backend

    # ── Public: chat ─────────────────────────────────────────────────────────

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

        outputs = extra_results or task.get("results", {}).get("data", {})
        stats = outputs.get("stats") or {}
        config = task.get("analysis_config") or {}

        system_prompt = self._build_chat_system_prompt(project, task, config, outputs, stats, location)
        max_tokens = 1500

        # Build message list from history + current question
        messages: list[dict] = []
        for msg in (history or [])[-20:]:  # cap at last 20 messages
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        current_q = question or "Provide the most helpful contextual analysis and guidance for this screen."
        messages.append({"role": "user", "content": current_q})

        try:
            text = self._vertex.generate(
                system_prompt=system_prompt,
                messages=messages,
                max_tokens=max_tokens,
            )
        except Exception:
            text = self._fallback_text(project, task, outputs, location, question)

        return self._parse_chat_response(text, location)

    # ── Public: export document generation ───────────────────────────────────

    def generate_export_report(
        self,
        project_id: str,
        task_id: str,
        full_results: dict,
    ) -> AuroraResponse:
        """
        Generate a structured, dynamic technical report using the comprehensive
        geophysical system prompt.  Returns an AuroraResponse whose `report_data`
        field contains the parsed JSON structure (report, slides, executive_summary).
        Falls back gracefully to a simple text response if JSON parsing fails.
        """
        project = self._store.get_project(project_id)
        task = self._store.get_task(task_id)
        if not project or not task:
            raise ValueError("Project or task not found.")

        config = task.get("analysis_config") or {}
        stats = full_results.get("stats") or {}

        ref_text = self._extract_reference_text(task)
        user_prompt = self._build_export_data_prompt(project, task, config, full_results, stats, ref_text)

        try:
            text = self._vertex.generate(
                system_prompt=_EXPORT_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_tokens=4000,
            )
            report_data = self._parse_export_json(text)
        except Exception:
            report_data = None

        if report_data:
            exec_summary = report_data.get("executive_summary", "")
            report_section = report_data.get("report", {})
            conclusions = report_section.get("conclusions", "")
            recommendations = report_section.get("recommendations", "")
            highlights = []
            results_interp = report_section.get("results_interpretation", [])
            for layer in results_interp[:5]:
                obs = layer.get("observations", "")
                if obs:
                    highlights.append(f"{layer.get('layer', 'Layer')}: {obs[:120]}")
            if recommendations:
                highlights.append(f"Recommendation: {recommendations[:200]}")
            return AuroraResponse(
                location="export",
                summary=exec_summary,
                highlights=highlights,
                message=exec_summary,
                report_data=report_data,
            )

        # Fallback to simple structured text
        fallback_text = self._fallback_text(project, task, full_results, "export", None)
        return self._parse_chat_response(fallback_text, "export")

    # ── Response parsing ─────────────────────────────────────────────────────

    def _parse_chat_response(self, text: str, location: str) -> AuroraResponse:
        """
        Parse a conversational AI response.
        The full text is stored in `message`.
        The first non-empty paragraph becomes `summary`.
        Lines that look like bullet points become `highlights`.
        """
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        summary = lines[0] if lines else text

        highlights = []
        for ln in lines[1:]:
            clean = re.sub(r"^[\-\*\•]+\s*", "", ln).strip()
            if clean and len(clean) > 10:
                highlights.append(clean)
                if len(highlights) >= 6:
                    break

        return AuroraResponse(
            location=location,
            summary=summary,
            highlights=highlights,
            message=text,
        )

    def _parse_export_json(self, text: str) -> dict | None:
        """
        Extract and parse the JSON object from the AI response.
        Handles ```json ... ``` fences and bare JSON.
        """
        # Strip markdown code fences if present
        fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        json_str = fence_match.group(1) if fence_match else text.strip()

        # Try to find a top-level JSON object even if there's surrounding text
        brace_match = re.search(r"\{[\s\S]+\}", json_str)
        if brace_match:
            json_str = brace_match.group(0)

        try:
            data = json.loads(json_str)
        except Exception:
            return None

        # Basic validation
        if not isinstance(data, dict):
            return None
        if "report" not in data and "executive_summary" not in data:
            return None
        return data

    # ── System prompt builders ────────────────────────────────────────────────

    def _build_chat_system_prompt(
        self,
        project: dict,
        task: dict,
        config: dict,
        outputs: dict,
        stats: dict,
        location: str,
    ) -> str:
        """
        Build a rich, project-aware system prompt for the conversational chat panels.
        All project context lives here so the conversation history stays clean.
        """
        corrections = ", ".join(config.get("corrections") or []) or "none"
        add_ons = ", ".join(config.get("add_ons") or []) or "none"
        model = config.get("model") or "not specified"
        scenario = task.get("scenario", "not specified")
        platform = task.get("platform", "not specified")

        ref_text = self._extract_reference_text(task)

        prompt = (
            "You are Aurora AI, a practical magnetic-survey assistant focused on setup, QA, processing outputs, and delivery choices. "
            "Keep answers direct, plain-language, and operational unless the user explicitly asks for technical depth. "
            "Do not add geology interpretation, structural speculation, or region descriptions unless the user explicitly asks for them. "
            "Avoid jargon where a simpler phrase will do. "
            "Ground every answer in the project data below. "
            "Be conversational, precise, and easy to follow. Answer follow-up questions "
            "naturally using the context you already have.\n\n"
            "--- PROJECT CONTEXT ---\n"
            f"Project: {project.get('name', '')} — {project.get('context', '')}\n"
            f"Task: {task.get('name', '')} — {task.get('description', '')}\n"
            f"Platform: {platform}  |  Scenario: {scenario}  |  Model: {model}\n"
            f"Corrections: {corrections}\n"
            f"Add-ons / derived layers: {add_ons}\n"
        )

        if stats:
            try:
                prompt += (
                    f"Magnetic stats: mean={stats.get('mean', 0):.2f} nT, "
                    f"std={stats.get('std', 0):.2f} nT, "
                    f"min={stats.get('min', 0):.2f} / max={stats.get('max', 0):.2f} nT, "
                    f"{stats.get('point_count', 0)} points, "
                    f"{stats.get('anomaly_count', 0)} anomalies (>mean+1σ)\n"
                )
            except Exception:
                pass

        # Sample of station values
        sample = (outputs.get("points") or [])[:20]
        if sample:
            prompt += "Sample stations (lat, lon, magnetic nT):\n"
            for p in sample:
                try:
                    prompt += f"  {p.get('latitude', 0):.5f}, {p.get('longitude', 0):.5f}, {p.get('magnetic', 0):.2f}\n"
                except Exception:
                    pass

        if ref_text:
            prompt += f"\nReference document uploaded by user:\n{ref_text}\n"

        prompt += f"\n--- CURRENT SCREEN: {location.upper()} ---\n"
        return prompt

    def _build_export_data_prompt(
        self,
        project: dict,
        task: dict,
        config: dict,
        full_results: dict,
        stats: dict,
        ref_text: str | None,
    ) -> str:
        """
        Build the structured data prompt that pairs with the export system prompt.
        Includes all available processing metadata so the AI can generate dynamic sections.
        """
        corrections = config.get("corrections") or []
        add_ons = config.get("add_ons") or []
        model = config.get("model") or "not specified"
        scenario = task.get("scenario", "explicit")

        # Determine which derived layers were actually computed
        selected_add_ons = full_results.get("selected_add_ons") or add_ons
        derived_layers = []
        layer_map = {
            "rtp": "Reduction to Pole (RTP)",
            "analytic_signal": "Analytic Signal",
            "first_vertical_derivative": "First Vertical Derivative (FVD)",
            "horizontal_derivative": "Horizontal Derivative",
            "tilt_derivative": "Tilt Derivative",
            "total_gradient": "Total Gradient",
            "emag2": "EMAG2 Residual",
            "uncertainty": "Uncertainty Surface",
        }
        for key in selected_add_ons:
            label = layer_map.get(key, key)
            derived_layers.append(label)

        # Always include the base TMF layer
        all_layers = ["Total Magnetic Field (TMF)"] + derived_layers

        # Available visualisation images
        available_vis = ["Magnetic Surface (heatmap)", "Magnetic Contours"]
        for key in selected_add_ons:
            if key in layer_map:
                available_vis.append(layer_map[key])

        # Sample points
        sample_points = (full_results.get("points") or [])[:30]
        sample_lines = []
        for p in sample_points:
            try:
                sample_lines.append(f"  {p.get('latitude', 0):.5f}, {p.get('longitude', 0):.5f}, {p.get('magnetic', 0):.2f} nT")
            except Exception:
                pass

        # Model diagnostics from stats
        rmse_val = stats.get("rmse")
        variance = stats.get("std", 0)
        model_diagnostics = {
            "model_used": full_results.get("model_used", model),
            "rmse": rmse_val,
            "std_deviation": variance,
            "point_count": stats.get("point_count", 0),
        }

        # Correction report
        correction_report: dict[str, str] = {}
        for corr in corrections:
            descriptions = {
                "igrf": "IGRF-13 geomagnetic reference field removed per survey date and station coordinates",
                "diurnal": "Diurnal drift correction applied using base station or FFT low-pass fallback",
                "spike_removal": "Spike removal using IQR-based outlier detection and interpolation",
                "lag_correction": "Sensor lag correction applied via cross-correlation with GPS timestamps",
                "heading_correction": "Heading-dependent bias removed using bidirectional flight line comparison",
                "fft_filter": "FFT high-cut filter applied to attenuate high-frequency noise",
                "leveling": "Tie-line leveling applied to remove systematic traverse biases",
            }
            correction_report[corr] = descriptions.get(corr, f"{corr} correction applied")

        # Processing quality score (heuristic)
        quality_score = 1.0
        if "igrf" not in corrections:
            quality_score -= 0.15
        if "diurnal" not in corrections:
            quality_score -= 0.1
        if stats.get("point_count", 0) < 50:
            quality_score -= 0.1
        quality_score = round(max(0.0, min(1.0, quality_score)), 2)

        data = {
            "project_name": project.get("name", ""),
            "project_context": project.get("context", ""),
            "task_name": task.get("name", ""),
            "task_description": task.get("description", ""),
            "platform": task.get("platform", "not specified"),
            "scenario": scenario,
            "processing_mode": task.get("processing_mode", "not specified"),
            "corrections_applied": corrections,
            "correction_report": correction_report,
            "model": model,
            "add_ons_enabled": add_ons,
            "derived_layers": derived_layers,
            "all_layers": all_layers,
            "available_visualisations": available_vis,
            "model_diagnostics": model_diagnostics,
            "stats": {
                "mean_nT": round(float(stats.get("mean", 0)), 3),
                "std_nT": round(float(stats.get("std", 0)), 3),
                "min_nT": round(float(stats.get("min", 0)), 3),
                "max_nT": round(float(stats.get("max", 0)), 3),
                "range_nT": round(float(stats.get("max", 0)) - float(stats.get("min", 0)), 3),
                "point_count": stats.get("point_count", 0),
                "anomaly_count": stats.get("anomaly_count", 0),
            },
            "processing_quality_score": quality_score,
            "run_status": "completed",
            "sample_stations_lat_lon_nT": sample_lines,
        }

        if ref_text:
            data["reference_document"] = ref_text[:3000]

        return (
            "INPUT DATA — use this to generate the dynamic technical deliverable:\n\n"
            + json.dumps(data, indent=2)
            + "\n\nReturn ONLY the JSON structure described in the system prompt. "
              "No markdown, no prose outside the JSON."
        )

    # ── Reference file extraction ─────────────────────────────────────────────

    _MAX_REF_CHARS = 6000

    def _extract_reference_text(self, task: dict) -> str | None:
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
                names = [el.text for el in root.iter() if el.tag.endswith("name") and el.text]
                descs = [el.text for el in root.iter() if el.tag.endswith("description") and el.text]
                text = "KML file contents:\n"
                if names:
                    text += "Names: " + ", ".join(names[:20]) + "\n"
                if descs:
                    text += "Descriptions:\n" + "\n".join(descs[:5])

            elif file_name.endswith(".kmz") or file_name.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
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
                    text = raw.decode("latin-1", errors="replace")
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
                return None

            if not text:
                return None
            return text[:self._MAX_REF_CHARS]

        except Exception:
            return None

    # ── Fallback ──────────────────────────────────────────────────────────────

    def _fallback_text(self, project: dict, task: dict, outputs: dict, location: str, question: str | None) -> str:
        stats = outputs.get("stats") or {}
        point_count = stats.get("point_count") or task.get("dataset_profile", {}).get("total_rows") or 0
        magnetic_mean = stats.get("mean")
        magnetic_range = None
        if stats.get("min") is not None and stats.get("max") is not None:
            magnetic_range = float(stats["max"]) - float(stats["min"])
        corrections = ", ".join(task.get("analysis_config", {}).get("corrections") or []) or "no explicit corrections"
        add_ons = ", ".join(task.get("analysis_config", {}).get("add_ons") or []) or "no add-ons"
        lines = [
            f"This {location} view is based on {point_count} survey points.",
            f"Enabled corrections: {corrections}. Enabled outputs: {add_ons}.",
        ]
        if magnetic_mean is not None:
            lines.append(
                f"Typical value is about {float(magnetic_mean):.2f} nT, with a spread of about {float(magnetic_range or 0):.2f} nT."
            )
        if location == "preview":
            lines.append("Use this screen to check the uploaded survey lines, predicted traverses, and whether the setup matches your plan.")
        elif location == "visualisation":
            lines.append("Focus on where values change, where they stay consistent, and where uncertainty is higher.")
        elif location == "export":
            lines.append("Use this screen to decide which files to deliver and what each one contains.")
        if question:
            lines.append(f"Question: {question}")
        return "\n".join(lines)
