"""Opt-in smoke check for the coordination trace exported to Langfuse.

No network call or credential lookup happens unless the explicit environment
flag is set. The test also asserts that JSONL remains available locally.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aula12_agents.infrastructure.trace.bootstrap import build_observability
from aula12_agents.infrastructure.trace.models import TraceEvent
from aula12_agents.settings import load_settings


@pytest.mark.integration
def test_coordination_langfuse_export_is_explicit_and_keeps_jsonl(tmp_path: Path) -> None:
    if os.getenv("RUN_COORDINATION_LANGFUSE_SMOKE") != "1":
        pytest.skip(
            "set RUN_COORDINATION_LANGFUSE_SMOKE=1 to enable the external coordination smoke test"
        )

    trace_settings = load_settings().trace_settings()
    if not trace_settings.has_langfuse_credentials:
        pytest.skip("Langfuse credentials are not configured")

    settings = trace_settings.model_copy(
        update={"backend": "langfuse", "trace_dir": tmp_path, "capture_content": False}
    )
    bootstrap = build_observability(settings)
    if not bootstrap.remote_enabled:
        pytest.fail(
            "Langfuse bootstrap fell back to JSONL; check configuration without printing keys"
        )

    root = TraceEvent(
        event_type="coordination.run.started",
        occurred_at=datetime.now(UTC),
        trace_id="c" * 32,
        span_id="d" * 16,
        workflow_name="aula12-agents-coordination",
        workflow_version="coordination-v1",
        attributes={"scenario": "langfuse-smoke", "prompt": "must remain redacted"},
    )
    task = root.model_copy(
        update={
            "event_type": "coordination.task.dispatched",
            "span_id": "e" * 16,
            "parent_span_id": root.span_id,
            "attributes": {"task_id": "smoke", "profile": "ci_analyst"},
        }
    )
    bootstrap.sink.emit(root)
    bootstrap.sink.emit(task)
    bootstrap.sink.flush()

    serialized = (tmp_path / f"{'c' * 32}.jsonl").read_text(encoding="utf-8")
    assert "must remain redacted" not in serialized
    assert '"coordination.task.dispatched"' in serialized
