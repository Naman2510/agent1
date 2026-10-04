"""Tracing (app/core/telemetry.py): off unless configured, and when configured, real spans reach a
real OTLP endpoint."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.core.config import Settings
from app.core.middleware import route_template
from app.core.telemetry import SERVICE_NAME, attributes, build_provider, epoch_ns, record_stages


def test_tracing_is_off_unless_configured(settings: Settings) -> None:
    assert settings.otel_exporter == "none"
    assert build_provider(settings) is None


class _Collector(BaseHTTPRequestHandler):
    """The smallest OTLP/HTTP trace receiver: keeps each export request's body."""

    bodies: ClassVar[list[bytes]] = []

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).bodies.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return None


@pytest.fixture
def collector() -> Iterator[str]:
    _Collector.bodies = []
    server = HTTPServer(("127.0.0.1", 0), _Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1/traces"
    finally:
        server.shutdown()


def test_spans_reach_an_otlp_collector(settings: Settings, collector: str) -> None:
    configured = settings.model_copy(update={"otel_exporter": "otlp", "otel_endpoint": collector})
    provider = build_provider(configured)
    assert provider is not None
    provider.get_tracer("probe").start_span("probe", attributes={"turn.id": 3}).end()
    assert provider.force_flush(timeout_millis=5000)
    provider.shutdown()

    assert _Collector.bodies, "the exporter posted nothing"
    request = ExportTraceServiceRequest()
    request.ParseFromString(_Collector.bodies[0])
    [resource_spans] = request.resource_spans
    resource = {a.key: a.value.string_value for a in resource_spans.resource.attributes}
    assert resource["service.name"] == SERVICE_NAME
    assert resource["deployment.environment"] == "test"
    [span] = [s for scope in resource_spans.scope_spans for s in scope.spans]
    assert span.name == "probe"


def test_monotonic_marks_become_wall_clock_times_that_keep_their_spacing() -> None:
    now = [1000.0]
    to_ns = epoch_ns(lambda: now[0])
    assert to_ns(1000.25) - to_ns(1000.0) == 250_000_000


def test_stages_become_events_and_child_spans_over_their_exact_interval() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("t")

    import app.core.telemetry as telemetry

    original = telemetry.tracer
    telemetry.tracer = tracer  # type: ignore[assignment]
    try:
        to_ns = epoch_ns(lambda: 10.0)
        turn = tracer.start_span("voice.turn", start_time=to_ns(9.0))
        marks = {"speech_end": 9.0, "turn_end": 9.5, "first_audio_played": 9.9}
        stages = (
            ("turn_end_ms", "speech_end", "turn_end"),
            ("ttfa_ms", "speech_end", "first_audio_played"),
            ("tts_ttfb_ms", "first_sentence", "tts_first_byte"),  # never marked: no span
        )
        record_stages(turn, marks, stages, to_ns)
        turn.end(end_time=to_ns(10.0))
    finally:
        telemetry.tracer = original

    finished = {s.name: s for s in exporter.get_finished_spans()}
    assert set(finished) == {"voice.turn", "stage turn_end", "stage ttfa"}
    assert [e.name for e in finished["voice.turn"].events] == [
        "speech_end",
        "turn_end",
        "first_audio_played",
    ]
    ttfa = finished["stage ttfa"]
    assert ttfa.parent is not None
    assert ttfa.parent.span_id == finished["voice.turn"].context.span_id
    assert ttfa.end_time is not None and ttfa.start_time is not None
    assert ttfa.end_time - ttfa.start_time == 900_000_000


def test_none_is_left_out_of_attributes() -> None:
    assert attributes(a=1, b=None, c="x") == {"a": 1, "c": "x"}


class _Route:
    path_format = "/sessions/{session_id}"


def test_a_route_template_keeps_the_prefix_it_was_included_under() -> None:
    scope = {"route": _Route(), "path_params": {"session_id": "abc"}, "path": "/v1/sessions/abc"}
    assert route_template(scope) == "/v1/sessions/{session_id}"


def test_a_route_template_it_cannot_join_safely_is_the_leaf_never_a_wrong_join() -> None:
    # A parameter that does not print as it was written (an upper-case UUID, say).
    scope = {"route": _Route(), "path_params": {"session_id": "abc"}, "path": "/v1/sessions/ABC"}
    assert route_template(scope) == "/sessions/{session_id}"
    assert route_template({"path": "/nowhere"}) is None
