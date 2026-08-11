"""Opt-in Langfuse smoke test; loads the lab settings only after opt-in."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aula12_agents.infrastructure.trace.bootstrap import build_observability
from aula12_agents.infrastructure.trace.models import TraceEvent
from aula12_agents.settings import load_settings


@pytest.mark.integration
def test_langfuse_export_when_explicitly_enabled(tmp_path: Path) -> None:
    if os.getenv("RUN_LANGFUSE_SMOKE") != "1":
        pytest.skip("set RUN_LANGFUSE_SMOKE=1 to enable the external Langfuse smoke test")
    settings = load_settings()
    trace_settings = settings.trace_settings()
    if not trace_settings.has_langfuse_credentials:
        pytest.skip("Langfuse credentials are not configured")

    smoke_settings = trace_settings.model_copy(
        update={"backend": "langfuse", "trace_dir": tmp_path}
    )
    bootstrap = build_observability(smoke_settings)
    if not bootstrap.remote_enabled:
        pytest.fail(
            "Langfuse bootstrap fell back to JSONL; check configuration without printing keys"
        )
    bootstrap.sink.emit(
        TraceEvent(
            event_type="smoke.langfuse.export",
            occurred_at=datetime.now(UTC),
            trace_id="e" * 32,
            span_id="d" * 16,
            workflow_name="langfuse-smoke",
            workflow_version="1",
        )
    )
    bootstrap.sink.flush()
