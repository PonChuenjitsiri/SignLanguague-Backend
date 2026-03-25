from datetime import datetime
from app.database import get_database
from app.services.model_manager import model_manager  # ดึงมาเพื่อเช็คชื่อโมเดล

class DeviceService:
    """Service layer for device CRUD operations."""

    COLLECTION_NAME = "devices"

    @staticmethod
    def _get_collection():
        db = get_database()
        return db[DeviceService.COLLECTION_NAME]

    @staticmethod
    async def create(data: dict):
        collection = DeviceService._get_collection()
        
        device_id = data.get("device_id")

        # 1. เช็คก่อนว่ามี Device ID นี้อยู่ในระบบแล้วหรือยัง?
        existing_device = await collection.find_one({"device_id": device_id})
        if existing_device:
            # ถ้ามีอยู่แล้วให้เด้ง Error กลับไปเลย
            raise ValueError(f"Device ID '{device_id}' already exists. Please use update instead.")

        # 2. เช็คว่า Model มีอยู่จริงไหมก่อนบันทึก
        available_models = model_manager.list_available_models()
        if data.get("model_name") not in available_models:
            raise ValueError(f"Model '{data.get('model_name')}' not found.")

        # 3. เพิ่มเวลาอัปเดต
        data["updated_at"] = datetime.utcnow()
        
        # 4. บันทึกลง Database (ใช้ copy() เพื่อไม่ให้ _id ติดไปใน dict ต้นฉบับ)
        insert_data = data.copy()
        await collection.insert_one(insert_data)
        
        # 5. คืนค่ากลับไปให้ Router เพื่อแปลงเป็น Response Model
        return data

    @staticmethod
    async def get_all():
        collection = DeviceService._get_collection()
        # ค้นหาทั้งหมด ดึง _id ออกเพื่อไม่ให้ Pydantic งง
        devices = await collection.find({}, {"_id": 0}).to_list(length=100)
        return devices

    @staticmethod
    async def get_by_id(device_id: str):
        collection = DeviceService._get_collection()
        device = await collection.find_one({"device_id": device_id}, {"_id": 0})
        return device

    @staticmethod
    async def update(device_id: str, data: dict):
        collection = DeviceService._get_collection()
        
        # ตัดค่า None ทิ้ง (อัปเดตเฉพาะ field ที่ส่งค่ามา)
        update_data = {k: v for k, v in data.items() if v is not None}
        if not update_data:
            return await DeviceService.get_by_id(device_id)

        # ถ้ามีการแก้ model_name ต้องเช็คด้วยว่าโมเดลใหม่มีจริงไหม
        if "model_name" in update_data:
            available_models = model_manager.list_available_models()
            if update_data["model_name"] not in available_models:
                raise ValueError(f"Model '{update_data['model_name']}' not found.")

        update_data["updated_at"] = datetime.utcnow()

        result = await collection.update_one(
            {"device_id": device_id}, 
            {"$set": update_data}
        )

        if result.modified_count == 0 and result.matched_count == 0:
            return None # ไม่พบข้อมูลให้อัปเดต
            
        return await DeviceService.get_by_id(device_id)

    @staticmethod
    async def delete(device_id: str):
        collection = DeviceService._get_collection()
        result = await collection.delete_one({"device_id": device_id})
        return result.deleted_count > 0