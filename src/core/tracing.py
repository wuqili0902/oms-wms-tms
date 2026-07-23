"""OpenTelemetry tracing setup for distributed tracing."""

import os
from opentelemetry import trace
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource, SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

from src.config import settings


def setup_tracing() -> None:
    """Initialize OpenTelemetry tracing.

    Configures a tracer provider with OTLP HTTP exporter and FastAPI instrumentation.
    Uses the same service name as defined in config (defaults to "oms-wms-tms").
    """
    resource = Resource.create({SERVICE_NAME: settings.app_name})
    provider = TracerProvider(resource=resource)

    # Configure OTLP endpoint based on environment
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", settings.otlp_endpoint or "http://localhost:4318/v1/traces")

    exporter = OTLPSpanExporter(endpoint=otlp_endpoint, timeout=5)
    processor = BatchSpanProcessor(exporter)
    provider.add_span_processor(processor)

    trace.set_tracer_provider(provider)

    # Gracefully attempt to instrument any globally-registered FastAPI app.
    registered_apps = getattr(trace, "_TRACER_PROVIDER", None)
    if registered_apps is not None:
        try:
            for name, handlers in registered_apps._instrumentors.items():  # type: ignore[attr-defined]
                app = handlers.app
                if hasattr(app, "build_middleware_stack"):
                    FastAPIInstrumentor.instrument_app(app)
                    break
        except Exception:
            pass

    tracer = trace.get_tracer(settings.app_name)
