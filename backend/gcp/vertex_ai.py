from __future__ import annotations

from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

from backend.config import Settings


class VertexGeminiClient:
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
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(creds)
        location = self._settings.aurora_chat_region or self._settings.ai_region or self._settings.region
        project_id = self._settings.aurora_chat_project_id or self._settings.infra_project_id
        model_name = (self._settings.aurora_chat_model or "gemini-2.5-flash").strip()
        url = (
            f"https://aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/"
            f"publishers/google/models/{model_name}:generateContent"
        )
        history = messages if messages is not None else [{"role": "user", "content": user_prompt or ""}]
        payload = {
            "system_instruction": {
                "parts": [{"text": system_prompt}],
            },
            "contents": [self._message_to_content(item) for item in history if item.get("content")],
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": 0.3,
            },
        }
        response = session.post(url, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return self._extract_text(data)

    def _message_to_content(self, item: dict[str, Any]) -> dict[str, Any]:
        role = "model" if item.get("role") == "assistant" else "user"
        return {
            "role": role,
            "parts": [{"text": str(item.get("content") or "")}],
        }

    def _extract_text(self, payload: dict[str, Any]) -> str:
        texts: list[str] = []
        for candidate in payload.get("candidates") or []:
            content = candidate.get("content") or {}
            for part in content.get("parts") or []:
                text = part.get("text")
                if text:
                    texts.append(str(text))
        return "\n".join(texts).strip()


class VertexClaudeClient:
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
        from anthropic import AnthropicVertex

        model_name = self._normalize_model_name(self._settings.aurora_export_model)
        client = AnthropicVertex(
            region=self._settings.aurora_export_region or self._settings.ai_region or self._settings.region,
            project_id=self._settings.aurora_export_project_id or self._settings.ai_project_id,
        )
        if messages is None:
            messages = [{"role": "user", "content": user_prompt or ""}]
        response = client.messages.create(
            model=model_name,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=messages,
        )
        return "".join(block.text for block in response.content if getattr(block, "text", None))

    def _normalize_model_name(self, model_name: str) -> str:
        normalized = (model_name or "").strip()
        aliases = {
            "claude-sonnet-4-6": "claude-sonnet-4@20250514",
            "claude-sonnet-4.6": "claude-sonnet-4@20250514",
            "claude-sonnet-4": "claude-sonnet-4@20250514",
        }
        return aliases.get(normalized, normalized)


VertexAIClient = VertexClaudeClient
VertexAuroraClient = VertexClaudeClient
