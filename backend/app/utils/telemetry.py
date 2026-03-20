"""OpenTelemetry bootstrap for Morai.

Opt-in observability — set OTEL_ENABLED=true to activate tracing.
When disabled (default), all calls return no-op tracers with zero overhead.

Usage:
    from backend.app.utils.telemetry import get_tracer
    tracer = get_tracer("my_module")
    with tracer.start_as_current_span("operation") as span:
        span.set_attribute("key", "value")
        ...
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opentelemetry.trace import Tracer

_initialized = False


def init_telemetry(service_name: str = "morai") -> None:
    """Initialise OTEL SDK if OTEL_ENABLED=true.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    if os.environ.get("OTEL_ENABLED", "false").lower() != "true":
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        resource = Resource(attributes={SERVICE_NAME: service_name})
        provider = TracerProvider(resource=resource)

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

    except ImportError:
        # OTEL SDK not installed — silently degrade
        pass


def get_tracer(name: str) -> "Tracer":
    """Return a tracer for *name*. Returns a no-op tracer when OTEL is disabled."""
    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except ImportError:
        from unittest.mock import MagicMock
        return MagicMock()
