from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def env_value(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


def bucket_name(value: str) -> str:
    normalized = (value or "").strip()
    if normalized.startswith("gs://"):
        normalized = normalized[5:]
    return normalized.split("/", 1)[0]


@dataclass(frozen=True)
class Settings:
    infra_project_id: str = env_value("GAIA_INFRA_PROJECT_ID", default="app-01-488817")
    ai_project_id: str = env_value("GAIA_AI_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", default="app-01-488817-ai")
    region: str = env_value("GAIA_REGION", "GOOGLE_CLOUD_REGION", default="us-central1")
    ai_region: str = env_value("GAIA_AI_REGION", default="global")
    aurora_chat_project_id: str = env_value("GAIA_AURORA_CHAT_PROJECT_ID", default=env_value("GAIA_INFRA_PROJECT_ID", default="app-01-488817"))
    aurora_chat_region: str = env_value("GAIA_AURORA_CHAT_REGION", default="global")
    aurora_chat_model: str = env_value("GAIA_AURORA_CHAT_MODEL", default="gemini-2.5-flash")
    aurora_export_project_id: str = env_value("GAIA_AURORA_EXPORT_PROJECT_ID", "GAIA_AI_PROJECT_ID", "GOOGLE_CLOUD_PROJECT", default="app-01-488817-ai")
    aurora_export_region: str = env_value("GAIA_AURORA_EXPORT_REGION", "GAIA_AI_REGION", default="global")
    aurora_export_model: str = env_value("GAIA_AURORA_EXPORT_MODEL", "GAIA_AURORA_MODEL", "CLAUDE_MODEL", default="claude-sonnet-4@20250514")
    firestore_database: str = env_value("GAIA_FIRESTORE_DATABASE", default="(default)")
    uploads_bucket: str = bucket_name(env_value("GAIA_UPLOADS_BUCKET", "GCS_BUCKET_RAW"))
    results_bucket: str = bucket_name(env_value("GAIA_RESULTS_BUCKET", "GCS_BUCKET_PROCESSED"))
    public_bucket: str = bucket_name(env_value("GAIA_PUBLIC_BUCKET", "GCS_BUCKET_EXPORTS"))
    processing_topic: str = env_value("GAIA_PROCESSING_TOPIC", default="gaia-magnetics-processing")
    export_topic: str = env_value("GAIA_EXPORT_TOPIC", default="gaia-magnetics-export")
    processing_job: str = env_value("GAIA_PROCESSING_JOB", default="gaia-magnetics-processing")
    export_job: str = env_value("GAIA_EXPORT_JOB", default="gaia-magnetics-export")
    maps_api_key_secret: str = env_value("GAIA_MAPS_API_KEY_SECRET", default="gaia-google-maps-api-key")
    maps_api_key: str = env_value("GAIA_MAPS_API_KEY", "GOOGLE_MAPS_API_KEY")
    service_name: str = env_value("GAIA_SERVICE_NAME", "K_SERVICE", default="gaia-magnetics")
    base_dir: Path = Path(__file__).resolve().parents[1]
    frontend_dir: Path = Path(__file__).resolve().parents[1] / "frontend"

    @property
    def ready_for_storage(self) -> bool:
        return bool(self.uploads_bucket and self.results_bucket)

    @property
    def ready_for_processing(self) -> bool:
        return bool(self.processing_topic and self.processing_job)

    @property
    def ready_for_exports(self) -> bool:
        return bool(self.export_topic and self.export_job and self.results_bucket)

    @property
    def ready_for_ai(self) -> bool:
        return bool(self.aurora_chat_model and self.aurora_export_model)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
