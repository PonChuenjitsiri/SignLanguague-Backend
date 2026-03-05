from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import connect_db, close_db
from app.routers import sign_language, sensor_data, data_collector, upload
from app.services.prediction_service import PredictionService
from app.services.minio_service import MinioService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup
    await connect_db()
    PredictionService.load_model()
    try:
        MinioService.ensure_bucket()
    except Exception as e:
        print(f"⚠️  MinIO not available: {e}")
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


@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "message": "Smart Glove API is running 🧤",
        "docs": "/docs",
        "version": "1.0.0",
    }
