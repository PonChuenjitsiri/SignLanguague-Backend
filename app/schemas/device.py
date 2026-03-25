from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class DeviceBase(BaseModel):
    device_id: str = Field(..., description="รหัสอุปกรณ์ เช่น ESP32-MAC-ADDRESS")
    model_name: str = Field(..., description="ชื่อ AI Model")

class DeviceCreate(DeviceBase):
    pass

class DeviceUpdate(BaseModel):
    # กำหนดให้แก้แค่ชื่อ model_name ได้
    model_name: Optional[str] = Field(None, description="ชื่อ AI Model ใหม่ที่ต้องการเปลี่ยน")

class DeviceResponse(DeviceBase):
    updated_at: datetime