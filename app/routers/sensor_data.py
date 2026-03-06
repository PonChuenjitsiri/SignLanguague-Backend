from fastapi import APIRouter, HTTPException
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List

from app.schemas.sensor_data import (
    GesturePredictRequest,
    RawPredictRequest,
)
from app.services.prediction_service import PredictionService
from app.services.sign_language_service import SignLanguageService
from app.services.sentence_buffer import sentence_buffer, BufferedWord
from app.services.prediction_stream import parse_raw_frames
from app.database import get_database

router = APIRouter(prefix="/api/sensor-data", tags=["Sensor Data & Prediction"])


# ======================================================
# Schemas (inline — specific to this router)
# ======================================================
class BufferWordInfo(BaseModel):
    word: str
    titleThai: Optional[str] = None
    titleEng: Optional[str] = None
    label: Optional[str] = None
    confidence: float


class PredictResponse(BaseModel):
    """Response from /predict — word predicted and added to buffer."""
    predicted_sign: str
    confidence: float
    titleThai: Optional[str] = None
    titleEng: Optional[str] = None
    label: Optional[str] = None
    recording: bool
    word_count: int
    current_words: List[BufferWordInfo]


# ======================================================
# Shared: predict → buffer → log
# ======================================================
async def _predict_and_buffer(frames_2d: list, source: str = "api") -> dict:
    """Common logic: predict gesture, buffer word, log to DB."""
    if not PredictionService.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="ML models not loaded. Run 'python -m app.services.train_model' first.",
        )

    if len(frames_2d) < 5:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 5 frames, got {len(frames_2d)}",
        )

    try:
        predicted_sign, ensemble_conf, cnn_conf, xgb_conf = PredictionService.predict(frames_2d)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Look up by label (handles variants like no_right → no)
    sign_entry = await SignLanguageService.find_by_label(predicted_sign)

    # Buffer the word
    word = BufferedWord(
        word=predicted_sign,
        confidence=ensemble_conf,
        titleThai=sign_entry.get("titleThai") if sign_entry else None,
        titleEng=sign_entry.get("titleEng") if sign_entry else None,
        label=sign_entry.get("label") if sign_entry else None,
    )
    buffer_state = await sentence_buffer.add_word(word)

    # Log prediction
    db = get_database()
    await db["prediction_logs"].insert_one({
        "predicted_sign": predicted_sign,
        "confidence": ensemble_conf,
        "cnn_lstm_confidence": cnn_conf,
        "xgboost_confidence": xgb_conf,
        "num_frames": len(frames_2d),
        "source": source,
        "created_at": datetime.utcnow(),
    })

    return {
        "predicted_sign": predicted_sign,
        "confidence": ensemble_conf,
        "sign_entry": sign_entry,
        "buffer_state": buffer_state,
    }


# ======================================================
# REST API Predict — JSON (structured)
# ======================================================
@router.post("/predict", response_model=PredictResponse)
async def predict_json(request: GesturePredictRequest):
    """
    Predict from structured JSON frames → add word to buffer.
    """
    frames_2d = [frame.to_flat_list() for frame in request.frames]
    result = await _predict_and_buffer(frames_2d, source="api_json")
    return _build_predict_response(result)


# ======================================================
# REST API Predict — Raw text (ESP32 format)
# ======================================================
@router.post("/predict/raw", response_model=PredictResponse)
async def predict_raw(request: RawPredictRequest):
    """
    Predict from raw ESP32 data (S ... E format) → add word to buffer.

    ESP32 sends raw data block:
    ```
    S 60 2824 1067 4 2 0.03 0.02 -1.01 ... 2.13
    60 2824 1067 ...
    60 2824 1067 ... 0.67 E
    ```
    """
    frames_2d = parse_raw_frames(request.raw_data)

    if not frames_2d:
        raise HTTPException(
            status_code=400,
            detail="No valid frames found. Each line needs exactly 22 numeric values.",
        )

    result = await _predict_and_buffer(frames_2d, source="api_raw")
    return _build_predict_response(result)


def _build_predict_response(result: dict) -> PredictResponse:
    """Build a PredictResponse from _predict_and_buffer result."""
    sign = result.get("sign_entry") or {}
    buf = result["buffer_state"]
    return PredictResponse(
        predicted_sign=result["predicted_sign"],
        confidence=result["confidence"],
        titleThai=sign.get("titleThai"),
        titleEng=sign.get("titleEng"),
        label=sign.get("label"),
        recording=buf["recording"],
        word_count=buf["word_count"],
        current_words=[BufferWordInfo(**w) for w in buf["current_words"]],
    )
