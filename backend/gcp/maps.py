from __future__ import annotations

from backend.config import Settings
from backend.gcp.clients import secret_manager_client


class MapsSecretProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = secret_manager_client()

    def get_maps_api_key(self) -> str:
        if self._settings.maps_api_key:
            return self._settings.maps_api_key
        name = (
            f"projects/{self._settings.infra_project_id}/secrets/"
            f"{self._settings.maps_api_key_secret}/versions/latest"
        )
        response = self._client.access_secret_version(request={"name": name})
        return response.payload.data.decode("utf-8").strip()
