"""Safe, edge-only configuration loaded from the lab's local ``.env`` file."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from aula12_agents.infrastructure.providers import ProviderSettings
from aula12_agents.infrastructure.trace import TraceSettings

LAB_ROOT = Path(__file__).resolve().parents[2]


class LabSettings(BaseSettings):
    """Configuration boundary. Secret values never leave this object as text."""

    model_config = SettingsConfigDict(
        env_file=LAB_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        populate_by_name=True,
    )

    model_provider: Literal["mock", "ollama", "openrouter"] = Field(
        default="mock",
        validation_alias=AliasChoices(
            "MODEL_PROVIDER",
            "AULA12_MODEL_PROVIDER",
            # Legacy aliases kept for existing local configurations.
            "LLM_PROVIDER",
            "AULA12_LLM_PROVIDER",
        ),
    )
    ollama_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OLLAMA_MODEL",
            "AULA12_OLLAMA_MODEL",
            # Legacy aliases kept for existing local configurations.
            "LLM_MODEL",
            "AULA12_LLM_MODEL",
        ),
    )
    ollama_base_url: str | None = Field(
        default=None, validation_alias=AliasChoices("OLLAMA_BASE_URL", "AULA12_OLLAMA_BASE_URL")
    )
    openrouter_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "AULA12_OPENROUTER_API_KEY"),
    )
    openrouter_primary_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "OPENROUTER_PRIMARY_MODEL", "AULA12_OPENROUTER_PRIMARY_MODEL"
        ),
    )
    openrouter_backup_model: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_BACKUP_MODEL", "AULA12_OPENROUTER_BACKUP_MODEL"),
    )
    openrouter_reasoning_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "OPENROUTER_REASONING_ENABLED", "AULA12_OPENROUTER_REASONING_ENABLED"
        ),
    )
    openrouter_app_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_APP_URL", "AULA12_OPENROUTER_APP_URL"),
    )
    openrouter_app_title: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENROUTER_APP_TITLE", "AULA12_OPENROUTER_APP_TITLE"),
    )
    observability_backend: Literal["jsonl", "langfuse", "both"] = Field(
        default="jsonl",
        validation_alias=AliasChoices("OBSERVABILITY_BACKEND", "AULA12_OBSERVABILITY_BACKEND"),
    )
    trace_dir: Path = Field(
        default=Path("runs/traces"), validation_alias=AliasChoices("TRACE_DIR", "AULA12_TRACE_DIR")
    )
    trace_capture_content: bool = Field(
        default=False,
        validation_alias=AliasChoices("TRACE_CAPTURE_CONTENT", "AULA12_TRACE_CAPTURE_CONTENT"),
    )
    langfuse_public_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGFUSE_PUBLIC_KEY", "AULA12_LANGFUSE_PUBLIC_KEY"),
    )
    langfuse_secret_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LANGFUSE_SECRET_KEY", "AULA12_LANGFUSE_SECRET_KEY"),
    )
    langfuse_base_url: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_BASE_URL", "AULA12_LANGFUSE_BASE_URL"),
    )
    langfuse_environment: str = Field(
        default="lab",
        validation_alias=AliasChoices(
            "LANGFUSE_TRACING_ENVIRONMENT", "AULA12_LANGFUSE_ENVIRONMENT"
        ),
    )
    langfuse_release: str | None = Field(
        default=None, validation_alias=AliasChoices("LANGFUSE_RELEASE", "AULA12_LANGFUSE_RELEASE")
    )
    run_db_path: Path = Field(
        default=Path("runs/aula12.sqlite3"),
        validation_alias=AliasChoices("RUN_DB_PATH", "AULA12_RUN_DB_PATH"),
    )
    coordination_run_timeout_seconds: int = Field(
        default=300,
        ge=60,
        validation_alias=AliasChoices(
            "COORDINATION_RUN_TIMEOUT_SECONDS", "AULA12_COORDINATION_RUN_TIMEOUT_SECONDS"
        ),
    )
    ollama_coordination_timeout_seconds: int = Field(
        default=180,
        ge=60,
        validation_alias=AliasChoices(
            "OLLAMA_COORDINATION_TIMEOUT_SECONDS",
            "AULA12_OLLAMA_COORDINATION_TIMEOUT_SECONDS",
        ),
    )

    def provider_settings(self) -> ProviderSettings:
        """Build the pre-existing provider adapter configuration without printing secrets."""

        model = self.ollama_model if self.model_provider == "ollama" else None
        if self.model_provider == "openrouter":
            model = self.openrouter_primary_model
        return ProviderSettings(
            kind=self.model_provider,
            model=model,
            base_url=self.ollama_base_url if self.model_provider == "ollama" else None,
            api_key=self.openrouter_api_key if self.model_provider == "openrouter" else None,
            app_url=self.openrouter_app_url,
            app_title=self.openrouter_app_title,
            backup_model=self.openrouter_backup_model
            if self.model_provider == "openrouter"
            else None,
            reasoning_enabled=self.openrouter_reasoning_enabled
            if self.model_provider == "openrouter"
            else False,
        )

    def trace_settings(self) -> TraceSettings:
        return TraceSettings(
            backend=self.observability_backend,
            trace_dir=self.trace_dir,
            capture_content=self.trace_capture_content,
            environment=self.langfuse_environment,
            langfuse_public_key=self.langfuse_public_key,
            langfuse_secret_key=self.langfuse_secret_key,
            langfuse_base_url=self.langfuse_base_url,
            langfuse_release=self.langfuse_release,
        )

    def doctor_report(self) -> dict[str, object]:
        """A safe status report: it reports presence, never credential values."""

        provider = self.provider_settings()
        trace = self.trace_settings()
        return {
            "model_provider": provider.kind,
            "model_configured": provider.model is not None,
            "trace_backend": trace.backend,
            "trace_directory": str(trace.trace_dir),
            "langfuse_credentials_configured": trace.has_langfuse_credentials,
            "openrouter_primary_model_configured": self.openrouter_primary_model is not None,
            "openrouter_backup_model_configured": self.openrouter_backup_model is not None,
            "run_database": str(self.run_db_path),
        }


def load_settings() -> LabSettings:
    """Construct settings at the application edge; importing modules has no env side effect."""

    return LabSettings()
