from pydantic import BaseModel, Field
from typing import List, Optional


class SensorFrame(BaseModel):
    """A single frame of sensor data from ESP32 (22 values per frame)."""

    # Left hand - 11 values
    left_flex: List[float] = Field(
        ..., description="Left hand flex sensors [F1, F2, F3, F4, F5]",
        min_length=5, max_length=5,
        json_schema_extra={"example": [0.0, 0.0, 0.0, 116.0, 0.0]},
    )
    left_accel: List[float] = Field(
        ..., description="Left hand accelerometer [x, y, z]",
        min_length=3, max_length=3,
        json_schema_extra={"example": [-0.5, 0.86, -0.42]},
    )
    left_gyro: List[float] = Field(
        ..., description="Left hand gyroscope [x, y, z]",
        min_length=3, max_length=3,
        json_schema_extra={"example": [0.42, 9.88, 1.83]},
    )

    # Right hand - 11 values
    right_flex: List[float] = Field(
        ..., description="Right hand flex sensors [F1, F2, F3, F4, F5]",
        min_length=5, max_length=5,
        json_schema_extra={"example": [760.0, 0.0, 0.0, 0.0, 0.0]},
    )
    right_accel: List[float] = Field(
        ..., description="Right hand accelerometer [x, y, z]",
        min_length=3, max_length=3,
        json_schema_extra={"example": [-0.07, -0.67, -0.7]},
    )
    right_gyro: List[float] = Field(
        ..., description="Right hand gyroscope [x, y, z]",
        min_length=3, max_length=3,
        json_schema_extra={"example": [10.92, -14.4, -0.85]},
    )

    def to_flat_list(self) -> List[float]:
        """Convert frame to flat 22-value list matching CSV column order."""
        return (
            self.left_flex + self.left_accel + self.left_gyro
            + self.right_flex + self.right_accel + self.right_gyro
        )


# --- JSON Predict Request ---

class GesturePredictRequest(BaseModel):
    """Predict request with structured JSON frames."""
    frames: List[SensorFrame] = Field(
        ...,
        description="Sequence of sensor frames (min 5 frames)",
        min_length=5,
    )


# --- Raw Text Predict Request ---

class RawPredictRequest(BaseModel):
    """Predict request with raw ESP32 text data (S ... E format)."""
    raw_data: str = Field(
        ...,
        description="Raw data block from ESP32, lines of 22 space-separated values with S/E markers",
        json_schema_extra={
            "example": "S 0 0 0 0 0 0 0 0 0 0 0 1404 1431 409 584 3 0.05 0.85 -0.43 -9.64 -0.30 47.91\n0 0 0 0 0 0 0 0 0 0 0 1375 604 412 592 3 -0.09 0.87 -0.35 -22.21 -8.48 -2.07\n0 0 0 0 0 0 0 0 0 0 0 1770 2112 410 522 4 0.08 0.94 -0.44 -5.12 0.67 -9.94 E"
        },
    )


# --- Response Schemas ---

class PredictionResponse(BaseModel):
    """Single gesture prediction response."""
    predicted_sign: str = Field(..., description="Predicted sign language label")
    confidence: float = Field(..., description="Ensemble confidence (0-1)")
    cnn_lstm_confidence: float = Field(..., description="CNN-LSTM confidence")
    xgboost_confidence: float = Field(..., description="XGBoost confidence")
    titleThai: Optional[str] = Field(None, description="Thai title if found in DB")
    titleEng: Optional[str] = Field(None, description="English title if found in DB")
    signMethod: Optional[str] = Field(None, description="Sign method description")


class BufferWordInfo(BaseModel):
    """A single word in the sentence buffer."""
    word: str
    titleThai: Optional[str] = None
    titleEng: Optional[str] = None
    confidence: float


class PredictBufferResponse(BaseModel):
    """Response from predict — word buffered, sentence accumulating."""
    predicted_sign: str
    confidence: float
    buffering: bool = True
    word_count: int
    current_words: List[BufferWordInfo]
    seconds_until_complete: float = 5.0


class SentenceResponse(BaseModel):
    """Accumulated sentence response."""
    complete: bool = Field(..., description="True = finalized (5s idle)")
    sentence: str
    words: List[BufferWordInfo]
    word_count: int
