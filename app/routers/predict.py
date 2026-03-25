from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List

from app.services.device_service import DeviceService
from app.services.model_manager import model_manager
from app.services.prediction_service import prediction_service
from app.services.prediction_stream import parse_raw_frames

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

@router.post("/")
async def predict_gesture(payload: PredictRequest):
    """ทำนายท่าทางภาษามือ โดยดึงโมเดลที่ผูกกับ Device โดยอัตโนมัติ"""
    try:
        # 1. ค้นหา Device ใน Database ด้วย device_id ที่ส่งมา
        device = await DeviceService.get_by_id(payload.device_id)
        if not device:
            raise HTTPException(
                status_code=404, 
                detail=f"Device '{payload.device_id}' not found. Please register the device first."
            )
        
        # ดึงชื่อโมเดลออกมาจากข้อมูล Device
        assigned_model = device["model_name"]

        # 2. เช็คว่าโมเดลที่ผูกไว้ มันมีไฟล์อยู่จริงไหม (เผื่อไฟล์โมเดลหาย)
        available_models = model_manager.list_available_models()
        if assigned_model not in available_models:
            raise HTTPException(
                status_code=500, # ใช้ 500 เพราะเป็นปัญหาที่ฝั่งเซิร์ฟเวอร์ (โมเดลหาย)
                detail=f"The assigned model '{assigned_model}' for this device is missing."
            )

        # 3. แปลง String ดิบเป็น List 2D ด้วยฟังก์ชันของคุณ
        frames_2d = parse_raw_frames(payload.raw_data)
        if not frames_2d:
            raise HTTPException(
                status_code=400, 
                detail="No valid frames found. Each line needs exactly 22 numeric values."
            )

        # 4. ส่งข้อมูลที่สะอาดแล้วให้ PredictionService ทำนาย
        # 👈 ใช้ assigned_model ที่ได้จาก Database โยนเข้า service
        result = prediction_service.predict(
            model_name=assigned_model, 
            raw_data=frames_2d  
        )
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        # (Optional) แนบชื่อ device_id กลับไปใน response ด้วยเผื่อเอาไปใช้แสดงผล
        result["device_id"] = payload.device_id

        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))