from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from statistics import fmean

from backend.logging_utils import log_event
from backend.models import ColumnMapping, DatasetProfile, TaskCreatePayload, TaskRecord
from backend.models.common import MapBounds, TaskLifecycle


def _xlsx_to_csv_bytes(raw_bytes: bytes) -> bytes:
    """Convert an xlsx file to CSV bytes, adding an __is_base_station__ column.

    Any row where every non-empty cell in the row uses bold font is treated
    as a base station reading and gets __is_base_station__ = 1.
    """
    import openpyxl

    wb = openpyxl.load_workbook(BytesIO(raw_bytes), data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows())
    if not rows:
        return b""

    # Build header from first row, append sentinel column
    header_cells = rows[0]
    headers = [str(c.value) if c.value is not None else f"col{i}" for i, c in enumerate(header_cells)]
    headers.append("__is_base_station__")

    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(headers)

    _BS_LABELS = {"bs", "base", "base station", "base_station"}
    for row in rows[1:]:
        values = [c.value for c in row]
        # Bold detection: all non-empty cells are bold
        bold_cells = [c for c in row if c.value not in (None, "") and c.font and c.font.bold]
        data_cells = [c for c in row if c.value not in (None, "")]
        is_base_bold = data_cells and len(bold_cells) == len(data_cells)
        # Text detection: any cell contains a recognised base-station label
        is_base_text = any(
            str(c.value).strip().lower() in _BS_LABELS
            for c in row if c.value not in (None, "")
        )
        is_base = 1 if (is_base_bold or is_base_text) else 0
        values.append(is_base)
        writer.writerow(values)

    return out.getvalue().encode("utf-8")


def _auto_detect_base_stations(csv_bytes: bytes, lat_col: str, lon_col: str, coordinate_system: str = "wgs84") -> bytes:
    """Mark base station rows by detecting repeated coordinates within a small tolerance."""
    import io
    import pandas as pd

    frame = pd.read_csv(io.StringIO(csv_bytes.decode("utf-8", errors="replace")))
    if lat_col not in frame.columns or lon_col not in frame.columns:
        return csv_bytes
    lat = pd.to_numeric(frame[lat_col], errors="coerce")
    lon = pd.to_numeric(frame[lon_col], errors="coerce")
    is_utm = str(coordinate_system or "wgs84").lower() == "utm"
    tolerance = 1.0 if is_utm else 1e-5
    lat_key = (lat / tolerance).round().astype("Int64")
    lon_key = (lon / tolerance).round().astype("Int64")
    coord_key = lat_key.astype(str) + "," + lon_key.astype(str)
    valid_mask = lat.notna() & lon.notna()
    counts = coord_key[valid_mask].value_counts()
    repeated = set(counts[counts > 1].index)
    base_mask = (valid_mask & coord_key.isin(repeated)).astype(int)
    for column in frame.columns:
        series = frame[column]
        if series.dtype == object:
            text = series.astype(str).str.strip().str.lower()
            if text.isin({"bs", "base", "base station", "base_station"}).any():
                base_mask = ((base_mask > 0) | text.isin({"bs", "base", "base station", "base_station"})).astype(int)
    frame["__is_base_station__"] = base_mask
    return frame.to_csv(index=False).encode("utf-8")


