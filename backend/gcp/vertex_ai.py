from __future__ import annotations

from backend.config import Settings


class VertexAIClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str | None = None,
        messages: list | None = None,
        max_tokens: int = 1500,
    ) -> str:
        """
        Call Claude via AnthropicVertex.

        Pass either ``user_prompt`` (single-turn) or ``messages`` (multi-turn
        with conversation history).  If both are given, ``messages`` takes
        precedence.
        """
        from anthropic import AnthropicVertex

        client = AnthropicVertex(
            region=self._settings.region,
            project_id=self._settings.ai_project_id,
        )
        if messages is None:
            messages = [{"role": "user", "content": user_prompt or ""}]
        response = client.messages.create(
            model=self._settings.aurora_model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return "".join(block.text for block in response.content if getattr(block, "text", None))


# Keep old name as alias so any external references don't break
VertexAuroraClient = VertexAIClient
