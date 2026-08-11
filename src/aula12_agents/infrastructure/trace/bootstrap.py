"""One explicit OpenTelemetry/Langfuse bootstrap for PydanticAI and workflow spans.

PydanticAI already emits native OTel spans when supplied an
``InstrumentationSettings`` object. This module gives it the *same* tracer
provider used by the one Langfuse client that exports workflow spans; it never
installs Logfire or a second global provider.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langfuse import Langfuse
from opentelemetry.sdk.trace import TracerProvider
from pydantic_ai.models import Model
from pydantic_ai.models.instrumented import (
    InstrumentationSettings,
    InstrumentedModel,
    instrument_model,
)

from .models import TraceSettings
from .sinks import (
    CompositeTraceSink,
    JsonlTraceSink,
    LangfuseTraceSink,
    TraceRedactor,
    TraceSink,
    build_trace_sink,
)

LangfuseFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class ObservabilityBootstrap:
    """Composable tracing dependencies for the application composition root."""

    sink: TraceSink
    local_sink: JsonlTraceSink
    pydantic_ai_instrumentation: InstrumentationSettings | None
    remote_enabled: bool

    def instrument_pydantic_ai_model(self, model: Model) -> Model:
        """Wrap a model once; no settings means local JSONL-only observability."""

        if self.pydantic_ai_instrumentation is None or isinstance(model, InstrumentedModel):
            return model
        return instrument_model(model, self.pydantic_ai_instrumentation)


def build_observability(
    settings: TraceSettings, *, langfuse_factory: LangfuseFactory = Langfuse
) -> ObservabilityBootstrap:
    """Build observability from injected settings without reading environment variables.

    Missing credentials and client-construction failures deliberately produce the
    same local JSONL fallback as remote export failures. Authentication is not
    proactively checked because bootstrap must not make network calls.
    """

    if settings.backend == "jsonl" or not settings.has_langfuse_credentials:
        sink = build_trace_sink(settings)
        return ObservabilityBootstrap(
            sink=sink,
            local_sink=_local_sink(sink),
            pydantic_ai_instrumentation=None,
            remote_enabled=False,
        )

    redactor = TraceRedactor(capture_content=settings.capture_content)
    local = JsonlTraceSink(settings.trace_dir, redactor=redactor)
    composite = CompositeTraceSink(local, remote=None)
    try:
        tracer_provider = TracerProvider()
        client = langfuse_factory(
            public_key=settings.langfuse_public_key.get_secret_value()
            if settings.langfuse_public_key
            else None,
            secret_key=settings.langfuse_secret_key.get_secret_value()
            if settings.langfuse_secret_key
            else None,
            base_url=settings.langfuse_base_url,
            environment=settings.environment,
            release=settings.langfuse_release,
            tracer_provider=tracer_provider,
        )
        remote = LangfuseTraceSink(settings, redactor=redactor, client=client)
    except Exception as error:  # setup is observational and cannot block a run
        composite.report_remote_unavailable(type(error).__name__)
        return ObservabilityBootstrap(
            sink=composite,
            local_sink=local,
            pydantic_ai_instrumentation=None,
            remote_enabled=False,
        )

    return ObservabilityBootstrap(
        sink=CompositeTraceSink(local, remote),
        local_sink=local,
        pydantic_ai_instrumentation=InstrumentationSettings(
            tracer_provider=tracer_provider,
            include_content=settings.capture_content,
            include_binary_content=False,
            include_model_request_parameters=False,
        ),
        remote_enabled=True,
    )


def _local_sink(sink: TraceSink) -> JsonlTraceSink:
    """Extract the JSONL sink from the no-remote construction path."""

    if isinstance(sink, JsonlTraceSink):
        return sink
    if isinstance(sink, CompositeTraceSink):
        return sink.local_sink
    raise TypeError("Observability bootstrap requires a JSONL local sink")
