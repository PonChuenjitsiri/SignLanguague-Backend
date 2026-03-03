from fastapi import APIRouter, HTTPException
from datetime import datetime

from app.schemas.sensor_data import (
    GesturePredictRequest,
    PredictBufferResponse,
    SentenceResponse,
    BufferWordInfo,
)
from app.services.prediction_service import PredictionService
from app.services.sign_language_service import SignLanguageService
from app.services.sentence_buffer import sentence_buffer, BufferedWord
from app.database import get_database

router = APIRouter(prefix="/api/sensor-data", tags=["Sensor Data & Prediction"])


@router.post("/predict", response_model=PredictBufferResponse)
async def predict_sign(request: GesturePredictRequest):
    """
    Receive a gesture from ESP32 → predict → buffer the word.

    The prediction is NOT returned as a final sentence immediately.
    Instead, the word is added to a sentence buffer.
    If no new gesture arrives within 5 seconds, the sentence is finalized.

    Use GET /sentence to retrieve the completed sentence.
    """
    if not PredictionService.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="ML models not loaded. Run 'python -m app.services.train_model' first.",
        )

    # Convert frames to 2D array
    frames_2d = [frame.to_flat_list() for frame in request.frames]

    try:
        predicted_sign, ensemble_conf, cnn_conf, xgb_conf = PredictionService.predict(frames_2d)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # Look up in DB for Thai title
    sign_entry = await SignLanguageService.find_by_title_eng(predicted_sign)

    # Build buffered word
    word = BufferedWord(
        word=predicted_sign,
        confidence=ensemble_conf,
        titleThai=sign_entry.get("titleThai") if sign_entry else None,
        titleEng=sign_entry.get("titleEng") if sign_entry else None,
    )

    # Add to sentence buffer (resets 5s timer)
    buffer_state = await sentence_buffer.add_word(word)

    # Log prediction
    db = get_database()
    await db["prediction_logs"].insert_one({
        "predicted_sign": predicted_sign,
        "confidence": ensemble_conf,
        "cnn_lstm_confidence": cnn_conf,
        "xgboost_confidence": xgb_conf,
        "num_frames": len(request.frames),
        "created_at": datetime.utcnow(),
    })

    return PredictBufferResponse(
        predicted_sign=predicted_sign,
        confidence=ensemble_conf,
        buffering=True,
        word_count=buffer_state["word_count"],
        current_words=[
            BufferWordInfo(**w) for w in buffer_state["current_words"]
        ],
        seconds_until_complete=buffer_state["seconds_until_complete"],
    )


@router.get("/sentence", response_model=SentenceResponse)
async def get_sentence():
    """
    Get the current sentence from the buffer.

    - If `complete: true` → sentence is finalized (5s idle passed), ready to display.
    - If `complete: false` → still buffering, more words may be coming.
    - If no words at all → returns 204 No Content.

    Frontend/client should poll this endpoint (e.g., every 1s) to check
    if the sentence is ready.
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
    """Clear the sentence buffer manually."""
    await sentence_buffer.clear()
    return {"message": "Sentence buffer cleared"}
