"""Pydantic contracts for trace events and explicit adapter settings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class TraceEvent(BaseModel):
    """An export-safe event shared by local and remote trace adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    event_id: UUID = Field(default_factory=uuid4)
    event_type: str = Field(min_length=1, max_length=120)
    occurred_at: datetime
    trace_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    span_id: str = Field(pattern=r"^[a-f0-9]{16}$")
    parent_span_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16}$")
    run_id: UUID | None = None
    session_id: str | None = Field(default=None, max_length=200)
    workflow_name: str = Field(min_length=1, max_length=120)
    workflow_version: str = Field(min_length=1, max_length=120)
    environment: str = Field(default="lab", pattern=r"^[a-z0-9_-]{1,40}$")
    status: Literal["ok", "error", "partial", "cancelled"] = "ok"
    attributes: dict[str, Any] = Field(default_factory=dict)


class TraceSettings(BaseModel):
    """Explicit settings; callers, not this adapter, decide how to read env vars."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    backend: Literal["jsonl", "langfuse", "both"] = "jsonl"
    trace_dir: Path
    capture_content: bool = False
    environment: str = Field(default="lab", pattern=r"^[a-z0-9_-]{1,40}$")
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_base_url: str = Field(default="https://cloud.langfuse.com", max_length=500)
    langfuse_release: str | None = Field(default=None, max_length=120)

    @property
    def has_langfuse_credentials(self) -> bool:
        return self.langfuse_public_key is not None and self.langfuse_secret_key is not None
