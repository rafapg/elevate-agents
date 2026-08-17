from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from pydantic_ai.models.test import TestModel

from aula12_agents.agent.deps import ToolObservation
from aula12_agents.infrastructure.trace.bootstrap import build_observability
from aula12_agents.infrastructure.trace.models import TraceEvent, TraceSettings
from aula12_agents.infrastructure.trace.tools import ToolTraceObserver


def _event() -> TraceEvent:
    return TraceEvent(
        event_type="workflow.node.finished",
        occurred_at=datetime(2026, 8, 8, tzinfo=UTC),
        trace_id="1" * 32,
        span_id="2" * 16,
        workflow_name="checkout-investigation",
        workflow_version="fixture-v1",
    )


def test_missing_credentials_uses_jsonl_and_does_not_enable_pydantic_ai(tmp_path: Path) -> None:
    bootstrap = build_observability(TraceSettings(backend="both", trace_dir=tmp_path))

    bootstrap.sink.emit(_event())

    assert not bootstrap.remote_enabled
    assert bootstrap.pydantic_ai_instrumentation is None
    failure = tmp_path / f"{'0' * 32}.jsonl"
    assert json.loads(failure.read_text())["event_type"] == "telemetry.remote_export_failed"


def test_client_construction_failure_preserves_the_jsonl_fallback(tmp_path: Path) -> None:
    def broken_factory(**_: object) -> object:
        raise RuntimeError("synthetic client configuration error")

    settings = TraceSettings(
        backend="langfuse",
        trace_dir=tmp_path,
        langfuse_public_key="pk-lf-synthetic",
        langfuse_secret_key="sk-lf-synthetic",
    )

    bootstrap = build_observability(settings, langfuse_factory=broken_factory)
    bootstrap.sink.emit(_event())

    assert not bootstrap.remote_enabled
    assert (tmp_path / f"{'1' * 32}.jsonl").exists()
    notice = json.loads((tmp_path / f"{'0' * 32}.jsonl").read_text())
    assert notice["attributes"] == {"reason": "RuntimeError"}


class _FakeObservation:
    def __init__(self, client: _FakeLangfuse, *, parent: _FakeObservation | None) -> None:
        self.client = client
        self.parent = parent
        self.ended = False

    def start_observation(self, **kwargs: object) -> _FakeObservation:
        self.client.observations.append({"parent": self, **kwargs})
        return _FakeObservation(self.client, parent=self)

    def end(self) -> None:
        self.ended = True


class _FakeLangfuse:
    def __init__(self) -> None:
        self.observations: list[dict[str, object]] = []
        self.flushed = False

    def start_observation(self, **kwargs: object) -> _FakeObservation:
        self.observations.append({"parent": None, **kwargs})
        return _FakeObservation(self, parent=None)

    def flush(self) -> None:
        self.flushed = True


def test_one_provider_is_shared_by_native_pydantic_ai_and_custom_events(tmp_path: Path) -> None:
    client = _FakeLangfuse()

    def factory(**_: object) -> _FakeLangfuse:
        return client

    settings = TraceSettings(
        backend="both",
        trace_dir=tmp_path,
        langfuse_public_key="pk-lf-synthetic",
        langfuse_secret_key="sk-lf-synthetic",
    )
    bootstrap = build_observability(settings, langfuse_factory=factory)
    model = TestModel()

    instrumented_once = bootstrap.instrument_pydantic_ai_model(model)
    instrumented_twice = bootstrap.instrument_pydantic_ai_model(instrumented_once)
    bootstrap.sink.emit(_event())

    assert bootstrap.remote_enabled
    assert instrumented_once is instrumented_twice
    assert client.observations[0]["name"] == "workflow.node.finished"


def test_coordination_events_use_a_real_langfuse_root_and_keep_jsonl(tmp_path: Path) -> None:
    client = _FakeLangfuse()

    def factory(**_: object) -> _FakeLangfuse:
        return client

    settings = TraceSettings(
        backend="both",
        trace_dir=tmp_path,
        langfuse_public_key="pk-lf-synthetic",
        langfuse_secret_key="sk-lf-synthetic",
        capture_content=False,
    )
    bootstrap = build_observability(settings, langfuse_factory=factory)
    root = TraceEvent(
        event_type="coordination.run.started",
        occurred_at=datetime(2026, 8, 11, tzinfo=UTC),
        trace_id="c" * 32,
        span_id="d" * 16,
        workflow_name="aula12-agents-coordination",
        workflow_version="coordination-v1",
        attributes={"scenario": "supervisor", "prompt": "not exported"},
    )
    child = root.model_copy(
        update={
            "event_type": "coordination.task.dispatched",
            "span_id": "e" * 16,
            "parent_span_id": root.span_id,
            "attributes": {"task_id": "synthetic", "read_scope": ["search_commits"]},
        }
    )

    bootstrap.sink.emit(root)
    bootstrap.sink.emit(child)
    bootstrap.sink.flush()

    remote_root, remote_child = client.observations
    assert remote_root["name"] == "coordination.run.started"
    assert remote_root["parent"] is None
    assert remote_child["name"] == "coordination.task.dispatched"
    assert remote_child["parent"] is not None
    assert "trace_context" not in remote_child
    root_metadata = cast(dict[str, Any], remote_root["metadata"])
    root_attributes = cast(dict[str, Any], root_metadata["attributes"])
    assert root_attributes["prompt"] == "[CONTENT_NOT_CAPTURED]"
    stored = (tmp_path / f"{'c' * 32}.jsonl").read_text(encoding="utf-8")
    assert "not exported" not in stored
    assert '"coordination.task.dispatched"' in stored


@pytest.mark.asyncio
async def test_tool_observations_stay_local_when_langfuse_native_spans_are_enabled(
    tmp_path: Path,
) -> None:
    client = _FakeLangfuse()

    def factory(**_: object) -> _FakeLangfuse:
        return client

    settings = TraceSettings(
        backend="both",
        trace_dir=tmp_path,
        langfuse_public_key="pk-lf-synthetic",
        langfuse_secret_key="sk-lf-synthetic",
    )
    bootstrap = build_observability(settings, langfuse_factory=factory)
    observer = ToolTraceObserver(
        sink=bootstrap.local_sink,
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

    assert client.observations == []
    trace_files = [path async for path in anyio.Path(tmp_path).glob("*.jsonl")]
    assert trace_files
