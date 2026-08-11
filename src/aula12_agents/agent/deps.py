"""Typed dependencies passed to PydanticAI through ``RunContext``."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from .contracts import EvidencePack


class ReadonlyEvidenceReader(Protocol):
    """Port implemented by fixtures or production read-only adapters."""

    async def read_evidence(self, incident_id: str, *, limit: int) -> EvidencePack: ...


class ToolObservation(BaseModel):
    """Sanitized fact emitted by a tool; never contains prompt text or secrets."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=120)
    tool_name: str = Field(min_length=1, max_length=100)
    incident_id: str = Field(min_length=1, max_length=120)
    outcome: str = Field(min_length=1, max_length=80)
    evidence_count: int = Field(ge=0, le=12)


ObservationSink = Callable[[ToolObservation], Awaitable[None] | None]


class AgentPolicy(BaseModel):
    """Visible resource and tool policy, injected rather than hidden in prompts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_evidence_items: int = Field(default=6, ge=1, le=12)
    request_limit: int = Field(default=3, ge=1, le=10)
    tool_calls_limit: int = Field(default=4, ge=1, le=12)
    # Includes the structured schema, tool result and accumulated retry context.
    # With four bounded requests, 10k permits the full fixture scenario without
    # making token use unbounded.
    total_tokens_limit: int | None = Field(default=10_000, ge=100)
    max_output_tokens: int = Field(default=256, ge=64, le=4_096)
    allow_read_evidence: bool = True


@dataclass(frozen=True, slots=True)
class AgentDeps:
    """Runtime-only dependencies. Concrete infrastructure stays outside agent code."""

    run_id: str
    evidence_reader: ReadonlyEvidenceReader
    policy: AgentPolicy
    observation_sink: ObservationSink | None = None

    async def observe(self, observation: ToolObservation) -> None:
        if self.observation_sink is None:
            return
        result = self.observation_sink(observation)
        if inspect.isawaitable(result):
            await result


@dataclass(frozen=True, slots=True)
class CriticDeps:
    """Runtime policy for the critic, which deliberately has no tools."""

    run_id: str
    policy: AgentPolicy
