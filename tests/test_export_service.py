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
            self.assertIn("csv_bundle/metadata.json", names)
            self.assertIn("csv_bundle/measured_points.csv", names)
            self.assertIn("csv_bundle/predicted_points.csv", names)
            self.assertIn("csv_bundle/corrected_field.csv", names)
            self.assertIn("csv_bundle/analytic_signal.csv", names)

    def test_geojson_bundle_contains_traverses_and_grid_layers(self):
        payload = self.service._build_geojson_bundle(self.project, self.task, self.data)
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            names = set(archive.namelist())
            self.assertIn("geojson_bundle/corrected_points.geojson", names)
            self.assertIn("geojson_bundle/corrected_surface.geojson", names)
            self.assertIn("geojson_bundle/predicted_points.geojson", names)
            traverses = json.loads(archive.read("geojson_bundle/corrected_points.geojson"))
            self.assertEqual(traverses["type"], "FeatureCollection")

    def test_artifact_stem_uses_task_and_project_names(self):
        stem = self.service._artifact_stem({"name": "Site C"}, {"name": "Permanent Site"})
        self.assertEqual(stem, "site_c_permanent_site")

    def test_quality_check_payload_removes_placeholder_only_sections(self):
        payload = {
            "title": "Deck",
            "sections": [
                {"title": "Main Result", "include": True, "bullets": ["Real finding"], "body": "[Insert map here]", "visual_refs": []},
                {"title": "Empty", "include": True, "bullets": [], "body": "", "visual_refs": []},
            ],
            "quality_checks": [],
        }

        cleaned = self.service._quality_check_payload(payload, slide_mode=True)

        self.assertEqual(len(cleaned["sections"]), 1)
        self.assertEqual(cleaned["sections"][0]["title"], "Main Result")
        self.assertEqual(cleaned["sections"][0]["body"], "")

    def test_layer_specs_use_truthful_residual_labeling(self):
        specs = self.service._layer_specs({"emag2_residual": [[1.0]]})
        labels = [spec["label"] for spec in specs]
        slugs = [spec["slug"] for spec in specs]
        self.assertIn("Regional Residual Product", labels)
        self.assertNotIn("EMAG2 Comparison", labels)
        self.assertIn("regional_residual_product", slugs)

    def test_rtp_export_label_reflects_fallback(self):
        label = self.service._rtp_export_label({"qa_report": {"fallback_events": [{"requested": "rtp", "actual": "low_latitude_fallback"}]}})
        self.assertEqual(label, "Low-latitude fallback transform")

    def test_document_payload_orders_core_sections(self):
        aurora = _FakeAurora()
        aurora.report_data = {
            "pdf": {
                "title": "Report",
                "executive_summary": "Summary",
                "sections": [
                    {"type": "conclusions", "title": "Conclusions", "include": True, "bullets": ["Done"], "body": "", "visual_refs": []},
                    {"type": "project_overview", "title": "Project Overview", "include": True, "bullets": ["Context"], "body": "", "visual_refs": []},
                    {"type": "processing_workflow", "title": "Processing Workflow Summary", "include": True, "bullets": ["Workflow"], "body": "", "visual_refs": []},
                ],
                "visuals": [],
                "recommendations": [],
                "file_manifest": [],
                "quality_checks": [],
            }
        }

        payload = self.service._document_payload(aurora, "pdf")

        self.assertEqual([section["type"] for section in payload["sections"][:3]], ["project_overview", "processing_workflow", "conclusions"])

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
