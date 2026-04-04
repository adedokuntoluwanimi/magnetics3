from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from backend.services.processing_service import (
    ProcessingRuntime,
    ProcessingService,
    _compute_igrf_total_supported,
)


class _FakeStore:
    def get_task(self, task_id):
        return None

    def get_processing_run(self, run_id):
        return None


class _FakeStorage:
    def __init__(self):
        self.uploads = []

    def upload_result(self, **kwargs):
        self.uploads.append(kwargs)
        return types.SimpleNamespace(
            model_dump=lambda mode="json": {
                "file_name": kwargs["file_name"],
                "bucket": "results-bucket",
                "object_name": kwargs["file_name"],
            }
        )


class ProcessingServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = ProcessingService(_FakeStore(), _FakeStorage())

    def test_coordinate_outliers_use_robust_filter(self):
        frame = pd.DataFrame(
            {
                "latitude": [7.0, 7.0001, 7.0002, 7.0003, 55.0],
                "longitude": [3.0, 3.0001, 3.0002, 3.0003, 90.0],
            }
        )
        cleaned, removed = self.service._remove_coordinate_outliers(frame)
        self.assertEqual(removed, 1)
        self.assertEqual(len(cleaned), 4)

    def test_diurnal_correction_records_quality_and_reduces_drift(self):
        time = np.arange(0, 600, 60, dtype=float)
        base = 50000.0 + np.sin(time / 240.0) * 10.0
        survey_mag = 100.0 + base
        frame = pd.DataFrame(
            {
                "time_s": np.concatenate([time, time]),
                "magnetic": np.concatenate([base, survey_mag]),
                "__is_base_station__": np.concatenate([np.ones_like(time), np.zeros_like(time)]),
                "longitude": np.concatenate([np.zeros_like(time), np.linspace(3.0, 3.01, len(time))]),
                "latitude": np.concatenate([np.zeros_like(time), np.linspace(7.0, 7.01, len(time))]),
            }
        )
        corrected, _ = self.service._apply_diurnal_correction(frame, {"analysis_config": {}})
        report = corrected.attrs.get("diurnal_report") or {}
        self.assertEqual(report.get("algorithm"), "interval_base_linear")
        self.assertEqual(report.get("segment_count"), len(time) - 1)
        self.assertGreater(report.get("quality", 0), 0.5)
        self.assertEqual(len(report.get("segments") or []), len(time) - 1)
        self.assertEqual(report.get("diurnal_method"), "interval_base_linear")
        self.assertAlmostEqual(report.get("diurnal_reference_value"), base[0], places=6)
        self.assertAlmostEqual(report.get("diurnal_interval_coverage_pct"), 100.0, places=6)

    def test_diurnal_correction_uses_consecutive_base_intervals(self):
        frame = pd.DataFrame(
            {
                "time_s": [0.0, 10.0, 20.0, 5.0, 15.0],
                "magnetic": [100.0, 110.0, 105.0, 60.0, 70.0],
                "__is_base_station__": [1, 1, 1, 0, 0],
                "longitude": [3.0, 3.0, 3.0, 3.01, 3.02],
                "latitude": [7.0, 7.0, 7.0, 7.01, 7.02],
            }
        )
        corrected, _ = self.service._apply_diurnal_correction(frame, {"analysis_config": {}})
        survey = corrected[corrected["__is_base_station__"] != 1].sort_values("time_s")
        values = survey["magnetic"].to_numpy(dtype=float)
        self.assertAlmostEqual(values[0], 55.0, places=3)
        self.assertAlmostEqual(values[1], 62.5, places=3)
        report = corrected.attrs.get("diurnal_report") or {}
        self.assertEqual(report.get("segment_count"), 2)
        self.assertEqual(len(report.get("segments") or []), 2)
        self.assertAlmostEqual(report.get("diurnal_max_correction_nT"), 7.5, places=3)

    def test_diurnal_correction_uses_constant_hold_outside_base_range(self):
        frame = pd.DataFrame(
            {
                "time_s": [10.0, 20.0, 0.0, 15.0, 30.0],
                "magnetic": [100.0, 110.0, 52.0, 65.0, 78.0],
                "__is_base_station__": [1, 1, 0, 0, 0],
                "longitude": [3.0, 3.0, 3.01, 3.02, 3.03],
                "latitude": [7.0, 7.0, 7.01, 7.02, 7.03],
            }
        )
        corrected, _ = self.service._apply_diurnal_correction(frame, {"analysis_config": {}})
        survey = corrected[corrected["__is_base_station__"] != 1].sort_values("time_s")
        values = survey["magnetic"].to_numpy(dtype=float)
        self.assertAlmostEqual(values[0], 52.0, places=3)
        self.assertAlmostEqual(values[1], 60.0, places=3)
        self.assertAlmostEqual(values[2], 68.0, places=3)
        report = corrected.attrs.get("diurnal_report") or {}
        self.assertEqual(report.get("leading_constant_hold_points"), 1)
        self.assertEqual(report.get("trailing_constant_hold_points"), 1)
        self.assertLess(report.get("diurnal_interval_coverage_pct", 0), 100.0)

    def test_clean_dataframe_preserves_repeated_base_station_revisits(self):
        frame = pd.DataFrame(
            {
                "latitude": [7.0, 7.0, 7.0, 7.01],
                "longitude": [3.0, 3.0, 3.0, 3.01],
                "magnetic": [50000.0, 50005.0, 50009.0, 100.0],
                "__is_base_station__": [1, 1, 1, 0],
                "_hour": [8, 10, 12, 9],
                "_minute": [0, 0, 0, 0],
                "_second": [0, 0, 0, 0],
            }
        )
        cleaned = self.service._clean_dataframe({"processing_mode": "single"}, frame)
        self.assertEqual(int(cleaned["__is_base_station__"].sum()), 3)

    def test_add_ons_include_regional_field_and_residual(self):
        results = {
            "surface": np.array([[1.0, 2.0], [3.0, 4.0]]),
            "grid_x": np.array([[3.0, 3.1], [3.0, 3.1]]),
            "grid_y": np.array([[7.0, 7.0], [7.1, 7.1]]),
        }
        payload = self.service._apply_add_ons({"analysis_config": {"add_ons": ["emag2"]}}, results)
        self.assertIn("regional_field", payload)
        self.assertIn("regional_residual", payload)
        self.assertIn("regional_surface", payload)
        self.assertIn("residual_surface", payload)
        self.assertEqual(len(payload["regional_field"]), 2)

    def test_add_ons_support_polynomial_regional_and_residual_consistency(self):
        results = {
            "surface": np.array([[32963.4, 32963.9], [32964.4, 32964.9]]),
            "grid_x": np.array([[3.0, 3.001], [3.0, 3.001]]),
            "grid_y": np.array([[7.0, 7.0], [7.001, 7.001]]),
            "points": [
                {"longitude": 3.0, "latitude": 7.0, "magnetic": 10.0, "along_line_m": 0.0, "line_id": 0},
                {"longitude": 3.001, "latitude": 7.001, "magnetic": 11.0, "along_line_m": 10.0, "line_id": 0},
                {"longitude": 3.002, "latitude": 7.002, "magnetic": 12.0, "along_line_m": 20.0, "line_id": 0},
            ],
            "correction_report": {"igrf_applied": False},
        }
        payload = self.service._apply_add_ons(
            {
                "processing_mode": "single",
                "analysis_config": {
                    "add_ons": ["emag2"],
                    "regional_residual_enabled": True,
                    "regional_method": "polynomial",
                    "regional_polynomial_degree": 1,
                },
            },
            results,
        )
        self.assertEqual(payload["metadata"].get("regional_method_used"), "polynomial")
        residual = np.asarray(payload["regional_residual"], dtype=float)
        corrected = np.asarray(payload["corrected_field"], dtype=float)
        regional = np.asarray(payload["regional_field"], dtype=float)
        self.assertTrue(np.allclose(residual, corrected - regional))

    def test_leveling_reduces_crossover_rmse(self):
        frame = pd.DataFrame(
            {
                "longitude": [0.0, 0.001, 0.002, 0.0, 0.001, 0.002],
                "latitude": [7.0, 7.0, 7.0, 7.00015, 7.00015, 7.00015],
                "magnetic": [100.0, 101.0, 102.0, 110.0, 111.0, 112.0],
                "_line_id": [1, 1, 1, 2, 2, 2],
            }
        )
        leveled, _ = self.service._apply_leveling_and_crossover({}, frame)
        report = leveled.attrs.get("leveling_report") or {}
        self.assertEqual(report.get("status"), "completed")
        self.assertLessEqual(report.get("after_rmse", 1e9), report.get("before_rmse", 0))
        self.assertGreater(report.get("affected_points", 0), 0)

    def test_single_mode_keeps_one_inferred_line(self):
        frame = pd.DataFrame(
            {
                "latitude": np.linspace(6.74, 6.75, 12),
                "longitude": np.linspace(3.376, 3.378, 12),
                "magnetic": np.linspace(32970.0, 32980.0, 12),
                "_hour": [14] * 12,
                "_minute": list(range(12)),
                "_second": [0] * 12,
            }
        )
        cleaned = self.service._clean_dataframe({"processing_mode": "single"}, frame)
        self.assertEqual(int(cleaned["_line_id"].nunique()), 1)

    def test_blank_scenario_becomes_automatic_without_prediction_targets(self):
        frame = pd.DataFrame(
            {
                "latitude": np.linspace(6.74, 6.75, 8),
                "longitude": np.linspace(3.376, 3.378, 8),
                "magnetic": np.linspace(32970.0, 32980.0, 8),
                "_line_id": [0] * 8,
                "along_line_m": np.linspace(0.0, 70.0, 8),
            }
        )
        prep = self.service._prepare_prediction_inputs({"processing_mode": "single"}, frame)
        self.assertEqual(prep["scenario"], "automatic")
        self.assertTrue(prep["predict_frame"].empty)

    def test_hybrid_model_reports_residual_strategy(self):
        lon = np.linspace(3.0, 3.01, 8)
        lat = np.linspace(7.0, 7.01, 8)
        magnetic = 100 + (lon - lon.mean()) * 1000 + (lat - lat.mean()) * 500
        frame = pd.DataFrame(
            {
                "longitude": lon,
                "latitude": lat,
                "magnetic": magnetic,
                "_line_id": [1, 1, 1, 1, 2, 2, 2, 2],
            }
        )
        grid_x, grid_y = np.meshgrid(np.linspace(lon.min(), lon.max(), 5), np.linspace(lat.min(), lat.max(), 5))
        result = self.service._generate_surfaces(
            {"analysis_config": {"model": "hybrid"}, "scenario": "sparse"},
            {"train_frame": frame, "frame": frame, "grid_x": grid_x, "grid_y": grid_y, "predict_frame": pd.DataFrame()},
        )
        self.assertEqual(result["model_used"], "hybrid")
        self.assertIn(result["model_metadata"]["algorithm"], {"rf_trend_plus_kriged_residual", "weighted_blend_fallback"})

    def test_qa_report_reflects_critical_fallback(self):
        runtime = ProcessingRuntime(
            validation_summary={"status": "valid", "row_count": 10, "valid_row_count": 10, "dropped_row_count": 0, "issues": [], "warnings": []},
            stage_reports=[
                {"metadata": {}},
                {"metadata": {}},
                {"metadata": {"igrf_applied": False, "lag": {}, "heading": {}}},
                {"metadata": {}},
            ],
            fallback_events=[
                {
                    "stage": "igrf",
                    "requested": "igrf",
                    "actual": "uncorrected_field",
                    "reason": "pyIGRF unavailable",
                    "severity": "critical",
                    "timestamp": "2026-01-01T00:00:00+00:00",
                }
            ],
            warnings=["igrf: pyIGRF unavailable"],
            correction_path=["spike removal"],
        )
        prep = {"train_frame": pd.DataFrame({"magnetic": [1.0, 2.0, 3.0]}), "frame": pd.DataFrame({"magnetic": [1.0, 2.0, 3.0]}), "predict_frame": pd.DataFrame(), "scenario": "explicit"}
        results = {"surface": np.array([[1.0, 2.0], [3.0, 4.0]]), "model_metadata": {}, "uncertainty_metadata": {}}
        qa = self.service._build_qa_report({}, prep, results, {"metadata": {}}, runtime)
        self.assertEqual(qa["status"], "degraded")
        self.assertTrue(qa["blocking_issues"])

    def test_igrf_prefers_ppigrf_backend_when_available(self):
        fake_module = types.SimpleNamespace(
            igrf=lambda lon, lat, h_km, dt: (1000.0 + lon, 2000.0 + lat, 3000.0 + h_km)
        )
        with mock.patch.dict(sys.modules, {"ppigrf": fake_module}, clear=False):
            result = _compute_igrf_total_supported(
                np.array([3.0, 3.1], dtype=float),
                np.array([7.0, 7.1], dtype=float),
                2026.25,
                elevation_m=np.array([120.0, 130.0], dtype=float),
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["backend"], "ppigrf")
        self.assertEqual(result["reference_model"], "IGRF-14")
        self.assertEqual(len(result["values"]), 2)
        self.assertTrue(np.all(np.isfinite(result["values"])))

    def test_igrf_returns_none_when_no_backend_is_available(self):
        def raising_import(name):
            raise ModuleNotFoundError(name)

        with mock.patch("backend.services.processing_service.importlib.import_module", side_effect=raising_import):
            result = _compute_igrf_total_supported(
                np.array([3.0], dtype=float),
                np.array([7.0], dtype=float),
                2026.25,
            )
        self.assertIsNone(result)

    def test_persist_outputs_keeps_support_mask_out_of_firestore_payload(self):
        prep = {
            "train_frame": pd.DataFrame({"longitude": [3.0], "latitude": [7.0], "magnetic": [100.0]}),
            "predict_frame": pd.DataFrame({"longitude": [], "latitude": [], "magnetic": []}),
        }
        results = {
            "grid_x": np.array([[3.0, 3.1], [3.0, 3.1]]),
            "grid_y": np.array([[7.0, 7.0], [7.1, 7.1]]),
            "surface": np.array([[100.0, 101.0], [102.0, 103.0]]),
            "uncertainty": np.array([[1.0, 2.0], [3.0, 4.0]]),
            "points": [{"latitude": 7.0, "longitude": 3.0, "magnetic": 100.0}],
            "stats": {"mean": 101.5},
            "model_used": "none",
            "model_metadata": {},
            "uncertainty_metadata": {},
            "support_mask": [[True, True], [True, False]],
        }
        with (
            mock.patch.object(self.service, "_render_heatmap_png", return_value=b"png"),
            mock.patch.object(self.service, "_render_contour_png", return_value=b"png"),
            mock.patch.object(self.service, "_render_surface_png", return_value=b"png"),
        ):
            stored = self.service._persist_outputs(
                {"project_id": "project-1", "id": "task-1"},
                prep,
                results,
                {"selected_add_ons": [], "metadata": {}},
                {"status": "valid"},
                {"status": "valid"},
            )
        self.assertNotIn("support_mask", stored["data"])


if __name__ == "__main__":
    unittest.main()
