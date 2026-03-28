from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd

from backend.logging_utils import log_event
from backend.models import ExportJob, ExportRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExportService:
    def __init__(self, store, storage_backend, ai_service) -> None:
        self._store = store
        self._storage = storage_backend
        self._ai_service = ai_service

    def _load_full_results(self, task: dict) -> dict:
        """Load the full results payload (including 2D grids) from GCS results.json."""
        artifacts = (task.get("results") or {}).get("artifacts") or []
        results_artifact = next(
            (a for a in artifacts if a.get("file_name") == "results.json"), None
        )
        if not results_artifact:
            raise ValueError("Results file not found. Run processing first.")
        data = self._storage.download_bytes(
            results_artifact["bucket"], results_artifact["object_name"]
        )
        return json.loads(data)

    def create_export(self, task_id: str, request: ExportRequest) -> dict:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")
        artifacts = (task.get("results") or {}).get("artifacts") or []
        if not any(a.get("file_name") == "results.json" for a in artifacts):
            raise ValueError("Run processing before exporting.")

        full_results = self._load_full_results(task)
        project = self._store.get_project(task["project_id"])

        # Use the comprehensive technical report generator for document exports
        aurora = self._ai_service.generate_export_report(
            task["project_id"],
            task_id,
            full_results,
        )

        job = ExportJob(task_id=task_id, formats=request.formats, status="running")
        persisted = self._store.create_export_job(job.model_dump(mode="json"))
        artifacts_out = []
        for export_format in request.formats:
            artifact = self._build_artifact(project, task, full_results, export_format, aurora)
            if artifact:
                artifacts_out.append(artifact.model_dump(mode="json"))

        completed = self._store.update_export_job(
            persisted["id"],
            {
                "status": "completed",
                "updated_at": utc_now(),
                "details": {
                    "artifacts": artifacts_out,
                    "aurora": aurora.model_dump(mode="json"),
                    "sections": request.aurora_sections,
                },
            },
        )
        existing_jobs = list(task.get("export_jobs") or [])
        existing_jobs.append(completed)
        self._store.update_task(
            task_id,
            {
                "export_jobs": existing_jobs[-10:],
                "updated_at": utc_now(),
            },
        )
        log_event("INFO", "Export completed", action="export.complete", task_id=task_id, export_job_id=completed["id"])
        return completed

    def _build_artifact(self, project: dict, task: dict, data: dict, export_format: str, aurora):
        normalized = export_format.lower()
        if normalized == "csv":
            rows = []
            for lat_row, lon_row, surface_row, uncertainty_row in zip(
                data["grid_y"],
                data["grid_x"],
                data["surface"],
                data["uncertainty"],
            ):
                for latitude, longitude, magnetic, uncertainty in zip(lat_row, lon_row, surface_row, uncertainty_row):
                    rows.append(
                        {
                            "longitude": longitude,
                            "latitude": latitude,
                            "predicted_magnetic": magnetic,
                            "uncertainty": uncertainty,
                        }
                    )
            frame = pd.DataFrame(rows)
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="export.csv",
                content_type="text/csv",
                data=frame.to_csv(index=False).encode("utf-8"),
                kind="export",
            )
        if normalized == "geojson":
            features = [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
                    "properties": {"magnetic": row["magnetic"]},
                }
                for row in data["points"]
            ]
            geojson = {"type": "FeatureCollection", "features": features}
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="export.geojson",
                content_type="application/geo+json",
                data=json.dumps(geojson).encode("utf-8"),
                kind="export",
            )
        if normalized in {"kml", "kmz"}:
            content = self._build_kml(data["points"]).encode("utf-8")
            if normalized == "kmz":
                buffer = io.BytesIO()
                with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr("doc.kml", content)
                payload = buffer.getvalue()
                file_name = "export.kmz"
                content_type = "application/vnd.google-earth.kmz"
            else:
                payload = content
                file_name = "export.kml"
                content_type = "application/vnd.google-earth.kml+xml"
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=file_name,
                content_type=content_type,
                data=payload,
                kind="export",
            )
        if normalized == "gdb":
            bundle = self._build_gdb_bundle(task)
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="export.gdb.zip",
                content_type="application/zip",
                data=bundle,
                kind="export",
            )
        if normalized == "pdf":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="report.pdf",
                content_type="application/pdf",
                data=self._build_pdf(project, task, full_results, aurora),
                kind="export",
            )
        if normalized == "word":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="report.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                data=self._build_docx(project, task, full_results, aurora),
                kind="export",
            )
        if normalized == "pptx":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="presentation.pptx",
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                data=self._build_pptx(project, task, full_results, aurora),
                kind="export",
            )
        if normalized in {"png", "jpg", "jpeg"}:
            from PIL import Image

            png_artifact = next((artifact for artifact in task["results"]["artifacts"] if artifact["file_name"] == "heatmap.png"), None)
            if not png_artifact:
                return None
            image_bytes = self._storage.download_bytes(png_artifact["bucket"], png_artifact["object_name"])
            if normalized in {"jpg", "jpeg"}:
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                output = io.BytesIO()
                image.save(output, format="JPEG", quality=92)
                image_bytes = output.getvalue()
                file_name = "heatmap.jpg"
                content_type = "image/jpeg"
            else:
                file_name = "heatmap.png"
                content_type = "image/png"
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=file_name,
                content_type=content_type,
                data=image_bytes,
                kind="export",
            )
        return None

    def _build_kml(self, points: list[dict]) -> str:
        placemarks = []
        for row in points:
            placemarks.append(
                f"<Placemark><name>{row['magnetic']}</name><Point><coordinates>{row['longitude']},{row['latitude']},0</coordinates></Point></Placemark>"
            )
        return (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<kml xmlns='http://www.opengis.net/kml/2.2'><Document>"
            + "".join(placemarks)
            + "</Document></kml>"
        )

    def _build_gdb_bundle(self, task: dict) -> bytes:
        buffer = io.BytesIO()
        rows = []
        data = task["results"]["data"]
        for lat_row, lon_row, surface_row, uncertainty_row in zip(
            data["grid_y"],
            data["grid_x"],
            data["surface"],
            data["uncertainty"],
        ):
            for latitude, longitude, magnetic, uncertainty in zip(lat_row, lon_row, surface_row, uncertainty_row):
                rows.append(
                    {
                        "longitude": longitude,
                        "latitude": latitude,
                        "predicted_magnetic": magnetic,
                        "uncertainty": uncertainty,
                    }
                )
        csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
        geojson_bytes = json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
                        "properties": {"magnetic": row["magnetic"]},
                    }
                    for row in data["points"]
                ],
            }
        ).encode("utf-8")
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("gaia_export.gdb/stations.geojson", geojson_bytes)
            archive.writestr("gaia_export.gdb/grid.csv", csv_bytes)
            archive.writestr(
                "gaia_export.gdb/README.txt",
                "Bundle contains geospatial layers and grid attributes prepared for downstream GIS ingestion.",
            )
        return buffer.getvalue()

    # ── Image helpers ─────────────────────────────────────────────────────────

    def _try_get_image_bytes(self, task: dict, file_name: str) -> bytes | None:
        """Download a named image artifact from GCS; return None if not found."""
        artifacts = (task.get("results") or {}).get("artifacts") or []
        artifact = next((a for a in artifacts if a.get("file_name") == file_name), None)
        if not artifact:
            return None
        try:
            return self._storage.download_bytes(artifact["bucket"], artifact["object_name"])
        except Exception:
            return None

    # ── PDF ───────────────────────────────────────────────────────────────────

    def _build_pdf(self, project: dict, task: dict, full_results: dict, aurora) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, KeepTogether
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                                topMargin=20*mm, bottomMargin=20*mm)
        styles = getSampleStyleSheet()

        h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=4)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceAfter=3, spaceBefore=12)
        h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=11, spaceAfter=2, spaceBefore=8)
        body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=15)
        bullet_s = ParagraphStyle("bullet", parent=styles["Normal"], fontSize=10, leading=14,
                                  leftIndent=14, bulletIndent=0)
        fig_cap = ParagraphStyle("figcap", parent=styles["Normal"], fontSize=9, leading=12,
                                 textColor=colors.HexColor("#444444"), leftIndent=8, spaceBefore=2)
        meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=9, textColor=colors.grey)
        fig_placeholder = ParagraphStyle("figph", parent=styles["Normal"], fontSize=10,
                                         backColor=colors.HexColor("#f0f4f0"),
                                         borderColor=colors.HexColor("#1a7340"),
                                         borderWidth=0.5, borderPadding=8, spaceAfter=4)

        story = []

        # ── Title block ──
        story.append(Paragraph(project.get("name", "Magnetic Survey Report"), h1))
        story.append(Paragraph(task.get("name", ""), styles["Heading2"]))
        story.append(Paragraph(f"Generated: {utc_now()}  |  GAIA Magnetics", meta))
        story.append(Spacer(1, 6*mm))

        rd = aurora.report_data or {}
        report = rd.get("report", {})

        def _add_section(heading, text):
            if text:
                story.append(Paragraph(heading, h2))
                for para in str(text).split("\n\n"):
                    stripped = para.strip()
                    if stripped:
                        story.append(Paragraph(stripped.replace("\n", " "), body))
                story.append(Spacer(1, 3*mm))

        def _add_figure(task_obj, file_name, caption):
            img_bytes = self._try_get_image_bytes(task_obj, file_name)
            if img_bytes:
                story.append(RLImage(io.BytesIO(img_bytes), width=150*mm, height=90*mm))
                story.append(Paragraph(caption, fig_cap))
            else:
                story.append(Paragraph(f"[ Figure: {caption} ]", fig_placeholder))
            story.append(Spacer(1, 4*mm))

        def _add_stats_table(stats: dict):
            if not stats:
                return
            tdata = [
                ["Metric", "Value"],
                ["Mean field", f"{stats.get('mean', 0):.2f} nT"],
                ["Std deviation", f"{stats.get('std', 0):.2f} nT"],
                ["Min / Max", f"{stats.get('min', 0):.2f} / {stats.get('max', 0):.2f} nT"],
                ["Points processed", str(stats.get("point_count", 0))],
                ["Anomaly count (>mean+1σ)", str(stats.get("anomaly_count", 0))],
            ]
            t = Table(tdata, colWidths=[65*mm, 80*mm])
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a7340")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]))
            story.append(t)
            story.append(Spacer(1, 4*mm))

        # ── Executive Summary ──
        exec_summary = rd.get("executive_summary") or aurora.summary
        if exec_summary:
            story.append(Paragraph("Executive Summary", h2))
            story.append(Paragraph(exec_summary, body))
            story.append(Spacer(1, 4*mm))

        # ── Project Overview ──
        _add_section("Project Overview", report.get("project_overview"))

        # ── Data Description ──
        _add_section("Data Description", report.get("data_description"))

        # ── Processing Workflow (dynamic — only active steps) ──
        workflow = report.get("processing_workflow")
        if workflow and isinstance(workflow, dict):
            story.append(Paragraph("Processing Workflow", h2))
            for step_name, step_text in workflow.items():
                story.append(Paragraph(step_name.replace("_", " ").title(), h3))
                story.append(Paragraph(str(step_text), body))
            story.append(Spacer(1, 3*mm))

        # ── Results & Interpretation — visual-first ──
        results_interp = report.get("results_interpretation")
        if results_interp:
            story.append(Paragraph("Results & Interpretation", h2))
            image_map = {
                "total magnetic field": "heatmap.png",
                "tmf": "heatmap.png",
                "magnetic surface": "heatmap.png",
                "contour": "contour.png",
                "magnetic contours": "contour.png",
                "surface": "surface.png",
            }
            for layer in results_interp:
                layer_name = layer.get("layer", "Layer")
                story.append(Paragraph(layer_name, h3))
                # Try to insert actual image
                img_key = layer_name.lower()
                img_file = image_map.get(img_key)
                if img_file:
                    _add_figure(task, img_file, f"Figure: {layer_name} Map")
                else:
                    story.append(Paragraph(f"[ Insert {layer_name} Map Here ]", fig_placeholder))
                    story.append(Spacer(1, 3*mm))
                for label, key in [("Description", "description"), ("Observations", "observations"),
                                    ("Interpretation", "interpretation"), ("Implication", "implication")]:
                    val = layer.get(key, "")
                    if val:
                        story.append(Paragraph(f"<b>{label}:</b> {val}", body))
                story.append(Spacer(1, 4*mm))

        # ── Modelling & Prediction ──
        _add_section("Modelling & Prediction", report.get("modelling"))

        # ── Magnetic Statistics table ──
        stats = full_results.get("stats") or {}
        story.append(Paragraph("Magnetic Statistics", h2))
        _add_stats_table(stats)

        # ── Data Quality & Reliability ──
        _add_section("Data Quality & Reliability", report.get("data_quality"))

        # ── Conclusions ──
        conclusions = report.get("conclusions") or ""
        if conclusions:
            story.append(Paragraph("Conclusions", h2))
            for pt in str(conclusions).split("\n"):
                pt = pt.strip().lstrip("•-*").strip()
                if pt:
                    story.append(Paragraph(f"• {pt}", bullet_s))
            story.append(Spacer(1, 3*mm))

        # ── Recommendations ──
        recommendations = report.get("recommendations") or ""
        if recommendations:
            story.append(Paragraph("Recommendations", h2))
            for pt in str(recommendations).split("\n"):
                pt = pt.strip().lstrip("•-*").strip()
                if pt:
                    story.append(Paragraph(f"• {pt}", bullet_s))

        # Fallback: use aurora.highlights if report_data was not available
        if not rd and aurora.highlights:
            story.append(Paragraph("Key Findings", h2))
            for item in aurora.highlights:
                story.append(Paragraph(f"• {item}", bullet_s))

        doc.build(story)
        return buffer.getvalue()

    # ── DOCX ──────────────────────────────────────────────────────────────────

    def _build_docx(self, project: dict, task: dict, full_results: dict, aurora) -> bytes:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches, Cm

        doc = Document()

        rd = aurora.report_data or {}
        report = rd.get("report", {})
        config = task.get("analysis_config") or {}
        stats = full_results.get("stats") or {}

        def _add_section_heading(text, level=2):
            doc.add_heading(text, level=level)

        def _add_body_text(text):
            if not text:
                return
            for para in str(text).split("\n\n"):
                stripped = para.strip()
                if stripped:
                    doc.add_paragraph(stripped.replace("\n", " "))

        def _add_bullet_list(text):
            if not text:
                return
            for pt in str(text).split("\n"):
                pt = pt.strip().lstrip("•-*").strip()
                if pt:
                    doc.add_paragraph(pt, style="List Bullet")

        def _add_figure_placeholder(layer_name, task_obj):
            image_map = {
                "total magnetic field": "heatmap.png",
                "tmf": "heatmap.png",
                "magnetic surface": "heatmap.png",
                "contour": "contour.png",
                "magnetic contours": "contour.png",
                "surface": "surface.png",
            }
            img_key = layer_name.lower()
            img_file = image_map.get(img_key)
            img_bytes = self._try_get_image_bytes(task_obj, img_file) if img_file else None
            if img_bytes:
                doc.add_picture(io.BytesIO(img_bytes), width=Inches(5.5))
                cap = doc.add_paragraph(f"Figure: {layer_name} Map")
                cap.runs[0].italic = True
            else:
                ph = doc.add_paragraph(f"[ Insert {layer_name} Map Here ]")
                ph.runs[0].bold = True
                ph.runs[0].font.color.rgb = RGBColor(0x1a, 0x73, 0x40)

        # ── Title ──
        title = doc.add_heading(project.get("name", "Magnetic Survey Report"), level=1)
        if title.runs:
            title.runs[0].font.color.rgb = RGBColor(0x1a, 0x73, 0x40)
        doc.add_heading(task.get("name", ""), level=2)
        doc.add_paragraph(f"Generated: {utc_now()}")

        # ── Executive Summary ──
        exec_summary = rd.get("executive_summary") or aurora.summary
        if exec_summary:
            _add_section_heading("Executive Summary")
            _add_body_text(exec_summary)

        # ── Project Overview ──
        if report.get("project_overview"):
            _add_section_heading("Project Overview")
            _add_body_text(report["project_overview"])

        # ── Data Description ──
        if report.get("data_description"):
            _add_section_heading("Data Description")
            _add_body_text(report["data_description"])

        # ── Processing Workflow ──
        workflow = report.get("processing_workflow")
        if workflow and isinstance(workflow, dict):
            _add_section_heading("Processing Workflow")
            for step_name, step_text in workflow.items():
                doc.add_heading(step_name.replace("_", " ").title(), level=3)
                _add_body_text(str(step_text))

        # ── Processing Configuration (always) ──
        _add_section_heading("Processing Configuration")
        cfg_para = doc.add_paragraph()
        for label, val in [
            ("Model", config.get("model") or "—"),
            ("Corrections", ", ".join(config.get("corrections") or []) or "None"),
            ("Add-ons", ", ".join(config.get("add_ons") or []) or "None"),
            ("Scenario", task.get("scenario") or "—"),
            ("Platform", task.get("platform") or "—"),
        ]:
            run = cfg_para.add_run(f"{label}: ")
            run.bold = True
            cfg_para.add_run(f"{val}\n")

        # ── Results & Interpretation ──
        results_interp = report.get("results_interpretation")
        if results_interp:
            _add_section_heading("Results & Interpretation")
            for layer in results_interp:
                layer_name = layer.get("layer", "Layer")
                doc.add_heading(layer_name, level=3)
                _add_figure_placeholder(layer_name, task)
                for label, key in [("Description", "description"), ("Observations", "observations"),
                                    ("Interpretation", "interpretation"), ("Implication", "implication")]:
                    val = layer.get(key, "")
                    if val:
                        p = doc.add_paragraph()
                        run = p.add_run(f"{label}: ")
                        run.bold = True
                        p.add_run(str(val))

        # ── Modelling & Prediction ──
        if report.get("modelling"):
            _add_section_heading("Modelling & Prediction")
            _add_body_text(report["modelling"])

        # ── Magnetic Statistics ──
        _add_section_heading("Magnetic Statistics")
        tbl = doc.add_table(rows=1, cols=2)
        tbl.style = "Table Grid"
        hdr = tbl.rows[0].cells
        hdr[0].text = "Metric"
        hdr[1].text = "Value"
        for label, val in [
            ("Mean field", f"{stats.get('mean', 0):.2f} nT"),
            ("Std deviation", f"{stats.get('std', 0):.2f} nT"),
            ("Min / Max", f"{stats.get('min', 0):.2f} / {stats.get('max', 0):.2f} nT"),
            ("Points processed", str(stats.get("point_count", 0))),
            ("Anomaly count (>mean+1σ)", str(stats.get("anomaly_count", 0))),
        ]:
            row = tbl.add_row().cells
            row[0].text = label
            row[1].text = val

        # ── Data Quality ──
        if report.get("data_quality"):
            _add_section_heading("Data Quality & Reliability")
            _add_body_text(report["data_quality"])

        # ── Conclusions ──
        if report.get("conclusions"):
            _add_section_heading("Conclusions")
            _add_bullet_list(report["conclusions"])

        # ── Recommendations ──
        if report.get("recommendations"):
            _add_section_heading("Recommendations")
            _add_bullet_list(report["recommendations"])

        # Fallback
        if not rd and aurora.highlights:
            _add_section_heading("Key Findings")
            for item in aurora.highlights:
                doc.add_paragraph(item, style="List Bullet")

        output = io.BytesIO()
        doc.save(output)
        return output.getvalue()

    # ── PPTX ──────────────────────────────────────────────────────────────────

    def _build_pptx(self, project: dict, task: dict, full_results: dict, aurora) -> bytes:
        from pptx import Presentation
        from pptx.util import Pt, Inches, Emu
        from pptx.dml.color import RGBColor as PPTXColor

        prs = Presentation()
        rd = aurora.report_data or {}
        slides_data = rd.get("slides") or []
        config = task.get("analysis_config") or {}
        stats = full_results.get("stats") or {}

        def _add_content_slide(title_text, bullets, notes=""):
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = title_text
            tf = slide.placeholders[1].text_frame
            tf.clear()
            for i, line in enumerate(bullets):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = str(line).lstrip("•-* ").strip()
                p.font.size = Pt(14)
            if notes:
                slide.notes_slide.notes_text_frame.text = notes
            return slide

        # ── Title slide ──
        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = project.get("name", "Magnetic Survey")
        title_slide.placeholders[1].text = f"{task.get('name', '')}  |  GAIA Magnetics"

        if slides_data:
            # Use AI-generated slide structure
            for sl in slides_data:
                if not isinstance(sl, dict):
                    continue
                title_text = sl.get("title", "")
                bullets = sl.get("bullets") or []
                notes = sl.get("speaker_notes") or sl.get("notes") or ""
                if title_text:
                    _add_content_slide(title_text, bullets, notes)
        else:
            # Fallback structure using aurora highlights
            exec_summary = rd.get("executive_summary") or aurora.summary
            if exec_summary:
                _add_content_slide("Survey Summary", [exec_summary[:300]])

            if aurora.highlights:
                _add_content_slide("Key Findings", [f"• {h}" for h in aurora.highlights])

            corrections = ", ".join(config.get("corrections") or []) or "None"
            add_ons = ", ".join(config.get("add_ons") or []) or "None"
            model = config.get("model") or "Not specified"
            _add_content_slide(
                "Processing Configuration",
                [
                    f"Model: {model}",
                    f"Corrections: {corrections}",
                    f"Add-ons: {add_ons}",
                    f"Scenario: {task.get('scenario', '—').capitalize()}",
                    f"Platform: {task.get('platform', '—').capitalize()}",
                ],
            )
            _add_content_slide(
                "Magnetic Statistics",
                [
                    f"Mean field: {stats.get('mean', 0):.2f} nT",
                    f"Std deviation: {stats.get('std', 0):.2f} nT",
                    f"Min / Max: {stats.get('min', 0):.2f} / {stats.get('max', 0):.2f} nT",
                    f"Points processed: {stats.get('point_count', 0)}",
                    f"Anomaly count (>mean+1σ): {stats.get('anomaly_count', 0)}",
                ],
            )
            _add_content_slide(
                "Notes & Limitations",
                [
                    "Results are model-dependent; account for survey geometry in interpretation.",
                    "Edge predictions carry higher uncertainty due to sparse control.",
                    "Corrections applied are listed on the Processing Configuration slide.",
                    "Verify outputs before drilling or resource decisions.",
                ],
            )

        output = io.BytesIO()
        prs.save(output)
        return output.getvalue()
