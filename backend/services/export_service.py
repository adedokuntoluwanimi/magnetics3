from __future__ import annotations

import io
import json
import re
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
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}_csv_bundle.zip",
                content_type="application/zip",
                data=self._build_csv_bundle(project, task, data),
                kind="export",
            )
        if normalized == "geojson":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}_geojson_bundle.zip",
                content_type="application/zip",
                data=self._build_geojson_bundle(project, task, data),
                kind="export",
            )
        if normalized in {"kml", "kmz"}:
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}_kmz_bundle.zip",
                content_type="application/zip",
                data=self._build_kmz_bundle(project, task, data),
                kind="export",
            )
        if normalized == "gdb":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}_gdb_bundle.zip",
                content_type="application/zip",
                data=self._build_gdb_bundle(project, task, data),
                kind="export",
            )
        if normalized == "pdf":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}.pdf",
                content_type="application/pdf",
                data=self._build_pdf(project, task, data, aurora),
                kind="export",
            )
        if normalized == "word":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                data=self._build_docx(project, task, data, aurora),
                kind="export",
            )
        if normalized == "pptx":
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}.pptx",
                content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                data=self._build_pptx(project, task, data, aurora),
                kind="export",
            )
        if normalized in {"png", "jpg", "jpeg"}:
            return self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name=f"{self._artifact_stem(task, project)}_map_bundle.zip",
                content_type="application/zip",
                data=self._build_raster_bundle(project, task),
                kind="export",
            )
        return None

    def _artifact_stem(self, task: dict, project: dict) -> str:
        raw = f"{task.get('name', 'task')}_{project.get('name', 'project')}"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
        return (safe or "gaia_export").lower()

    def _layer_specs(self, data: dict) -> list[dict]:
        specs = [
            {"key": "surface", "slug": "tmf", "label": "Total Magnetic Field"},
            {"key": "corrected_field", "slug": "corrected_field", "label": "Corrected Magnetic Field"},
            {"key": "uncertainty", "slug": "uncertainty", "label": "Uncertainty"},
            {"key": "filtered_surface", "slug": "filtered_surface", "label": "Filtered Surface"},
            {"key": "rtp_surface", "slug": "rtp", "label": "Reduction to Pole"},
            {"key": "analytic_signal", "slug": "analytic_signal", "label": "Analytic Signal"},
            {"key": "first_vertical_derivative", "slug": "first_vertical_derivative", "label": "First Vertical Derivative"},
            {"key": "horizontal_derivative", "slug": "horizontal_derivative", "label": "Horizontal Derivative"},
            {"key": "regional_field", "slug": "regional_field", "label": "Regional Field"},
            {"key": "regional_surface", "slug": "regional_field", "label": "Regional Field"},
            {"key": "regional_residual", "slug": "regional_residual", "label": "Regional Residual"},
            {"key": "residual_surface", "slug": "regional_residual", "label": "Regional Residual"},
            {"key": "emag2_residual", "slug": "regional_residual", "label": "Regional Residual"},
            {"key": "tilt_derivative", "slug": "tilt_derivative", "label": "Tilt Derivative"},
            {"key": "total_gradient", "slug": "total_gradient", "label": "Total Gradient"},
        ]
        active = []
        seen = set()
        for spec in specs:
            if data.get(spec["key"]) is not None and spec["slug"] not in seen:
                active.append(spec)
                seen.add(spec["slug"])
        return active

    def _grid_rows(self, data: dict, key: str, value_field: str) -> list[dict]:
        rows = []
        grid_x = data.get("grid_x") or []
        grid_y = data.get("grid_y") or []
        values = data.get(key) or []
        for lat_row, lon_row, value_row in zip(grid_y, grid_x, values):
            for latitude, longitude, value in zip(lat_row, lon_row, value_row):
                rows.append({"longitude": longitude, "latitude": latitude, value_field: value})
        return rows

    def _point_rows(self, points: list[dict]) -> list[dict]:
        rows = []
        for point in points or []:
            row = dict(point)
            rows.append(row)
        return rows

    def _point_value(self, point: dict):
        for key in ("magnetic", "corrected_magnetic", "predicted_magnetic", "value"):
            if point.get(key) is not None:
                return point.get(key)
        return None

    def _points_geojson(self, points: list[dict], *, value_field: str = "magnetic") -> dict:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [row["longitude"], row["latitude"]]},
                    "properties": {
                        **{k: v for k, v in row.items() if k not in {"longitude", "latitude"}},
                        value_field: row.get(value_field, self._point_value(row)),
                    },
                }
                for row in points
                if row.get("longitude") is not None and row.get("latitude") is not None
            ],
        }

    def _traverse_geojson(self, points: list[dict]) -> dict:
        groups = {}
        for point in points or []:
            line_id = point.get("line_id") or point.get("traverse_label") or "line"
            groups.setdefault(str(line_id), []).append(point)
        features = []
        for line_id, group in groups.items():
            coords = [
                [point.get("longitude"), point.get("latitude")]
                for point in group
                if point.get("longitude") is not None and point.get("latitude") is not None
            ]
            if len(coords) >= 2:
                features.append(
                    {
                        "type": "Feature",
                        "geometry": {"type": "LineString", "coordinates": coords},
                        "properties": {"line_id": line_id},
                    }
                )
        return {"type": "FeatureCollection", "features": features}

    def _build_kml(self, points: list[dict], *, name: str, value_field: str = "magnetic") -> str:
        placemarks = []
        for row in points or []:
            longitude = row.get("longitude")
            latitude = row.get("latitude")
            if longitude is None or latitude is None:
                continue
            value = row.get(value_field, self._point_value(row))
            placemarks.append(
                "<Placemark>"
                f"<name>{value if value is not None else name}</name>"
                f"<description>{name}</description>"
                f"<Point><coordinates>{longitude},{latitude},0</coordinates></Point>"
                "</Placemark>"
            )
        return (
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<kml xmlns='http://www.opengis.net/kml/2.2'><Document>"
            f"<name>{name}</name>"
            + "".join(placemarks)
            + "</Document></kml>"
        )

    def _build_csv_bundle(self, project: dict, task: dict, data: dict) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata/project.json", json.dumps({"project": project, "task": task}, default=str, indent=2))
            archive.writestr("metadata/qa_report.json", json.dumps(data.get("qa_report") or {}, indent=2))
            archive.writestr("metadata/validation_summary.json", json.dumps(data.get("validation_summary") or {}, indent=2))
            archive.writestr("metadata/model_metadata.json", json.dumps(data.get("model_metadata") or {}, indent=2))
            archive.writestr("metadata/uncertainty_metadata.json", json.dumps(data.get("uncertainty_metadata") or {}, indent=2))
            archive.writestr("points/measured/measured_points.csv", pd.DataFrame(self._point_rows(data.get("points") or [])).to_csv(index=False))
            if data.get("predicted_points"):
                archive.writestr("points/predicted/predicted_points.csv", pd.DataFrame(self._point_rows(data["predicted_points"])).to_csv(index=False))
            for spec in self._layer_specs(data):
                rows = self._grid_rows(data, spec["key"], spec["slug"])
                if rows:
                    archive.writestr(f"analysis/{spec['slug']}/grid.csv", pd.DataFrame(rows).to_csv(index=False))
            archive.writestr("traverses/traverses.csv", pd.DataFrame(self._point_rows(data.get("points") or [])).to_csv(index=False))
            archive.writestr("README.txt", "CSV bundle contains task metadata, measured and predicted points, and one folder per exported analysis layer.")
        return buffer.getvalue()

    def _build_geojson_bundle(self, project: dict, task: dict, data: dict) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata/project.json", json.dumps({"project": project, "task": task}, default=str, indent=2))
            archive.writestr("points/measured/measured_points.geojson", json.dumps(self._points_geojson(data.get("points") or [])))
            if data.get("predicted_points"):
                archive.writestr("points/predicted/predicted_points.geojson", json.dumps(self._points_geojson(data["predicted_points"], value_field="predicted_magnetic")))
            archive.writestr("traverses/traverses.geojson", json.dumps(self._traverse_geojson(data.get("points") or [])))
            for spec in self._layer_specs(data):
                rows = self._grid_rows(data, spec["key"], spec["slug"])
                if rows:
                    archive.writestr(f"analysis/{spec['slug']}/grid.geojson", json.dumps(self._points_geojson(rows, value_field=spec["slug"])))
            archive.writestr("README.txt", "GeoJSON bundle contains structured folders for measured data, predicted data, traverses, and each generated analysis layer.")
        return buffer.getvalue()

    def _build_kmz_bundle(self, project: dict, task: dict, data: dict) -> bytes:
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata/project.json", json.dumps({"project": project, "task": task}, default=str, indent=2))
            archive.writestr("points/measured/measured_points.kml", self._build_kml(data.get("points") or [], name=f"{project.get('name', 'Project')} measured points"))
            if data.get("predicted_points"):
                archive.writestr(
                    "points/predicted/predicted_points.kml",
                    self._build_kml(data["predicted_points"], name=f"{project.get('name', 'Project')} predicted points", value_field="predicted_magnetic"),
                )
            for spec in self._layer_specs(data):
                rows = self._grid_rows(data, spec["key"], spec["slug"])
                if rows:
                    archive.writestr(f"analysis/{spec['slug']}/{spec['slug']}.kml", self._build_kml(rows, name=spec["label"], value_field=spec["slug"]))
            kmz_buffer = io.BytesIO()
            with zipfile.ZipFile(kmz_buffer, "w", zipfile.ZIP_DEFLATED) as kmz:
                kmz.writestr("doc.kml", self._build_kml(data.get("points") or [], name=f"{project.get('name', 'Project')} measured points"))
            archive.writestr("overview/google_earth_overview.kmz", kmz_buffer.getvalue())
            archive.writestr("README.txt", "KMZ bundle contains structured KML/KMZ outputs for each generated analysis layer.")
        return outer.getvalue()

    def _build_gdb_bundle(self, project: dict, task: dict, data: dict) -> bytes:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("gaia_export.gdb/metadata/project.json", json.dumps({"project": project, "task": task}, default=str, indent=2))
            archive.writestr("gaia_export.gdb/points/measured_points.geojson", json.dumps(self._points_geojson(data.get("points") or [])))
            if data.get("predicted_points"):
                archive.writestr("gaia_export.gdb/points/predicted_points.geojson", json.dumps(self._points_geojson(data["predicted_points"], value_field="predicted_magnetic")))
            archive.writestr("gaia_export.gdb/traverses/traverses.geojson", json.dumps(self._traverse_geojson(data.get("points") or [])))
            for spec in self._layer_specs(data):
                rows = self._grid_rows(data, spec["key"], spec["slug"])
                if rows:
                    archive.writestr(f"gaia_export.gdb/analysis/{spec['slug']}/{spec['slug']}.csv", pd.DataFrame(rows).to_csv(index=False))
                    archive.writestr(f"gaia_export.gdb/analysis/{spec['slug']}/{spec['slug']}.geojson", json.dumps(self._points_geojson(rows, value_field=spec["slug"])))
            archive.writestr("gaia_export.gdb/metadata/qa_report.json", json.dumps(data.get("qa_report") or {}, indent=2))
            archive.writestr(
                "gaia_export.gdb/README.txt",
                "Bundle contains measured points, predicted points, traverses, and one analysis folder per generated output layer.",
            )
        return buffer.getvalue()

    def _build_raster_bundle(self, project: dict, task: dict) -> bytes:
        from PIL import Image

        buffer = io.BytesIO()
        image_names = [
            "heatmap.png",
            "contour.png",
            "surface.png",
            "regional_heatmap.png",
            "regional_contour.png",
            "regional_surface.png",
            "residual_heatmap.png",
            "residual_contour.png",
            "residual_surface.png",
        ]
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("metadata/project.json", json.dumps({"project": project, "task": task}, default=str, indent=2))
            for image_name in image_names:
                image_bytes = self._try_get_image_bytes(task, image_name)
                if not image_bytes:
                    continue
                archive.writestr(f"images/png/{image_name}", image_bytes)
                jpg_output = io.BytesIO()
                Image.open(io.BytesIO(image_bytes)).convert("RGB").save(jpg_output, format="JPEG", quality=92)
                archive.writestr(f"images/jpg/{image_name.replace('.png', '.jpg')}", jpg_output.getvalue())
            archive.writestr("README.txt", f"Raster bundle for {project.get('name', 'project')} includes generated map images grouped by image format.")
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
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage
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
        hero = ParagraphStyle("hero", parent=styles["Normal"], fontSize=12, leading=17, textColor=colors.white)

        story = []
        title_block = Table(
            [[Paragraph(f"<b>{project.get('name', 'Magnetic Survey Report')}</b><br/>{task.get('name', '')}", hero)]],
            colWidths=[170 * mm],
        )
        title_block.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#153a2d")),
            ("LEFTPADDING", (0, 0), (-1, -1), 16),
            ("RIGHTPADDING", (0, 0), (-1, -1), 16),
            ("TOPPADDING", (0, 0), (-1, -1), 18),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ]))
        story.append(title_block)
        story.append(Spacer(1, 3*mm))

        # ── Title block ──
        story.append(Paragraph(f"Generated: {utc_now()}  |  Aurora AI document engine", meta))
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
            summary_card = Table([[Paragraph(exec_summary, body)]], colWidths=[170 * mm])
            summary_card.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef6f1")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#1a7340")),
                ("LEFTPADDING", (0, 0), (-1, -1), 12),
                ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ("TOPPADDING", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ]))
            story.append(summary_card)
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
                "corrected magnetic field": "heatmap.png",
                "magnetic surface": "heatmap.png",
                "contour": "contour.png",
                "magnetic contours": "contour.png",
                "surface": "surface.png",
                "regional field": "regional_heatmap.png",
                "regional magnetic field": "regional_heatmap.png",
                "regional magnetic contours": "regional_contour.png",
                "regional magnetic surface": "regional_surface.png",
                "regional residual": "residual_heatmap.png",
                "residual magnetic field": "residual_heatmap.png",
                "residual magnetic contours": "residual_contour.png",
                "residual magnetic surface": "residual_surface.png",
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
                "corrected magnetic field": "heatmap.png",
                "magnetic surface": "heatmap.png",
                "contour": "contour.png",
                "magnetic contours": "contour.png",
                "surface": "surface.png",
                "regional field": "regional_heatmap.png",
                "regional magnetic field": "regional_heatmap.png",
                "regional magnetic contours": "regional_contour.png",
                "regional magnetic surface": "regional_surface.png",
                "regional residual": "residual_heatmap.png",
                "residual magnetic field": "residual_heatmap.png",
                "residual magnetic contours": "residual_contour.png",
                "residual magnetic surface": "residual_surface.png",
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
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls

        cover = doc.add_table(rows=1, cols=1)
        cover.style = "Table Grid"
        cover_cell = cover.cell(0, 0)
        cover_cell.text = ""
        cover_para = cover_cell.paragraphs[0]
        cover_title = cover_para.add_run(project.get("name", "Magnetic Survey Report") + "\n")
        cover_title.bold = True
        cover_title.font.size = Pt(22)
        cover_title.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        cover_sub = cover_para.add_run(task.get("name", ""))
        cover_sub.font.size = Pt(13)
        cover_sub.font.color.rgb = RGBColor(0xE6, 0xF4, 0xEA)
        cover_cell._tc.get_or_add_tcPr().append(parse_xml(r'<w:shd {} w:fill="153A2D"/>'.format(nsdecls('w'))))
        doc.add_paragraph(f"Generated: {utc_now()} | Aurora AI document engine")

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
        from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Pt, Inches
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

        def _apply_slide_background(slide, *, dark=False):
            slide.background.fill.solid()
            slide.background.fill.fore_color.rgb = PPTXColor(0x15, 0x3A, 0x2D) if dark else PPTXColor(0xF5, 0xF7, 0xF4)
            band = slide.shapes.add_shape(MSO_AUTO_SHAPE_TYPE.RECTANGLE, Inches(0), Inches(0), Inches(13.33), Inches(0.55))
            band.fill.solid()
            band.fill.fore_color.rgb = PPTXColor(0x15, 0x3A, 0x2D)
            band.line.fill.background()

        def _figure_file_for_ref(visual_ref):
            ref = str(visual_ref or "").lower()
            if "regional" in ref and "residual" not in ref:
                if "contour" in ref:
                    return "regional_contour.png"
                if "3d" in ref or "surface" in ref:
                    return "regional_surface.png"
                return "regional_heatmap.png"
            if "residual" in ref:
                if "contour" in ref:
                    return "residual_contour.png"
                if "3d" in ref or "surface" in ref:
                    return "residual_surface.png"
                return "residual_heatmap.png"
            if "contour" in ref:
                return "contour.png"
            if "3d" in ref or "surface" in ref:
                return "surface.png"
            return "heatmap.png"

        def _add_designed_slide(title_text, bullets, notes="", visual_ref=None):
            slide = prs.slides.add_slide(prs.slide_layouts[6])
            _apply_slide_background(slide)
            title_box = slide.shapes.add_textbox(Inches(0.65), Inches(0.72), Inches(6.1), Inches(0.8))
            title_frame = title_box.text_frame
            title_run = title_frame.paragraphs[0].add_run()
            title_run.text = title_text
            title_run.font.size = Pt(24)
            title_run.font.bold = True
            title_run.font.color.rgb = PPTXColor(0x15, 0x3A, 0x2D)
            body_box = slide.shapes.add_textbox(Inches(0.7), Inches(1.65), Inches(5.2), Inches(4.9))
            tf = body_box.text_frame
            tf.word_wrap = True
            for i, line in enumerate(bullets[:5]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.text = str(line).lstrip("â€¢-* ").strip()
                p.font.size = Pt(16)
                p.font.color.rgb = PPTXColor(0x2E, 0x3C, 0x36)
                p.space_after = Pt(9)
            image_name = _figure_file_for_ref(visual_ref)
            image_bytes = self._try_get_image_bytes(task, image_name) if image_name else None
            if image_bytes:
                slide.shapes.add_picture(io.BytesIO(image_bytes), Inches(6.2), Inches(1.5), width=Inches(6.2), height=Inches(3.8))
            else:
                placeholder = slide.shapes.add_textbox(Inches(6.2), Inches(1.5), Inches(6.0), Inches(3.7))
                placeholder.fill.solid()
                placeholder.fill.fore_color.rgb = PPTXColor(0xE7, 0xEF, 0xEA)
                placeholder.line.color.rgb = PPTXColor(0x15, 0x3A, 0x2D)
                frame = placeholder.text_frame
                frame.paragraphs[0].alignment = PP_ALIGN.CENTER
                run = frame.paragraphs[0].add_run()
                run.text = visual_ref or "Map"
                run.font.size = Pt(18)
                run.font.bold = True
                run.font.color.rgb = PPTXColor(0x15, 0x3A, 0x2D)
            if notes:
                slide.notes_slide.notes_text_frame.text = notes
            return slide

        # ── Title slide ──
        title_slide = prs.slides.add_slide(prs.slide_layouts[6])
        _apply_slide_background(title_slide, dark=True)
        title_box = title_slide.shapes.add_textbox(Inches(0.8), Inches(1.0), Inches(8.3), Inches(1.2))
        title_frame = title_box.text_frame
        title_run = title_frame.paragraphs[0].add_run()
        title_run.text = project.get("name", "Magnetic Survey")
        title_run.font.size = Pt(28)
        title_run.font.bold = True
        title_run.font.color.rgb = PPTXColor(0xFF, 0xFF, 0xFF)
        subtitle = title_slide.shapes.add_textbox(Inches(0.82), Inches(2.0), Inches(8.0), Inches(1.2))
        subtitle_run = subtitle.text_frame.paragraphs[0].add_run()
        subtitle_run.text = f"{task.get('name', '')} | Aurora AI"
        subtitle_run.font.size = Pt(15)
        subtitle_run.font.color.rgb = PPTXColor(0xD7, 0xE7, 0xDE)
        stats_box = title_slide.shapes.add_textbox(Inches(0.85), Inches(4.6), Inches(4.8), Inches(1.2))
        stats_frame = stats_box.text_frame
        stats_frame.paragraphs[0].add_run().text = f"{stats.get('point_count', 0)} survey points"
        stats_frame.paragraphs[0].runs[0].font.size = Pt(20)
        stats_frame.paragraphs[0].runs[0].font.bold = True
        stats_frame.paragraphs[0].runs[0].font.color.rgb = PPTXColor(0xFF, 0xFF, 0xFF)
        stats_p = stats_frame.add_paragraph()
        stats_p.text = f"Mean {stats.get('mean', 0):.2f} nT | Std {stats.get('std', 0):.2f} nT"
        stats_p.font.size = Pt(13)
        stats_p.font.color.rgb = PPTXColor(0xD7, 0xE7, 0xDE)
        hero_image = self._try_get_image_bytes(task, "heatmap.png")
        if hero_image:
            title_slide.shapes.add_picture(io.BytesIO(hero_image), Inches(7.25), Inches(0.95), width=Inches(5.0), height=Inches(5.0))

        if slides_data:
            # Use AI-generated slide structure
            for sl in slides_data:
                if not isinstance(sl, dict):
                    continue
                title_text = sl.get("title", "")
                bullets = sl.get("bullets") or []
                notes = sl.get("speaker_notes") or sl.get("notes") or ""
                if title_text:
                    _add_designed_slide(title_text, bullets, notes, sl.get("visual_ref"))
        else:
            # Fallback structure using aurora highlights
            exec_summary = rd.get("executive_summary") or aurora.summary
            if exec_summary:
                _add_designed_slide("Survey Summary", [exec_summary[:300]], visual_ref="TMF")

            if aurora.highlights:
                _add_designed_slide("Key Findings", [str(h) for h in aurora.highlights], visual_ref="TMF")

            corrections = ", ".join(config.get("corrections") or []) or "None"
            add_ons = ", ".join(config.get("add_ons") or []) or "None"
            model = config.get("model") or "Not specified"
            _add_designed_slide(
                "Processing Configuration",
                [
                    f"Model: {model}",
                    f"Corrections: {corrections}",
                    f"Add-ons: {add_ons}",
                    f"Scenario: {str(task.get('scenario') or 'off').capitalize()}",
                    f"Platform: {str(task.get('platform') or '—').capitalize()}",
                ],
            )
            _add_designed_slide(
                "Magnetic Statistics",
                [
                    f"Mean field: {stats.get('mean', 0):.2f} nT",
                    f"Std deviation: {stats.get('std', 0):.2f} nT",
                    f"Min / Max: {stats.get('min', 0):.2f} / {stats.get('max', 0):.2f} nT",
                    f"Points processed: {stats.get('point_count', 0)}",
                    f"Anomaly count (>mean+1σ): {stats.get('anomaly_count', 0)}",
                ],
            )
            _add_designed_slide(
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
