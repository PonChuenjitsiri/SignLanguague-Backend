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
async def _predict_and_buffer(frames_2d: list, source: str = "api", model_name: str = None) -> dict:
    """Common logic: predict gesture, buffer word, log to DB."""

    if len(frames_2d) < 5:
        raise HTTPException(
            status_code=400,
            detail=f"Need at least 5 frames, got {len(frames_2d)}",
        )

    try:
        # 🌟 รับค่ามาก้อนเดียวก่อน อย่าเพิ่ง Unpack (แยกตัวแปร) เพื่อกันปัญหาได้ชื่อ Key มาแทน
        predict_output = PredictionService().predict(
            model_name=model_name, 
            raw_data=frames_2d
        )

        # 🌟 เช็คว่าถ้าออกมาเป็น Dictionary ให้ใช้ .get() เพื่อดึง "ค่า (Value)" จริงๆ ออกมา
        if isinstance(predict_output, dict):
            predicted_sign = predict_output.get("prediction") or predict_output.get("predicted_sign")
            ensemble_conf = float(predict_output.get("confidence", 0.0))
            cnn_conf = float(predict_output.get("cnn_conf", 0.0))
            xgb_conf = float(predict_output.get("xgb_conf", 0.0))
        else:
            # แต่ถ้าคุณแก้ให้มัน Return เป็น Tuple (ค่าเรียงกัน 4 ตัว) ไปแล้ว ก็ให้ Unpack ได้เลย
            predicted_sign, ensemble_conf, cnn_conf, xgb_conf = predict_output

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        # 🚨 ดัก Error อื่นๆ
        print(f"🔥 DEBUG PREDICT ERROR: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Prediction System Error: {str(e)}")

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
        "model_used": model_name or "default_model", 
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
    
    # 🌟 สร้างลิสต์เปล่ามารอรับข้อมูลที่ผ่านการคลีนแล้ว
    safe_current_words = []
    
    for w in buf.get("current_words", []):
        # 1. เช็คว่าเป็นอะไร: ถ้าเป็น Dict อยู่แล้วเอามาใช้ได้เลย แต่ถ้าเป็น Object ให้แปลงก่อน
        if isinstance(w, dict):
            w_dict = w.copy()
        elif hasattr(w, "model_dump"):
            w_dict = w.model_dump()
        else:
            w_dict = w.dict()
            
        # 2. แก้ปัญหาตัวเลข confidence กลายเป็น String (ต้นเหตุของ Error แรกสุด)
        conf_val = w_dict.get("confidence", 0.0)
        try:
            w_dict["confidence"] = float(conf_val)
        except (ValueError, TypeError):
            w_dict["confidence"] = 0.0 # ถ้ามันแปลงเป็นเลขไม่ได้จริงๆ บังคับเป็น 0 ซะเลย
            
        # 3. แพ็กใส่ Pydantic Model แบบสวยๆ
        safe_current_words.append(BufferWordInfo(**w_dict))

    return PredictResponse(
        predicted_sign=result["predicted_sign"],
        confidence=result["confidence"],
        titleThai=sign.get("titleThai"),
        titleEng=sign.get("titleEng"),
        label=sign.get("label"),
        recording=buf["recording"],
        word_count=buf["word_count"],
        current_words=safe_current_words, # 👈 ใส่ลิสต์ที่เราคลีนเรียบร้อยแล้ว
    )
