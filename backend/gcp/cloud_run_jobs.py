from __future__ import annotations

from backend.config import Settings
from backend.gcp.clients import run_jobs_client


class CloudRunJobsBackend:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = run_jobs_client()

    def run_processing_job(self, env_vars: dict[str, str]) -> str:
        return self._run_job(self._settings.processing_job, env_vars)

    def run_export_job(self, env_vars: dict[str, str]) -> str:
        return self._run_job(self._settings.export_job, env_vars)

    def _run_job(self, job_name: str, env_vars: dict[str, str]) -> str:
        from google.cloud.run_v2.types import EnvVar, RunJobOverrides, RunJobRequest

        name = (
            f"projects/{self._settings.infra_project_id}/locations/"
            f"{self._settings.region}/jobs/{job_name}"
        )
        request = RunJobRequest(
            name=name,
            overrides=RunJobOverrides(
                container_overrides=[
                    RunJobOverrides.ContainerOverride(
                        env=[EnvVar(name=key, value=value) for key, value in env_vars.items()]
                    )
                ]
            ),
        )
        # Fire-and-forget: submit the execution and return immediately.
        # The job writes its own status updates to Firestore; the API does not block.
        operation = self._client.run_job(request=request)
        try:
            return operation.operation.name
        except Exception:
            return ""
