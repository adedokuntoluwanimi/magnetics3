from __future__ import annotations

from functools import lru_cache

from backend.config import Settings


@lru_cache(maxsize=1)
def firestore_client(settings: Settings):
    from google.cloud import firestore

    return firestore.Client(
        project=settings.infra_project_id,
        database=settings.firestore_database,
    )


@lru_cache(maxsize=1)
def storage_client(settings: Settings):
    from google.cloud import storage

    return storage.Client(project=settings.infra_project_id)


@lru_cache(maxsize=1)
def pubsub_publisher_client():
    from google.cloud import pubsub_v1

    return pubsub_v1.PublisherClient()


@lru_cache(maxsize=1)
def run_jobs_client():
    from google.cloud import run_v2

    return run_v2.JobsClient()


@lru_cache(maxsize=1)
def secret_manager_client():
    from google.cloud import secretmanager

    return secretmanager.SecretManagerServiceClient()


@lru_cache(maxsize=1)
def cloud_logging_client(settings: Settings):
    from google.cloud import logging as cloud_logging

    client = cloud_logging.Client(project=settings.infra_project_id)
    client.setup_logging()
    return client
