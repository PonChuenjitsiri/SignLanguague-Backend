from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from app.database import get_database
from app.routers.sensor_data import PredictResponse, _build_predict_response
from app.services import sentence_buffer
from app.services.device_service import DeviceService
from app.services.model_manager import model_manager
from app.services.prediction_service import prediction_service
from app.services.prediction_stream import parse_raw_frames
from app.services.sentence_buffer import BufferedWord
from app.services.sign_language_service import SignLanguageService

router = APIRouter(
    prefix="/predict",
    tags=["Prediction"]
)

# โครงสร้าง Data ที่ Frontend ต้องส่งมา
class PredictRequest(BaseModel):
    # ให้รับ model_name ด้วย จะได้รู้ว่าต้องใช้สมองก้อนไหน (ใส่ default เผื่อไว้ได้)
    device_id: str 
    # รับ raw_data เป็น String ก้อนยาวๆ ตาม JSON ที่คุณส่งมา
    raw_data: str

@router.get("/models")
async def get_available_models():
    """ดึงรายชื่อโมเดลทั้งหมดที่มีใน MinIO (เอาไปทำ Dropdown ใน Frontend)"""
    models = model_manager.list_available_models()
    return {"available_models": models}

# ======================================================
# REST API Predict — จาก Device (ผูกโมเดลอัตโนมัติ)
# ======================================================
@router.post("/", response_model=PredictResponse)  # 👈 ใส่ response_model ด้วย
async def predict_gesture(payload: PredictRequest):
    """ทำนายท่าทางภาษามือ โดยดึงโมเดลที่ผูกกับ Device โดยอัตโนมัติ และบันทึกคำลง Buffer"""
    try:
        # 1. ค้นหา Device
        device = await DeviceService.get_by_id(payload.device_id)
        if not device:
            raise HTTPException(
                status_code=404, 
                detail=f"Device '{payload.device_id}' not found. Please register the device first."
            )
        
        assigned_model = device["model_name"]

        # 2. เช็คว่าโมเดลที่ผูกไว้มีอยู่จริงไหม
        available_models = model_manager.list_available_models()
        if assigned_model not in available_models:
            raise HTTPException(
                status_code=500,
                detail=f"The assigned model '{assigned_model}' for this device is missing."
            )

        # 3. แปลง String ดิบเป็น List 2D
        frames_2d = parse_raw_frames(payload.raw_data)
        if not frames_2d:
            raise HTTPException(
                status_code=400, 
                detail="No valid frames found. Each line needs exactly 22 numeric values."
            )

        # 4. ส่งไปทำนาย
        # สมมติว่า prediction_service.predict() ของคุณคืนค่า dict ที่มี "predicted_sign" และ "confidence"
        # (และอาจมี detail อื่นๆ)
        pred_result = prediction_service.predict(
            model_name=assigned_model, 
            raw_data=frames_2d  
        )
        
        if "error" in pred_result:
            raise HTTPException(status_code=400, detail=pred_result["error"])

        predicted_sign = pred_result["predicted_sign"]
        ensemble_conf = pred_result.get("confidence", 0.0) # ดึงค่าความมั่นใจมา (กันเหนียวถ้าไม่มีให้เป็น 0)

        # 5. ค้นหาข้อมูลคำแปลใน Database
        sign_entry = await SignLanguageService.find_by_label(predicted_sign)

        # 6. บันทึกคำลง Buffer
        word = BufferedWord(
            word=predicted_sign,
            confidence=ensemble_conf,
            titleThai=sign_entry.get("titleThai") if sign_entry else None,
            titleEng=sign_entry.get("titleEng") if sign_entry else None,
            label=sign_entry.get("label") if sign_entry else None,
        )
        buffer_state = await sentence_buffer.add_word(word)

        # 7. (Optional) เก็บ Log ลง Database เหมือนใน _predict_and_buffer
        db = get_database()
        await db["prediction_logs"].insert_one({
            "predicted_sign": predicted_sign,
            "confidence": ensemble_conf,
            "cnn_lstm_confidence": pred_result.get("cnn_conf", 0.0), # ถ้าใน service คุณไม่ได้คืนค่ามา ก็ใส่ 0 หรือลบออกได้
            "xgboost_confidence": pred_result.get("xgb_conf", 0.0),  # ถ้าใน service คุณไม่ได้คืนค่ามา ก็ใส่ 0 หรือลบออกได้
            "num_frames": len(frames_2d),
            "source": "device_" + payload.device_id, # ระบุ Source ให้ชัดเจนไปเลยว่ามาจาก Device ไหน
            "model_used": assigned_model, # เก็บชื่อโมเดลที่ใช้ลง Log ด้วย
            "created_at": datetime.utcnow(),
        })

        # 8. สร้าง dict กลางเพื่อส่งให้ _build_predict_response
        combined_result = {
            "predicted_sign": predicted_sign,
            "confidence": ensemble_conf,
            "sign_entry": sign_entry,
            "buffer_state": buffer_state,
        }

        # 9. คืนค่าผ่านฟังก์ชัน _build_predict_response
        return _build_predict_response(combined_result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))