"""Explicit model construction for mock, local Ollama, and OpenRouter."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel, OpenRouterModelSettings
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider

from .mock import build_mock_model

ProviderKind = Literal["mock", "ollama", "openrouter"]


class ProviderSettings(BaseModel):
    """Provider configuration supplied by environment/configuration at the edge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ProviderKind = "mock"
    model: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, min_length=1, max_length=500)
    api_key: SecretStr | None = None
    app_url: str | None = Field(default=None, max_length=500)
    app_title: str | None = Field(default=None, max_length=120)
    backup_model: str | None = Field(default=None, min_length=1, max_length=200)
    reasoning_enabled: bool = False

    @model_validator(mode="after")
    def require_provider_model(self) -> ProviderSettings:
        if self.kind != "mock" and self.model is None:
            raise ValueError("model is required for Ollama and OpenRouter")
        if self.kind == "openrouter" and self.api_key is None:
            raise ValueError("api_key is required for OpenRouter")
        return self


def build_model(settings: ProviderSettings) -> Model:
    """Build a model without reading environment variables or leaking secrets."""

    if settings.kind == "mock":
        return build_mock_model()

    if settings.kind == "ollama":
        ollama_provider = OpenAIProvider(
            base_url=settings.base_url or "http://localhost:11434/v1",
            api_key=settings.api_key.get_secret_value() if settings.api_key else "ollama",
        )
        return OpenAIChatModel(settings.model or "", provider=ollama_provider)

    openrouter_provider = OpenRouterProvider(
        api_key=settings.api_key.get_secret_value() if settings.api_key else None,
        app_url=settings.app_url,
        app_title=settings.app_title,
    )
    # Qwen's Alibaba route rejects required tool calls while thinking is enabled.
    # The lab's agent requires read-only tools plus typed output, so reasoning is
    # an explicit provider setting and defaults to the compatible mode.
    model_settings: OpenRouterModelSettings = {
        "openrouter_reasoning": {"enabled": settings.reasoning_enabled}
    }
    primary = OpenRouterModel(
        settings.model or "", provider=openrouter_provider, settings=model_settings
    )
    if settings.backup_model is None:
        return primary
    backup = OpenRouterModel(
        settings.backup_model, provider=openrouter_provider, settings=model_settings
    )
    return FallbackModel(primary, backup, fallback_on=is_openrouter_credit_exhausted)


def is_openrouter_credit_exhausted(error: Exception) -> bool:
    """Fail over only when OpenRouter rejects a request for insufficient credits."""

    return isinstance(error, ModelHTTPError) and error.status_code == 402
