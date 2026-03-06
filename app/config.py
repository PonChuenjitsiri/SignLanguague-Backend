from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    MONGODB_URL: str = "mongodb://admin:smartglove2026@localhost:27017/smart_glove?authSource=admin"

    DATABASE_NAME: str = "smart_glove"
    MODEL_PATH: str = "models/sign_language_model.pkl"

    # Model paths
    CNNLSTM_MODEL_PATH: str = "app/models_trained/gesture_model_best_cnnlstm.pth"
    XGB_MODEL_PATH: str = "app/models_trained/gesture_model_best_xgb.json"
    LABELS_MAP_PATH: str = "app/models_trained/labels_map.json"

    # Dataset
    DATASET_DIR: str = "app/dataset"

    # Training config
    EXPECTED_FRAMES: int = 70
    NUM_FEATURES: int = 22

    # Glove heartbeat
    GLOVE_HEARTBEAT_TIMEOUT: int = 10  # seconds before glove is considered offline

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore" 


@lru_cache()
def get_settings() -> Settings:
    return Settings()
