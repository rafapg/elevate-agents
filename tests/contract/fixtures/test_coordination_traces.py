"""Keep the pre-executed coordination examples safe and structurally valid."""

from __future__ import annotations

from pathlib import Path

from aula12_agents.infrastructure.trace.models import TraceEvent

FIXTURES = Path(__file__).parents[3] / "fixtures" / "coordination"


def test_coordination_examples_are_valid_synthetic_trace_events() -> None:
    scenario_files = sorted(FIXTURES.glob("*.jsonl"))

    assert [path.name for path in scenario_files] == [
        "01-supervisor-fixo.jsonl",
        "02-spawn-saudavel.jsonl",
        "03-no-spawn.jsonl",
        "04-cancelamento-resultado-tardio.jsonl",
    ]

    for scenario in scenario_files:
        serialized = scenario.read_text().lower()
        events = [
            TraceEvent.model_validate_json(line) for line in scenario.read_text().splitlines()
        ]
        assert events
        assert len({event.trace_id for event in events}) == 1
        assert len({event.run_id for event in events}) == 1
        assert all(event.attributes.get("synthetic") is True for event in events)
        assert "api_key" not in serialized


def test_cancellation_example_rejects_a_result_after_its_task_was_cancelled() -> None:
    events = [
        TraceEvent.model_validate_json(line)
        for line in (FIXTURES / "04-cancelamento-resultado-tardio.jsonl").read_text().splitlines()
    ]

    cancelled = next(event for event in events if event.event_type == "coordination.task.cancelled")
    rejected = next(
        event for event in events if event.event_type == "coordination.task.result_rejected"
    )

    assert cancelled.attributes["task_id"] == rejected.attributes["task_id"]
    assert rejected.attributes["reason"] == "stale_result_after_cancellation"
    assert rejected.attributes["result_aggregated"] is False
