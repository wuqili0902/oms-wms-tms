"""Simple demand forecasting using moving average.

Provides basic time-series forecasting for order volume prediction.
In production, this would be replaced with a proper ML pipeline
(e.g., Prophet, ARIMA, or a custom neural network).
"""
from collections import deque
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional


@dataclass
class ForecastResult:
    """Single forecast data point."""

    date: str
    predicted_orders: float
    confidence_lower: Optional[float] = None
    confidence_upper: Optional[float] = None


class DemandForecaster:
    """Simple exponential moving average forecaster.

    Maintains a window of historical daily order counts and produces
    short-term forecasts (1-7 days ahead).
    """

    def __init__(self, window_size: int = 14, alpha: float = 0.3):
        self.window_size = window_size
        self.alpha = alpha
        self._history: deque[float] = deque(maxlen=window_size)
        self._ema: Optional[float] = None

    def add_observation(self, orders: float) -> None:
        """Record a daily order count observation."""
        self._history.append(orders)
        if self._ema is None:
            self._ema = orders
        else:
            self._ema = self.alpha * orders + (1 - self.alpha) * self._ema

    @property
    def current_forecast(self) -> Optional[float]:
        """Current EMA forecast for the next period."""
        return self._ema

    @property
    def history(self) -> list[float]:
        """Return the current history window."""
        return list(self._history)

    def forecast(self, days: int = 1) -> list[ForecastResult]:
        """Generate forecasts for the next N days.

        Uses EMA + simple trend from the last 3 observations.
        """
        history = self.history
        if len(history) < 2:
            # Not enough data — return flat forecast
            val = self._ema or 0.0
            today = date.today()
            return [
                ForecastResult(
                    date=(today + timedelta(days=i)).isoformat(),
                    predicted_orders=round(val, 1),
                )
                for i in range(1, days + 1)
            ]

        # Calculate simple trend from recent observations
        recent = history[-3:] if len(history) >= 3 else history
        if len(recent) >= 2:
            trend = (recent[-1] - recent[0]) / len(recent)
        else:
            trend = 0.0

        # Calculate standard deviation for confidence intervals
        mean = sum(history) / len(history)
        variance = sum((x - mean) ** 2 for x in history) / len(history)
        std_dev = variance ** 0.5

        today = date.today()
        results = []
        for i in range(1, days + 1):
            predicted = round((self._ema or mean) + trend * i, 1)
            results.append(ForecastResult(
                date=(today + timedelta(days=i)).isoformat(),
                predicted_orders=predicted,
                confidence_lower=round(predicted - 1.96 * std_dev, 1),
                confidence_upper=round(predicted + 1.96 * std_dev, 1),
            ))
        return results

    def reset(self) -> None:
        """Reset the forecaster state."""
        self._history.clear()
        self._ema = None


# Singleton forecaster for the application
forecaster = DemandForecaster()
