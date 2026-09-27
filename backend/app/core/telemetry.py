"""OpenTelemetry tracing (ADR-0014; ARCHITECTURE §14).

"Why was this turn slow?" is a per-turn question, so a voice turn is one trace: a `voice.turn` span
from the end of the student's speech to the end of playback, one child span per stage, the stage
marks as its events, and inside it the spans for whatever the turn called — generation, each tool
call, retrieval. HTTP requests, including a typed turn, get a span each.

Export is off unless configured (`VAANIOS_OTEL_EXPORTER`): with no exporter the SDK is never
installed, and every span is the API's no-op. `console` prints spans; `otlp` sends them to any
OpenTelemetry collector (`VAANIOS_OTEL_ENDPOINT`), such as Jaeger or Tempo.

One rule for writing spans here: inside an async generator, start a span with `start_span` and end
it yourself — never `start_as_current_span`. A generator can be closed from another task (a
barge-in, a client that hangs up), and detaching a context there fails. Coroutines may use either.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from opentelemetry import trace

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider

    from app.core.config import Settings

SERVICE_NAME = "vaanios-backend"

_installed = False

tracer = trace.get_tracer("vaanios")


def build_provider(settings: Settings) -> TracerProvider | None:
    """The tracer provider the settings ask for, or None when tracing is off."""
    if settings.otel_exporter == "none":
        return None

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    provider = TracerProvider(
        resource=Resource.create(
            {"service.name": SERVICE_NAME, "deployment.environment": settings.environment}
        )
    )
    if settings.otel_exporter == "console":
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    else:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_endpoint))
        )
    return provider


def configure_tracing(settings: Settings) -> None:
    """Install the configured provider, once per process: OpenTelemetry's global provider can be
    set only once, and every app instance in a process shares it."""
    global _installed
    if _installed:
        return
    provider = build_provider(settings)
    if provider is not None:
        trace.set_tracer_provider(provider)
    _installed = True


def epoch_ns(clock: Callable[[], float]) -> Callable[[float], int]:
    """Convert readings of a monotonic `clock` (seconds) into the wall-clock nanoseconds span
    timestamps need, anchored at this instant. Stage marks are taken on the monotonic clock, which
    is right for durations and means nothing as a date."""
    anchor_clock, anchor_ns = clock(), time.time_ns()

    def convert(reading: float) -> int:
        return anchor_ns - round((anchor_clock - reading) * 1e9)

    return convert


def record_stages(
    span: trace.Span,
    marks: Mapping[str, float],
    stages: tuple[tuple[str, str, str], ...],
    to_ns: Callable[[float], int],
) -> None:
    """Each mark as an event on `span`, and each stage whose two marks exist as a child span over
    exactly that interval — so a trace viewer draws the turn's timeline as it happened."""
    for name, at in sorted(marks.items(), key=lambda item: item[1]):
        span.add_event(name, timestamp=to_ns(at))
    parent = trace.set_span_in_context(span)
    for label, start, end in stages:
        if start in marks and end in marks and marks[end] >= marks[start]:
            stage = tracer.start_span(
                f"stage {label.removesuffix('_ms')}",
                context=parent,
                start_time=to_ns(marks[start]),
            )
            stage.end(end_time=to_ns(marks[end]))


def attributes(**values: Any) -> dict[str, Any]:
    """Span attributes without the Nones, which OpenTelemetry rejects."""
    return {key: value for key, value in values.items() if value is not None}
