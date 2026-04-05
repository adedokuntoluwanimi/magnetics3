from __future__ import annotations

import json
import unittest

from backend.gcp.vertex_ai import ExportProviderError
from backend.services.ai_service import AIService


class _FakeStore:
    def __init__(self, project, task):
        self._project = project
        self._task = task

    def get_project(self, project_id):
        return self._project if project_id == self._project["id"] else None

    def get_task(self, task_id):
        return self._task if task_id == self._task["id"] else None


class _FakeClient:
    def __init__(self, text="Assistant response"):
        self.text = text
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.text, Exception):
            raise self.text
        if isinstance(self.text, list):
            value = self.text.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return self.text


class _FakeStorage:
    def __init__(self, blobs):
        self._blobs = blobs

    def download_bytes(self, bucket, object_name):
        return self._blobs[(bucket, object_name)]


class AIServiceTests(unittest.TestCase):
    def _build_task(self):
        return {
            "id": "task-1",
            "project_id": "project-1",
            "name": "Task",
            "description": "Mag survey task",
            "platform": "ground",
            "scenario": None,
            "processing_mode": "single",
            "analysis_config": {"corrections": ["diurnal"], "add_ons": ["analytic_signal"], "model": "kriging"},
            "survey_files": [
                {
                    "file_name": "survey.csv",
                    "bucket": "uploads",
                    "object_name": "survey.csv",
                }
            ],
            "basemap_file": {
                "file_name": "notes.txt",
                "bucket": "uploads",
                "object_name": "notes.txt",
            },
            "results": {
                "artifacts": [
                    {"file_name": "results.json", "bucket": "results", "object_name": "results.json"}
                ],
                "data": {"stats": {"mean": 1.0}},
            },
            "dataset_profile": {"total_rows": 3},
        }

    def _build_project(self):
        return {"id": "project-1", "name": "Project", "context": "Context"}

    def test_generate_response_loads_results_and_uploaded_context(self):
        full_results = {
            "stats": {"mean": 10.0, "std": 1.2, "min": 8.0, "max": 12.0, "point_count": 3, "anomaly_count": 1},
            "points": [
                {"latitude": 6.1, "longitude": 3.2, "magnetic": 10.5},
            ],
            "qa_report": {"status": "valid", "quality_score": 0.9, "fallback_events": []},
            "validation_summary": {"status": "valid", "row_count": 3, "warnings": []},
            "analytic_signal": [[1.0, 2.0], [3.0, 4.0]],
        }
        blobs = {
            ("results", "results.json"): json.dumps(full_results).encode("utf-8"),
            ("uploads", "survey.csv"): b"latitude,longitude,magnetic\n6.1,3.2,10.5\n6.2,3.3,11.0\n",
            ("uploads", "notes.txt"): b"Client note: focus on QA and clean outputs.",
        }
        chat_client = _FakeClient("Working chat response")
        export_client = _FakeClient("Export response")
        service = AIService(_FakeStore(self._build_project(), self._build_task()), chat_client, export_client, _FakeStorage(blobs))

        response = service.generate_response("project-1", "task-1", location="preview", question="What do we have?")

        self.assertEqual(response.message, "Working chat response")
        prompt = chat_client.calls[0]["system_prompt"]
        self.assertIn("File: survey.csv", prompt)
        self.assertIn("File: notes.txt", prompt)
        self.assertIn("Analytic Signal", prompt)
        self.assertIn("QA status: valid", prompt)

    def test_generate_export_report_includes_uploaded_file_summary(self):
        report_json = {
            "summary": "Summary",
            "docx": {"title": "Docx", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": []},
            "pdf": {"title": "Pdf", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": []},
            "pptx": {"title": "Pptx", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": []},
        }
        blobs = {
            ("uploads", "survey.csv"): b"latitude,longitude,magnetic\n6.1,3.2,10.5\n",
            ("uploads", "notes.txt"): b"Reference note",
        }
        chat_client = _FakeClient("Chat response")
        export_client = _FakeClient(json.dumps(report_json))
        service = AIService(_FakeStore(self._build_project(), self._build_task()), chat_client, export_client, _FakeStorage(blobs))

        result = service.generate_export_report(
            "project-1",
            "task-1",
            {"stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0}, "points": []},
        )

        self.assertEqual(result.report_data["pdf"]["executive_summary"], "Summary")
        prompt = export_client.calls[0]["user_prompt"]
        self.assertIn("uploaded_files_summary", prompt)
        self.assertIn("survey.csv", prompt)
        self.assertIn("notes.txt", prompt)
        self.assertIn("Relevant export rules", prompt)
        self.assertIn("PPTX: <=5 bullets per slide", prompt)

    def test_export_prompt_uses_compact_context_and_rule_excerpt(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        prompt = service._build_export_data_prompt(
            self._build_project(),
            self._build_task(),
            self._build_task()["analysis_config"],
            {
                "stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
                "surface": [[10.0, 11.0], [11.0, 12.0]],
                "qa_report": {"status": "valid_with_warnings", "quality_score": 0.8, "warnings": ["Limited leveling support"], "fallback_events": []},
                "stage_log": [{"stage": "validation", "detail": "very long"} for _ in range(20)],
            },
            {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
            "survey.csv: some uploaded context",
            {"formats": ["pdf", "pptx"], "aurora_sections": ["Structural interpretation"], "export_options": {"include_corrected_field": True}},
        )

        self.assertIn("\"qa_summary\"", prompt)
        self.assertIn("\"diagnostics_summary\"", prompt)
        self.assertIn("\"processing_path\"", prompt)
        self.assertNotIn("\"stage_log\"", prompt)
        self.assertNotIn("\"correction_report\"", prompt)
        self.assertLess(len(prompt), 9000)

    def test_generate_export_report_falls_back_to_structured_report_data(self):
        blobs = {
            ("uploads", "survey.csv"): b"latitude,longitude,magnetic\n6.1,3.2,10.5\n",
            ("uploads", "notes.txt"): b"Reference note",
        }
        chat_client = _FakeClient("Chat response")
        export_client = _FakeClient("not-json")
        service = AIService(_FakeStore(self._build_project(), self._build_task()), chat_client, export_client, _FakeStorage(blobs))

        result = service.generate_export_report(
            "project-1",
            "task-1",
            {
                "stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
                "points": [],
                "surface": [[10.0, 11.0], [11.5, 12.0]],
                "regional_residual": [[0.4, 0.6], [0.3, 0.5]],
                "analytic_signal": [[1.0, 1.2], [1.1, 1.3]],
                "validation_summary": {"base_station_count": 3},
                "qa_report": {"status": "valid_with_warnings", "quality_score": 0.82, "warnings": ["Leveling support was limited."], "fallback_events": []},
            },
        )

        self.assertIn("pdf", result.report_data)
        self.assertIn("docx", result.report_data)
        self.assertIn("pptx", result.report_data)
        self.assertIn("Project", result.report_data["summary"])
        layer_sections = [section for section in result.report_data["pdf"]["sections"] if section.get("type") == "layer"]
        self.assertTrue(layer_sections)
        flattened = " ".join(
            " ".join(section.get("bullets") or []) + " " + (section.get("body") or "")
            for section in layer_sections
        ).lower()
        self.assertNotIn("was available for this run", flattened)
        self.assertNotIn("has been included because it exists", flattened)
        self.assertIn("residual", flattened)
        self.assertIn("confidence", flattened)

    def test_generate_export_report_rejects_raw_dump_output_and_uses_fallback(self):
        report_json = {
            "summary": "Bad summary",
            "docx": {
                "title": "Docx",
                "executive_summary": "Summary",
                "sections": [
                    {
                        "type": "layer",
                        "title": "Corrected Magnetic Field",
                        "include": True,
                        "bullets": ["{'type': 'FeatureCollection'}"],
                        "body": '{"type": "FeatureCollection"}',
                        "visual_refs": [],
                    }
                ],
                "visuals": [],
                "recommendations": [],
                "file_manifest": [],
            },
            "pdf": {
                "title": "Pdf",
                "executive_summary": "Summary",
                "sections": [
                    {
                        "type": "layer",
                        "title": "Corrected Magnetic Field",
                        "include": True,
                        "bullets": ["latitude,longitude,magnetic"],
                        "body": '{"type": "FeatureCollection"}',
                        "visual_refs": [],
                    }
                ],
                "visuals": [],
                "recommendations": [],
                "file_manifest": [],
            },
            "pptx": {"title": "Pptx", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": []},
        }
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient(json.dumps(report_json)), _FakeStorage({}))

        result = service.generate_export_report(
            "project-1",
            "task-1",
            {
                "stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
                "surface": [[10.0, 11.0], [11.5, 12.0]],
                "regional_residual": [[0.4, 0.6], [0.3, 0.5]],
                "qa_report": {"status": "valid_with_warnings", "quality_score": 0.82, "warnings": ["Leveling support was limited."], "fallback_events": []},
            },
        )

        flattened = json.dumps(result.report_data).lower()
        self.assertIn("confidence", flattened)
        self.assertNotIn("featurecollection", flattened)
        self.assertNotIn("latitude,longitude,magnetic", flattened)

    def test_generate_export_report_degrades_honestly_on_provider_failure(self):
        provider_error = ExportProviderError(
            "Anthropic export generation failed (rate_limit): exhausted",
            category="rate_limit",
            provider="anthropic",
            model="claude-sonnet-4-6-20250514",
            retryable=True,
        )
        export_client = _FakeClient(provider_error)
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), export_client, _FakeStorage({}))

        result = service.generate_export_report(
            "project-1",
            "task-1",
            {
                "stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
                "surface": [[10.0, 11.0], [11.5, 12.0]],
                "qa_report": {"status": "degraded", "quality_score": 0.5, "warnings": ["Provider degraded."], "fallback_events": []},
            },
        )

        workflow_sections = [section for section in result.report_data["pdf"]["sections"] if section.get("type") == "processing_workflow"]
        self.assertTrue(workflow_sections)
        callouts = " ".join(" ".join(section.get("callouts") or []) for section in workflow_sections).lower()
        self.assertIn("anthropic export generation failed", callouts)
        self.assertIn("fallback", json.dumps(result.report_data).lower())


if __name__ == "__main__":
    unittest.main()