class TaskService:
    def __init__(self, store, storage_backend) -> None:
        self._store = store
        self._storage = storage_backend

    def list_tasks(self, project_id: str) -> list[dict]:
        return self._store.list_tasks(project_id)

    def get_task(self, task_id: str) -> dict | None:
        return self._store.get_task(task_id)

    def rename_task(self, task_id: str, name: str) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        return self._store.update_task(task_id, {"name": name, "updated_at": now})

    def delete_task(self, task_id: str) -> None:
        self._store.delete_task(task_id)

    def create_task(
        self,
        *,
        project_id: str,
        payload: TaskCreatePayload,
        survey_files: list[tuple[str, str, bytes]],
        basemap_file: tuple[str, str, bytes] | None = None,
    ) -> dict:
        if not survey_files:
            raise ValueError("At least one survey CSV file is required.")
        if payload.processing_mode == "single" and len(survey_files) != 1:
            raise ValueError("Single-line mode requires exactly one survey CSV file.")

        # Normalise xlsx to csv with bold-row base-station detection.
        normalised_survey: list[tuple[str, str, bytes]] = []
        for file_name, content_type, data in survey_files:
            if file_name.lower().endswith((".xlsx", ".xls")):
                csv_bytes = _xlsx_to_csv_bytes(data)
                base_name = file_name.rsplit(".", 1)[0] + ".csv"
                normalised_survey.append((base_name, "text/csv", csv_bytes))
            else:
                # Always auto-detect by duplicate coordinates
                data = _auto_detect_base_stations(
                    data,
                    payload.column_mapping.latitude,
                    payload.column_mapping.longitude,
                    payload.column_mapping.coordinate_system,
                )
                normalised_survey.append((file_name, content_type, data))

        dataset_profile = self._build_dataset_profile(
            survey_files=normalised_survey,
            mapping=payload.column_mapping,
        )

        task = TaskRecord(
            project_id=project_id,
            dataset_profile=dataset_profile,
            survey_files=[],
            **payload.model_dump(),
        )

        task.survey_files = [
            self._storage.upload_task_input(
                project_id=project_id,
                task_id=task.id,
                file_name=file_name,
                content_type=content_type,
                data=data,
                kind="survey",
            )
            for file_name, content_type, data in normalised_survey
        ]

        if basemap_file:
            file_name, content_type, data = basemap_file
            task.basemap_file = self._storage.upload_task_input(
                project_id=project_id,
                task_id=task.id,
                file_name=file_name,
                content_type=content_type,
                data=data,
                kind="basemap",
            )

        log_event(
            "INFO",
            "Task created",
            action="task.create",
            project_id=project_id,
            task_id=task.id,
        )
        return self._store.create_task(task.model_dump(mode="json"))

    def update_task(
        self,
        *,
        task_id: str,
        payload: TaskCreatePayload,
        survey_files: list[tuple[str, str, bytes]] | None = None,
        basemap_file: tuple[str, str, bytes] | None = None,
    ) -> dict:
        existing = self.get_task(task_id)
        if not existing:
            raise ValueError("Task not found.")

        project_id = existing["project_id"]
        effective_survey_files = survey_files or [
            (
                artifact["file_name"],
                artifact.get("content_type") or "text/csv",
                self._storage.download_bytes(artifact["bucket"], artifact["object_name"]),
            )
            for artifact in (existing.get("survey_files") or [])
        ]
        if not effective_survey_files:
            raise ValueError("At least one survey CSV file is required.")

        effective_basemap = basemap_file
        if effective_basemap is None and existing.get("basemap_file"):
            artifact = existing["basemap_file"]
            effective_basemap = (
                artifact["file_name"],
                artifact.get("content_type") or "application/octet-stream",
                self._storage.download_bytes(artifact["bucket"], artifact["object_name"]),
            )

        normalised_survey: list[tuple[str, str, bytes]] = []
        for file_name, content_type, data in effective_survey_files:
            if file_name.lower().endswith((".xlsx", ".xls")):
                csv_bytes = _xlsx_to_csv_bytes(data)
                base_name = file_name.rsplit(".", 1)[0] + ".csv"
                normalised_survey.append((base_name, "text/csv", csv_bytes))
            else:
                data = _auto_detect_base_stations(
                    data,
                    payload.column_mapping.latitude,
                    payload.column_mapping.longitude,
                    payload.column_mapping.coordinate_system,
                )
                normalised_survey.append((file_name, content_type, data))

        dataset_profile = self._build_dataset_profile(
            survey_files=normalised_survey,
            mapping=payload.column_mapping,
        )

        uploaded_survey_files = [
            self._storage.upload_task_input(
                project_id=project_id,
                task_id=task_id,
                file_name=file_name,
                content_type=content_type,
                data=data,
                kind="survey",
            )
            for file_name, content_type, data in normalised_survey
        ]

        uploaded_basemap = None
        if effective_basemap:
            file_name, content_type, data = effective_basemap
            uploaded_basemap = self._storage.upload_task_input(
                project_id=project_id,
                task_id=task_id,
                file_name=file_name,
                content_type=content_type,
                data=data,
                kind="basemap",
            )

        now = datetime.now(timezone.utc).isoformat()
        fields = {
            **payload.model_dump(mode="json"),
            "dataset_profile": dataset_profile.model_dump(mode="json"),
            "survey_files": [artifact.model_dump(mode="json") for artifact in uploaded_survey_files],
            "basemap_file": uploaded_basemap.model_dump(mode="json") if uploaded_basemap else None,
            "analysis_config": {},
            "processing_run_id": None,
            "export_jobs": [],
            "results": {},
            "lifecycle": TaskLifecycle.draft.value,
            "updated_at": now,
        }
        updated = self._store.update_task(task_id, fields)
        self._store.update_project(project_id, {"updated_at": now})
        return updated

    def _build_dataset_profile(
        self,
        *,
        survey_files: list[tuple[str, str, bytes]],
        mapping: ColumnMapping,
    ) -> DatasetProfile:
        headers: list[str] = []
        total_rows = 0
        xs: list[float] = []
        ys: list[float] = []
        magnetic_values: list[float] = []
        preview_points: list[dict[str, float]] = []

        for file_name, _content_type, raw_bytes in survey_files:
            text = raw_bytes.decode("utf-8-sig")
            reader = csv.DictReader(StringIO(text))
            if not reader.fieldnames:
                raise ValueError(f"{file_name} does not contain a CSV header row.")
            if not headers:
                headers = list(reader.fieldnames)
            missing = {
                mapping.latitude,
                mapping.longitude,
                mapping.magnetic_field,
            } - set(reader.fieldnames)
            if missing:
                missing_list = ", ".join(sorted(missing))
                raise ValueError(f"{file_name} is missing required columns: {missing_list}.")

            for row in reader:
                total_rows += 1
                try:
                    longitude = float(row[mapping.longitude])
                    latitude = float(row[mapping.latitude])
                    magnetic = float(row[mapping.magnetic_field])
                    xs.append(longitude)
                    ys.append(latitude)
                    magnetic_values.append(magnetic)
                    if len(preview_points) < 500:
                        preview_points.append(
                            {
                                "longitude": longitude,
                                "latitude": latitude,
                                "magnetic": magnetic,
                            }
                        )
                except (TypeError, ValueError):
                    continue

        bounds = MapBounds(
            min_x=min(xs) if xs else None,
            min_y=min(ys) if ys else None,
            max_x=max(xs) if xs else None,
            max_y=max(ys) if ys else None,
        )
        return DatasetProfile(
            headers=headers,
            total_rows=total_rows,
            files_count=len(survey_files),
            column_mapping=mapping,
            preview_points=preview_points,
            bounds=bounds,
            magnetic_min=min(magnetic_values) if magnetic_values else None,
            magnetic_max=max(magnetic_values) if magnetic_values else None,
            magnetic_mean=fmean(magnetic_values) if magnetic_values else None,
        )
