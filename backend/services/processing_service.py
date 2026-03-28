from __future__ import annotations

import io
import json
import math
from datetime import datetime, timezone

import pandas as pd

from backend.logging_utils import log_event
from backend.models import PipelineRun, PipelineStep


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProcessingService:
    def __init__(self, store, storage_backend) -> None:
        self._store = store
        self._storage = storage_backend

    def start_run(self, task_id: str) -> dict:
        task = self._store.get_task(task_id)
        if not task:
            raise ValueError("Task not found.")

        run = PipelineRun(
            task_id=task_id,
            status="queued",
            steps=[
                PipelineStep(name="Data loading", status="queued", detail="Waiting to start"),
                PipelineStep(name="Data cleaning", status="queued", detail="Queued"),
                PipelineStep(name="Corrections", status="queued", detail="Queued"),
                PipelineStep(name="Station grid", status="queued", detail="Queued"),
                PipelineStep(name="Modelling", status="queued", detail="Queued"),
                PipelineStep(name="Derived layers", status="queued", detail="Queued"),
                PipelineStep(name="Save results", status="queued", detail="Queued"),
            ],
        )
        payload = run.model_dump(mode="json")
        payload["logs"] = []
        persisted = self._store.create_processing_run(payload)
        self._store.update_task(
            task_id,
            {
                "processing_run_id": run.id,
                "lifecycle": "queued",
                "updated_at": utc_now(),
            },
        )
        return persisted

    def execute_run(self, run_id: str) -> dict:
        run = self._store.get_processing_run(run_id)
        if not run:
            raise ValueError("Processing run not found.")

        task = self._store.get_task(run["task_id"])
        if not task:
            raise ValueError("Task not found.")

        try:
            self._update_run(run_id, 0, "running", "Checking your uploaded survey data...")
            frame = self._load_dataframe(task)
            frame, n_removed = self._remove_coordinate_outliers(frame)
            removed_msg = f" ({n_removed} out-of-area points removed)" if n_removed > 0 else ""
            self._update_run(run_id, 0, "completed", f"{len(frame)} survey readings loaded{removed_msg}")

            self._update_run(run_id, 1, "running", "Removing duplicates and sorting data...")
            cleaned = self._clean_dataframe(frame)
            self._update_run(run_id, 1, "completed", f"{len(cleaned)} readings ready after cleaning")

            self._update_run(run_id, 2, "running", "Applying your selected magnetic corrections...")
            corrected, correction_summary = self._apply_corrections(task, cleaned)
            self._update_run(run_id, 2, "completed", correction_summary)

            config = task.get("analysis_config") or {}
            run_prediction = config.get("run_prediction", True)

            if run_prediction:
                self._update_run(run_id, 3, "running", "Preparing station data for modelling...")
                prep = self._prepare_prediction_inputs(task, corrected)
                self._update_run(run_id, 3, "completed", prep["detail"])

                self._update_run(run_id, 4, "running", "Running the magnetic field model...")
                results = self._generate_surfaces(task, prep)
                self._update_run(run_id, 4, "completed", f"Model complete - used {results['model_used']} approach")

                self._update_run(run_id, 5, "running", "Calculating derived layers...")
                add_on_payload = self._apply_add_ons(task, results)
                self._update_run(run_id, 5, "completed", add_on_payload["detail"])
            else:
                # Skip modelling and output corrected data only.
                import numpy as np
                self._update_run(run_id, 3, "completed", "Prediction modelling disabled - skipped")
                self._update_run(run_id, 4, "completed", "Prediction modelling disabled - skipped")
                self._update_run(run_id, 5, "completed", "No derived layers - modelling was disabled")
                grid_x, grid_y = self._build_grid(task, corrected)
                surface = self._nearest_surface(
                    corrected["longitude"].to_numpy(),
                    corrected["latitude"].to_numpy(),
                    corrected["magnetic"].to_numpy(),
                    grid_x,
                    grid_y,
                )
                uncertainty = self._uncertainty_surface(
                    corrected["longitude"].to_numpy(),
                    corrected["latitude"].to_numpy(),
                    grid_x,
                    grid_y,
                    np.zeros_like(surface),
                )
                results = {
                    "grid_x": grid_x,
                    "grid_y": grid_y,
                    "surface": surface,
                    "uncertainty": uncertainty,
                    "model_used": "none",
                    "points": corrected[["latitude", "longitude", "magnetic"]
                        + (["__is_base_station__"] if "__is_base_station__" in corrected.columns else [])
                        + (["_line_id"] if "_line_id" in corrected.columns else [])
                    ].rename(columns={"__is_base_station__": "is_base_station", "_line_id": "line_id"}).to_dict(orient="records"),
                    "stats": {
                        "min": float(corrected["magnetic"].min()), "max": float(corrected["magnetic"].max()),
                        "mean": float(corrected["magnetic"].mean()), "std": float(corrected["magnetic"].std()),
                        "point_count": len(corrected), "anomaly_count": 0,
                    },
                    "predicted_points": [],
                }
                add_on_payload = {
                    "analytic_signal": [],
                    "first_vertical_derivative": [],
                    "horizontal_derivative": [],
                    "filtered_surface": [],
                    "emag2_residual": [],
                    "rtp_surface": [],
                    "selected_add_ons": [],
                    "detail": "No add-ons — modelling disabled",
                }
                prep = {
                    "frame": corrected,
                    "train_frame": corrected,
                    "predict_frame": pd.DataFrame({"latitude": [], "longitude": []}),
                    "grid_x": grid_x,
                    "grid_y": grid_y,
                }

            self._update_run(run_id, 6, "running", "Saving results to your project...")
            stored = self._persist_outputs(task, prep, results, add_on_payload)
            self._update_run(run_id, 6, "completed", "Saved outputs, visual assets, and grid artifacts")

            self._store.update_processing_run(
                run_id,
                {
                    "status": "completed",
                    "updated_at": utc_now(),
                },
            )
            self._store.update_task(
                task["id"],
                {
                    "lifecycle": "completed",
                    "updated_at": utc_now(),
                    "results": stored,
                },
            )
            log_event("INFO", "Processing completed", action="processing.complete", task_id=task["id"], run_id=run_id)
            return self._store.get_processing_run(run_id)
        except Exception as exc:
            self._store.update_processing_run(
                run_id,
                {
                    "status": "failed",
                    "updated_at": utc_now(),
                    "error": str(exc),
                },
            )
            self._store.update_task(
                task["id"],
                {
                    "lifecycle": "failed",
                    "updated_at": utc_now(),
                },
            )
            log_event("ERROR", "Processing failed", action="processing.failed", task_id=task["id"], run_id=run_id, error=str(exc))
            raise

    def get_run(self, run_id: str) -> dict | None:
        return self._store.get_processing_run(run_id)

    def _load_dataframe(self, task: dict) -> pd.DataFrame:
        mapping = task["column_mapping"]
        frames: list[pd.DataFrame] = []
        for artifact in task.get("survey_files") or []:
            csv_text = self._storage.download_text(artifact["bucket"], artifact["object_name"])
            frame = pd.read_csv(io.StringIO(csv_text))
            missing_cols = [mapping["latitude"], mapping["longitude"]]
            if any(col not in frame.columns for col in missing_cols):
                log_event(
                    "WARNING",
                    "Survey file missing coordinate columns",
                    task_id=task.get("id"),
                    missing=missing_cols,
                    file=artifact.get("object_name"),
                )
                continue

            frame["_raw_lat"] = pd.to_numeric(frame[mapping["latitude"]], errors="coerce")
            frame["_raw_lon"] = pd.to_numeric(frame[mapping["longitude"]], errors="coerce")
            frame["magnetic"] = pd.to_numeric(frame.get(mapping["magnetic_field"], pd.Series(dtype=float)), errors="coerce")

            # Load time columns if present
            for col_key, dest in [("hour", "_hour"), ("minute", "_minute"), ("second", "_second")]:
                col_name = mapping.get(col_key)
                if col_name and col_name in frame.columns:
                    frame[dest] = pd.to_numeric(frame[col_name], errors="coerce")

            # Drop rows with invalid coordinates
            frame = frame.dropna(subset=["_raw_lat", "_raw_lon"]).copy()

            # UTM conversion if needed
            coord_sys = (mapping.get("coordinate_system") or "wgs84").lower()
            if coord_sys == "utm":
                from pyproj import Proj, Transformer
                utm_zone = mapping.get("utm_zone")
                utm_hemi = mapping.get("utm_hemisphere") or "N"
                if not utm_zone:
                    first_n = float(frame["_raw_lat"].iloc[0])
                    utm_zone = 32
                    utm_hemi = "N" if first_n < 5_000_000 else "S"
                south = str(utm_hemi).upper() == "S"
                utm_proj = Proj(proj="utm", zone=int(utm_zone), ellps="WGS84", south=south)
                wgs84_proj = Proj(proj="latlong", ellps="WGS84")
                transformer = Transformer.from_proj(utm_proj, wgs84_proj, always_xy=True)
                lats, lons = [], []
                for _, row in frame.iterrows():
                    try:
                        lon, lat = transformer.transform(float(row["_raw_lon"]), float(row["_raw_lat"]))
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
            if not frame.empty:
                frames.append(frame)

        if not frames:
            raise ValueError("No valid coordinate rows found in the survey file(s).")

        return pd.concat(frames, ignore_index=True)

    @staticmethod
    def _remove_coordinate_outliers(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
        """Remove points whose coordinates are statistical outliers (3xIQR fence)."""
        original_len = len(frame)
        for col in ("latitude", "longitude"):
            if col not in frame.columns or frame.empty:
                continue
            q1 = frame[col].quantile(0.25)
            q3 = frame[col].quantile(0.75)
            iqr = q3 - q1
            if iqr == 0:
                continue
            lo = q1 - 3 * iqr
            hi = q3 + 3 * iqr
            frame = frame[(frame[col] >= lo) & (frame[col] <= hi)]
        return frame.reset_index(drop=True), original_len - len(frame)

    @staticmethod
    def _filter_predicted_to_bounds(predicted: list[dict], frame: pd.DataFrame) -> list[dict]:
        if not predicted or frame.empty:
            return predicted
        min_lat, max_lat = float(frame["latitude"].min()), float(frame["latitude"].max())
        min_lon, max_lon = float(frame["longitude"].min()), float(frame["longitude"].max())
        pad_lat = max((max_lat - min_lat) * 0.05, 0.002)
        pad_lon = max((max_lon - min_lon) * 0.05, 0.002)
        return [
            p for p in predicted
            if min_lat - pad_lat <= p.get("latitude", 0) <= max_lat + pad_lat
            and min_lon - pad_lon <= p.get("longitude", 0) <= max_lon + pad_lon
        ]

    def _clean_dataframe(self, frame: pd.DataFrame) -> pd.DataFrame:
        cleaned = frame.copy()
        cleaned = cleaned.drop_duplicates(subset=["latitude", "longitude", "magnetic"])
        cleaned = cleaned.sort_values(["latitude", "longitude"]).reset_index(drop=True)
        return cleaned

    def _apply_corrections(self, task: dict, frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
        corrected = frame.copy()
        selected = {item.lower() for item in (task.get("analysis_config", {}).get("corrections") or [])}
        notes = []

        if "diurnal" in selected:
            mapping = task.get("column_mapping") or {}
            has_time = "_hour" in frame.columns and "_minute" in frame.columns
            bs_col = "__is_base_station__"
            has_bs = bs_col in frame.columns and frame[bs_col].sum() > 0

            if has_bs and has_time:
                # Compute decimal seconds for time-based interpolation
                _sec = corrected["_second"].fillna(0) if "_second" in corrected.columns else 0
                corrected["_time"] = (
                    corrected["_hour"].fillna(0) * 3600
                    + corrected["_minute"].fillna(0) * 60
                    + _sec
                )
                bs = corrected[corrected[bs_col] == 1].dropna(subset=["_time", "magnetic"])
                survey = corrected[corrected[bs_col] != 1].copy()
                if not bs.empty and not survey.empty:
                    import numpy as np
                    bs_sorted = bs.sort_values("_time")
                    survey["_diurnal"] = np.interp(
                        survey["_time"].fillna(bs_sorted["_time"].iloc[0]),
                        bs_sorted["_time"].values,
                        bs_sorted["magnetic"].values,
                        left=bs_sorted["magnetic"].iloc[0],
                        right=bs_sorted["magnetic"].iloc[-1],
                    )
                    survey["magnetic"] = survey["magnetic"] - survey["_diurnal"] + bs_sorted["magnetic"].mean()
                    corrected = pd.concat([bs, survey]).sort_index()
                    notes.append("diurnal correction using base station time series")
                else:
                    corrected["magnetic"] = corrected["magnetic"] - corrected["magnetic"].median()
                    notes.append("diurnal normalisation (median, no base station time data)")
            else:
                corrected["magnetic"] = corrected["magnetic"] - corrected["magnetic"].median()
                notes.append("diurnal normalisation (median)")
        if "igrf" in selected:
            corrected["magnetic"] = corrected["magnetic"] - corrected["magnetic"].mean()
            notes.append("regional field removal")
        if "lag" in selected and len(corrected) > 3:
            corrected["magnetic"] = corrected["magnetic"].rolling(window=3, center=True, min_periods=1).mean()
            notes.append("lag smoothing")
        if "heading" in selected and len(corrected) > 3:
            corrected["magnetic"] = corrected["magnetic"] - corrected.groupby(corrected.index % 2)["magnetic"].transform("mean")
            notes.append("heading bias balancing")
        if "filtering" in selected:
            filter_type = (task.get("analysis_config") or {}).get("filter_type")
            if filter_type == "low-pass":
                corrected["magnetic"] = corrected["magnetic"].rolling(window=5, center=True, min_periods=1).mean()
                notes.append("low-pass filtering")
            elif filter_type == "high-pass":
                trend = corrected["magnetic"].rolling(window=9, center=True, min_periods=1).mean()
                corrected["magnetic"] = corrected["magnetic"] - trend
                notes.append("high-pass filtering")

        detail = ", ".join(notes) if notes else "No additional corrections were requested"
        return corrected, detail

    def _prepare_prediction_inputs(self, task: dict, frame: pd.DataFrame) -> dict:
        grid_x, grid_y = self._build_grid(task, frame)
        scenario = (task.get("scenario") or "explicit").lower()

        if scenario == "explicit":
            # Train on rows that HAVE magnetic values; predict on rows that don't
            has_mag = frame["magnetic"].notna()
            train = frame[has_mag].dropna(subset=["magnetic"]).reset_index(drop=True)
            predict = frame[~has_mag][["latitude", "longitude"]].reset_index(drop=True)
            if train.empty:
                raise ValueError("No rows with magnetic field values found for training.")
            if predict.empty:
                # Fallback: use last 20% as prediction targets
                n = max(1, int(len(train) * 0.2))
                predict = train.tail(n)[["latitude", "longitude"]].reset_index(drop=True)
                train = train.iloc[: len(train) - n].reset_index(drop=True)
            detail = f"Explicit: {len(train)} measured stations train the model, predicting at {len(predict)} unmeasured locations"
        else:
            # Sparse: all rows with magnetic values train the model; predict at the regular grid
            train = frame.dropna(subset=["magnetic"]).reset_index(drop=True)
            if train.empty:
                raise ValueError("No rows with magnetic field values found.")
            predict = pd.DataFrame({"longitude": grid_x.ravel(), "latitude": grid_y.ravel()})
            detail = f"Sparse: {len(train)} measured stations, predicting at {len(predict)} grid nodes"

        return {
            "frame": train,
            "train_frame": train,
            "predict_frame": predict,
            "grid_x": grid_x,
            "grid_y": grid_y,
            "detail": detail,
            "scenario": scenario,
        }

    def _generate_surfaces(self, task: dict, prep: dict) -> dict:
        import numpy as np

        train = prep["train_frame"]
        # Exclude base station rows from modelling
        bs_col = "__is_base_station__"
        if bs_col in train.columns:
            train = train[train[bs_col] != 1].copy()
        x = train["longitude"].to_numpy()
        y = train["latitude"].to_numpy()
        z = train["magnetic"].to_numpy()
        grid_x = prep["grid_x"]
        grid_y = prep["grid_y"]

        analysis = task.get("analysis_config", {})
        requested_model = (analysis.get("model") or "Machine learning").lower()

        kriging_surface, variance = self._krige(x, y, z, grid_x, grid_y)
        ml_surface = self._xgboost_surface(x, y, z, grid_x, grid_y)
        if "kriging" in requested_model:
            surface = kriging_surface
            model_used = "kriging"
        elif "hybrid" in requested_model:
            surface = (kriging_surface + ml_surface) / 2.0
            model_used = "hybrid"
        else:
            surface = ml_surface
            model_used = "machine_learning"

        uncertainty = self._uncertainty_surface(x, y, grid_x, grid_y, variance)
        anomaly_threshold = float(np.nanmean(surface) + np.nanstd(surface))
        anomaly_mask = surface >= anomaly_threshold
        scenario = (task.get("scenario") or "explicit").lower()
        result = {
            "grid_x": grid_x,
            "grid_y": grid_y,
            "surface": surface,
            "uncertainty": uncertainty,
            "model_used": model_used,
            "points": prep["frame"][["latitude", "longitude", "magnetic"]
                + (["__is_base_station__"] if "__is_base_station__" in prep["frame"].columns else [])
                + (["_line_id"] if "_line_id" in prep["frame"].columns else [])
            ].rename(columns={"__is_base_station__": "is_base_station", "_line_id": "line_id"}).to_dict(orient="records"),
            "stats": {
                "min": float(np.nanmin(surface)),
                "max": float(np.nanmax(surface)),
                "mean": float(np.nanmean(surface)),
                "std": float(np.nanstd(surface)),
                "point_count": int(len(prep["frame"])),
                "anomaly_count": int(np.count_nonzero(anomaly_mask)),
            },
        }
        if scenario == "sparse":
            result["predicted_points"] = prep["predict_frame"][["latitude", "longitude"]].head(600).to_dict(orient="records")
        else:
            result["predicted_points"] = []
        result["predicted_points"] = self._filter_predicted_to_bounds(result["predicted_points"], prep["frame"])
        return result

    def _build_grid(self, task: dict, frame: pd.DataFrame):
        import numpy as np

        spacing_value = float(task.get("station_spacing") or 20)
        spacing_unit = (task.get("station_spacing_unit") or "Metres").lower()
        spacing_metres = spacing_value * (1000 if "kilo" in spacing_unit else 0.3048 if "feet" in spacing_unit else 1)
        spacing_degrees = max(spacing_metres / 111_320, 0.0002)

        lon_min, lon_max = frame["longitude"].min(), frame["longitude"].max()
        lat_min, lat_max = frame["latitude"].min(), frame["latitude"].max()

        scenario = (task.get("scenario") or "explicit").lower()
        if scenario == "sparse":
            # Validate spacing against survey traverse length
            lon_range_m = (lon_max - lon_min) * 111_320
            lat_range_m = (lat_max - lat_min) * 111_320
            traverse_length_m = max(float(np.sqrt(lon_range_m**2 + lat_range_m**2)), 1.0)
            line_interp = task.get("line_interpolation", True)
            if not line_interp:
                # Full 2D grid mode: ignore traverse grouping.
                grid_rows = int(task.get("grid_rows") or 0)
                grid_cols = int(task.get("grid_cols") or 0)
                if grid_rows >= 2 and grid_cols >= 2:
                    x_points = min(max(grid_cols, 2), 80)
                    y_points = min(max(grid_rows, 2), 80)
                else:
                    x_points = min(max(int(((lon_max - lon_min) / spacing_degrees) + 1), 25), 80)
                    y_points = min(max(int(((lat_max - lat_min) / spacing_degrees) + 1), 25), 80)
                x_axis = np.linspace(lon_min, lon_max, x_points)
                y_axis = np.linspace(lat_min, lat_max, y_points)
                return np.meshgrid(x_axis, y_axis)
            if spacing_metres > traverse_length_m:
                raise ValueError(
                    f"Station spacing ({spacing_value} {spacing_unit}) exceeds the survey traverse length "
                    f"({traverse_length_m:.0f} m). Enter a spacing between 1 m and {traverse_length_m:.0f} m."
                )
            if spacing_metres < 1.0:
                raise ValueError("Station spacing must be at least 1 metre.")
            lon_range = lon_max - lon_min
            lat_range = lat_max - lat_min
            if lon_range >= lat_range:
                group_col = "latitude"
                line_col = "longitude"
                line_min, line_max = lon_min, lon_max
            else:
                group_col = "longitude"
                line_col = "latitude"
                line_min, line_max = lat_min, lat_max

            group_vals = frame[group_col].values
            sorted_groups = np.sort(np.unique(np.round(group_vals / (spacing_degrees * 2)) * (spacing_degrees * 2)))

            pred_lons, pred_lats = [], []
            for g in sorted_groups:
                mask = np.abs(group_vals - g) <= spacing_degrees * 3
                if mask.sum() < 2:
                    continue
                trav = frame[mask]
                line_start = trav[line_col].min()
                line_end = trav[line_col].max()
                n_pts = max(int((line_end - line_start) / spacing_degrees) + 1, 2)
                pts = np.linspace(line_start, line_end, n_pts)
                for p in pts:
                    if group_col == "latitude":
                        pred_lats.append(g); pred_lons.append(p)
                    else:
                        pred_lats.append(p); pred_lons.append(g)

            if not pred_lons:
                x_pts = min(max(int((lon_range / spacing_degrees) + 1), 25), 80)
                y_pts = min(max(int((lat_range / spacing_degrees) + 1), 25), 80)
                x_ax = np.linspace(lon_min, lon_max, x_pts)
                y_ax = np.linspace(lat_min, lat_max, y_pts)
                return np.meshgrid(x_ax, y_ax)

            pred_lons_arr = np.array(pred_lons)
            pred_lats_arr = np.array(pred_lats)
            grid_x = pred_lons_arr.reshape(1, -1)
            grid_y = pred_lats_arr.reshape(1, -1)
            return grid_x, grid_y
        else:
            x_points = min(max(int(((lon_max - lon_min) / spacing_degrees) + 1), 25), 80)
            y_points = min(max(int(((lat_max - lat_min) / spacing_degrees) + 1), 25), 80)
            x_axis = np.linspace(lon_min, lon_max, x_points)
            y_axis = np.linspace(lat_min, lat_max, y_points)
            return np.meshgrid(x_axis, y_axis)

    def _krige(self, x, y, z, grid_x, grid_y):
        from pykrige.ok import OrdinaryKriging
        import numpy as np

        if len(z) < 4:
            grid = np.full(grid_x.shape, float(np.mean(z)))
            variance = np.zeros(grid_x.shape)
            return grid, variance
        try:
            ok = OrdinaryKriging(x, y, z, variogram_model="spherical", verbose=False, enable_plotting=False)
            grid, variance = ok.execute("grid", grid_x[0, :], grid_y[:, 0])
            return np.asarray(grid), np.asarray(variance)
        except Exception:
            grid = np.full(grid_x.shape, float(np.mean(z)))
            variance = np.zeros(grid_x.shape)
            return grid, variance

    def _xgboost_surface(self, x, y, z, grid_x, grid_y):
        from xgboost import XGBRegressor
        import numpy as np

        if len(z) < 4:
            return np.full(grid_x.shape, float(np.mean(z)))
        model = XGBRegressor(
            n_estimators=240,
            max_depth=5,
            learning_rate=0.06,
            subsample=0.9,
            colsample_bytree=0.9,
            objective="reg:squarederror",
            random_state=42,
        )
        model.fit(np.column_stack([x, y]), z)
        predictions = model.predict(np.column_stack([grid_x.ravel(), grid_y.ravel()]))
        return predictions.reshape(grid_x.shape)

    def _nearest_surface(self, x, y, z, grid_x, grid_y):
        import numpy as np
        from scipy.spatial import cKDTree

        if len(z) == 0:
            return np.zeros_like(grid_x)
        tree = cKDTree(np.column_stack([x, y]))
        _, idx = tree.query(np.column_stack([grid_x.ravel(), grid_y.ravel()]), k=1)
        return z[idx].reshape(grid_x.shape)

    def _uncertainty_surface(self, x, y, grid_x, grid_y, variance):
        import numpy as np
        from scipy.spatial import cKDTree

        tree = cKDTree(np.column_stack([x, y]))
        distance, _ = tree.query(np.column_stack([grid_x.ravel(), grid_y.ravel()]), k=1)
        distance_surface = distance.reshape(grid_x.shape)
        distance_surface = distance_surface / max(float(np.nanmax(distance_surface)), 1e-6)
        variance_norm = variance / max(float(np.nanmax(variance)), 1e-6)
        return ((distance_surface + variance_norm) / 2.0) * 100.0

    def _apply_add_ons(self, task: dict, results: dict) -> dict:
        import numpy as np
        from scipy.ndimage import gaussian_filter

        surface = results["surface"]
        add_ons = (task.get("analysis_config") or {}).get("add_ons") or []
        selected = set(add_ons)
        detail_items = []

        # np.gradient requires at least 2 elements per dimension; guard for sparse along-line grids.
        def gradient_components(values):
            values = np.asarray(values, dtype=float)
            if values.ndim == 1:
                values = values.reshape(1, -1)
            grad_y = np.zeros_like(values)
            grad_x = np.zeros_like(values)
            if values.shape[0] > 1:
                grad_y = np.gradient(values, axis=0)
            if values.shape[1] > 1:
                grad_x = np.gradient(values, axis=1)
            if values.shape[0] <= 1 < values.shape[1]:
                grad_x = np.gradient(values.ravel()).reshape(values.shape)
            if values.shape[1] <= 1 < values.shape[0]:
                grad_y = np.gradient(values.ravel()).reshape(values.shape)
            return grad_x, grad_y

        def second_derivative(values):
            values = np.asarray(values, dtype=float)
            if values.ndim == 1:
                values = values.reshape(1, -1)
            if values.shape[0] > 1 and values.shape[1] > 1:
                grad_x = np.gradient(values, axis=1)
                grad_y = np.gradient(values, axis=0)
                return np.gradient(grad_x, axis=1) + np.gradient(grad_y, axis=0)
            axis = 1 if values.shape[1] > 1 else 0
            first = np.gradient(values, axis=axis)
            return np.gradient(first, axis=axis)

        grad_x, grad_y = gradient_components(surface)
        first_vertical_derivative = second_derivative(surface)
        horizontal_derivative = np.sqrt((grad_x ** 2) + (grad_y ** 2))
        analytic = np.sqrt((grad_x ** 2) + (grad_y ** 2) + (first_vertical_derivative ** 2))
        filtered_surface = surface
        # gaussian_filter sigma must not exceed array size; clamp it
        sigma = min(5.0, max(surface.shape) / 4.0) if surface.size > 1 else 0.0
        emag2_residual = surface - gaussian_filter(surface, sigma=sigma) if sigma > 0 else np.zeros_like(surface)
        rtp_surface = surface - np.nanmean(surface)
        if "analytic_signal" in selected:
            detail_items.append("analytic signal")
        if "emag2" in selected:
            detail_items.append("regional residual comparison")
        if "rtp" in selected:
            detail_items.append("RTP-style centred field")
        if "first_vertical_derivative" in selected:
            detail_items.append("first vertical derivative")
        if "horizontal_derivative" in selected:
            detail_items.append("horizontal derivative")
        if "uncertainty" in selected:
            detail_items.append("uncertainty surface")

        filter_type = (task.get("analysis_config") or {}).get("filter_type")
        if filter_type == "low-pass":
            filtered_surface = gaussian_filter(surface, sigma=1.2)
        elif filter_type == "high-pass":
            filtered_surface = surface - gaussian_filter(surface, sigma=1.2)

        return {
            "analytic_signal": analytic.tolist(),
            "first_vertical_derivative": first_vertical_derivative.tolist(),
            "horizontal_derivative": horizontal_derivative.tolist(),
            "filtered_surface": filtered_surface.tolist(),
            "emag2_residual": emag2_residual.tolist(),
            "rtp_surface": rtp_surface.tolist(),
            "selected_add_ons": add_ons,
            "detail": ", ".join(detail_items) if detail_items else "No add-on layers were requested",
        }

    def _persist_outputs(self, task: dict, prep: dict, results: dict, add_ons: dict) -> dict:
        payload = {
            "grid_x": results["grid_x"].tolist(),
            "grid_y": results["grid_y"].tolist(),
            "surface": results["surface"].tolist(),
            "uncertainty": results["uncertainty"].tolist(),
            "points": results["points"],
            "stats": results["stats"],
            "model_used": results["model_used"],
            **add_ons,
        }
        if "predicted_points" in results:
            payload["predicted_points"] = results["predicted_points"]

        payload = self._sanitize_payload(payload)
        artifacts = []
        json_bytes = json.dumps(payload, allow_nan=False).encode("utf-8")
        results_artifact = self._storage.upload_result(
            project_id=task["project_id"],
            task_id=task["id"],
            file_name="results.json",
            content_type="application/json",
            data=json_bytes,
        ).model_dump(mode="json")
        artifacts.append(results_artifact)

        grid_frame = pd.DataFrame(
            {
                "longitude": results["grid_x"].ravel(),
                "latitude": results["grid_y"].ravel(),
                "predicted_magnetic": results["surface"].ravel(),
                "uncertainty": results["uncertainty"].ravel(),
            }
        )
        artifacts.append(
            self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="grid.csv",
                content_type="text/csv",
                data=grid_frame.to_csv(index=False).encode("utf-8"),
            ).model_dump(mode="json")
        )

        artifacts.append(
            self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="train.csv",
                content_type="text/csv",
                data=prep["train_frame"].to_csv(index=False).encode("utf-8"),
            ).model_dump(mode="json")
        )

        artifacts.append(
            self._storage.upload_result(
                project_id=task["project_id"],
                task_id=task["id"],
                file_name="predict.csv",
                content_type="text/csv",
                data=prep["predict_frame"].to_csv(index=False).encode("utf-8"),
            ).model_dump(mode="json")
        )

        for file_name, renderer in (
            ("heatmap.png", self._render_heatmap_png),
            ("contour.png", self._render_contour_png),
            ("surface.png", self._render_surface_png),
        ):
            artifacts.append(
                self._storage.upload_result(
                    project_id=task["project_id"],
                    task_id=task["id"],
                    file_name=file_name,
                    content_type="image/png",
                    data=renderer(results["surface"]),
                ).model_dump(mode="json")
            )
        # Firestore rejects list-of-lists (nested arrays). Store only lightweight
        # scalar/1D data in the task document; full grid data lives in results.json.
        _2d_keys = {"grid_x", "grid_y", "surface", "uncertainty", "analytic_signal",
                    "first_vertical_derivative", "horizontal_derivative",
                    "filtered_surface", "emag2_residual", "rtp_surface"}
        firestore_data = {k: v for k, v in payload.items() if k not in _2d_keys}
        # Cap points to 500 for Firestore document size limits
        if "points" in firestore_data:
            firestore_data["points"] = firestore_data["points"][:500]
        if "predicted_points" in firestore_data:
            firestore_data["predicted_points"] = firestore_data["predicted_points"][:500]
        return {"data": firestore_data, "artifacts": artifacts}

    def _sanitize_payload(self, value):
        if value is None:
            return None
        if isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if math.isnan(value) or math.isinf(value):
                return None
            return value
        if isinstance(value, dict):
            return {key: self._sanitize_payload(val) for key, val in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize_payload(val) for val in value]
        if hasattr(value, "item"):
            return self._sanitize_payload(value.item())
        return value

    def _render_heatmap_png(self, surface) -> bytes:
        from matplotlib import pyplot as plt

        figure, axis = plt.subplots(figsize=(6, 4))
        heatmap = axis.imshow(surface, cmap="viridis", origin="lower")
        figure.colorbar(heatmap, ax=axis, fraction=0.046, pad=0.04)
        axis.set_title("Magnetic Surface")
        axis.set_xlabel("Grid X")
        axis.set_ylabel("Grid Y")
        output = io.BytesIO()
        figure.tight_layout()
        figure.savefig(output, format="png", dpi=180)
        plt.close(figure)
        return output.getvalue()

    def _render_contour_png(self, surface) -> bytes:
        import numpy as np
        from matplotlib import pyplot as plt

        figure, axis = plt.subplots(figsize=(6, 4))
        if surface.ndim == 2 and surface.shape[0] > 1 and surface.shape[1] > 1:
            contour = axis.contourf(surface, levels=16, cmap="viridis")
            figure.colorbar(contour, ax=axis, fraction=0.046, pad=0.04)
        else:
            # Along-line surface: fall back to line plot
            axis.plot(surface.ravel(), color="teal")
            axis.set_ylabel("nT")
        axis.set_title("Magnetic Contours")
        output = io.BytesIO()
        figure.tight_layout()
        figure.savefig(output, format="png", dpi=180)
        plt.close(figure)
        return output.getvalue()

    def _render_surface_png(self, surface) -> bytes:
        import numpy as np
        from matplotlib import pyplot as plt

        figure = plt.figure(figsize=(6, 4))
        if surface.ndim == 2 and surface.shape[0] > 1 and surface.shape[1] > 1:
            axis = figure.add_subplot(111, projection="3d")
            x = np.arange(surface.shape[1])
            y = np.arange(surface.shape[0])
            grid_x, grid_y = np.meshgrid(x, y)
            axis.plot_surface(grid_x, grid_y, surface, cmap="viridis", linewidth=0, antialiased=True)
        else:
            axis = figure.add_subplot(111)
            axis.plot(surface.ravel(), color="teal")
            axis.set_ylabel("nT")
        axis.set_title("3D Magnetic Surface")
        output = io.BytesIO()
        figure.tight_layout()
        figure.savefig(output, format="png", dpi=180)
        plt.close(figure)
        return output.getvalue()

    def _update_run(self, run_id: str, index: int, status: str, detail: str) -> None:
        run = self._store.get_processing_run(run_id)
        steps = run["steps"]
        steps[index]["status"] = status
        steps[index]["detail"] = detail
        logs = list(run.get("logs") or [])
        logs.append(
            {
                "timestamp": utc_now(),
                "step": steps[index]["name"],
                "status": status,
                "detail": detail,
            }
        )
        run_status = "running" if status == "running" else run.get("status", "queued")
        self._store.update_processing_run(
            run_id,
            {
                "steps": steps,
                "logs": logs[-100:],
                "status": run_status,
                "updated_at": utc_now(),
            },
        )
