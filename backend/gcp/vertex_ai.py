from __future__ import annotations

from backend.config import Settings


class VertexAuroraClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        from anthropic import AnthropicVertex

        client = AnthropicVertex(
            region=self._settings.region,
            project_id=self._settings.ai_project_id,
        )
        response = client.messages.create(
            model=self._settings.aurora_model,
            max_tokens=1200,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "text", None))
