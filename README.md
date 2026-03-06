# Smart Glove Backend

FastAPI + MongoDB backend for the Smart Glove sign language recognition system.
Recognizes Thai Sign Language gestures from ESP32 sensor data using a CNN-LSTM + XGBoost ensemble model.

## Features

- **Gesture Prediction** — CNN-LSTM + XGBoost ensemble (soft voting) for sign language recognition
- **Unified WebSocket** — Single WebSocket แสดงสถานะทั้งหมด (online, calibrate, gesture, sentence)
- **Glove Calibration** — Calibration flow (แบ/กำมือ × 5 รอบ ทั้งซ้ายและขวา)
- **Gesture Lifecycle** — Start/stop gesture recording + sentence buffering
- **Sign Language Dictionary** — CRUD API for 50 sign language entries (Thai/English)
- **Data Collection** — Collect training data from ESP32 via serial port
- **Image Upload** — Upload sign language images to MinIO object storage
- **MongoDB + Docker** — Containerized database with Mongo Express UI

## Quick Start

### 1. Prerequisites

- [Python 3.11+](https://www.python.org/)
- [uv](https://docs.astral.sh/uv/) — Python package manager
- [Docker](https://www.docker.com/) — for MongoDB & MinIO

### 2. Setup

```bash
# Clone the repository
git clone https://github.com/PonChuenjitsiri/SignLanguague-Backend.git
cd SignLanguague-Backend

# Install dependencies
uv sync

# Start MongoDB + MinIO (Docker)
docker compose up -d

# Configure environment
copy .env.example .env

# Seed sign language dictionary (50 words from Excel)
uv run python scripts/seed_sign_languages.py

# Train the model (requires dataset in app/dataset/)
uv run python -m app.services.train_model

# Run the server
uv run uvicorn app.main:app --reload
```

### 3. Access

- **API Docs (Swagger):** http://127.0.0.1:8000/docs
- **Mongo Express UI:** http://localhost:8081
- **MinIO Console:** http://localhost:9001

---

## API Endpoints

### Glove — Connection & Control (`/api/glove`)

| Method | Endpoint | ใช้โดย | Description |
|--------|----------|--------|-------------|
| POST | `/heartbeat` | ESP32 | ส่ง heartbeat ทุก 5 วิ |
| GET | `/status` | Frontend | เช็คถุงมือ online/offline |
| GET | `/status/all` | Frontend | ดูสถานะถุงมือทุกตัว |
| POST | `/calibrate/start` | ESP32 | เริ่ม calibration (ระบุ `hand: left/right`) |
| POST | `/calibrate/update` | ESP32 | อัพเดท step (open/close/done, round 1-5) |
| GET | `/calibrate/status` | Frontend | ดูคำสั่ง calibration (ไทย/อังกฤษ) |
| POST | `/gesture/start` | ESP32 | เริ่มบันทึกท่ามือ |
| POST | `/gesture/stop` | ESP32 | หยุดบันทึก (5 วิ timeout) |
| GET | `/gesture/status` | Frontend | เช็คสถานะ gesture active |
| **WS** | **`/ws`** | **Frontend** | 🔌 **Unified WebSocket — ทุกสถานะในหน้าเดียว** |

### Sensor Data & Prediction (`/api/sensor-data`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/predict` | รับ gesture (JSON frames) → predict → buffer |
| POST | `/predict/raw` | รับ raw text จาก ESP32 (`S ... E` format) → predict → buffer |

### Sign Languages — CRUD (`/api/sign-languages`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | ดึงรายการท่าภาษามือทั้งหมด (`?category=` filter) |
| GET | `/{id}` | ดึงข้อมูลท่าตาม ID |
| POST | `/` | เพิ่มท่าภาษามือใหม่ |
| PUT | `/{id}` | แก้ไขข้อมูลท่า |
| DELETE | `/{id}` | ลบท่า |

### Upload (`/api/upload`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/image` | อัพโหลดรูปท่าภาษามือไปยัง MinIO |

### Data Collector (`/collector`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/start` | เริ่มเก็บ data จาก serial port |
| POST | `/stop` | หยุดเก็บ data |
| GET | `/status` | เช็คสถานะ |

---

## Communication Flow

### Full System Flow

```
ESP32 (ถุงมือ)                  Backend                       Frontend (App)
      │                            │                              │
  ① Health Check                   │                              │
      │──POST /heartbeat ────────►│                              │
      │  (ทุก 5 วิ)               │                              │
      │                            │                              │
  ② Calibrate                      │◄─── WS /ws ─────────────────│
      │──POST /calibrate/start ──►│     (connect ครั้งเดียว)      │
      │──POST /calibrate/update ─►│                              │
      │  (open/close/done × 5)    │──── push state ─────────────►│
      │                            │                              │
  ③ Gesture Recording              │                              │
      │──POST /gesture/start ────►│                              │
      │──POST /predict/raw ──────►│  (predict + buffer word)     │
      │  (ส่ง sensor data)         │──── push {thai_word} ───────►│
      │                            │                              │
  ④ Gesture Done (5s timeout)      │                              │
      │──POST /gesture/stop ─────►│──── push {complete:true} ───►│
      │                            │                              │
  ⑤ ทำท่าถัดไป (กลับไป ③)          │                              │
```

### ESP32 → Backend Protocol

```
1. POST /api/glove/heartbeat               → health check
2. POST /api/glove/calibrate/start         → เริ่ม calibration (hand: left/right)
3. POST /api/glove/calibrate/update        → {step:"open/close/done", round:1-5}
4. POST /api/glove/gesture/start           → เริ่มทำท่ามือ
5. POST /api/sensor-data/predict/raw       → {raw_data: "S 60 2824 ... E"}
6. POST /api/glove/gesture/stop            → หยุด (timeout 5 วิ)
```

### Frontend — Unified WebSocket

Frontend connect แค่ WebSocket เดียว แล้วใช้ `state` ตัดสินใจว่าจะโชว์หน้าไหน:

```javascript
const ws = new WebSocket("ws://localhost:8000/api/glove/ws?device_id=default");
ws.onmessage = (e) => {
  const data = JSON.parse(e.data);
  // data = {
  //   status: "online" | "offline",
  //   state: "idle" | "calibrate" | "gesture",
  //   hand: "left" | "right",
  //   round: "1"-"5" | "done",
  //   thai_word: "ฉันหิว",
  //   eng_word: "I hungry",
  //   recording: true/false,
  //   complete: true/false,
  //   word_count: 2
  // }

  if (data.state === "calibrate") showCalibrationPage(data);
  else if (data.state === "gesture") showGesturePage(data);
  else showIdlePage(data);
};
```

### Data Format (22 values per frame)

```
L_F1 L_F2 L_F3 L_F4 L_F5 L_Ax L_Ay L_Az L_Gx L_Gy L_Gz R_F1 R_F2 R_F3 R_F4 R_F5 R_Ax R_Ay R_Az R_Gx R_Gy R_Gz
```

- `L_F1-F5` — Left hand flex sensors
- `L_Ax/Ay/Az` — Left hand accelerometer
- `L_Gx/Gy/Gz` — Left hand gyroscope
- `R_*` — Right hand (same layout)

---

## Scripts

```bash
uv sync                                        # Install dependencies
uv sync --dev                                   # Install dev dependencies
uv run python scripts/seed_sign_languages.py    # Seed dictionary (50 words)
uv run python -m app.services.train_model       # Train model
uv run uvicorn app.main:app --reload            # Run server
```

## Project Structure

```
app/
├── main.py                    # FastAPI entry point
├── config.py                  # Settings (pydantic-settings)
├── database.py                # MongoDB connection (motor)
├── models/                    # Pydantic DB models
├── schemas/
│   ├── sign_language.py       # Sign language CRUD schemas
│   └── sensor_data.py         # Prediction request/response schemas
├── routers/
│   ├── glove.py               # ★ Heartbeat, calibration, gesture, WebSocket
│   ├── sensor_data.py         # Prediction endpoints (/predict, /predict/raw)
│   ├── sign_language.py       # CRUD endpoints
│   ├── upload.py              # Image upload to MinIO
│   └── data_collector.py      # Data collection endpoints
├── services/
│   ├── prediction_service.py  # CNN-LSTM + XGBoost ensemble inference
│   ├── prediction_stream.py   # ESP32 raw data parser (parse_raw_frames)
│   ├── sentence_buffer.py     # Word → sentence accumulator + WebSocket events
│   ├── sign_language_service.py  # DB CRUD + label lookup
│   ├── minio_service.py       # MinIO object storage
│   ├── data_collector.py      # Serial port data collection → CSV
│   └── train_model.py         # Model training script
├── dataset/                   # Training CSV data (per gesture folder)
├── models_trained/            # Saved models (.pth, .json, labels_map.json)
└── utils/
    └── object_id.py           # PyObjectId for Pydantic v2

scripts/
└── seed_sign_languages.py     # Import 50 words from Excel → MongoDB

docker-compose.yml             # MongoDB + Mongo Express + MinIO
pyproject.toml                 # Dependencies (uv)
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MONGODB_URL` | `mongodb://admin:smartglove2026@localhost:27017/smart_glove?authSource=admin` | MongoDB connection string |
| `DATABASE_NAME` | `smart_glove` | Database name |
| `GLOVE_HEARTBEAT_TIMEOUT` | `15` | วินาทีก่อนถือว่าถุงมือ offline |
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO endpoint |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO access key |
| `MINIO_SECRET_KEY` | `minioadmin123` | MinIO secret key |
| `MINIO_BUCKET` | `smartglove-images` | MinIO bucket name |