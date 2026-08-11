from __future__ import annotations

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from aula12_agents.agent.deps import ToolObservation
from aula12_agents.infrastructure.trace.sinks import JsonlTraceSink, TraceRedactor
from aula12_agents.infrastructure.trace.tools import ToolTraceObserver


@pytest.mark.asyncio
async def test_tool_observation_is_serialized_locally_without_payload_content(
    tmp_path: Path,
) -> None:
    observer = ToolTraceObserver(
        sink=JsonlTraceSink(tmp_path, redactor=TraceRedactor(capture_content=False)),
        workflow_name="checkout-investigation",
        workflow_version="fixture-v1",
        environment="test",
        now=lambda: datetime(2026, 8, 10, tzinfo=UTC),
    )

    await observer(
        ToolObservation(
            run_id="tool-contract-run",
            tool_name="read_evidence",
            incident_id="BUG-204",
            outcome="truncated",
            evidence_count=3,
        )
    )

    trace_id = sha256(b"tool-contract-run").hexdigest()[:32]
    [stored] = [
        json.loads(line) for line in (tmp_path / f"{trace_id}.jsonl").read_text().splitlines()
    ]
    assert stored["event_type"] == "agent.tool.observation"
    assert stored["attributes"] == {
        "tool_name": "read_evidence",
        "incident_id": "BUG-204",
        "outcome": "truncated",
        "evidence_count": 3,
    }


@pytest.mark.asyncio
async def test_tool_observation_does_not_raise_when_local_trace_write_fails() -> None:
    class BrokenSink:
        def emit(self, _: object) -> None:
            raise OSError("synthetic disk failure")

    observer = ToolTraceObserver(
        sink=BrokenSink(),
        workflow_name="checkout-investigation",
        workflow_version="fixture-v1",
        environment="test",
        now=lambda: datetime(2026, 8, 10, tzinfo=UTC),
    )

    await observer(
        ToolObservation(
            run_id="tool-contract-run",
            tool_name="read_evidence",
            incident_id="BUG-204",
            outcome="ok",
            evidence_count=1,
        )
    )
