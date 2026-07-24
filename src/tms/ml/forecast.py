"""Demand forecasting for transport orders."""
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class ForecastPoint:
    date: str
    predicted_orders: float
    confidence_lower: float | None = None
    confidence_upper: float | None = None


class OrderForecaster:
    """Forecast future order volume per origin/destination city."""

    def __init__(self, window_size: int = 14, alpha: float = 0.3):
        self.window_size = window_size
        self.alpha = alpha
        self._history: dict[str, list[float]] = defaultdict(list)

    def add_observation(self, key: str, count: float) -> None:
        hist = self._history[key]
        hist.append(count)
        if len(hist) > self.window_size:
            del hist[:len(hist) - self.window_size]

    def forecast(self, key: str, days: int = 7) -> list[ForecastPoint]:
        hist = self._history.get(key, [])
        if len(hist) < 2:
            return [ForecastPoint(date=(date.today() + timedelta(days=i)).isoformat(),
                                  predicted_orders=0.0) for i in range(1, days+1)]

        ema = sum(h * (self.alpha ** i) for i, h in enumerate(reversed(hist)))
        mean = sum(hist) / len(hist)
        variance = sum((x - mean)**2 for x in hist) / len(hist)
        std_dev = variance**0.5
        trend = (hist[-1] - hist[0]) / max(len(hist), 1)

        results = []
        today = date.today()
        for i in range(1, days + 1):
            pred = round(max((ema or mean) + trend * i, 0), 1)
            lower = round(pred - 1.96 * std_dev, 1) if std_dev else None
            upper = round(pred + 1.96 * std_dev, 1) if std_dev else None
            results.append(ForecastPoint(
                date=(today + timedelta(days=i)).isoformat(),
                predicted_orders=pred, confidence_lower=lower, confidence_upper=upper,
            ))
        return results


forecaster = OrderForecaster()
