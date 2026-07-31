"""Validated LLM request, response and audit-safe records."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from ai_ui_explorer.knowledge.immutability import DeepFrozenModel
from ai_ui_explorer.llm.token_budget import estimate_tokens


class LLMMessage(DeepFrozenModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1)


class LLMRequest(DeepFrozenModel):
    application_id: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    identity_alias: str | None
    model: str = Field(min_length=1)
    messages: list[LLMMessage] = Field(min_length=1)
    max_output_tokens: int = Field(default=1024, ge=1, le=32_000)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)

    @property
    def estimated_prompt_tokens(self) -> int:
        return estimate_tokens(
            [message.model_dump(mode="json") for message in self.messages]
        )


class LLMUsage(DeepFrozenModel):
    estimated_prompt_tokens: int = Field(ge=0)
    estimated_completion_tokens: int = Field(ge=0)
    provider_prompt_tokens: int | None = Field(default=None, ge=0)
    provider_completion_tokens: int | None = Field(default=None, ge=0)
    provider_total_tokens: int | None = Field(default=None, ge=0)


class LLMResponse(DeepFrozenModel):
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    content: str
    usage: LLMUsage
    audit_id: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
