from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class SensorDataModel(BaseModel):
    """MongoDB document model for ESP32 sensor readings (dual-hand: 22 features per frame)."""

    # Left hand
    left_flex: List[float] = Field(
        ..., description="Left hand flex sensor readings (F1-F5)", min_length=5, max_length=5
    )
    left_accel: List[float] = Field(
        ..., description="Left hand accelerometer [x, y, z]", min_length=3, max_length=3
    )
    left_gyro: List[float] = Field(
        ..., description="Left hand gyroscope [x, y, z]", min_length=3, max_length=3
    )

    # Right hand
    right_flex: List[float] = Field(
        ..., description="Right hand flex sensor readings (F1-F5)", min_length=5, max_length=5
    )
    right_accel: List[float] = Field(
        ..., description="Right hand accelerometer [x, y, z]", min_length=3, max_length=3
    )
    right_gyro: List[float] = Field(
        ..., description="Right hand gyroscope [x, y, z]", min_length=3, max_length=3
    )

    predicted_sign: str = Field(default="", description="Predicted sign label")
    confidence: float = Field(default=0.0, description="Prediction confidence score")
    created_at: datetime = Field(default_factory=datetime.utcnow)
