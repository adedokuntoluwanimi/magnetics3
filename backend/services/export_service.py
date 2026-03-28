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

        # Pass the full GCS results (stats + points sample) so the AI has richer context
        # than the lightweight Firestore copy. Strip large grids — only metadata is needed.
        results_for_ai = {
            "stats": full_results.get("stats"),
            "model_used": full_results.get("model_used"),
            "points": full_results.get("points", [])[:50],
            "predicted_points": full_results.get("predicted_points", [])[:20],
            "selected_add_ons": full_results.get("selected_add_ons", []),
        }
        aurora = self._ai_service.generate_response(
            task["project_id"],
            task_id,
            location="export",
            question="Prepare a professional geophysical interpretation for the export deliverables.",
            extra_results=results_for_ai,
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
                data=self._build_pdf(project, task, aurora),
                kind="export",
            )
        if normalized == "word":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="report.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                data=self._build_docx(project, task, aurora),
                kind="export",
            )
        if normalized == "pptx":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="presentation.pptx",
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                data=self._build_pptx(project, task, aurora),
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

    def _build_pdf(self, project: dict, task: dict, aurora) -> bytes:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                                topMargin=20*mm, bottomMargin=20*mm)
        styles = getSampleStyleSheet()
        story = []

        h1 = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=18, spaceAfter=4)
        h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceAfter=3, spaceBefore=10)
        body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10, leading=15)
        bullet = ParagraphStyle("bullet", parent=styles["Normal"], fontSize=10, leading=14,
                                leftIndent=12, bulletIndent=0)
        meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=9, textColor=colors.grey)

        story.append(Paragraph(project["name"], h1))
        story.append(Paragraph(task["name"], styles["Heading2"]))
        story.append(Paragraph(f"Generated: {utc_now()}", meta))
        story.append(Spacer(1, 6*mm))

        if task.get("description"):
            story.append(Paragraph("Survey Description", h2))
            story.append(Paragraph(task["description"], body))
            story.append(Spacer(1, 4*mm))

        # Stats table
        results_data = task.get("results", {}).get("data", {})
        stats = results_data.get("stats") or {}
        if stats:
            story.append(Paragraph("Magnetic Statistics", h2))
            tdata = [
                ["Metric", "Value"],
                ["Mean field", f"{stats.get('mean', 0):.2f} nT"],
                ["Std deviation", f"{stats.get('std', 0):.2f} nT"],
                ["Min / Max", f"{stats.get('min', 0):.2f} / {stats.get('max', 0):.2f} nT"],
                ["Points processed", str(stats.get("point_count", 0))],
                ["Anomaly count", str(stats.get("anomaly_count", 0))],
            ]
            t = Table(tdata, colWidths=[60*mm, 80*mm])
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

        # AI analysis
        story.append(Paragraph("AI Analysis", h2))
        if aurora.summary:
            story.append(Paragraph(aurora.summary, body))
            story.append(Spacer(1, 3*mm))
        for item in aurora.highlights:
            story.append(Paragraph(f"• {item}", bullet))

        doc.build(story)
        return buffer.getvalue()

    def _build_docx(self, project: dict, task: dict, aurora) -> bytes:
        from docx import Document
        from docx.shared import Pt, RGBColor

        doc = Document()

        # Title
        title = doc.add_heading(project["name"], level=1)
        title.runs[0].font.color.rgb = RGBColor(0x1a, 0x73, 0x40)
        doc.add_heading(task["name"], level=2)
        doc.add_paragraph(f"Generated: {utc_now()}")

        # Survey description
        if task.get("description"):
            doc.add_heading("Survey Description", level=2)
            doc.add_paragraph(task["description"])

        # Configuration summary
        config = task.get("analysis_config") or {}
        doc.add_heading("Processing Configuration", level=2)
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

        # Statistics
        results_data = task.get("results", {}).get("data", {})
        stats = results_data.get("stats") or {}
        if stats:
            doc.add_heading("Magnetic Statistics", level=2)
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
                ("Anomaly count", str(stats.get("anomaly_count", 0))),
            ]:
                row = tbl.add_row().cells
                row[0].text = label
                row[1].text = val

        # AI analysis
        doc.add_heading("AI Analysis", level=2)
        if aurora.summary:
            doc.add_paragraph(aurora.summary)
        for item in aurora.highlights:
            doc.add_paragraph(item, style="List Bullet")

        output = io.BytesIO()
        doc.save(output)
        return output.getvalue()

    def _build_pptx(self, project: dict, task: dict, aurora) -> bytes:
        from pptx import Presentation
        from pptx.util import Pt

        prs = Presentation()

        def _add_slide(title_text, body_text):
            slide = prs.slides.add_slide(prs.slide_layouts[1])
            slide.shapes.title.text = title_text
            tf = slide.placeholders[1].text_frame
            tf.clear()
            for i, line in enumerate(body_text.splitlines()):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = line
                p.font.size = Pt(14)
            return slide

        config = task.get("analysis_config") or {}
        stats = task.get("results", {}).get("data", {}).get("stats") or {}
        corrections = ", ".join(config.get("corrections") or []) or "None"
        add_ons = ", ".join(config.get("add_ons") or []) or "None"
        model = config.get("model") or "Not specified"

        # Slide 1 — Title
        title_slide = prs.slides.add_slide(prs.slide_layouts[0])
        title_slide.shapes.title.text = project["name"]
        title_slide.placeholders[1].text = f"{task['name']}  |  GAIA Magnetics"

        # Slide 2 — Executive summary (AI-generated)
        _add_slide("Survey Summary", aurora.summary)

        # Slide 3 — AI highlights / anomaly observations
        if aurora.highlights:
            _add_slide("Key Findings", "\n".join(f"• {h}" for h in aurora.highlights))

        # Slide 4 — Processing configuration
        _add_slide(
            "Processing Configuration",
            f"Model:  {model}\n"
            f"Corrections:  {corrections}\n"
            f"Add-ons:  {add_ons}\n"
            f"Scenario:  {task.get('scenario', '—').capitalize()}\n"
            f"Platform:  {task.get('platform', '—').capitalize()}",
        )

        # Slide 5 — Magnetic statistics
        _add_slide(
            "Magnetic Statistics",
            f"Mean field:  {stats.get('mean', 0):.2f} nT\n"
            f"Std deviation:  {stats.get('std', 0):.2f} nT\n"
            f"Min / Max:  {stats.get('min', 0):.2f} / {stats.get('max', 0):.2f} nT\n"
            f"Points processed:  {stats.get('point_count', 0)}\n"
            f"Anomaly count (>mean+1σ):  {stats.get('anomaly_count', 0)}",
        )

        # Slide 6 — Notes / Limitations
        _add_slide(
            "Notes & Limitations",
            "• Results are model-dependent; interpretation should account for survey geometry.\n"
            "• Uncertainty surface reflects spatial data density — edge predictions carry higher uncertainty.\n"
            "• Corrections applied are listed on the Processing Configuration slide.\n"
            "• Report generated by GAIA Magnetics. Verify outputs before drilling or resource decisions.",
        )

        output = io.BytesIO()
        prs.save(output)
        return output.getvalue()
