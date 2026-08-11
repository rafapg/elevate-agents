"""Local-only tracing adapter for sanitized PydanticAI tool observations.

PydanticAI's native OpenTelemetry instrumentation already exports model and
tool spans to Langfuse.  This adapter intentionally writes only the compact
application observation to JSONL, so the local fallback remains useful without
duplicating those remote spans.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from aula12_agents.agent.deps import ToolObservation

from .models import TraceEvent


class ToolObservationSink(Protocol):
    """Minimal local event writer required by the adapter."""

    def emit(self, event: TraceEvent) -> None: ...


@dataclass(frozen=True, slots=True)
class ToolTraceObserver:
    """Turn a sanitized agent tool observation into a local JSONL event."""

    sink: ToolObservationSink
    workflow_name: str
    workflow_version: str
    environment: str
    now: Callable[[], datetime]

    async def __call__(self, observation: ToolObservation) -> None:
        """Best effort: tracing failures must not turn a read-only tool into a failure."""

        try:
            occurred_at = self.now()
            self.sink.emit(
                TraceEvent(
                    event_type="agent.tool.observation",
                    occurred_at=occurred_at,
                    trace_id=_identifier(observation.run_id, 32),
                    span_id=_identifier(
                        f"{observation.run_id}:{observation.tool_name}:"
                        f"{observation.incident_id}:{occurred_at.isoformat()}",
                        16,
                    ),
                    run_id=_as_uuid(observation.run_id),
                    session_id=observation.run_id,
                    workflow_name=self.workflow_name,
                    workflow_version=self.workflow_version,
                    environment=self.environment,
                    attributes={
                        "tool_name": observation.tool_name,
                        "incident_id": observation.incident_id,
                        "outcome": observation.outcome,
                        "evidence_count": observation.evidence_count,
                    },
                )
            )
        except Exception:
            return


def _identifier(value: str, length: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
