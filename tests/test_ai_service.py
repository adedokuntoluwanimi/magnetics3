from __future__ import annotations

import json
import unittest

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
            "executive_summary": "Summary",
            "report": {
                "results_interpretation": [
                    {"layer": "Total Magnetic Field (TMF)", "observations": "Consistent measured coverage."}
                ],
                "recommendations": "Deliver the report and figures.",
            },
            "slides": [],
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

        self.assertEqual(result.report_data["executive_summary"], "Summary")
        prompt = export_client.calls[0]["user_prompt"]
        self.assertIn("uploaded_files_summary", prompt)
        self.assertIn("survey.csv", prompt)
        self.assertIn("notes.txt", prompt)


if __name__ == "__main__":
    unittest.main()
