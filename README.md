# Smart Glove Backend 🧤

FastAPI + MongoDB backend สำหรับระบบแปลภาษามือไทย (Thai Sign Language Recognition)  
รับข้อมูล sensor จากถุงมือ ESP32 → ทำนายท่าทางด้วย CNN-LSTM + XGBoost ensemble → สร้างประโยค → ส่งผลลัพธ์ผ่าน WebSocket แบบ real-time

## สถาปัตยกรรมระบบ

```
ESP32 Gloves (L+R)          Backend (FastAPI)              Frontend (Flutter)
       │                          │                              │
   Heartbeat ──── POST ─────────►│                              │
   Calibrate ──── POST ─────────►│                              │
   Gesture ────── POST ─────────►│     ◄──── WebSocket ─────────│
   Sensor Data ── POST ─────────►│── push real-time state ─────►│
                                  │                              │
                            ┌─────┴─────┐                        
                            │  Services  │                        
                            ├────────────┤                        
                            │ CNN-LSTM   │  ← PyTorch             
                            │ XGBoost    │  ← Ensemble (50:50)    
                            │ MinIO      │  ← Model Storage       
                            │ MongoDB    │  ← Data + Logs         
                            └────────────┘                        
```

## Tech Stack

| Layer | Technology |
|-------|------------|
| API Framework | FastAPI + Uvicorn |
| Database | MongoDB (Motor async driver) |
| ML Inference | PyTorch (CNN-LSTM) + XGBoost |
| Object Storage | MinIO (models, images, videos) |
| Package Manager | [uv](https://docs.astral.sh/uv/) |
| Containerization | Docker Compose |

---

## Quick Start

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [Docker](https://www.docker.com/)

### Setup

```bash
# Clone
git clone https://github.com/PonChuenjitsiri/SignLanguague-Backend.git
cd SignLanguague-Backend

# Install dependencies
uv sync

# Start infrastructure (MongoDB + MinIO)
docker compose up -d

# Configure environment
copy .env.example .env

# Seed sign language dictionary (50 words from Excel)
uv run python scripts/seed_sign_languages.py

# Train model (ต้องมี dataset ใน app/dataset/)
uv run python -m app.services.train_model --model-name v1

# Run server
uv run uvicorn app.main:app --reload
```

### Access Points

| Service | URL |
|---------|-----|
| API Docs (Swagger) | http://127.0.0.1:8000/docs |
| Mongo Express | http://localhost:8081 |
| MinIO Console | http://localhost:9001 |

---

## Core Features

### 1. Glove Communication (`/api/glove`)

จัดการ lifecycle ทั้งหมดของถุงมือ ESP32

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/heartbeat` | POST | ESP32 ส่ง heartbeat ทุก 5 วิ + แรงดัน battery |
| `/status` | GET | เช็คถุงมือ online/offline |
| `/status/all` | GET | ดูสถานะถุงมือทุกตัว |
| `/calibrate/start` | POST | เริ่ม calibration (ระบุ `hand: left/right`) |
| `/calibrate/update` | POST | อัพเดท step — open/close/done × 5 รอบ |
| `/calibrate/status` | GET | ดูสถานะ calibration ปัจจุบัน |
| `/gesture/start` | POST | เริ่มบันทึกท่ามือ |
| `/gesture/stop` | POST | หยุดบันทึก |
| `/gesture/status` | GET | เช็คสถานะ gesture |
| **`/ws`** | **WebSocket** | **🔌 Unified WebSocket — ทุกสถานะแบบ real-time** |

### 2. Prediction (`/predict`)

ระบบทำนายท่าทาง — รับ raw sensor data จาก ESP32, ทำนาย, บันทึกคำลง sentence buffer

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | POST | ทำนายจาก raw data โดยใช้โมเดลที่ผูกกับ device |
| `/models` | GET | ดูรายชื่อโมเดลทั้งหมดที่มีในระบบ |

### 3. Sensor Data (`/api/sensor-data`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/predict` | POST | ทำนายจาก structured JSON frames |
| `/predict/raw` | POST | ทำนายจาก raw ESP32 text format (`S ... E`) |

### 4. Device Management (`/api/devices`)

จัดการ device registration + ผูกโมเดลกับอุปกรณ์

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | ดู device ทั้งหมด |
| `/{device_id}` | GET | ดู device ตาม ID |
| `/` | POST | ลงทะเบียน device ใหม่ + assign model อัตโนมัติ |
| `/{device_id}` | PUT | เปลี่ยนโมเดลที่ผูกกับ device |
| `/{device_id}` | DELETE | ลบ device |

### 5. Sign Language Dictionary (`/api/sign-languages`)

CRUD สำหรับคลังคำศัพท์ภาษามือ (50 คำ ไทย/อังกฤษ)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | ดึงรายการทั้งหมด (`?category=` filter) |
| `/{id}` | GET | ดึงตาม ID |
| `/` | POST | เพิ่มคำใหม่ |
| `/{id}` | PUT | แก้ไข |
| `/{id}` | DELETE | ลบ |
| `/uploadpicture` | POST | อัพโหลดรูปภาพไปยัง MinIO |
| `/uploadvideo` | POST | อัพโหลดวิดีโอสาธิตไปยัง MinIO |

---

## Unified WebSocket

Frontend connect WebSocket เดียว — ใช้ `state` ตัดสินใจว่าจะโชว์หน้าไหน:

```
ws://localhost:8000/api/glove/ws?device_id=default
```

**Payload ที่ได้รับ:**

```json
{
  "status": "online",
  "state": "gesture",
  "hand": "right",
  "round": "done",
  "thai_word": "ฉันหิว",
  "eng_word": "I hungry",
  "recording": true,
  "complete": false,
  "word_count": 2,
  "calibrate_left": true,
  "calibrate_right": false,
  "right_voltage": 3.95,
  "right_battery": 72.2,
  "left_voltage": 4.01,
  "left_battery": 78.9
}
```

| Field | Type | Description |
|-------|------|-------------|
| `status` | `online` / `offline` | สถานะ heartbeat |
| `state` | `idle` / `calibrate` / `gesture` | สถานะปัจจุบัน |
| `hand` | `left` / `right` | มือที่กำลัง calibrate |
| `round` | `1`-`5` / `done` | รอบ calibration |
| `thai_word` | string | ประโยคภาษาไทยที่สะสม |
| `eng_word` | string | ประโยคภาษาอังกฤษ |
| `recording` | boolean | กำลังบันทึกท่ามืออยู่ |
| `complete` | boolean | ประโยคสมบูรณ์แล้ว |
| `word_count` | number | จำนวนคำที่ทำนายได้ |
| `*_voltage` | number | แรงดัน battery (V) |
| `*_battery` | number | เปอร์เซ็นต์ battery |

---

## Communication Flow

```
ESP32 (ถุงมือ)                  Backend                       Frontend (App)
      │                            │                              │
  ① Heartbeat                      │                              │
      │──POST /heartbeat ────────►│                              │
      │  (ทุก 5 วิ + voltage)     │                              │
      │                            │                              │
  ② Calibrate                      │◄─── WS /ws ─────────────────│
      │──POST /calibrate/start ──►│     (connect ครั้งเดียว)      │
      │──POST /calibrate/update ─►│                              │
      │  (open/close/done × 5)    │──── push state ─────────────►│
      │                            │                              │
  ③ Gesture Recording              │                              │
      │──POST /gesture/start ────►│                              │
      │──POST /predict ──────────►│  (predict + buffer word)     │
      │  (ส่ง sensor data)         │──── push {thai_word} ───────►│
      │                            │                              │
  ④ Gesture Done (5s timeout)      │                              │
      │──POST /gesture/stop ─────►│──── push {complete:true} ───►│
      │                            │                              │
  ⑤ ทำท่าถัดไป (กลับไป ③)          │                              │
```

---

## ML Pipeline

### Model Architecture

**CNN-LSTM + XGBoost Ensemble (Soft Voting 50:50)**

```
Raw Sensor Data (22 features × N frames)
        │
        ▼
  Resample → 70 frames (interpolation)
        │
        ▼
  Zero-Starting Normalization
        │
   ┌────┴────┐
   ▼         ▼
CNN-LSTM   XGBoost
   │         │
   ▼         ▼
Softmax   predict_proba
   │         │
   └────┬────┘
        ▼
  Ensemble (avg)
        ▼
  Predicted Sign
```

### Sensor Data Format (22 values per frame)

```
L_F1 L_F2 L_F3 L_F4 L_F5 L_Ax L_Ay L_Az L_Gx L_Gy L_Gz R_F1 R_F2 R_F3 R_F4 R_F5 R_Ax R_Ay R_Az R_Gx R_Gy R_Gz
```

| Sensor | Fields | Description |
|--------|--------|-------------|
| Flex (×5 per hand) | `F1`-`F5` | ค่างอนิ้ว (0-100) |
| Accelerometer (×3 per hand) | `Ax`, `Ay`, `Az` | ความเร่ง |
| Gyroscope (×3 per hand) | `Gx`, `Gy`, `Gz` | ความเร็วเชิงมุม |

### Training

```bash
uv run python -m app.services.train_model --model-name <version>

# ตัวอย่าง
uv run python -m app.services.train_model --model-name v1
```

- อ่าน CSV จาก `app/dataset/` (แต่ละโฟลเดอร์ = 1 ท่ามือ)
- เทรน CNN-LSTM (100 epochs) + XGBoost
- เซฟไฟล์ลง `app/models_trained/` + อัพโหลดขึ้น MinIO อัตโนมัติ
- Output: `<name>_cnnlstm.pth`, `<name>_xgb.json`, `<name>_labels_map.json`

### Model Management

- โมเดลเก็บใน **MinIO** (`smartglove-models` bucket) จัดกลุ่มตาม model name
- เมื่อ server start จะดาวน์โหลดจาก MinIO มาเก็บใน RAM (memory cache)
- แต่ละ device สามารถผูกกับโมเดลคนละเวอร์ชันได้

---

## Project Structure

```
app/
├── main.py                       # FastAPI entry point + lifespan
├── config.py                     # Settings (pydantic-settings + .env)
├── database.py                   # MongoDB connection (motor async)
│
├── routers/
│   ├── glove.py                  # ★ Heartbeat, Calibration, Gesture, WebSocket
│   ├── predict.py                # Device-bound prediction endpoint
│   ├── sensor_data.py            # JSON/Raw prediction + sentence buffer
│   ├── devices.py                # Device registration + model assignment
│   ├── sign_language.py          # Dictionary CRUD
│   ├── upload.py                 # Image & video upload to MinIO
│   └── data_collector.py         # Serial port data collection
│
├── services/
│   ├── prediction_service.py     # CNN-LSTM + XGBoost ensemble inference
│   ├── prediction_stream.py      # ESP32 raw data parser (S...E format)
│   ├── sentence_buffer.py        # Word accumulator + async WebSocket events
│   ├── device_service.py         # Device CRUD + model assignment logic
│   ├── model_manager.py          # MinIO model upload/download/cache
│   ├── sign_language_service.py  # DB CRUD + label lookup
│   ├── minio_service.py          # MinIO object storage
│   ├── data_collector.py         # Serial port → CSV collection
│   └── train_model.py            # Training pipeline (CNN-LSTM + XGBoost)
│
├── models/                       # Pydantic DB models
├── schemas/                      # Request/response schemas
├── dataset/                      # Training data (CSV per gesture folder)
├── models_trained/               # Local model files (.pth, .json)
└── utils/
    └── object_id.py              # PyObjectId for Pydantic v2

scripts/
├── seed_sign_languages.py        # Import 50 words from Excel → MongoDB
└── rename_dataset.py             # Batch rename dataset folders/files

glove/                            # ESP32 Arduino code (left & right hand)

docker-compose.yml                # MongoDB + Mongo Express + MinIO + Backend
pyproject.toml                    # Dependencies (uv)
```

---

## Environment Variables

```env
# MongoDB
MONGODB_URL=mongodb://admin:smartglove2026@localhost:27017/smart_glove?authSource=admin
DATABASE_NAME=smart_glove

# MinIO
MINIO_ENDPOINT=127.0.0.1:9000
MINIO_PUBLIC_URL=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin123
MINIO_BUCKET=smartglove-images
MINIO_SECURE=false
```

| Variable | Description |
|----------|-------------|
| `MONGODB_URL` | MongoDB connection string |
| `DATABASE_NAME` | ชื่อ database |
| `MINIO_ENDPOINT` | MinIO endpoint (internal) |
| `MINIO_PUBLIC_URL` | MinIO URL ที่เข้าถึงได้จากภายนอก |
| `MINIO_ACCESS_KEY` | MinIO access key |
| `MINIO_SECRET_KEY` | MinIO secret key |
| `MINIO_BUCKET` | Bucket สำหรับเก็บรูป/วิดีโอ |

---

## Common Commands

```bash
uv sync                                                          # Install dependencies
docker compose up -d                                              # Start infrastructure
uv run uvicorn app.main:app --reload                              # Run dev server
uv run python -m app.services.train_model --model-name v1         # Train model
uv run python scripts/seed_sign_languages.py                      # Seed dictionary
```