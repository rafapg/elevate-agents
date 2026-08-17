"""End-to-end checks for the offline reference coordination implementation."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aula12_agents.application.coordination import CoordinationCoordinator
from aula12_agents.domain.models import (
    CoordinationDecisionKind,
    CoordinationRunState,
    CoordinationScenario,
    CoordinationTaskState,
)
from aula12_agents.infrastructure.fixtures import FixtureReader
from aula12_agents.infrastructure.persistence import SQLiteCoordinationStore
from aula12_agents.infrastructure.trace import CoordinationTraceObserver
from aula12_agents.infrastructure.trace.sinks import JsonlTraceSink, TraceRedactor

NOW = datetime(2026, 8, 10, tzinfo=UTC)


def _coordinator(tmp_path: Path) -> tuple[CoordinationCoordinator, SQLiteCoordinationStore, Path]:
    store = SQLiteCoordinationStore(tmp_path / "coordination.sqlite3")
    trace_dir = tmp_path / "traces"
    coordinator = CoordinationCoordinator(
        store=store,
        events=store,
        reader=FixtureReader(),
        observer=CoordinationTraceObserver(
            sink=JsonlTraceSink(trace_dir, redactor=TraceRedactor(capture_content=False)),
            workflow_name="coordination-e2e",
            environment="test",
        ),
        now=lambda: NOW,
    )
    return coordinator, store, trace_dir


@pytest.mark.parametrize(
    ("scenario", "expected_decision", "task_count"),
    [
        (CoordinationScenario.SUPERVISOR, CoordinationDecisionKind.AGGREGATE, 2),
        (CoordinationScenario.SPAWN, CoordinationDecisionKind.AGGREGATE, 2),
        (CoordinationScenario.NO_SPAWN, CoordinationDecisionKind.NO_SPAWN, 1),
    ],
)
def test_reference_scenarios_complete_offline_with_the_expected_task_board(
    tmp_path: Path,
    scenario: CoordinationScenario,
    expected_decision: CoordinationDecisionKind,
    task_count: int,
) -> None:
    coordinator, store, trace_dir = _coordinator(tmp_path)

    result = asyncio.run(coordinator.run(scenario))

    assert result.state is CoordinationRunState.COMPLETED
    assert result.decision is not None
    assert result.decision.kind is expected_decision
    assert len(result.tasks) == task_count
    assert all(task.status is CoordinationTaskState.COMPLETED for task in result.tasks)
    assert store.load(result.run_id) == result
    assert store.list_events(result.run_id)
    trace_event_types = _trace_event_types(trace_dir)
    assert trace_event_types[0] == "coordination.run.started"
    assert "coordination.task.dispatched" in trace_event_types


def test_cancellation_rejects_a_late_result_from_the_real_task_board(tmp_path: Path) -> None:
    coordinator, store, trace_dir = _coordinator(tmp_path)

    result = asyncio.run(coordinator.run(CoordinationScenario.CANCELLATION))

    parent, dependent = result.tasks
    assert result.state is CoordinationRunState.COMPLETED
    assert result.decision is not None
    assert result.decision.kind is CoordinationDecisionKind.REJECT_LATE_RESULT
    assert dependent.depends_on == (parent.task_id,)
    assert parent.status is CoordinationTaskState.COMPLETED
    assert parent.result is not None
    assert dependent.status is CoordinationTaskState.CANCELLED
    assert dependent.result is None
    assert [event.event_type for event in store.list_events(result.run_id)] == [
        "coordination_run_created",
        "coordination_decision_cancel",
        "coordination_decision_reject_late_result",
    ]
    trace_events = _trace_event_types(trace_dir)
    assert trace_events.count("coordination.task.dispatched") == 2
    assert trace_events.count("coordination.task.cancelled") == 1
    assert trace_events[-2:] == [
        "coordination.task.result_rejected",
        "coordination.decision.recorded",
    ]


def _trace_event_types(trace_dir: Path) -> list[str]:
    return [
        json.loads(line)["event_type"]
        for path in trace_dir.glob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
