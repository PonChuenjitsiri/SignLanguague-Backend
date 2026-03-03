from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import connect_db, close_db
from app.routers import sign_language, sensor_data
from app.services.prediction_service import PredictionService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    # Startup
    await connect_db()
    PredictionService.load_model()
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


@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint."""
    return {
        "message": "Smart Glove API is running 🧤",
        "docs": "/docs",
        "version": "1.0.0",
    }
