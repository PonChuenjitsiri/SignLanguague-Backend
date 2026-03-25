from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from app.services.model_manager import model_manager
from app.services.prediction_service import prediction_service

router = APIRouter(
    prefix="/predict",
    tags=["Prediction"]
)

# โครงสร้าง Data ที่ Frontend ต้องส่งมา
class PredictRequest(BaseModel):
    # ให้รับ model_name ด้วย จะได้รู้ว่าต้องใช้สมองก้อนไหน (ใส่ default เผื่อไว้ได้)
    model_name: str = "sign_language_model_v1" 
    # รับ raw_data เป็น String ก้อนยาวๆ ตาม JSON ที่คุณส่งมา
    raw_data: str

@router.get("/models")
async def get_available_models():
    """ดึงรายชื่อโมเดลทั้งหมดที่มีใน MinIO (เอาไปทำ Dropdown ใน Frontend)"""
    models = model_manager.list_available_models()
    return {"available_models": models}

@router.post("/")
async def predict_gesture(payload: PredictRequest):
    """ทำนายท่าทางภาษามือ"""
    try:
        # เช็คก่อนว่าโมเดลนี้มีอยู่จริงไหม
        available_models = model_manager.list_available_models()
        if payload.model_name not in available_models:
            raise HTTPException(status_code=404, detail=f"Model '{payload.model_name}' not found.")

        # ส่งให้ PredictionService ทำนาย
        result = prediction_service.predict(
            model_name=payload.model_name,
            raw_data=payload.raw_data  # 👈 เปลี่ยนตรงนี้เป็น raw_data
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))