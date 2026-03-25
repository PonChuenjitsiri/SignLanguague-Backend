from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routers.sensor_data import PredictResponse, _build_predict_response, _predict_and_buffer
from app.services.device_service import DeviceService
from app.services.model_manager import model_manager
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

# ======================================================
# REST API Predict — จาก Device (ผูกโมเดลอัตโนมัติ)
# ======================================================
@router.post("/", response_model=PredictResponse)
async def predict_gesture(payload: PredictRequest):
    """ทำนายท่าทางภาษามือ โดยดึงโมเดลที่ผูกกับ Device โดยอัตโนมัติ และบันทึกคำลง Buffer"""
    
    # 1. ค้นหา Device เพื่อเอา Assigned Model
    device = await DeviceService.get_by_id(payload.device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device '{payload.device_id}' not found.")
        
    assigned_model = device["model_name"]

    # 2. เช็คความถูกต้องของโมเดล
    available_models = model_manager.list_available_models()
    if assigned_model not in available_models:
        raise HTTPException(status_code=500, detail=f"Model '{assigned_model}' is missing.")

    # 3. แปลงข้อมูลดิบจาก ESP32
    frames_2d = parse_raw_frames(payload.raw_data)
    if not frames_2d:
        raise HTTPException(status_code=400, detail="No valid frames found.")

    # 4. 🌟 โยนทุกอย่างเข้า _predict_and_buffer แล้วรอรับผลลัพธ์ 🌟
    result = await _predict_and_buffer(
        frames_2d=frames_2d, 
        source=f"device_{payload.device_id}", # แปะชื่อ Device ลง Log
        model_name=assigned_model             # ส่งชื่อโมเดลไปให้ฟังก์ชัน
    )
    
    # 5. Build response ส่งกลับ!
    return _build_predict_response(result)