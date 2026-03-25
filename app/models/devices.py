from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class Device(BaseModel):
    # ใช้ alias="_id" เพื่อให้เข้ากับโครงสร้างของ MongoDB
    device_id: str = Field(..., description="รหัสประจำตัวของอุปกรณ์ เช่น ESP32-MAC-ADDRESS หรือชื่อถุงมือ")
    model_name: str = Field(..., description="ชื่อ AI Model ที่อุปกรณ์นี้ตั้งค่าให้ใช้งานอยู่ เช่น sign_language_model_v1")
    
    # (Optional) แนะนำให้เก็บเวลาที่อัปเดตข้อมูลด้วย เผื่อมีประโยชน์ตอนดู Log ครับ
    updated_at: Optional[datetime] = Field(default_factory=datetime.utcnow, description="เวลาที่อัปเดตข้อมูลล่าสุด")

    class Config:
        # อนุญาตให้ใช้ชื่อ field ปกติหรือ alias ก็ได้
        populate_by_name = True
        
        # ตัวอย่างข้อมูล (เอาไว้โชว์ในหน้า Docs/Swagger UI สวยๆ)
        json_schema_extra = {
            "example": {
                "device_id": "smartglove-001",
                "model_name": "sign_language_model_v1",
                "updated_at": "2026-03-25T14:30:00Z"
            }
        }

class DeviceModelUpdate(BaseModel):
    model_name: str = Field(..., description="ชื่อ AI Model ใหม่ที่ต้องการเปลี่ยนให้ถุงมือ")