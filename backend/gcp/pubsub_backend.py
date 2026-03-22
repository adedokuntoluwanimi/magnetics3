from __future__ import annotations

import json

from backend.config import Settings
from backend.gcp.clients import pubsub_publisher_client


class PubSubBackend:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._publisher = pubsub_publisher_client()

    def publish_processing(self, payload: dict) -> str:
        topic = self._publisher.topic_path(self._settings.infra_project_id, self._settings.processing_topic)
        future = self._publisher.publish(topic, json.dumps(payload).encode("utf-8"))
        return future.result()

    def publish_export(self, payload: dict) -> str:
        topic = self._publisher.topic_path(self._settings.infra_project_id, self._settings.export_topic)
        future = self._publisher.publish(topic, json.dumps(payload).encode("utf-8"))
        return future.result()
