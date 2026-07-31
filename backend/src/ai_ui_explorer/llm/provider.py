"""LLM Provider abstraction and offline-testable OpenAI-compatible adapter."""

import hashlib
import json
from collections.abc import Mapping
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from ai_ui_explorer.llm.models import LLMRequest, LLMResponse, LLMUsage
from ai_ui_explorer.llm.token_budget import estimate_tokens


class LLMProviderError(RuntimeError):
    """Safe provider failure surface that must not include secrets or raw bodies."""


class LLMProvider(Protocol):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Return a non-streaming completion for a validated request."""


class MockProvider:
    provider_name = "mock"

    async def complete(self, request: LLMRequest) -> LLMResponse:
        digest = _stable_digest(request.model_dump(mode="json"))
        content = f"mock-response:{digest[:16]}"
        return LLMResponse(
            provider=self.provider_name,
            model=request.model,
            content=content,
            usage=LLMUsage(
                estimated_prompt_tokens=request.estimated_prompt_tokens,
                estimated_completion_tokens=estimate_tokens(content),
            ),
            audit_id=f"llm-audit-{digest[:24]}",
        )


class OpenAICompatibleProvider:
    provider_name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = _validate_base_url(base_url)
        if not api_key:
            raise ValueError("api_key is required")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def complete(self, request: LLMRequest) -> LLMResponse:
        payload = {
            "model": request.model,
            "messages": [
                message.model_dump(mode="json") for message in request.messages
            ],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            transport=self._transport,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            try:
                response = await client.post(
                    urljoin(self._base_url.rstrip("/") + "/", "chat/completions"),
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
            except Exception:
                raise LLMProviderError("LLM provider request failed") from None

        content = _extract_content(body)
        usage = _extract_usage(body, request, content)
        audit_digest = _stable_digest(
            {"request": payload, "body": _audit_body(body)}
        )
        return LLMResponse(
            provider=self.provider_name,
            model=_string_or_default(body.get("model"), request.model),
            content=content,
            usage=usage,
            audit_id=f"llm-audit-{audit_digest[:24]}",
        )


def _validate_base_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValueError("base_url must use https")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain userinfo")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain query or fragment")
    if not parsed.netloc:
        raise ValueError("base_url must include a host")
    return value


def _extract_content(body: Mapping[str, object]) -> str:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderError("LLM provider response is invalid")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise LLMProviderError("LLM provider response is invalid")
    message = first.get("message")
    if not isinstance(message, Mapping):
        raise LLMProviderError("LLM provider response is invalid")
    content = message.get("content")
    if not isinstance(content, str):
        raise LLMProviderError("LLM provider response is invalid")
    return content


def _extract_usage(
    body: Mapping[str, object],
    request: LLMRequest,
    content: str,
) -> LLMUsage:
    usage = body.get("usage")
    if not isinstance(usage, Mapping):
        return LLMUsage(
            estimated_prompt_tokens=request.estimated_prompt_tokens,
            estimated_completion_tokens=estimate_tokens(content),
        )
    return LLMUsage(
        estimated_prompt_tokens=request.estimated_prompt_tokens,
        estimated_completion_tokens=estimate_tokens(content),
        provider_prompt_tokens=_optional_int(usage.get("prompt_tokens")),
        provider_completion_tokens=_optional_int(usage.get("completion_tokens")),
        provider_total_tokens=_optional_int(usage.get("total_tokens")),
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and value >= 0 else None


def _string_or_default(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _stable_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _audit_body(body: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": body.get("id"),
        "model": body.get("model"),
        "has_usage": isinstance(body.get("usage"), Mapping),
    }
