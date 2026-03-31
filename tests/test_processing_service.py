from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from backend.services.processing_service import ProcessingRuntime, ProcessingService


class _FakeStore:
    def get_task(self, task_id):
        return None

    def get_processing_run(self, run_id):
        return None


class _FakeStorage:
    pass


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
        self.assertEqual(report.get("algorithm"), "base_station_cubic_spline")
        self.assertGreater(report.get("quality", 0), 0.5)
        self.assertLessEqual(report.get("residual_drift_after", 1e9), report.get("residual_drift_before", 0))

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


if __name__ == "__main__":
    unittest.main()
