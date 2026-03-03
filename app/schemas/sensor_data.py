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


class GesturePredictRequest(BaseModel):
    """Request body for gesture prediction — a full gesture as a sequence of frames."""

    frames: List[SensorFrame] = Field(
        ...,
        description="Sequence of sensor frames representing one gesture (min 5 frames)",
        min_length=5,
    )


# --- Prediction Response (single gesture) ---


class PredictionResponse(BaseModel):
    """Response body for gesture prediction."""

    predicted_sign: str = Field(..., description="Predicted sign language label")
    confidence: float = Field(..., description="Ensemble prediction confidence (0-1)")
    cnn_lstm_confidence: float = Field(..., description="CNN-LSTM model confidence")
    xgboost_confidence: float = Field(..., description="XGBoost model confidence")
    titleThai: Optional[str] = Field(None, description="Thai title if found in DB")
    titleEng: Optional[str] = Field(None, description="English title if found in DB")
    signMethod: Optional[str] = Field(None, description="Sign method description")


# --- Sentence Buffer Responses ---


class BufferWordInfo(BaseModel):
    """A single word in the sentence buffer."""

    word: str
    titleThai: Optional[str] = None
    titleEng: Optional[str] = None
    confidence: float


class PredictBufferResponse(BaseModel):
    """Response from POST /predict — word buffered, waiting for sentence completion."""

    predicted_sign: str = Field(..., description="Just-predicted word")
    confidence: float
    buffering: bool = Field(True, description="True = still accumulating words")
    word_count: int = Field(..., description="Total words in current buffer")
    current_words: List[BufferWordInfo]
    seconds_until_complete: float = Field(5.0, description="Idle timeout in seconds")


class SentenceResponse(BaseModel):
    """Response from GET /sentence — the accumulated sentence."""

    complete: bool = Field(..., description="True = sentence is finalized (5s idle passed)")
    sentence: str = Field(..., description="Accumulated sentence text")
    words: List[BufferWordInfo]
    word_count: int
