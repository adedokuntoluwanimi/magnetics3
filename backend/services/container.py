from __future__ import annotations

from functools import lru_cache

from backend.config import get_settings
from backend.gcp.cloud_run_jobs import CloudRunJobsBackend
from backend.gcp.firestore_store import FirestoreStore
from backend.gcp.maps import MapsSecretProvider
from backend.gcp.storage_backend import StorageBackend
from backend.gcp.vertex_ai import VertexAuroraClient
from backend.services.ai_service import AIService
from backend.services.analysis_service import AnalysisService
from backend.services.export_service import ExportService
from backend.services.maps_service import MapsService
from backend.services.preview_service import PreviewService
from backend.services.processing_service import ProcessingService
from backend.services.project_service import ProjectService
from backend.services.task_service import TaskService


@lru_cache(maxsize=1)
def get_store() -> FirestoreStore:
    return FirestoreStore(get_settings())


@lru_cache(maxsize=1)
def get_storage_backend() -> StorageBackend:
    return StorageBackend(get_settings())


@lru_cache(maxsize=1)
def get_project_service() -> ProjectService:
    return ProjectService(get_store())


@lru_cache(maxsize=1)
def get_task_service() -> TaskService:
    return TaskService(get_store(), get_storage_backend())


@lru_cache(maxsize=1)
def get_analysis_service() -> AnalysisService:
    return AnalysisService(get_store())


@lru_cache(maxsize=1)
def get_ai_service() -> AIService:
    return AIService(get_store(), VertexAuroraClient(get_settings()))


@lru_cache(maxsize=1)
def get_preview_service() -> PreviewService:
    return PreviewService(get_store(), get_ai_service(), get_storage_backend())


@lru_cache(maxsize=1)
def get_processing_service() -> ProcessingService:
    return ProcessingService(get_store(), get_storage_backend())


@lru_cache(maxsize=1)
def get_export_service() -> ExportService:
    return ExportService(get_store(), get_storage_backend(), get_ai_service())


@lru_cache(maxsize=1)
def get_jobs_backend() -> CloudRunJobsBackend:
    return CloudRunJobsBackend(get_settings())


@lru_cache(maxsize=1)
def get_maps_service() -> MapsService:
    return MapsService(MapsSecretProvider(get_settings()))
