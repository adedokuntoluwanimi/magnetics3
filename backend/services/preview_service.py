from __future__ import annotations

import io

import pandas as pd

from backend.logging_utils import log_event


def _utm_to_wgs84(easting: float, northing: float, zone: int, hemisphere: str) -> tuple[float, float]:
    """Convert UTM easting/northing to WGS84 (lat, lon) using pyproj."""
    from pyproj import Proj, Transformer
    south = hemisphere.upper() == "S"
    utm_proj = Proj(proj="utm", zone=int(zone), ellps="WGS84", south=south)
    wgs84_proj = Proj(proj="latlong", ellps="WGS84")
    transformer = Transformer.from_proj(utm_proj, wgs84_proj, always_xy=True)
    lon, lat = transformer.transform(easting, northing)
    return lat, lon


def _auto_utm_zone(easting: float, northing: float) -> tuple[int, str]:
    """Heuristic: infer a UTM zone from coordinate magnitudes.

    Returns (zone_number, hemisphere) where hemisphere is 'N' or 'S'.
    This is an approximation — works best when the survey is in West/Central Africa.
    """
    # Easting 166000–834000 is valid for any UTM zone.
    # We can't determine the zone number from easting alone, so default to zone 32.
    # Northern hemisphere UTM: northing = distance from equator (small values, e.g. 745700 for ~7°N Nigeria).
    # Southern hemisphere UTM: false northing of 10,000,000 added, so values are large (e.g. 9,300,000 for 6°S).
    # Threshold: northing < 5,000,000 → northern hemisphere; >= 5,000,000 → southern hemisphere.
    hemisphere = "N" if northing < 5_000_000 else "S"
    # Conservative default for West/Central Africa (where UTM surveys are common)
    zone = 32
    return zone, hemisphere


