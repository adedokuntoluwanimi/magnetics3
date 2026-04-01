from __future__ import annotations

import io
import json
import unittest
import zipfile

from backend.services.export_service import ExportService


class _FakeStore:
    pass


class _FakeStorage:
    def __init__(self):
        self.downloads = {}

    def download_bytes(self, bucket, object_name):
        return self.downloads[(bucket, object_name)]


class _FakeAI:
    pass


class _FakeAurora:
    def __init__(self):
        self.report_data = None
        self.summary = "Summary"
        self.highlights = ["Highlight one", "Highlight two"]


class ExportServiceTests(unittest.TestCase):
    def setUp(self):
        self.storage = _FakeStorage()
        self.service = ExportService(_FakeStore(), self.storage, _FakeAI())
        self.project = {"name": "Project"}
        self.task = {"name": "Task", "results": {"artifacts": []}}
        self.data = {
            "grid_x": [[3.0, 3.1], [3.0, 3.1]],
            "grid_y": [[6.0, 6.0], [6.1, 6.1]],
            "surface": [[10.0, 11.0], [12.0, 13.0]],
            "uncertainty": [[0.1, 0.2], [0.3, 0.4]],
            "analytic_signal": [[1.0, 1.1], [1.2, 1.3]],
            "points": [{"longitude": 3.0, "latitude": 6.0, "magnetic": 10.0, "line_id": 1}],
            "predicted_points": [{"longitude": 3.1, "latitude": 6.1, "predicted_magnetic": 11.0, "line_id": 2}],
            "qa_report": {"status": "valid"},
            "validation_summary": {"status": "valid"},
        }

    def test_csv_bundle_contains_metadata_points_and_layers(self):
        payload = self.service._build_csv_bundle(self.project, self.task, self.data)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            self.assertIn("metadata/qa_report.json", names)
            self.assertIn("points/measured_points.csv", names)
            self.assertIn("points/predicted_points.csv", names)
            self.assertIn("grids/tmf.csv", names)
            self.assertIn("grids/analytic_signal.csv", names)

    def test_geojson_bundle_contains_traverses_and_grid_layers(self):
        payload = self.service._build_geojson_bundle(self.project, self.task, self.data)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            self.assertIn("traverses/traverses.geojson", names)
            self.assertIn("grids/tmf.geojson", names)
            self.assertIn("points/measured_points.geojson", names)
            traverses = json.loads(archive.read("traverses/traverses.geojson"))
            self.assertEqual(traverses["type"], "FeatureCollection")

    def test_pptx_builder_handles_missing_scenario(self):
        try:
            import pptx  # noqa: F401
        except ModuleNotFoundError:
            self.skipTest("python-pptx is not installed in this local test environment")
        task = {"name": "Task", "scenario": None, "platform": None, "analysis_config": {}, "results": {"artifacts": []}}
        payload = self.service._build_pptx(self.project, task, {"stats": {"point_count": 1, "mean": 10.0, "std": 1.0, "min": 9.0, "max": 11.0}}, _FakeAurora())
        self.assertTrue(payload.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
