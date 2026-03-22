from __future__ import annotations


class MapsService:
    def __init__(self, provider) -> None:
        self._provider = provider

    def get_api_key(self) -> dict:
        return {"apiKey": self._provider.get_maps_api_key()}
