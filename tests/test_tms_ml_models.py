"""Tests for tms/ml/models.py — Pydantic schemas."""
import pytest

from src.tms.ml.models import (
    ForecastPoint,
    ForecastPredictRequest,
    ForecastPredictResponse,
    ForecastTrainRequest,
    ForecastTrainResponse,
)


class TestForecastTrainRequest:
    def test_valid(self):
        r = ForecastTrainRequest(key="BJ:SH", data=[1.0, 2.0, 3.0])
        assert r.key == "BJ:SH"
        assert r.period == "monthly"

    def test_quarterly(self):
        r = ForecastTrainRequest(key="k", data=[1.0, 2.0], period="quarterly")
        assert r.period == "quarterly"

    def test_min_data_length(self):
        with pytest.raises(Exception):
            ForecastTrainRequest(key="k", data=[1.0])

    def test_invalid_period(self):
        with pytest.raises(Exception):
            ForecastTrainRequest(key="k", data=[1.0, 2.0], period="daily")


class TestForecastTrainResponse:
    def test_valid(self):
        r = ForecastTrainResponse(model_id="m1", key="k", trained_at="2026-01-01")
        assert r.model_id == "m1"

    def test_with_metrics(self):
        r = ForecastTrainResponse(
            model_id="m1", key="k", trained_at="2026-01-01",
            metrics={"mae": 0.5, "r2": 0.9},
        )
        assert r.metrics["r2"] == 0.9


class TestForecastPredictRequest:
    def test_valid(self):
        r = ForecastPredictRequest(model_id="m1")
        assert r.periods == 6
        assert r.period_type == "monthly"

    def test_min_periods(self):
        r = ForecastPredictRequest(model_id="m1", periods=1)
        assert r.periods == 1

    def test_zero_periods_invalid(self):
        with pytest.raises(Exception):
            ForecastPredictRequest(model_id="m1", periods=0)


class TestForecastPoint:
    def test_valid(self):
        p = ForecastPoint(date="2026-01-01", predicted_orders=42.0)
        assert p.confidence_lower is None
        assert p.confidence_upper is None

    def test_with_confidence(self):
        p = ForecastPoint(
            date="2026-01-01", predicted_orders=42.0,
            confidence_lower=35.0, confidence_upper=49.0,
        )
        assert p.confidence_lower == 35.0


class TestForecastPredictResponse:
    def test_valid(self):
        r = ForecastPredictResponse(
            model_id="m1", key="k", period_type="monthly", periods=3,
            points=[ForecastPoint(date="2026-01-01", predicted_orders=10.0)],
        )
        assert len(r.points) == 1

    def test_empty_points(self):
        r = ForecastPredictResponse(
            model_id="m1", key="k", period_type="monthly", periods=0, points=[],
        )
        assert r.points == []
