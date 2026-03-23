import os
from minio import Minio
from app.config import get_settings

settings = get_settings()

class ModelManagerService:
    def __init__(self):
        self.client = Minio(
            settings.MINIO_ENDPOINT,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE
        )
        self.bucket_name = getattr(settings, "MINIO_MODEL_BUCKET", "smartglove-models")
        self.local_models_dir = "app/models_trained"
        self._ensure_bucket_exists()
        os.makedirs(self.local_models_dir, exist_ok=True)

    def _ensure_bucket_exists(self):
        """เช็คว่ามี Bucket หรือยัง ถ้ายังให้สร้างใหม่"""
        if not self.client.bucket_exists(self.bucket_name):
            self.client.make_bucket(self.bucket_name)
            print(f"[ModelManager] Created MinIO bucket: '{self.bucket_name}'")

    def upload_model(self, model_name: str, pth_path: str, xgb_path: str, labels_path: str):
        """อัปโหลดไฟล์โมเดลที่เทรนเสร็จแล้วขึ้น MinIO โดยจัดกลุ่มใส่โฟลเดอร์ตาม model_name"""
        files_to_upload = {
            f"{model_name}/cnnlstm.pth": pth_path,
            f"{model_name}/xgb.json": xgb_path,
            f"{model_name}/labels_map.json": labels_path
        }

        print(f"\n[ModelManager] Uploading model '{model_name}' to MinIO...")
        for object_name, local_path in files_to_upload.items():
            if os.path.exists(local_path):
                self.client.fput_object(self.bucket_name, object_name, local_path)
                print(f"  -> Uploaded: {object_name}")
            else:
                print(f"  -> [!] File not found: {local_path}")

    def list_available_models(self) -> list:
        """กวาดรายชื่อโมเดลทั้งหมดที่มีใน MinIO (ดูจากชื่อโฟลเดอร์)"""
        try:
            objects = self.client.list_objects(self.bucket_name, recursive=False)
            # MinIO จะคืนค่า prefix มาเป็น "model_name/" เราเลยต้องตัด "/" ออก
            model_names = [obj.object_name.strip("/") for obj in objects if obj.is_dir]
            return model_names
        except Exception as e:
            print(f"[ModelManager] Error listing models: {e}")
            return []

    def download_model_if_needed(self, model_name: str) -> dict:
        """ดาวน์โหลดโมเดลจาก MinIO ลงมาที่เครื่อง (ถ้ายังไม่มี) และคืนค่า path ของไฟล์ทั้ง 3"""
        model_dir = os.path.join(self.local_models_dir, model_name)
        os.makedirs(model_dir, exist_ok=True)

        paths = {
            "pth": os.path.join(model_dir, "cnnlstm.pth"),
            "xgb": os.path.join(model_dir, "xgb.json"),
            "labels": os.path.join(model_dir, "labels_map.json")
        }

        files_to_download = {
            f"{model_name}/cnnlstm.pth": paths["pth"],
            f"{model_name}/xgb.json": paths["xgb"],
            f"{model_name}/labels_map.json": paths["labels"]
        }

        for object_name, local_path in files_to_download.items():
            if not os.path.exists(local_path):
                print(f"[ModelManager] Downloading {object_name} from MinIO...")
                try:
                    self.client.fget_object(self.bucket_name, object_name, local_path)
                except Exception as e:
                    print(f"[ModelManager] [!] Failed to download {object_name}: {e}")
                    raise e
        
        return paths

# สร้าง Instance ไว้เรียกใช้ (Singleton Pattern)
model_manager = ModelManagerService()