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

    def create_export(self, task_id: str, request: ExportRequest) -> dict:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")
        if not task.get("results", {}).get("data"):
            raise ValueError("Run processing before exporting.")

        project = self._store.get_project(task["project_id"])
        aurora = self._ai_service.generate_response(
            task["project_id"],
            task_id,
            location="export",
            question="Prepare concise export-ready interpretation and delivery guidance.",
        )

        job = ExportJob(task_id=task_id, formats=request.formats, status="running")
        persisted = self._store.create_export_job(job.model_dump(mode="json"))
        artifacts = []
        for export_format in request.formats:
            artifact = self._build_artifact(project, task, export_format, aurora)
            if artifact:
                artifacts.append(artifact.model_dump(mode="json"))

        completed = self._store.update_export_job(
            persisted["id"],
            {
                "status": "completed",
                "updated_at": utc_now(),
                "details": {
                    "artifacts": artifacts,
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

    def _build_artifact(self, project: dict, task: dict, export_format: str, aurora):
        data = task["results"]["data"]
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
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        pdf.setTitle("GAIA Magnetics Report")
        pdf.drawString(48, 800, project["name"])
        pdf.drawString(48, 782, task["name"])
        pdf.drawString(48, 764, f"Generated: {utc_now()}")
        pdf.drawString(48, 746, task["description"][:96])
        stats = task["results"]["data"]["stats"]
        pdf.drawString(48, 718, f"Mean magnetic field: {stats['mean']:.2f}")
        pdf.drawString(48, 700, f"Std dev: {stats['std']:.2f}")
        pdf.drawString(48, 682, f"Points processed: {stats['point_count']}")
        pdf.drawString(48, 648, "Aurora summary")
        pdf.drawString(48, 630, aurora.summary[:108])
        y_pos = 610
        for highlight in aurora.highlights[:3]:
            pdf.drawString(60, y_pos, f"- {highlight[:100]}")
            y_pos -= 18
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    def _build_docx(self, project: dict, task: dict, aurora) -> bytes:
        from docx import Document

        doc = Document()
        doc.add_heading(project["name"], level=1)
        doc.add_heading(task["name"], level=2)
        doc.add_paragraph(task["description"])
        doc.add_paragraph(f"Aurora summary: {aurora.summary}")
        for highlight in aurora.highlights:
            doc.add_paragraph(highlight, style="List Bullet")
        stats = task["results"]["data"]["stats"]
        doc.add_paragraph(f"Mean magnetic field: {stats['mean']:.2f}")
        doc.add_paragraph(f"Standard deviation: {stats['std']:.2f}")
        doc.add_paragraph(f"Points processed: {stats['point_count']}")
        output = io.BytesIO()
        doc.save(output)
        return output.getvalue()

    def _build_pptx(self, project: dict, task: dict, aurora) -> bytes:
        from pptx import Presentation

        presentation = Presentation()
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = project["name"]
        slide.placeholders[1].text = task["name"]
        summary_slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        summary_slide.shapes.title.text = "Aurora Summary"
        summary_slide.placeholders[1].text = aurora.summary
        stats_slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        stats_slide.shapes.title.text = "Magnetic Summary"
        stats = task["results"]["data"]["stats"]
        stats_slide.placeholders[1].text = (
            f"Mean: {stats['mean']:.2f}\n"
            f"Std dev: {stats['std']:.2f}\n"
            f"Points: {stats['point_count']}\n"
            f"Anomalies: {stats.get('anomaly_count', 0)}"
        )
        output = io.BytesIO()
        presentation.save(output)
        return output.getvalue()
