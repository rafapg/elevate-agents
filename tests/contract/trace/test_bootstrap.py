from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

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
    def end(self) -> None:
        pass


class _FakeLangfuse:
    def __init__(self) -> None:
        self.observations: list[dict[str, object]] = []
        self.flushed = False

    def start_observation(self, **kwargs: object) -> _FakeObservation:
        self.observations.append(kwargs)
        return _FakeObservation()

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
