"""JSONL-first trace sinks and a best-effort Langfuse exporter.

The remote adapter is deliberately an observer: an unavailable endpoint or bad
credential can add a local failure event, but cannot affect workflow control.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from langfuse import Langfuse
from langfuse.types import TraceContext

from .models import TraceEvent, TraceSettings

_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|password|secret|token)", re.I)
_SENSITIVE_VALUE = re.compile(r"(?:sk-[A-Za-z0-9_-]+|Bearer\s+\S+)", re.I)
_CONTENT_KEY = re.compile(r"(?:content|input|output|prompt|completion|excerpt)", re.I)


class TraceSink(Protocol):
    """Small port shared by tracing infrastructure consumers."""

    def emit(self, event: TraceEvent) -> None: ...

    def flush(self) -> None: ...


class TraceRedactor:
    """Deterministic redaction before any local or remote serialization."""

    def __init__(self, *, capture_content: bool) -> None:
        self._capture_content = capture_content

    def redact_event(self, event: TraceEvent) -> TraceEvent:
        return event.model_copy(update={"attributes": self._redact(event.attributes)})

    def _redact(self, value: Any, *, key: str | None = None) -> Any:
        if key and _SENSITIVE_KEY.search(key):
            return "[REDACTED]"
        if key and not self._capture_content and _CONTENT_KEY.search(key):
            return "[CONTENT_NOT_CAPTURED]"
        if isinstance(value, dict):
            return {
                str(item_key): self._redact(item, key=str(item_key))
                for item_key, item in value.items()
            }
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, tuple):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            return _SENSITIVE_VALUE.sub("[REDACTED]", value)
        return value


class JsonlTraceSink:
    """Append-only local trace store; one sanitized event per line."""

    def __init__(self, trace_dir: Path, *, redactor: TraceRedactor) -> None:
        self._trace_dir = trace_dir
        self._redactor = redactor

    def emit(self, event: TraceEvent) -> None:
        sanitized = self._redactor.redact_event(event)
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        destination = self._trace_dir / f"{sanitized.trace_id}.jsonl"
        with destination.open("a", encoding="utf-8") as stream:
            stream.write(sanitized.model_dump_json() + "\n")

    def flush(self) -> None:
        """Writes are synchronously committed by ``emit``; kept for port symmetry."""


class LangfuseTraceSink:
    """Thin Langfuse adapter. It must be used behind ``CompositeTraceSink``."""

    def __init__(
        self, settings: TraceSettings, *, redactor: TraceRedactor, client: Any | None = None
    ) -> None:
        if not settings.has_langfuse_credentials:
            raise ValueError("Langfuse requires both public and secret keys")
        self._redactor = redactor
        self._client = client or Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value()
            if settings.langfuse_public_key
            else None,
            secret_key=settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_secret_key
            else None,
            base_url=settings.langfuse_base_url,
            environment=settings.environment,
            release=settings.langfuse_release,
        )

    def emit(self, event: TraceEvent) -> None:
        sanitized = self._redactor.redact_event(event)
        trace_context: TraceContext = {"trace_id": sanitized.trace_id}
        if sanitized.parent_span_id is not None:
            trace_context["parent_span_id"] = sanitized.parent_span_id
        observation = self._client.start_observation(
            trace_context=trace_context,
            name=sanitized.event_type,
            as_type="span",
            metadata={
                "event_id": str(sanitized.event_id),
                "span_id": sanitized.span_id,
                "run_id": str(sanitized.run_id) if sanitized.run_id else None,
                "session_id": sanitized.session_id,
                "workflow_name": sanitized.workflow_name,
                "workflow_version": sanitized.workflow_version,
                "status": sanitized.status,
                "attributes": sanitized.attributes,
            },
        )
        observation.end()

    def flush(self) -> None:
        self._client.flush()


class CompositeTraceSink:
    """Local-first composition with a disabled-on-failure remote exporter."""

    def __init__(self, local: JsonlTraceSink, remote: TraceSink | None) -> None:
        self._local = local
        self._remote = remote
        self._remote_disabled = remote is None
        self._reported_unavailable = False

    @property
    def local_sink(self) -> JsonlTraceSink:
        """The durable local fallback, exposed for local-only adapter events."""

        return self._local

    def report_remote_unavailable(self, reason: str, *, event: TraceEvent | None = None) -> None:
        if self._reported_unavailable:
            return
        self._reported_unavailable = True
        self._local.emit(_failure_event(reason, context=event))

    def emit(self, event: TraceEvent) -> None:
        self._local.emit(event)
        if self._remote_disabled or self._remote is None:
            return
        try:
            self._remote.emit(event)
        except Exception as error:  # remote telemetry must never change application outcome
            self._remote_disabled = True
            self.report_remote_unavailable(type(error).__name__, event=event)

    def flush(self) -> None:
        if not self._remote_disabled and self._remote is not None:
            try:
                self._remote.flush()
            except Exception as error:  # see emit: local tracing remains usable
                self._remote_disabled = True
                self.report_remote_unavailable(type(error).__name__)
        self._local.flush()


def build_trace_sink(settings: TraceSettings) -> TraceSink:
    """Build a sink without environment reads or network/auth checks at startup."""

    redactor = TraceRedactor(capture_content=settings.capture_content)
    local = JsonlTraceSink(settings.trace_dir, redactor=redactor)
    if settings.backend == "jsonl":
        return local

    composite = CompositeTraceSink(local, remote=None)
    if not settings.has_langfuse_credentials:
        composite.report_remote_unavailable("missing_credentials")
        return composite
    try:
        remote = LangfuseTraceSink(settings, redactor=redactor)
    except Exception as error:  # invalid config/client construction must remain observational
        composite.report_remote_unavailable(type(error).__name__)
        return composite
    return CompositeTraceSink(local, remote)


def _failure_event(reason: str, *, context: TraceEvent | None = None) -> TraceEvent:
    """Create a safe local event without application identifiers or payload content."""

    return TraceEvent(
        event_type="telemetry.remote_export_failed",
        occurred_at=datetime.now(UTC),
        trace_id=context.trace_id if context else "0" * 32,
        span_id="f" * 16,
        parent_span_id=context.span_id if context else None,
        workflow_name=context.workflow_name if context else "telemetry",
        workflow_version=context.workflow_version if context else "1",
        environment=context.environment if context else "lab",
        status="error",
        attributes={"reason": reason},
    )
