"""Translation of application workflow transitions into export-safe trace events."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from aula12_agents.domain.models import RunCheckpoint

from .models import TraceEvent
from .sinks import TraceSink

WorkflowStage = Literal["hypothesis", "critic", "gate"]
StageOutcome = Literal["started", "completed", "failed"]
GateDecision = Literal["approve", "retry", "escalate"]
StaleResultKind = Literal["revision_conflict", "superseded_stage"]


@dataclass(frozen=True, slots=True)
class WorkflowTraceObserver:
    """Best-effort adapter; tracing must never change workflow control flow."""

    sink: TraceSink
    workflow_name: str
    environment: str

    def record(self, *, checkpoint: RunCheckpoint, event_type: str, occurred_at: datetime) -> None:
        """Record an existing durable workflow transition.

        This is kept for generic checkpoint events. New multi-agent stages use
        the explicit methods below so their event shape remains stable and
        contains no model output or evidence content.
        """

        try:
            self._emit(
                checkpoint=checkpoint,
                event_type=f"workflow.{event_type}",
                occurred_at=occurred_at,
                status=_status_for(checkpoint),
                attributes=self._checkpoint_attributes(checkpoint),
            )
        except Exception:
            # Observability is deliberately non-authoritative, including local I/O failures.
            return

    def record_stage_started(
        self, *, checkpoint: RunCheckpoint, stage: WorkflowStage, occurred_at: datetime
    ) -> None:
        self._record_stage(
            checkpoint=checkpoint,
            stage=stage,
            outcome="started",
            occurred_at=occurred_at,
        )

    def record_stage_completed(
        self, *, checkpoint: RunCheckpoint, stage: WorkflowStage, occurred_at: datetime
    ) -> None:
        self._record_stage(
            checkpoint=checkpoint,
            stage=stage,
            outcome="completed",
            occurred_at=occurred_at,
        )

    def record_stage_failed(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: WorkflowStage,
        failure_kind: str,
        occurred_at: datetime,
    ) -> None:
        """Record a failure category, never an exception message or model content."""

        self._record_stage(
            checkpoint=checkpoint,
            stage=stage,
            outcome="failed",
            occurred_at=occurred_at,
            failure_kind=failure_kind,
        )

    def record_gate_decision(
        self,
        *,
        checkpoint: RunCheckpoint,
        decision: GateDecision,
        occurred_at: datetime,
    ) -> None:
        """Record the deterministic gate result, separate from an LLM span."""

        try:
            if decision == "approve":
                status: Literal["ok", "error", "partial", "cancelled"] = "ok"
            elif decision == "retry":
                status = "partial"
            else:
                status = "error"
            self._emit(
                checkpoint=checkpoint,
                event_type="workflow.gate.decided",
                occurred_at=occurred_at,
                status=status,
                attributes={
                    **self._checkpoint_attributes(checkpoint),
                    "stage": "gate",
                    "decision": decision,
                },
            )
        except Exception:
            return

    def record_retry_scheduled(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: WorkflowStage,
        occurred_at: datetime,
    ) -> None:
        """Record a durable retry boundary without exporting the failure payload."""

        self._record_resilience_event(
            checkpoint=checkpoint,
            event_type="workflow.retry.scheduled",
            stage=stage,
            occurred_at=occurred_at,
            status="partial",
        )

    def record_resume_started(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: WorkflowStage,
        resumed_from_revision: int,
        occurred_at: datetime,
    ) -> None:
        """Record an explicit restart from a persisted checkpoint boundary."""

        self._record_resilience_event(
            checkpoint=checkpoint,
            event_type="workflow.resume.started",
            stage=stage,
            occurred_at=occurred_at,
            status="partial",
            attributes={"resumed_from_revision": resumed_from_revision},
        )

    def record_stale_result_rejected(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: WorkflowStage,
        expected_revision: int,
        observed_revision: int,
        kind: StaleResultKind,
        occurred_at: datetime,
    ) -> None:
        """Record that optimistic concurrency rejected a late stage result.

        Revision numbers and the fixed rejection category are safe operational
        metadata. Exception messages, prompts, evidence and model outputs are
        deliberately excluded.
        """

        self._record_resilience_event(
            checkpoint=checkpoint,
            event_type="workflow.execution.stale_result_rejected",
            stage=stage,
            occurred_at=occurred_at,
            status="ok",
            attributes={
                "expected_revision": expected_revision,
                "observed_revision": observed_revision,
                "rejection_kind": kind,
            },
        )

    def _record_stage(
        self,
        *,
        checkpoint: RunCheckpoint,
        stage: WorkflowStage,
        outcome: StageOutcome,
        occurred_at: datetime,
        failure_kind: str | None = None,
    ) -> None:
        try:
            attributes: dict[str, object] = {
                **self._checkpoint_attributes(checkpoint),
                "stage": stage,
                "outcome": outcome,
            }
            if failure_kind is not None:
                attributes["failure_kind"] = _safe_category(failure_kind)
            self._emit(
                checkpoint=checkpoint,
                event_type=f"workflow.stage.{outcome}",
                occurred_at=occurred_at,
                status="error" if outcome == "failed" else _status_for(checkpoint),
                attributes=attributes,
            )
        except Exception:
            return

    def _record_resilience_event(
        self,
        *,
        checkpoint: RunCheckpoint,
        event_type: str,
        stage: WorkflowStage,
        occurred_at: datetime,
        status: Literal["ok", "error", "partial", "cancelled"],
        attributes: dict[str, object] | None = None,
    ) -> None:
        try:
            self._emit(
                checkpoint=checkpoint,
                event_type=event_type,
                occurred_at=occurred_at,
                status=status,
                attributes={
                    **self._checkpoint_attributes(checkpoint),
                    "stage": stage,
                    **(attributes or {}),
                },
            )
        except Exception:
            return

    def _emit(
        self,
        *,
        checkpoint: RunCheckpoint,
        event_type: str,
        occurred_at: datetime,
        status: Literal["ok", "error", "partial", "cancelled"],
        attributes: dict[str, object],
    ) -> None:
        self.sink.emit(
            TraceEvent(
                event_type=event_type,
                occurred_at=occurred_at,
                trace_id=_identifier(str(checkpoint.run_id), 32),
                span_id=_identifier(f"{checkpoint.run_id}:{checkpoint.revision}:{event_type}", 16),
                run_id=checkpoint.run_id,
                session_id=str(checkpoint.run_id),
                workflow_name=self.workflow_name,
                workflow_version=checkpoint.workflow_version,
                environment=self.environment,
                status=status,
                attributes=attributes,
            )
        )

    @staticmethod
    def _checkpoint_attributes(checkpoint: RunCheckpoint) -> dict[str, object]:
        return {
            "checkpoint_state": checkpoint.state.value,
            "checkpoint_revision": checkpoint.revision,
            "next_step": checkpoint.next_step,
            "attempts": checkpoint.attempts,
            "has_failure": checkpoint.last_failure is not None,
        }


def _identifier(value: str, length: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _status_for(checkpoint: RunCheckpoint) -> Literal["ok", "error", "partial", "cancelled"]:
    if checkpoint.state.value in {"failed", "escalated"}:
        return "error"
    if checkpoint.state.value in {"waiting_retry", "waiting_approval"}:
        return "partial"
    if checkpoint.state.value == "cancelled":
        return "cancelled"
    return "ok"


def _safe_category(value: str) -> str:
    """Preserve a compact machine category without leaking exception text."""

    category = value.split(":", maxsplit=1)[0].strip()
    normalized = "".join(
        character if character.isalnum() or character in "_-" else "_" for character in category
    )
    return normalized[:80] or "unknown"
