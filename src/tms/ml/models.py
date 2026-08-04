"""ML models for forecast API."""
from typing import Any

from pydantic import BaseModel, Field


class ForecastTrainRequest(BaseModel):
    """请求体：训练时间序列模型。"""
    key: str = Field(..., description="唯一标识符（如 origin_city:dest_city）")
    data: list[float] = Field(..., min_length=2)
    period: str = Field(default="monthly", pattern=r"^(monthly|quarterly)$")


class ForecastTrainResponse(BaseModel):
    """响应：模型训练成功。"""
    model_id: str
    key: str
    trained_at: str
    metrics: dict[str, Any] | None = None


class ForecastPredictRequest(BaseModel):
    """请求体：预测未来值。"""
    model_id: str
    periods: int = Field(default=6, ge=1)
    period_type: str | None = Field(default="monthly")  # "monthly" | "quarterly"


class ForecastPoint(BaseModel):
    """单个预测点。"""
    date: str  # ISO date string
    predicted_orders: float
    confidence_lower: float | None = None
    confidence_upper: float | None = None


class ForecastPredictResponse(BaseModel):
    """响应：预测结果列表。"""
    model_id: str
    key: str
    period_type: str
    periods: int
    points: list[ForecastPoint]
