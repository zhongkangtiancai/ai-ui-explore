"""Provider contract tests for Sprint 3 LLM infrastructure."""

import json
from asyncio import run

import httpx
import pytest

from ai_ui_explorer.llm.models import LLMMessage, LLMRequest
from ai_ui_explorer.llm.provider import (
    LLMProviderError,
    MockProvider,
    OpenAICompatibleProvider,
)


def test_mock_provider_returns_deterministic_response_and_usage() -> None:
    async def exercise() -> None:
        provider = MockProvider()
        request = LLMRequest(
            application_id="example-app",
            environment="test",
            identity_alias="anonymous",
            model="mock-model",
            messages=[LLMMessage(role="user", content="Summarize the package.")],
        )

        first = await provider.complete(request)
        second = await provider.complete(request)

        assert first.content == second.content
        assert first.model == "mock-model"
        assert first.provider == "mock"
        assert first.usage.estimated_prompt_tokens > 0
        assert first.usage.provider_prompt_tokens is None

    run(exercise())


def test_openai_compatible_provider_uses_non_streaming_chat_completions() -> None:
    async def exercise() -> None:
        captured_headers: dict[str, str] = {}
        captured_payload: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_headers, captured_payload
            captured_headers = dict(request.headers)
            captured_payload = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl-test",
                    "model": "compatible-model",
                    "choices": [{"message": {"content": "Synthetic answer"}}],
                    "usage": {
                        "prompt_tokens": 7,
                        "completion_tokens": 3,
                        "total_tokens": 10,
                    },
                },
            )

        provider = OpenAICompatibleProvider(
            base_url="https://llm.example.test/v1",
            api_key="synthetic-api-key",
            transport=httpx.MockTransport(handler),
        )
        response = await provider.complete(
            LLMRequest(
                application_id="example-app",
                environment="test",
                identity_alias="qa-user",
                model="compatible-model",
                messages=[LLMMessage(role="user", content="Use synthetic data only.")],
            )
        )

        assert response.content == "Synthetic answer"
        assert response.provider == "openai-compatible"
        assert response.usage.provider_prompt_tokens == 7
        assert captured_payload["stream"] is False
        assert captured_payload["model"] == "compatible-model"
        assert captured_headers["authorization"] == "Bearer synthetic-api-key"
        assert "synthetic-api-key" not in response.model_dump_json()

    run(exercise())


def test_openai_compatible_provider_redacts_error_surface() -> None:
    async def exercise() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="upstream saw synthetic-api-key")

        provider = OpenAICompatibleProvider(
            base_url="https://llm.example.test/v1",
            api_key="synthetic-api-key",
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(LLMProviderError, match="LLM provider request failed"):
            await provider.complete(
                LLMRequest(
                    application_id="example-app",
                    environment="test",
                    identity_alias=None,
                    model="compatible-model",
                    messages=[LLMMessage(role="user", content="Hello")],
                )
            )

    run(exercise())


def test_openai_compatible_provider_rejects_unsafe_base_url() -> None:
    with pytest.raises(ValueError, match="must not contain userinfo"):
        OpenAICompatibleProvider(
            base_url="https://token@example.test/v1",
            api_key="synthetic-api-key",
        )

    with pytest.raises(ValueError, match="must not contain query or fragment"):
        OpenAICompatibleProvider(
            base_url="https://example.test/v1?key=value",
            api_key="synthetic-api-key",
        )
