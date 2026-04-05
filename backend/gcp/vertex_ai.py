from __future__ import annotations

from typing import Any

from backend.config import Settings
from backend.logging_utils import log_event


class ExportProviderError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        category: str,
        provider: str,
        model: str,
        retryable: bool = False,
        request_id: str | None = None,
        status_code: int | None = None,
        provider_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.provider = provider
        self.model = model
        self.retryable = retryable
        self.request_id = request_id
        self.status_code = status_code
        self.provider_message = provider_message or message


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
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

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


class AnthropicClaudeClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured_model_name(self) -> str:
        return self._normalize_model_name(self._settings.aurora_export_model)

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str | None = None,
        messages: list | None = None,
        max_tokens: int = 1500,
    ) -> str:
        from anthropic import Anthropic

        if not self._settings.anthropic_api_key:
            raise ExportProviderError(
                "ANTHROPIC_API_KEY is not configured for direct Claude export usage.",
                category="configuration",
                provider="anthropic",
                model=self.configured_model_name,
                retryable=False,
            )

        client = Anthropic(api_key=self._settings.anthropic_api_key)
        model_name = self.configured_model_name
        if messages is None:
            messages = [{"role": "user", "content": user_prompt or ""}]
        try:
            response = client.messages.create(
                model=model_name,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
        except Exception as exc:
            raise self._classify_error(exc, model_name) from exc
        return "".join(block.text for block in response.content if getattr(block, "text", None))

    def _normalize_model_name(self, model_name: str) -> str:
        return (model_name or "").strip()

    def preflight_model_availability(self) -> bool:
        model_name = self.configured_model_name
        if not self._settings.anthropic_api_key:
            log_event(
                "ERROR",
                "Anthropic export preflight failed",
                action="export.provider.preflight",
                provider="anthropic",
                model=model_name,
                status="error",
                provider_error_category="configuration",
                provider_error_message="ANTHROPIC_API_KEY is not configured for direct Claude export usage.",
            )
            return False
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self._settings.anthropic_api_key)
            model_ids = self._list_model_ids(client)
        except Exception as exc:
            classified = self._classify_error(exc, model_name)
            log_event(
                "ERROR",
                "Anthropic export preflight failed",
                action="export.provider.preflight",
                provider="anthropic",
                model=model_name,
                status="error",
                provider_error_category=classified.category,
                provider_error_message=classified.provider_message,
                status_code=classified.status_code,
                request_id=classified.request_id,
            )
            return False
        if model_ids and model_name not in model_ids:
            log_event(
                "ERROR",
                "Anthropic export preflight failed",
                action="export.provider.preflight",
                provider="anthropic",
                model=model_name,
                status="error",
                provider_error_category="model_unavailable",
                provider_error_message="Configured export model is not available from the Anthropic models API.",
                available_models_preview=sorted(model_ids)[:10],
            )
            return False
        log_event(
            "INFO",
            "Anthropic export preflight passed",
            action="export.provider.preflight",
            provider="anthropic",
            model=model_name,
            status="ok",
        )
        return True

    def _list_model_ids(self, client: Any) -> set[str]:
        models = getattr(client, "models", None)
        if models is None or not hasattr(models, "list"):
            return set()
        response = models.list(limit=100)
        data = getattr(response, "data", response)
        model_ids: set[str] = set()
        for item in data or []:
            identifier = getattr(item, "id", None)
            if identifier:
                model_ids.add(str(identifier))
        return model_ids

    def _classify_error(self, exc: Exception, model_name: str) -> ExportProviderError:
        error_name = exc.__class__.__name__
        category = "provider_failure"
        retryable = False
        if error_name in {"AuthenticationError", "PermissionDeniedError"}:
            category = "permission_failure"
        elif error_name in {"RateLimitError"}:
            category = "rate_limit"
            retryable = True
        elif error_name in {"NotFoundError"}:
            category = "model_unavailable"
        elif error_name in {"BadRequestError"} and "model" in str(exc).lower():
            category = "model_unavailable"
        elif error_name in {"APIConnectionError", "APIError", "InternalServerError", "ServiceUnavailableError"}:
            category = "provider_failure"
            retryable = True
        return ExportProviderError(
            f"Anthropic export generation failed ({category}): {exc}",
            category=category,
            provider="anthropic",
            model=model_name,
            retryable=retryable,
            request_id=getattr(exc, "request_id", None),
            status_code=getattr(exc, "status_code", None),
            provider_message=str(exc),
        )


VertexAIClient = VertexClaudeClient
VertexAuroraClient = VertexClaudeClient
