from datetime import UTC, datetime, timedelta

from aula12_agents.domain.models import (
    CoordinationDecision,
    CoordinationDecisionKind,
    CoordinationRun,
    CoordinationScenario,
    CoordinationTask,
    CoordinationTaskState,
    EvidenceRef,
    EvidenceReport,
    SubagentProfile,
)
from aula12_agents.infrastructure.trace.coordination import CoordinationTraceObserver

NOW = datetime(2026, 8, 11, tzinfo=UTC)
HASH = "a" * 64


class MemorySink:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event) -> None:
        self.events.append(event)

    def flush(self) -> None:
        return None


def task() -> CoordinationTask:
    return CoordinationTask(
        profile=SubagentProfile.CI_ANALYST,
        read_scope=("ci/run-1842.json",),
        budget_steps=2,
        deadline=NOW + timedelta(seconds=20),
        expected_revision=0,
    )


def run(task_board: tuple[CoordinationTask, ...] = ()) -> CoordinationRun:
    return CoordinationRun(
        scenario=CoordinationScenario.SUPERVISOR,
        deadline=NOW + timedelta(seconds=45),
        tasks=task_board,
        created_at=NOW,
        updated_at=NOW,
    )


def test_coordination_trace_emits_safe_task_lifecycle_metadata() -> None:
    sink = MemorySink()
    observer = CoordinationTraceObserver(
        sink=sink,
        workflow_name="checkout-coordination",
        environment="lab",
    )
    dispatched = task()
    started = run((dispatched,))
    report = EvidenceReport(
        task_id=dispatched.task_id,
        expected_revision=0,
        evidence=(
            EvidenceRef(
                source="ci/run-1842.json",
                artifact_id="run-1842",
                content_sha256=HASH,
                captured_at=NOW,
            ),
        ),
        provenance="fixture:ci",
        limitation="only the latest run",
        coverage=("ci_failure",),
        completed_at=NOW + timedelta(seconds=2),
    )
    completed = dispatched.model_copy(
        update={"status": CoordinationTaskState.COMPLETED, "result": report}
    )
    finished = started.model_copy(update={"tasks": (completed,)})

    observer.record_run_started(run=started, occurred_at=NOW)
    observer.record_task_dispatched(run=started, task=dispatched, occurred_at=NOW)
    observer.record_task_completed(
        run=finished, task=completed, report=report, occurred_at=report.completed_at
    )

    assert [event.event_type for event in sink.events] == [
        "coordination.run.started",
        "coordination.task.dispatched",
        "coordination.task.completed",
    ]
    assert sink.events[1].attributes["read_scope"] == ["ci/run-1842.json"]
    assert sink.events[2].attributes["evidence_sources"] == ["ci/run-1842.json"]
    assert "provenance" not in sink.events[2].attributes
    assert "limitation" not in sink.events[2].attributes
    root, dispatched_event, completed_event = sink.events
    assert root.parent_span_id is None
    assert root.span_id == observer_root_span_id(started)
    assert dispatched_event.parent_span_id == root.span_id
    assert completed_event.parent_span_id == root.span_id


def test_coordination_trace_records_cancellation_rejection_and_decision() -> None:
    sink = MemorySink()
    observer = CoordinationTraceObserver(
        sink=sink,
        workflow_name="checkout-coordination",
        environment="lab",
    )
    pending = task()
    active_run = run((pending,))
    cancelled = pending.model_copy(update={"status": CoordinationTaskState.CANCELLED})
    revised_run = active_run.model_copy(
        update={
            "tasks": (cancelled,),
            "revision": 1,
            "updated_at": NOW + timedelta(seconds=1),
        }
    )
    decision = CoordinationDecision(
        kind=CoordinationDecisionKind.REJECT_LATE_RESULT,
        reason="stale result after cancellation",
        task_id=cancelled.task_id,
    )
    late_report = EvidenceReport(
        task_id=cancelled.task_id,
        expected_revision=0,
        evidence=(
            EvidenceRef(
                source="ci/run-1842.json",
                artifact_id="run-1842",
                content_sha256=HASH,
                captured_at=NOW,
            ),
        ),
        provenance="fixture:ci",
        limitation="result arrived after cancellation",
        coverage=("ci_failure",),
        completed_at=NOW + timedelta(seconds=2),
    )

    observer.record_task_cancelled(
        run=revised_run,
        task=cancelled,
        reason="parent hypothesis invalidated",
        occurred_at=NOW + timedelta(seconds=1),
    )
    observer.record_result_rejected(
        run=revised_run,
        task=cancelled,
        report=late_report,
        observed_revision=1,
        reason="stale result after cancellation",
        occurred_at=NOW + timedelta(seconds=2),
    )
    observer.record_decision(
        run=revised_run,
        decision=decision,
        occurred_at=NOW + timedelta(seconds=2),
    )

    assert sink.events[0].status == "cancelled"
    assert sink.events[1].attributes["result_aggregated"] is False
    assert sink.events[1].attributes["task_expected_revision"] == 0
    assert sink.events[1].attributes["task_revision_at_rejection"] == 0
    assert sink.events[1].attributes["declared_result_revision"] == 0
    assert sink.events[1].attributes["board_revision_at_rejection"] == 1
    assert sink.events[2].event_type == "coordination.decision.recorded"


def observer_root_span_id(coordination_run: CoordinationRun) -> str:
    """Avoid hard-coding an implementation hash in the tree-shape assertion."""

    import hashlib

    return hashlib.sha256(f"{coordination_run.run_id}:root".encode()).hexdigest()[:16]
