"""Export-safe trace events for the deterministic coordination demonstration."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from aula12_agents.domain.models import (
    CoordinationDecision,
    CoordinationRun,
    CoordinationTask,
    EvidenceReport,
)

from .models import TraceEvent
from .sinks import TraceSink


@dataclass(frozen=True, slots=True)
class CoordinationTraceObserver:
    """Observer for task-board transitions; trace failures never alter the run."""

    sink: TraceSink
    workflow_name: str
    environment: str

    def record_run_started(self, *, run: CoordinationRun, occurred_at: datetime) -> None:
        self._record(
            run=run,
            event_type="coordination.run.started",
            occurred_at=occurred_at,
            attributes={
                "scenario": run.scenario.value,
                "coverage_target": run.coverage_target,
                "budget_steps": run.budget_steps,
            },
        )

    def record_task_dispatched(
        self, *, run: CoordinationRun, task: CoordinationTask, occurred_at: datetime
    ) -> None:
        self._record(
            run=run,
            event_type="coordination.task.dispatched",
            occurred_at=occurred_at,
            task=task,
            attributes={
                "profile": task.profile.value,
                "read_scope": list(task.read_scope),
                "budget_steps": task.budget_steps,
                "expected_revision": task.expected_revision,
            },
        )

    def record_task_completed(
        self,
        *,
        run: CoordinationRun,
        task: CoordinationTask,
        report: EvidenceReport,
        occurred_at: datetime,
    ) -> None:
        self._record(
            run=run,
            event_type="coordination.task.completed",
            occurred_at=occurred_at,
            task=task,
            attributes={
                "evidence_sources": [item.source for item in report.evidence],
                "has_provenance": bool(report.provenance),
                "has_limitation": bool(report.limitation),
                "coverage_count": len(report.coverage),
            },
        )

    def record_task_cancelled(
        self,
        *,
        run: CoordinationRun,
        task: CoordinationTask,
        reason: str,
        occurred_at: datetime,
    ) -> None:
        self._record(
            run=run,
            event_type="coordination.task.cancelled",
            occurred_at=occurred_at,
            task=task,
            status="cancelled",
            attributes={"reason": _safe_category(reason), "cancelled_at_revision": run.revision},
        )

    def record_result_rejected(
        self,
        *,
        run: CoordinationRun,
        task: CoordinationTask,
        report: EvidenceReport,
        observed_revision: int,
        reason: str,
        occurred_at: datetime,
    ) -> None:
        self._record(
            run=run,
            event_type="coordination.task.result_rejected",
            occurred_at=occurred_at,
            task=task,
            attributes={
                "reason": _safe_category(reason),
                # Keep the dispatch contract and the revision declared by the
                # returned report distinct. A policy may reject a result even
                # when they happen to be equal.
                "task_expected_revision": task.expected_revision,
                "task_revision_at_rejection": task.revision,
                "declared_result_revision": report.expected_revision,
                "board_revision_at_rejection": observed_revision,
                "result_aggregated": False,
            },
        )

    def record_decision(
        self,
        *,
        run: CoordinationRun,
        decision: CoordinationDecision,
        occurred_at: datetime,
    ) -> None:
        event_type = (
            "coordination.aggregate.decided"
            if decision.kind.value == "aggregate"
            else "coordination.spawn.decided"
            if decision.kind.value in {"spawn", "no_spawn"}
            else "coordination.decision.recorded"
        )
        self._record(
            run=run,
            event_type=event_type,
            occurred_at=occurred_at,
            attributes={
                "decision": decision.kind.value,
                "reason": _safe_category(decision.reason),
                "decision_task_id": None if decision.task_id is None else str(decision.task_id),
                "coverage_valid": _coverage_count(run),
                "coverage_target": run.coverage_target,
            },
        )

    def _record(
        self,
        *,
        run: CoordinationRun,
        event_type: str,
        occurred_at: datetime,
        attributes: dict[str, object],
        task: CoordinationTask | None = None,
        status: Literal["ok", "error", "partial", "cancelled"] = "ok",
    ) -> None:
        try:
            root_span_id = _identifier(f"{run.run_id}:root", 16)
            is_root_event = event_type == "coordination.run.started"
            parent = str(task.task_id) if task is not None else "run"
            self.sink.emit(
                TraceEvent(
                    event_type=event_type,
                    occurred_at=occurred_at,
                    trace_id=_identifier(str(run.run_id), 32),
                    # The start event is a real, stable root span. Every
                    # following coordination event is its direct child. This
                    # intentionally models a flat task board rather than
                    # inventing parent task spans that were never emitted.
                    span_id=(
                        root_span_id
                        if is_root_event
                        else _identifier(f"{run.run_id}:{run.revision}:{event_type}:{parent}", 16)
                    ),
                    parent_span_id=None if is_root_event else root_span_id,
                    run_id=run.run_id,
                    session_id=str(run.run_id),
                    workflow_name=self.workflow_name,
                    workflow_version="coordination-v1",
                    environment=self.environment,
                    status=status,
                    attributes={
                        "run_state": run.state.value,
                        "run_revision": run.revision,
                        "spent_steps": run.spent_steps,
                        **({"task_id": str(task.task_id)} if task is not None else {}),
                        **attributes,
                    },
                )
            )
        except Exception:
            return


def _coverage_count(run: CoordinationRun) -> int:
    return len(
        {item for task in run.tasks if task.result is not None for item in task.result.coverage}
    )


def _identifier(value: str, length: int) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:length]


def _safe_category(value: str) -> str:
    """Keep a stable category while excluding free-form detail from traces."""

    normalized = "".join(
        character if character.isalnum() or character in "_-" else "_" for character in value
    )
    return normalized[:80] or "unknown"
