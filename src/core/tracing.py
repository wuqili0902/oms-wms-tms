"""OpenTelemetry tracing setup for distributed tracing."""

import os


def _safe_import_otel():
    """Import OpenTelemetry if installed, otherwise return None."""
    try:
        from opentelemetry import trace  # noqa: F401
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (  # noqa: F401
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # noqa: F401
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource  # noqa: F401
        from opentelemetry.sdk.trace import TracerProvider  # noqa: F401
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # noqa: F401
        return True
    except ImportError as e:
        print(f"[otel] OpenTelemetry not available: {e}")
        return False


_otel_available = _safe_import_otel()

from src.config import settings  # noqa: E402  # imported after otel probe


def setup_tracing() -> None:
    """Initialize OpenTelemetry tracing.

    Configures a tracer provider with OTLP HTTP exporter and FastAPI instrumentation.
    Uses the same service name as defined in config (defaults to "oms-wms-tms").
    """
    if not _otel_available:
        return  # otel dependencies not installed

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

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
        except (ImportError, AttributeError, RuntimeError):
            pass

    trace.get_tracer(settings.app_name)
