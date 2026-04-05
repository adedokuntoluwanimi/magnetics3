from __future__ import annotations

import json
import re
import unittest

from backend.config import Settings
from backend.gcp.vertex_ai import AnthropicClaudeClient
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


class _BlockAwareClient:
    def __init__(self, responses_by_block, default=None):
        self.responses_by_block = {key: list(value) for key, value in responses_by_block.items()}
        self.default = default
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        prompt = kwargs.get("user_prompt") or ""
        match = re.search(r"block `([^`]+)`", prompt)
        block_name = match.group(1) if match else ""
        queue = self.responses_by_block.get(block_name)
        if queue:
            value = queue.pop(0)
        else:
            value = self.default
        if isinstance(value, Exception):
            raise value
        return value


class _FakeStorage:
    def __init__(self, blobs):
        self._blobs = blobs

    def download_bytes(self, bucket, object_name):
        return self._blobs[(bucket, object_name)]


class AIServiceTests(unittest.TestCase):
    def _valid_export_package(self):
        return {
            "summary": "Summary",
            "docx": {"title": "Docx", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": []},
            "pdf": {"title": "Pdf", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": []},
            "pptx": {"title": "Pptx", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": []},
        }

    def _valid_report_fragment(self):
        return {
            "summary": "Summary",
            "report": {
                "title": "Report",
                "subtitle": "Sub",
                "executive_summary": "Summary",
                "sections": [
                    {"type": "executive_summary", "title": "Executive Summary", "include": True, "bullets": ["Short grounded summary."]},
                    {"type": "layer", "title": "Corrected Magnetic Field", "include": True, "bullets": ["Range and confidence remain tied to measured support."], "visual_refs": ["corrected_heatmap.png"]},
                ],
                "visuals": [{"visual_ref": "corrected_heatmap.png", "caption": "Corrected map"}],
                "recommendations": ["Validate weaker-support zones before follow-up targeting because support remains limited outside measured coverage."],
                "quality_checks": ["Run-specific content only."],
            },
        }

    def _valid_pptx_fragment(self):
        return {
            "summary": "Summary",
            "pptx": {
                "title": "Slides",
                "subtitle": "Sub",
                "executive_summary": "Summary",
                "sections": [
                    {"type": "executive_summary", "title": "Executive Summary", "include": True, "bullets": ["Main result", "QA warning", "Next step"], "speaker_notes": "Keep this concise."},
                ],
                "visuals": [],
                "recommendations": ["Confirm anomalies with field follow-up where support remains limited."],
                "quality_checks": ["Slide bullets kept concise."],
            },
        }

    def _valid_block_payloads(self):
        return {
            "executive_summary": {"title": "Permanent Site Technical Report", "subtitle": "Compact export", "executive_summary": "Summary"},
            "project_setup": {"sections": [{"type": "project_overview", "title": "Project Overview", "bullets": ["Ground magnetic survey over the project area."], "body": "Project overview grounded in task metadata.", "visual_refs": [], "callouts": []}]},
            "task_summary": {"sections": [{"type": "data_summary", "title": "Data and Survey Summary", "bullets": ["64 stations", "Base-station support noted"], "body": "Survey/data summary remains concise and grounded.", "visual_refs": [], "callouts": []}]},
            "processing_qa": {"sections": [{"type": "processing_workflow", "title": "Processing Workflow Summary", "bullets": ["Diurnal applied where supported", "QA warning retained"], "body": "Processing path is described with explicit QA caution.", "visual_refs": [], "callouts": ["warning: support remains limited"]}]},
            "key_findings": {"sections": [{"type": "key_findings", "title": "Key Findings", "bullets": ["Residual contrast persists near measured support."], "body": "Key findings stay tied to the processed outputs.", "visual_refs": ["corrected_heatmap.png"], "callouts": []}]},
            "result_layers": {"sections": [{"type": "layer", "title": "Corrected Magnetic Field", "bullets": ["Amplitude remains grounded in measured support.", "Confidence is strongest near observed stations."], "body": "Corrected field interpretation remains compact and run-specific.", "visual_refs": ["corrected_heatmap.png"], "interpretation": "Broad trend and local contrast are separated cautiously.", "implication": "Use the corrected map with residual and QA context.", "callouts": ["confidence remains support-limited"]}]},
            "limitations": {"sections": [{"type": "data_quality", "title": "Data Quality and Reliability", "bullets": ["QA status: valid_with_warnings", "Uncertainty remains important."], "body": "Reliability weakens where support thins or fallbacks were used.", "visual_refs": ["uncertainty.png"], "callouts": ["caution: fallback and support limits remain relevant"]}]},
            "recommendations": {"sections": [{"type": "conclusions", "title": "Conclusions", "bullets": ["Interpretation should stay tied to support and QA."], "body": "Conclusions remain run-specific and QA-aware.", "visual_refs": [], "callouts": ["confidence is moderate because support remains limited"]}], "recommendations": ["Prioritise support-driven follow-up where uncertainty remains elevated."]},
            "pptx_group_1": {"title": "Slides", "subtitle": "Compact deck", "executive_summary": "Summary", "sections": [{"type": "executive_summary", "title": "Executive Summary", "bullets": ["Main result", "QA warning", "Next step"], "speaker_notes": "Compact summary for the slide deck."}], "recommendations": []},
            "pptx_group_2": {"sections": [{"type": "project_overview", "title": "Project Overview", "bullets": ["Project context"], "speaker_notes": "Context slide."}, {"type": "data_summary", "title": "Data and Survey Summary", "bullets": ["64 stations", "5 m spacing"], "speaker_notes": "Data slide."}, {"type": "processing_workflow", "title": "Processing Workflow Summary", "bullets": ["Diurnal", "IGRF", "QA caution"], "speaker_notes": "Workflow slide."}], "recommendations": []},
            "pptx_group_3": {"sections": [{"type": "key_findings", "title": "Key Findings", "bullets": ["Residual contrast persists."], "visual_refs": ["corrected_heatmap.png"], "speaker_notes": "Findings slide."}, {"type": "layer", "title": "Corrected Magnetic Field", "bullets": ["Measured support anchors confidence."], "visual_refs": ["corrected_heatmap.png"], "speaker_notes": "Map slide."}], "recommendations": []},
            "pptx_group_4": {"sections": [{"type": "data_quality", "title": "Data Quality and Reliability", "bullets": ["QA warning", "Support caution"], "speaker_notes": "Reliability slide."}, {"type": "conclusions", "title": "Conclusions", "bullets": ["Keep recommendations support-driven."], "speaker_notes": "Closing slide."}], "recommendations": ["Focus follow-up on support-limited zones with elevated uncertainty."]},
        }

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

    def test_provider_error_classification_captures_status_and_request_id(self):
        class RateLimitError(Exception):
            def __init__(self):
                super().__init__("rate limit exceeded")
                self.request_id = "req_456"
                self.status_code = 429

        client = AnthropicClaudeClient(Settings())
        err = client._classify_error(RateLimitError(), "claude-sonnet-4-6")

        self.assertEqual(err.category, "rate_limit")
        self.assertEqual(err.request_id, "req_456")
        self.assertEqual(err.status_code, 429)
        self.assertTrue(err.retryable)

    def test_preflight_logs_model_unavailable_when_models_api_excludes_configured_model(self):
        class _Model:
            def __init__(self, model_id):
                self.id = model_id

        class _ModelsAPI:
            def list(self, limit=100):
                return type("Response", (), {"data": [_Model("claude-3-5-sonnet-latest")]})()

        class _Client:
            def __init__(self):
                self.models = _ModelsAPI()

        client = AnthropicClaudeClient(Settings(aurora_export_model="claude-sonnet-4-6", anthropic_api_key="test-key"))

        with self.assertLogs("gaia", level="INFO") as logs:
            available = client._list_model_ids(_Client())
            self.assertNotIn("claude-sonnet-4-6", available)
            log_client = AnthropicClaudeClient(Settings(aurora_export_model="claude-sonnet-4-6", anthropic_api_key="test-key"))
            original = log_client._list_model_ids
            try:
                log_client._list_model_ids = lambda _: available
                import sys
                import types

                fake_module = types.SimpleNamespace(Anthropic=lambda api_key: _Client())
                original_module = sys.modules.get("anthropic")
                sys.modules["anthropic"] = fake_module
                self.assertFalse(log_client.preflight_model_availability())
            finally:
                log_client._list_model_ids = original
                if original_module is None:
                    sys.modules.pop("anthropic", None)
                else:
                    sys.modules["anthropic"] = original_module

        combined_logs = "\n".join(logs.output)
        self.assertIn('"action": "export.provider.preflight"', combined_logs)
        self.assertIn('"provider_error_category": "model_unavailable"', combined_logs)
        self.assertIn('"model": "claude-sonnet-4-6"', combined_logs)

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
        blobs = {
            ("uploads", "survey.csv"): b"latitude,longitude,magnetic\n6.1,3.2,10.5\n",
            ("uploads", "notes.txt"): b"Reference note",
        }
        chat_client = _FakeClient("Chat response")
        export_client = _BlockAwareClient({key: [json.dumps(value)] for key, value in self._valid_block_payloads().items()})
        service = AIService(_FakeStore(self._build_project(), self._build_task()), chat_client, export_client, _FakeStorage(blobs))

        result = service.generate_export_report(
            "project-1",
            "task-1",
            {"stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0}, "points": []},
        )

        self.assertEqual(result.report_data["pdf"]["executive_summary"], "Summary")
        prompts = "\n".join(call["user_prompt"] for call in export_client.calls)
        self.assertIn("uploaded_files_summary", prompts)
        self.assertIn("survey.csv", prompts)
        self.assertIn("notes.txt", prompts)
        self.assertIn("compact export block", prompts)

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

    def test_export_prompt_uses_compact_report_schema_for_docx_pdf(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        prompt = service._build_export_data_prompt(
            self._build_project(),
            self._build_task(),
            self._build_task()["analysis_config"],
            {"stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0}, "surface": [[1.0]], "qa_report": {"status": "valid"}},
            {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
            "survey.csv: some uploaded context",
            {"formats": ["pdf", "docx"]},
            expected_formats=["pdf", "docx"],
            retry_mode="initial",
        )

        self.assertIn("- top keys: summary, report", prompt)
        self.assertNotIn("- top keys: docx, pdf, pptx, summary", prompt)
        self.assertIn("return compact completed json only", prompt.lower())

    def test_generate_export_report_falls_back_to_structured_report_data(self):
        blobs = {
            ("uploads", "survey.csv"): b"latitude,longitude,magnetic\n6.1,3.2,10.5\n",
            ("uploads", "notes.txt"): b"Reference note",
        }
        chat_client = _FakeClient("Chat response")
        export_client = _BlockAwareClient({}, default="not-json")
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
        block_payloads = self._valid_block_payloads()
        block_payloads["result_layers"] = {
            "sections": [
                {
                    "type": "layer",
                    "title": "Corrected Magnetic Field",
                    "bullets": ["latitude,longitude,magnetic"],
                    "body": '{"type":"FeatureCollection"}',
                    "visual_refs": [],
                    "interpretation": "",
                    "implication": "",
                    "callouts": [],
                }
            ]
        }
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _BlockAwareClient({key: [json.dumps(value)] for key, value in block_payloads.items()}), _FakeStorage({}))

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

    def test_parse_export_json_accepts_bare_json(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        parsed, meta = service._parse_export_json(json.dumps(self._valid_export_package()))

        self.assertIsNotNone(parsed)
        self.assertEqual(meta["strategies"], ["direct_json"])
        self.assertFalse(meta["fenced_json_detected"])

    def test_parse_export_json_accepts_fenced_json(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        parsed, meta = service._parse_export_json(f"```json\n{json.dumps(self._valid_export_package())}\n```")

        self.assertIsNotNone(parsed)
        self.assertEqual(meta["strategies"], ["direct_json", "fenced_json"])
        self.assertTrue(meta["fenced_json_detected"])

    def test_parse_export_json_accepts_unlabeled_fenced_json(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        parsed, meta = service._parse_export_json(f"```\n{json.dumps(self._valid_export_package())}\n```")

        self.assertIsNotNone(parsed)
        self.assertEqual(meta["strategies"], ["direct_json", "fenced_json"])
        self.assertTrue(meta["fenced_json_detected"])

    def test_parse_export_json_accepts_opening_fence_without_closing_fence(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        parsed, meta = service._parse_export_json(f"```json\n{json.dumps(self._valid_export_package())}")

        self.assertIsNotNone(parsed)
        self.assertEqual(meta["strategies"], ["direct_json", "wrapper_stripped_json"])
        self.assertTrue(meta["fenced_json_detected"])

    def test_parse_export_json_accepts_single_extracted_object_from_harmless_text(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))
        wrapped = f"Here is the export package.\n\n{json.dumps(self._valid_export_package())}\n\nEnd of package."

        parsed, meta = service._parse_export_json(wrapped)

        self.assertIsNotNone(parsed)
        self.assertEqual(meta["strategies"], ["direct_json", "object_extraction"])
        self.assertTrue(meta["object_extraction_attempted"])

    def test_parse_export_json_rejects_malformed_json(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        parsed, meta = service._parse_export_json("```json\n{\"docx\":\n```")

        self.assertIsNone(parsed)
        self.assertEqual(meta["strategies"], ["direct_json", "fenced_json", "wrapper_stripped_json", "object_extraction"])
        self.assertTrue(meta["fenced_json_detected"])
        self.assertTrue(meta["object_extraction_attempted"])

    def test_parse_export_json_rejects_ambiguous_multiple_objects(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))
        payload = f"{json.dumps(self._valid_export_package())}\n{json.dumps(self._valid_export_package())}"

        parsed, meta = service._parse_export_json(payload)

        self.assertIsNone(parsed)
        self.assertEqual(meta["strategies"], ["direct_json", "object_extraction"])
        self.assertTrue(meta["object_extraction_attempted"])
        self.assertEqual(meta["failure_category"], "response_parse_ambiguous")
        self.assertEqual(meta["object_candidate_count"], 2)
        self.assertEqual(meta["forensics"][-1]["failure_class"], "ambiguous_multiple_objects")

    def test_parse_export_json_classifies_truncated_json(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        parsed, meta = service._parse_export_json('{"docx": {"title": "Docx"')

        self.assertIsNone(parsed)
        self.assertEqual(meta["forensics"][0]["failure_class"], "truncated_json")

    def test_parse_export_json_classifies_invalid_escape(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        parsed, meta = service._parse_export_json('{"docx":"bad\\qescape"}')

        self.assertIsNone(parsed)
        self.assertEqual(meta["forensics"][0]["failure_class"], "invalid_string_escaping")

    def test_decode_export_json_candidate_classifies_trailing_prose(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))
        payload = f'{json.dumps(self._valid_export_package())} trailing prose'

        parsed, forensic = service._decode_export_json_candidate(
            payload,
            strategy="direct_json",
            fenced_json_detected=False,
        )

        self.assertIsNone(parsed)
        self.assertEqual(forensic["failure_class"], "trailing_non_json_content")

    def test_safe_error_preview_sanitizes_whitespace_and_truncates(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))

        preview = service._safe_error_preview("abc\n\tdef{\"oops\":1}\nxyz", 8, radius=6)

        self.assertIn("\\n", preview)
        self.assertIn("\\t", preview)
        self.assertLessEqual(len(preview), 32)

    def test_generate_export_report_degrades_honestly_on_provider_failure(self):
        provider_error = ExportProviderError(
            "Anthropic export generation failed (rate_limit): exhausted",
            category="rate_limit",
            provider="anthropic",
            model="claude-sonnet-4-6",
            retryable=True,
            request_id="req_123",
            status_code=429,
            provider_message="rate limit exceeded",
        )
        export_client = _FakeClient(provider_error)
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), export_client, _FakeStorage({}))

        with self.assertLogs("gaia", level="INFO") as logs:
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
        combined_logs = "\n".join(logs.output)
        self.assertIn('"action": "export.path.failure"', combined_logs)
        self.assertIn('"provider_error_category": "rate_limit"', combined_logs)
        self.assertIn('"status_code": 429', combined_logs)
        self.assertIn('"request_id": "req_123"', combined_logs)
        self.assertIn('"outcome": "anthropic_request_failed_fallback_used"', combined_logs)

    def test_generate_export_report_uses_reduced_scope_retry_after_truncated_report_response(self):
        block_payloads = self._valid_block_payloads()
        export_client = _BlockAwareClient(
            {
                "executive_summary": ['{"title":"Permanent Site","executive_summary":"Summary"', json.dumps(block_payloads["executive_summary"])],
                "project_setup": [json.dumps(block_payloads["project_setup"])],
                "task_summary": [json.dumps(block_payloads["task_summary"])],
                "processing_qa": [json.dumps(block_payloads["processing_qa"])],
                "key_findings": [json.dumps(block_payloads["key_findings"])],
                "result_layers": [json.dumps(block_payloads["result_layers"])],
                "limitations": [json.dumps(block_payloads["limitations"])],
                "recommendations": [json.dumps(block_payloads["recommendations"])],
            }
        )
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), export_client, _FakeStorage({}))

        with self.assertLogs("gaia", level="INFO") as logs:
            result = service.generate_export_report(
                "project-1",
                "task-1",
                {
                    "stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
                    "surface": [[10.0, 11.0], [11.5, 12.0]],
                    "qa_report": {"status": "valid_with_warnings", "quality_score": 0.82, "warnings": ["Leveling support was limited."], "fallback_events": []},
                },
                {"formats": ["pdf", "docx"], "aurora_sections": ["Structural interpretation", "Anomaly catalogue", "QA summary"]},
            )

        self.assertEqual(result.report_data["pdf"]["executive_summary"], "Summary")
        self.assertEqual(result.report_data["docx"]["executive_summary"], "Summary")
        self.assertGreaterEqual(len(export_client.calls), 9)
        self.assertIn("retry mode: compact_schema_retry", export_client.calls[1]["user_prompt"].lower())
        combined_logs = "\n".join(logs.output)
        self.assertIn('"action": "export.path.retry"', combined_logs)
        self.assertIn('"retry_mode": "compact_schema_retry"', combined_logs)
        self.assertIn('"outcome": "anthropic_success"', combined_logs)

    def test_generate_export_report_uses_compact_schema_retry_for_pptx_truncation(self):
        block_payloads = self._valid_block_payloads()
        export_client = _BlockAwareClient(
            {
                "pptx_group_1": ['{"sections":[{"type":"executive_summary","title":"Executive Summary","bullets":["Main result"', json.dumps(block_payloads["pptx_group_1"])],
                "pptx_group_2": [json.dumps(block_payloads["pptx_group_2"])],
                "pptx_group_3": [json.dumps(block_payloads["pptx_group_3"])],
                "pptx_group_4": [json.dumps(block_payloads["pptx_group_4"])],
            }
        )
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), export_client, _FakeStorage({}))

        with self.assertLogs("gaia", level="INFO") as logs:
            result = service.generate_export_report(
                "project-1",
                "task-1",
                {
                    "stats": {"mean": 10.0, "std": 1.0, "min": 8.0, "max": 12.0, "point_count": 1, "anomaly_count": 0},
                    "surface": [[10.0, 11.0], [11.5, 12.0]],
                    "qa_report": {"status": "valid", "quality_score": 0.9, "warnings": [], "fallback_events": []},
                },
                {"formats": ["pptx"]},
            )

        self.assertEqual(result.report_data["pptx"]["executive_summary"], "Summary")
        self.assertGreaterEqual(len(export_client.calls), 5)
        self.assertIn("retry mode: compact_schema_retry", export_client.calls[1]["user_prompt"].lower())
        combined_logs = "\n".join(logs.output)
        self.assertIn('"retry_mode": "compact_schema_retry"', combined_logs)
        self.assertIn('"outcome": "anthropic_success"', combined_logs)

    def test_merge_export_block_payload_updates_existing_sections(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))
        package = service._build_fallback_export_package(self._build_project(), self._build_task(), self._build_task()["analysis_config"], {"surface": [[1.0]], "qa_report": {"status": "valid"}}, {"point_count": 1}, None, {"formats": ["pdf", "docx"]})
        merged = service._merge_export_block_payload(package, {"name": "key_findings", "doc_key": "report"}, self._valid_block_payloads()["key_findings"])

        pdf_section = next(section for section in merged["pdf"]["sections"] if section.get("title") == "Key Findings")
        docx_section = next(section for section in merged["docx"]["sections"] if section.get("title") == "Key Findings")
        self.assertEqual(pdf_section["body"], "Key findings stay tied to the processed outputs.")
        self.assertEqual(docx_section["body"], "Key findings stay tied to the processed outputs.")

    def test_validate_export_block_payload_rejects_repeated_content_against_existing_package(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))
        package = service._build_fallback_export_package(self._build_project(), self._build_task(), self._build_task()["analysis_config"], {"surface": [[1.0]], "qa_report": {"status": "valid"}}, {"point_count": 1}, None, {"formats": ["pdf", "docx"]})
        existing = next(section for section in package["pdf"]["sections"] if section.get("title") == "Key Findings")
        payload = {
            "sections": [
                {
                    "type": "key_findings",
                    "title": "Key Findings",
                    "bullets": [],
                    "body": existing["body"],
                    "visual_refs": [],
                    "callouts": [],
                }
            ]
        }
        validated, issues = service._validate_export_block_payload({"name": "key_findings", "doc_key": "report", "target_titles": ["Key Findings"]}, payload, {"surface": [[1.0]], "qa_report": {"status": "valid"}}, {"formats": ["pdf", "docx"]}, package)

        self.assertIsNone(validated)
        self.assertIn("repeated_block_content", issues)

    def test_validation_rejection_logs_exact_reasons(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))
        package = {
            "summary": "Summary",
            "docx": {
                "title": "Docx",
                "executive_summary": "Summary",
                "sections": [{"type": "layer", "title": "Corrected Magnetic Field", "include": True, "body": '{"type": "FeatureCollection"}', "bullets": []}],
                "visuals": [],
                "recommendations": [],
                "file_manifest": [],
                "quality_checks": [],
            },
            "pdf": {
                "title": "Pdf",
                "executive_summary": "Summary",
                "sections": [{"type": "layer", "title": "Made Up Layer", "include": True, "body": "text", "bullets": []}],
                "visuals": [],
                "recommendations": [],
                "file_manifest": [],
                "quality_checks": [],
            },
            "pptx": {"title": "Pptx", "executive_summary": "Summary", "sections": [], "visuals": [], "recommendations": [], "file_manifest": [], "quality_checks": []},
        }
        with self.assertLogs("gaia", level="INFO") as logs:
            prepared = service._prepare_export_package(
                package,
                {"surface": [[1.0]], "qa_report": {"status": "valid"}},
                {"export_options": {"include_corrected_field": True}},
                task_id="task-1",
                export_type="pdf,pptx",
                provider="anthropic",
                model="claude-sonnet-4-6",
                attempt_number=1,
            )
        self.assertIsNone(prepared)
        combined_logs = "\n".join(logs.output)
        self.assertIn('"phase": "export_package_validation"', combined_logs)
        self.assertIn('raw_dump_content', combined_logs)
        self.assertIn('blocked_content', combined_logs)

    def test_parse_forensics_logging_includes_decode_details(self):
        service = AIService(_FakeStore(self._build_project(), self._build_task()), _FakeClient("chat"), _FakeClient("{}"), _FakeStorage({}))
        _, meta = service._parse_export_json('{"docx":"bad\\qescape"}')

        with self.assertLogs("gaia", level="INFO") as logs:
            service._log_export_parse_forensics(
                task_id="task-1",
                export_type="pdf,pptx",
                provider="anthropic",
                model="claude-sonnet-4-6",
                attempt_number=1,
                phase="api_response_parse",
                forensics=meta["forensics"],
            )
        combined_logs = "\n".join(logs.output)
        self.assertIn('"action": "export.path.parse_forensics"', combined_logs)
        self.assertIn('"failure_class": "invalid_string_escaping"', combined_logs)
        self.assertIn('"decode_error_type": "JSONDecodeError"', combined_logs)


if __name__ == "__main__":
    unittest.main()
