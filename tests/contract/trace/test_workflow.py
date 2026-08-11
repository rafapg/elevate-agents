from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from aula12_agents.domain.models import CheckpointState, Incident, RunCheckpoint
from aula12_agents.infrastructure.trace.sinks import JsonlTraceSink, TraceRedactor
from aula12_agents.infrastructure.trace.workflow import WorkflowTraceObserver


def _checkpoint() -> RunCheckpoint:
    now = datetime(2026, 8, 10, tzinfo=UTC)
    return RunCheckpoint(
        workflow_version="fixture-v1",
        state=CheckpointState.RUNNING,
        incident=Incident(
            incident_id="BUG-204",
            title="Synthetic incident",
            description="A synthetic incident used by a trace contract.",
            reported_at=now,
            service="checkout",
            severity="high",
        ),
        input_sha256="a" * 64,
        next_step="critic",
        attempts={"hypothesis": 1},
        created_at=now,
        updated_at=now,
    )


def _events(trace_dir: Path, checkpoint: RunCheckpoint) -> list[dict[str, object]]:
    from hashlib import sha256

    trace_id = sha256(str(checkpoint.run_id).encode()).hexdigest()[:32]
    return [json.loads(line) for line in (trace_dir / f"{trace_id}.jsonl").read_text().splitlines()]


def test_stage_events_are_correlated_and_include_only_safe_stage_metadata(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    observer = WorkflowTraceObserver(
        sink=JsonlTraceSink(tmp_path, redactor=TraceRedactor(capture_content=False)),
        workflow_name="checkout-investigation",
        environment="test",
    )
    occurred_at = datetime(2026, 8, 10, 12, tzinfo=UTC)

    observer.record_stage_started(
        checkpoint=checkpoint, stage="hypothesis", occurred_at=occurred_at
    )
    observer.record_stage_completed(checkpoint=checkpoint, stage="critic", occurred_at=occurred_at)
    observer.record_stage_failed(
        checkpoint=checkpoint,
        stage="gate",
        failure_kind="PolicyViolation: raw model output must not be exported",
        occurred_at=occurred_at,
    )

    events = _events(tmp_path, checkpoint)
    assert [event["event_type"] for event in events] == [
        "workflow.stage.started",
        "workflow.stage.completed",
        "workflow.stage.failed",
    ]
    assert {event["run_id"] for event in events} == {str(checkpoint.run_id)}
    assert {event["trace_id"] for event in events} == {events[0]["trace_id"]}
    assert events[0]["attributes"]["stage"] == "hypothesis"
    assert events[1]["attributes"]["stage"] == "critic"
    assert events[2]["status"] == "error"
    assert events[2]["attributes"]["failure_kind"] == "PolicyViolation"
    assert "raw model output" not in json.dumps(events)


def test_gate_decision_has_its_own_deterministic_event(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    observer = WorkflowTraceObserver(
        sink=JsonlTraceSink(tmp_path, redactor=TraceRedactor(capture_content=False)),
        workflow_name="checkout-investigation",
        environment="test",
    )

    observer.record_gate_decision(
        checkpoint=checkpoint,
        decision="retry",
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
    )

    [event] = _events(tmp_path, checkpoint)
    assert event["event_type"] == "workflow.gate.decided"
    assert event["status"] == "partial"
    assert event["attributes"]["stage"] == "gate"
    assert event["attributes"]["decision"] == "retry"


def test_resilience_events_are_correlated_and_do_not_export_runtime_content(tmp_path: Path) -> None:
    checkpoint = _checkpoint()
    observer = WorkflowTraceObserver(
        sink=JsonlTraceSink(tmp_path, redactor=TraceRedactor(capture_content=False)),
        workflow_name="checkout-investigation",
        environment="test",
    )
    occurred_at = datetime(2026, 8, 10, tzinfo=UTC)

    observer.record_retry_scheduled(
        checkpoint=checkpoint,
        stage="critic",
        occurred_at=occurred_at,
    )
    observer.record_resume_started(
        checkpoint=checkpoint,
        stage="critic",
        resumed_from_revision=4,
        occurred_at=occurred_at,
    )
    observer.record_stale_result_rejected(
        checkpoint=checkpoint,
        stage="gate",
        expected_revision=5,
        observed_revision=6,
        kind="revision_conflict",
        occurred_at=occurred_at,
    )

    events = _events(tmp_path, checkpoint)
    assert [event["event_type"] for event in events] == [
        "workflow.retry.scheduled",
        "workflow.resume.started",
        "workflow.execution.stale_result_rejected",
    ]
    assert {event["run_id"] for event in events} == {str(checkpoint.run_id)}
    assert {event["trace_id"] for event in events} == {events[0]["trace_id"]}
    assert events[0]["status"] == "partial"
    assert events[0]["attributes"]["stage"] == "critic"
    assert events[1]["attributes"]["resumed_from_revision"] == 4
    assert events[2]["status"] == "ok"
    assert events[2]["attributes"] == {
        "checkpoint_state": "running",
        "checkpoint_revision": 0,
        "next_step": "critic",
        "attempts": {"hypothesis": 1},
        "has_failure": False,
        "stage": "gate",
        "expected_revision": 5,
        "observed_revision": 6,
        "rejection_kind": "revision_conflict",
    }
    serialized = json.dumps(events)
    assert "raw model output" not in serialized
    assert "Synthetic incident" not in serialized


def test_stage_trace_failure_is_best_effort() -> None:
    class BrokenSink:
        def emit(self, _: object) -> None:
            raise OSError("synthetic disk failure")

    observer = WorkflowTraceObserver(
        sink=BrokenSink(),  # type: ignore[arg-type]
        workflow_name="checkout-investigation",
        environment="test",
    )

    observer.record_stage_started(
        checkpoint=_checkpoint(),
        stage="hypothesis",
        occurred_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
