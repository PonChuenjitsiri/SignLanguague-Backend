from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import connect_db, close_db
from app.routers import devices, sign_language, sensor_data, data_collector, upload, glove, predict
from app.services.prediction_service import PredictionService
from app.services.minio_service import MinioService

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # 1. เชื่อมต่อ Database
    await connect_db()
    
    # 2. โหลดโมเดล (แก้ไขตรงนี้)
    try:
        # สร้าง instance และระบุชื่อไฟล์โมเดล (สมมติว่าชื่อตามใน .env หรือ default)
        predictor = PredictionService()
        predictor.load_model(model_name="sign_language_model.pkl") 
        print("✅ Prediction model loaded successfully.")
    except Exception as e:
        print(f"⚠️ Could not load prediction model: {e}")
        print("👉 Make sure you run 'uv run python -m app.services.train_model' first.")

    # 3. เช็ค MinIO
    try:
        MinioService.ensure_bucket()
    except Exception as e:
        print(f"⚠️ MinIO not available: {e}")

    yield
    
    # Shutdown
    await close_db()


app = FastAPI(
    title="Smart Glove API",
    description="FastAPI backend for Smart Glove sign language recognition system",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development (restrict in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(sign_language.router)
app.include_router(sensor_data.router)
app.include_router(data_collector.router)
app.include_router(upload.router)
app.include_router(glove.router)
app.include_router(predict.router)
app.include_router(devices.router)


@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "message": "Smart Glove API is running 🧤",
        "docs": "/docs",
        "version": "1.0.0",
    }