class PreviewService:
    def __init__(self, store, ai_service, storage_backend) -> None:
        self._store = store
        self._ai_service = ai_service
        self._storage = storage_backend

    def build_preview(self, project_id: str, task_id: str) -> dict:
        project = self._store.get_project(project_id)
        task = self._store.get_task(task_id)
        if not project or not task:
            raise ValueError("Project or task not found.")

        preview_points = self._extract_preview_points(task)
        predicted_points = self._extract_predicted_points(task)
        traverse_count, predicted_traverse_count = self._count_traverses(preview_points, predicted_points, task)
        aurora = self._ai_service.generate_preview(project_id, task_id)
        return {
            "project": project,
            "task": task,
            "preview_points": preview_points,
            "predicted_points": predicted_points,
            "traverse_count": traverse_count,
            "predicted_traverse_count": predicted_traverse_count,
            "aurora": aurora.model_dump(mode="json"),
        }

    def _count_traverses(self, points: list[dict], predicted_points: list[dict], task: dict) -> tuple[int, int]:
        """Count distinct survey traverses and predicted traverses.

        A traverse is a survey line. We group points by the axis perpendicular
        to the dominant survey direction (the axis with less spread = the
        cross-line spacing) to count distinct lines.
        """
        if not points:
            return 0, 0

        spacing_value = float(task.get("station_spacing") or 20)
        spacing_unit = (task.get("station_spacing_unit") or "Metres").lower()
        spacing_metres = spacing_value * (
            1000 if "kilo" in spacing_unit else 0.3048 if "feet" in spacing_unit else 1
        )
        # Group tolerance = 3× station spacing to cluster points on the same traverse
        tol = max(spacing_metres / 111_320 * 3, 0.001)

        lats = [p["latitude"] for p in points]
        lons = [p["longitude"] for p in points]
        lat_range = max(lats) - min(lats) if lats else 0
        lon_range = max(lons) - min(lons) if lons else 0

        # E-W traverses (more longitude spread): group by latitude
        # N-S traverses (more latitude spread): group by longitude
        if lon_range >= lat_range:
            groups = {round(lat / tol) for lat in lats}
        else:
            groups = {round(lon / tol) for lon in lons}
        survey_count = len(groups)

        if not predicted_points:
            return survey_count, 0

        pred_lats = [p["latitude"] for p in predicted_points]
        pred_lons = [p["longitude"] for p in predicted_points]
        if lon_range >= lat_range:
            pred_groups = {round(lat / tol) for lat in pred_lats}
        else:
            pred_groups = {round(lon / tol) for lon in pred_lons}
        return survey_count, len(pred_groups)

    def _extract_predicted_points(self, task: dict) -> list[dict]:
        """For sparse scenario: compute predicted station positions for the preview map."""
        scenario = (task.get("scenario") or "explicit").lower()
        if scenario != "sparse":
            return []

        measured = self._extract_preview_points(task)
        if not measured:
            return []

        def _filter_to_bounds(points: list[dict]) -> list[dict]:
            lats = [p["latitude"] for p in measured]
            lons = [p["longitude"] for p in measured]
            lat_min, lat_max = min(lats), max(lats)
            lon_min, lon_max = min(lons), max(lons)
            pad_lat = max((lat_max - lat_min) * 0.05, 0.002)
            pad_lon = max((lon_max - lon_min) * 0.05, 0.002)
            return [
                p for p in points
                if (lat_min - pad_lat) <= p["latitude"] <= (lat_max + pad_lat)
                and (lon_min - pad_lon) <= p["longitude"] <= (lon_max + pad_lon)
            ]

        line_interpolation = bool(task.get("line_interpolation", True))
        spacing_value = float(task.get("station_spacing") or 20)
        spacing_unit = (task.get("station_spacing_unit") or "Metres").lower()
        spacing_metres = spacing_value * (1000 if "kilo" in spacing_unit else 0.3048 if "feet" in spacing_unit else 1)
        spacing_deg = max(spacing_metres / 111_320, 0.0002)

        lats = [p["latitude"] for p in measured]
        lons = [p["longitude"] for p in measured]
        lat_min, lat_max = min(lats), max(lats)
        lon_min, lon_max = min(lons), max(lons)

        if line_interpolation:
            lat_range = lat_max - lat_min
            lon_range = lon_max - lon_min
            tol = max(spacing_deg * 3, 0.001)

            def _group_key(point: dict) -> int:
                return round(point["latitude"] / tol) if lon_range >= lat_range else round(point["longitude"] / tol)

            groups: dict[int, list[dict]] = {}
            for point in measured:
                groups.setdefault(_group_key(point), []).append(point)

            predicted: list[dict] = []
            for points in groups.values():
                if lon_range >= lat_range:
                    points.sort(key=lambda p: p["longitude"])
                else:
                    points.sort(key=lambda p: p["latitude"])
                for idx in range(len(points) - 1):
                    a = points[idx]
                    b = points[idx + 1]
                    predicted.append({
                        "latitude": (a["latitude"] + b["latitude"]) / 2,
                        "longitude": (a["longitude"] + b["longitude"]) / 2,
                    })
            return _filter_to_bounds(predicted)[:600]

        import numpy as np
        grid_rows = int(task.get("grid_rows") or 0)
        grid_cols = int(task.get("grid_cols") or 0)
        if grid_rows < 2 or grid_cols < 2:
            x_pts = min(max(int((lon_max - lon_min) / spacing_deg) + 1, 5), 60)
            y_pts = min(max(int((lat_max - lat_min) / spacing_deg) + 1, 5), 60)
        else:
            x_pts = min(max(grid_cols, 2), 60)
            y_pts = min(max(grid_rows, 2), 60)

        pad_lat = (lat_max - lat_min) * 0.05
        pad_lon = (lon_max - lon_min) * 0.05
        lat_min = lat_min + pad_lat
        lat_max = lat_max - pad_lat
        lon_min = lon_min + pad_lon
        lon_max = lon_max - pad_lon

        x_axis = np.linspace(lon_min, lon_max, x_pts)
        y_axis = np.linspace(lat_min, lat_max, y_pts)
        grid_x, grid_y = np.meshgrid(x_axis, y_axis)

        predicted = [
            {"latitude": float(lat), "longitude": float(lon)}
            for lat, lon in zip(grid_y.ravel(), grid_x.ravel())
        ]
        return _filter_to_bounds(predicted)[:600]

    def _extract_preview_points(self, task: dict) -> list[dict]:
        """Load up to 500 rows from the first survey CSV for the preview map."""
        # If processing has already run, reuse those points
        existing = task.get("results", {}).get("data", {}).get("points")
        if existing:
            return existing[:500]

        survey_files = task.get("survey_files") or []
        if not survey_files:
            return []

        mapping = task.get("column_mapping") or {}
        lat_col = mapping.get("latitude")
        lon_col = mapping.get("longitude")
        mag_col = mapping.get("magnetic_field")
        if not lat_col or not lon_col:
            return []

        coord_sys = (mapping.get("coordinate_system") or "wgs84").lower()
        utm_zone = mapping.get("utm_zone")
        utm_hemi = mapping.get("utm_hemisphere") or "N"

        try:
            artifact = survey_files[0]
            csv_text = self._storage.download_text(artifact["bucket"], artifact["object_name"])
            frame = pd.read_csv(io.StringIO(csv_text))
            needed = [c for c in [lat_col, lon_col, mag_col] if c and c in frame.columns]
            frame = frame.dropna(subset=needed).copy()
            frame["_raw_lat"] = pd.to_numeric(frame[lat_col], errors="coerce")
            frame["_raw_lon"] = pd.to_numeric(frame[lon_col], errors="coerce")
            if mag_col and mag_col in frame.columns:
                frame["magnetic"] = pd.to_numeric(frame[mag_col], errors="coerce")
            else:
                frame["magnetic"] = 0.0
            frame = frame.dropna(subset=["_raw_lat", "_raw_lon"]).head(500)

            if coord_sys == "utm":
                # Determine zone — use saved zone or auto-detect from first coordinate
                if utm_zone:
                    zone = int(utm_zone)
                    hemi = str(utm_hemi)
                else:
                    first_e = float(frame["_raw_lon"].iloc[0])
                    first_n = float(frame["_raw_lat"].iloc[0])
                    zone, hemi = _auto_utm_zone(first_e, first_n)

                lats, lons = [], []
                for _, row in frame.iterrows():
                    try:
                        lat, lon = _utm_to_wgs84(float(row["_raw_lon"]), float(row["_raw_lat"]), zone, hemi)
                        lats.append(lat)
                        lons.append(lon)
                    except Exception:
                        lats.append(None)
                        lons.append(None)
                frame["latitude"] = lats
                frame["longitude"] = lons
            else:
                frame["latitude"] = frame["_raw_lat"]
                frame["longitude"] = frame["_raw_lon"]

            frame = frame.dropna(subset=["latitude", "longitude"])

            # Detect base stations: explicit column or duplicate (lat, lon) pairs
            bs_col = mapping.get("base_station_column")
            bs_val = str(mapping.get("base_station_value") or "1")
            if bs_col and bs_col in frame.columns:
                frame["is_base_station"] = (frame[bs_col].astype(str).str.strip() == bs_val).astype(int)
            else:
                # Duplicate coordinate detection — same (lat, lon) appears more than once
                dup_mask = frame.duplicated(subset=["latitude", "longitude"], keep=False)
                frame["is_base_station"] = dup_mask.astype(int)

            return frame[["latitude", "longitude", "magnetic", "is_base_station"]].to_dict(orient="records")
        except Exception as exc:
            log_event("WARNING", "Preview point extraction failed", error=str(exc), task_id=task.get("id"))
            return []
