from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import SecretStr

from aula12_agents.infrastructure.trace.models import TraceEvent, TraceSettings
from aula12_agents.infrastructure.trace.sinks import (
    CompositeTraceSink,
    JsonlTraceSink,
    TraceRedactor,
    build_trace_sink,
)


def _event(
    *, attributes: dict[str, object] | None = None, event_type: str = "tool.call.finished"
) -> TraceEvent:
    return TraceEvent(
        event_type=event_type,
        occurred_at=datetime(2026, 8, 8, tzinfo=UTC),
        trace_id="a" * 32,
        span_id="b" * 16,
        workflow_name="checkout-investigation",
        workflow_version="fixture-v1",
        attributes=attributes or {"tool_name": "query_error_logs"},
    )


def _read_events(trace_dir: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in (trace_dir / f"{'a' * 32}.jsonl").read_text().splitlines()]


def test_jsonl_sink_keeps_a_serialized_pydantic_event(tmp_path: Path) -> None:
    sink = JsonlTraceSink(tmp_path, redactor=TraceRedactor(capture_content=False))

    sink.emit(_event())

    [stored] = _read_events(tmp_path)
    assert stored["event_type"] == "tool.call.finished"
    assert stored["attributes"] == {"tool_name": "query_error_logs"}


def test_redaction_happens_before_the_local_write(tmp_path: Path) -> None:
    sink = JsonlTraceSink(tmp_path, redactor=TraceRedactor(capture_content=False))

    sink.emit(
        _event(
            attributes={
                "api_key": "sk-not-a-real-secret",
                "prompt": "customer@example.test",
                "nested": {"authorization": "Bearer not-a-real-token"},
            }
        )
    )

    serialized = (tmp_path / f"{'a' * 32}.jsonl").read_text()
    assert "sk-not-a-real-secret" not in serialized
    assert "not-a-real-token" not in serialized
    stored = _read_events(tmp_path)[0]
    assert stored["attributes"]["prompt"] == "[CONTENT_NOT_CAPTURED]"


class _FailingRemote:
    def emit(self, event: TraceEvent) -> None:
        raise PermissionError("synthetic auth rejection")

    def flush(self) -> None:
        raise AssertionError("flush should not be reached after remote failure")


def test_remote_export_failure_keeps_event_and_records_one_local_failure(tmp_path: Path) -> None:
    local = JsonlTraceSink(tmp_path, redactor=TraceRedactor(capture_content=False))
    sink = CompositeTraceSink(local, _FailingRemote())

    sink.emit(_event())
    sink.emit(_event(event_type="workflow.node.finished"))

    stored = _read_events(tmp_path)
    assert [event["event_type"] for event in stored] == [
        "tool.call.finished",
        "telemetry.remote_export_failed",
        "workflow.node.finished",
    ]
    assert stored[1]["attributes"] == {"reason": "PermissionError"}


def test_missing_credentials_falls_back_to_jsonl_and_emits_a_local_notice(tmp_path: Path) -> None:
    sink = build_trace_sink(TraceSettings(backend="both", trace_dir=tmp_path))

    sink.emit(_event())

    zero_trace_file = tmp_path / f"{'0' * 32}.jsonl"
    assert zero_trace_file.exists()
    assert _read_events(tmp_path)[0]["event_type"] == "tool.call.finished"
    assert json.loads(zero_trace_file.read_text())["event_type"] == "telemetry.remote_export_failed"


def test_explicit_langfuse_settings_do_not_expose_secret_on_model_dump(tmp_path: Path) -> None:
    settings = TraceSettings(
        backend="langfuse",
        trace_dir=tmp_path,
        langfuse_public_key=SecretStr("pk-lf-example"),
        langfuse_secret_key=SecretStr("sk-lf-example"),
    )

    assert "sk-lf-example" not in str(settings)
    assert settings.has_langfuse_credentials
