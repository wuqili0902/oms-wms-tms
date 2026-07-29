from unittest.mock import MagicMock, patch

import pytest


class TestSafeImportOtel:
    def test_safe_import_otel_import_error(self):
        from src.core import tracing as t
        with patch.dict("sys.modules", {"opentelemetry": None}):
            result = t._safe_import_otel()
            assert result is False


class TestSetupTracing:
    def test_returns_early_when_otel_unavailable(self):
        from src.core import tracing as t
        with patch.object(t, "_otel_available", False):
            t.setup_tracing()

    def test_setup_tracing_skips_instrumentation_without_registered_apps(self):
        from src.core import tracing as t

        with (
            patch("opentelemetry.trace._TRACER_PROVIDER", None, create=True),
        ):
            t.setup_tracing()

    def test_setup_tracing_instruments_app(self):
        from src.core import tracing as t

        mock_handler = MagicMock()
        mock_app = MagicMock()
        mock_handler.app = mock_app

        mock_provider = MagicMock()
        mock_provider._instrumentors = {"test": mock_handler}

        from opentelemetry import trace as otel_trace

        with (
            patch("opentelemetry.sdk.trace.TracerProvider", return_value=mock_provider),
            patch("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor.instrument_app", return_value=None) as mock_inst,
            patch.object(otel_trace, "_TRACER_PROVIDER", mock_provider),
        ):
            t.setup_tracing()
            assert mock_inst.called
