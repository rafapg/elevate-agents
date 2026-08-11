from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel

from aula12_agents.infrastructure.providers import (
    ProviderSettings,
    build_model,
    is_openrouter_credit_exhausted,
)


def test_mock_is_the_secret_free_default() -> None:
    assert isinstance(build_model(ProviderSettings()), FunctionModel)


def test_ollama_uses_local_openai_compatible_provider() -> None:
    model = build_model(ProviderSettings(kind="ollama", model="qwen3:8b"))
    assert isinstance(model, OpenAIChatModel)


def test_openrouter_requires_key_but_does_not_expose_it() -> None:
    with pytest.raises(ValidationError, match="api_key is required"):
        ProviderSettings(kind="openrouter", model="openai/gpt-4.1-mini")

    settings = ProviderSettings(
        kind="openrouter",
        model="openai/gpt-4.1-mini",
        api_key="not-a-real-secret",
    )
    assert "not-a-real-secret" not in repr(settings)
    assert isinstance(build_model(settings), OpenRouterModel)


def test_openrouter_uses_backup_only_for_insufficient_credits() -> None:
    settings = ProviderSettings(
        kind="openrouter",
        model="qwen/qwen3.7-plus",
        backup_model="poolside/laguna-s-2.1:free",
        api_key="not-a-real-secret",
    )
    assert isinstance(build_model(settings), FallbackModel)

    credit_error = ModelHTTPError(402, "qwen/qwen3.7-plus", "insufficient credits")
    assert is_openrouter_credit_exhausted(credit_error) is True
    assert is_openrouter_credit_exhausted(ModelHTTPError(429, "model", "rate limited")) is False
    assert is_openrouter_credit_exhausted(RuntimeError("unrelated")) is False


def test_openrouter_defaults_to_non_thinking_mode_for_required_tool_calls() -> None:
    settings = ProviderSettings(
        kind="openrouter",
        model="qwen/qwen3.7-plus",
        api_key="not-a-real-secret",
    )

    model = build_model(settings)

    assert isinstance(model, OpenRouterModel)
    assert model.settings["openrouter_reasoning"] == {"enabled": False}


@pytest.mark.asyncio
async def test_credit_exhaustion_routes_to_backup_model() -> None:
    """Exercise PydanticAI's fallback chain without making an OpenRouter request."""

    calls: list[str] = []

    def exhausted_primary(*_: object) -> ModelResponse:
        calls.append("primary")
        raise ModelHTTPError(402, "paid-model", "insufficient credits")

    def free_backup(*_: object) -> ModelResponse:
        calls.append("backup")
        return ModelResponse(parts=[TextPart("served by backup")])

    model = FallbackModel(
        FunctionModel(exhausted_primary, model_name="paid-model"),
        FunctionModel(free_backup, model_name="free-model"),
        fallback_on=is_openrouter_credit_exhausted,
    )

    result = await Agent(model, output_type=str).run("Reply with the selected provider.")

    assert result.output == "served by backup"
    assert calls == ["primary", "backup"]


@pytest.mark.asyncio
async def test_non_credit_error_does_not_route_to_backup_model() -> None:
    """Rate limits and transient provider failures must remain visible to the caller."""

    backup_called = False

    def rate_limited_primary(*_: object) -> ModelResponse:
        raise ModelHTTPError(429, "paid-model", "rate limited")

    def free_backup(*_: object) -> ModelResponse:
        nonlocal backup_called
        backup_called = True
        return ModelResponse(parts=[TextPart("should not run")])

    model = FallbackModel(
        FunctionModel(rate_limited_primary, model_name="paid-model"),
        FunctionModel(free_backup, model_name="free-model"),
        fallback_on=is_openrouter_credit_exhausted,
    )

    with pytest.raises(ModelHTTPError, match="rate limited"):
        await Agent(model, output_type=str).run("Reply with the selected provider.")

    assert backup_called is False
