from fastapi import APIRouter, HTTPException
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional

from app.schemas.sensor_data import (
    GesturePredictRequest,
    RawPredictRequest,
    PredictBufferResponse,
    SentenceResponse,
    BufferWordInfo,
)
from app.services.prediction_service import PredictionService
from app.services.sign_language_service import SignLanguageService
from app.services.sentence_buffer import sentence_buffer, BufferedWord
from app.services.prediction_stream import parse_raw_frames
from app.database import get_database

router = APIRouter(prefix="/api/sensor-data", tags=["Sensor Data & Prediction"])


# ======================================================
# Glove Signal — ESP32 sends status updates via REST API
# ======================================================
class GloveSignalRequest(BaseModel):
    msg: str = Field(..., description="Signal from ESP32: START_SIGNAL or STOP_SIGNAL")


class GloveState:
    """Tracks the glove's current state."""
    def __init__(self):
        self.is_recording = False
        self.last_signal: Optional[str] = None
        self.last_signal_time: Optional[datetime] = None

    def update(self, signal: str):
        self.last_signal = signal
        self.last_signal_time = datetime.utcnow()
        if signal == "START_SIGNAL":
            self.is_recording = True
        elif signal == "STOP_SIGNAL":
            self.is_recording = False

    def get_status(self):
        return {
            "is_recording": self.is_recording,
            "last_signal": self.last_signal,
            "last_signal_time": str(self.last_signal_time) if self.last_signal_time else None,
        }


glove_state = GloveState()


@router.post("/signal")
async def receive_signal(request: GloveSignalRequest):
    """
    Receive signal from ESP32 glove.

    - `{"msg": "START_SIGNAL"}` → Glove started recording gesture
    - `{"msg": "STOP_SIGNAL"}` → Glove stopped recording, data coming next

    ESP32 calls this to notify the server about glove state.
    """
    if request.msg not in ("START_SIGNAL", "STOP_SIGNAL"):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown signal: {request.msg}. Use START_SIGNAL or STOP_SIGNAL.",
        )

    glove_state.update(request.msg)

    return {
        "message": f"Signal received: {request.msg}",
        "glove": glove_state.get_status(),
    }


@router.get("/signal/status")
async def get_glove_status():
    """Get the current glove state."""
    return glove_state.get_status()



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
        "buffer_state": buffer_state,
        "sign_entry": sign_entry,
    }


# ======================================================
# REST API Predict — JSON (structured)
# ======================================================
@router.post("/predict", response_model=PredictBufferResponse)
async def predict_json(request: GesturePredictRequest):
    """
    Predict from structured JSON.

    ESP32 sends frames as JSON → predict → buffer word.
    """
    frames_2d = [frame.to_flat_list() for frame in request.frames]
    result = await _predict_and_buffer(frames_2d, source="api_json")

    return PredictBufferResponse(
        predicted_sign=result["predicted_sign"],
        confidence=result["confidence"],
        buffering=True,
        word_count=result["buffer_state"]["word_count"],
        current_words=[BufferWordInfo(**w) for w in result["buffer_state"]["current_words"]],
        seconds_until_complete=result["buffer_state"]["seconds_until_complete"],
    )


# ======================================================
# REST API Predict — Raw text (same format as serial port)
# ======================================================
@router.post("/predict/raw", response_model=PredictBufferResponse)
async def predict_raw(request: RawPredictRequest):
    """
    Predict from raw ESP32 data (same format as serial port).

    Send the data block with S/E markers:
    ```
    S 0 0 0 0 0 0 0 0 0 0 0 1404 1431 409 584 3 0.05 0.85 -0.43 -9.64 -0.30 47.91
    0 0 0 0 0 0 0 0 0 0 0 1375 604 412 592 3 -0.09 0.87 -0.35 -22.21 -8.48 -2.07
    ...
    0 0 0 0 0 0 0 0 0 0 0 1770 2112 410 522 4 0.08 0.94 -0.44 -5.12 0.67 -9.94 E
    ```
    """
    frames_2d = parse_raw_frames(request.raw_data)

    if not frames_2d:
        raise HTTPException(
            status_code=400,
            detail="No valid frames found. Each line needs exactly 22 numeric values.",
        )

    result = await _predict_and_buffer(frames_2d, source="api_raw")

    return PredictBufferResponse(
        predicted_sign=result["predicted_sign"],
        confidence=result["confidence"],
        buffering=True,
        word_count=result["buffer_state"]["word_count"],
        current_words=[BufferWordInfo(**w) for w in result["buffer_state"]["current_words"]],
        seconds_until_complete=result["buffer_state"]["seconds_until_complete"],
    )






# ======================================================
# Sentence Buffer (shared by all predict methods)
# ======================================================
@router.get("/sentence", response_model=SentenceResponse)
async def get_sentence():
    """
    Get accumulated sentence.

    - `complete: true` → finalized (5s idle), display it.
    - `complete: false` → still buffering.
    - 204 → empty buffer.

    Poll every ~1s to check.
    """
    result = await sentence_buffer.get_sentence()
    if result is None:
        raise HTTPException(status_code=204, detail="No words in buffer")

    return SentenceResponse(
        complete=result["complete"],
        sentence=result["sentence"],
        words=[BufferWordInfo(**w) for w in result["words"]],
        word_count=result["word_count"],
    )


@router.delete("/sentence")
async def clear_sentence():
    """Clear the sentence buffer."""
    await sentence_buffer.clear()
    return {"message": "Sentence buffer cleared"}
