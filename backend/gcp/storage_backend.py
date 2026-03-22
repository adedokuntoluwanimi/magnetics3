from __future__ import annotations

from io import BytesIO
from urllib.parse import quote

from backend.config import Settings
from backend.gcp.clients import storage_client
from backend.logging_utils import log_event
from backend.models import ArtifactRecord


class StorageBackend:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = storage_client(settings)

    def upload_task_input(
        self,
        *,
        project_id: str,
        task_id: str,
        file_name: str,
        content_type: str,
        data: bytes,
        kind: str,
    ) -> ArtifactRecord:
        bucket = self._client.bucket(self._settings.uploads_bucket)
        object_name = f"projects/{project_id}/tasks/{task_id}/{kind}/{quote(file_name)}"
        blob = bucket.blob(object_name)
        blob.upload_from_file(BytesIO(data), content_type=content_type)
        signed_url = self._safe_signed_url(blob, bucket.name, object_name)
        return ArtifactRecord(
            file_name=file_name,
            content_type=content_type or "application/octet-stream",
            bucket=bucket.name,
            object_name=object_name,
            gcs_uri=f"gs://{bucket.name}/{object_name}",
            signed_url=signed_url,
            kind=kind,
            size_bytes=len(data),
        )

    def upload_result(
        self,
        *,
        project_id: str,
        task_id: str,
        file_name: str,
        content_type: str,
        data: bytes,
        kind: str = "result",
    ) -> ArtifactRecord:
        bucket = self._client.bucket(self._settings.results_bucket)
        object_name = f"projects/{project_id}/tasks/{task_id}/{kind}/{quote(file_name)}"
        blob = bucket.blob(object_name)
        blob.upload_from_file(BytesIO(data), content_type=content_type)
        signed_url = self._safe_signed_url(blob, bucket.name, object_name)
        return ArtifactRecord(
            file_name=file_name,
            content_type=content_type,
            bucket=bucket.name,
            object_name=object_name,
            gcs_uri=f"gs://{bucket.name}/{object_name}",
            signed_url=signed_url,
            kind=kind,
            size_bytes=len(data),
        )

    def download_text(self, bucket_name: str, object_name: str) -> str:
        bucket = self._client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        return blob.download_as_text()

    def download_bytes(self, bucket_name: str, object_name: str) -> bytes:
        bucket = self._client.bucket(bucket_name)
        blob = bucket.blob(object_name)
        return blob.download_as_bytes()

    def _safe_signed_url(self, blob, bucket_name: str, object_name: str) -> str:
        try:
            return blob.generate_signed_url(version="v4", expiration=3600)
        except Exception as exc:
            log_event(
                "WARNING",
                "Falling back from signed URL generation",
                action="storage.sign_url.fallback",
                bucket=bucket_name,
                object_name=object_name,
                error=str(exc),
            )
            return f"https://storage.googleapis.com/{bucket_name}/{object_name}"
