"""
Prediction service using CNN-LSTM + XGBoost ensemble (Soft Voting).

Loads trained models on startup and provides inference for real-time
gesture prediction via the REST API.
"""

import numpy as np
import json
import os
import torch
import torch.nn as nn
import xgboost as xgb
from scipy.interpolate import interp1d
from typing import Tuple, Optional

from app.config import get_settings


# ======================================================
# CNN-LSTM Model Definition (must match training)
# ======================================================
class CNNLSTM(nn.Module):
    def __init__(self, num_classes, num_features=22):
        super(CNNLSTM, self).__init__()
        self.conv1 = nn.Conv1d(in_channels=num_features, out_channels=64, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm1d(64)
        self.pool1 = nn.MaxPool1d(2)

        self.conv2 = nn.Conv1d(in_channels=64, out_channels=128, kernel_size=3, padding=1)
        self.bn2 = nn.BatchNorm1d(128)
        self.pool2 = nn.MaxPool1d(2)

        self.relu = nn.ReLU()
        self.dropout = nn.Dropout(0.3)
        self.lstm = nn.LSTM(input_size=128, hidden_size=64, num_layers=2, batch_first=True, dropout=0.3)
        self.fc = nn.Linear(64, num_classes)

    def forward(self, x):
        x = x.permute(0, 2, 1)  # (Batch, Features, Frames)
        x = self.pool1(self.relu(self.bn1(self.conv1(x))))
        x = self.pool2(self.relu(self.bn2(self.conv2(x))))
        x = x.permute(0, 2, 1)  # (Batch, seq_len, features)
        lstm_out, _ = self.lstm(x)
        out = self.fc(self.dropout(lstm_out[:, -1, :]))
        return out


# ======================================================
# Prediction Service
# ======================================================
class PredictionService:
    """
    Ensemble prediction service: CNN-LSTM + XGBoost with soft voting.
    """

    cnn_lstm_model: Optional[CNNLSTM] = None
    xgb_model: Optional[xgb.XGBClassifier] = None
    labels_map: dict = {}
    is_loaded: bool = False

    @staticmethod
    def resample_gesture(data: np.ndarray, target: int = 70) -> Optional[np.ndarray]:
        """Resample gesture data to fixed number of frames."""
        non_zero_data = data[~np.all(data == 0, axis=1)]
        current_len = non_zero_data.shape[0]
        if current_len < 2:
            return None
        old_x = np.linspace(0, current_len - 1, num=current_len)
        new_x = np.linspace(0, current_len - 1, num=target)
        f = interp1d(old_x, non_zero_data, axis=0, kind='linear', fill_value="extrapolate")
        return f(new_x)

    @staticmethod
    def load_model(
        cnnlstm_path: str = None,
        xgb_path: str = None,
        labels_path: str = None,
    ):
        """Load both trained models and labels map."""
        settings = get_settings()
        cnnlstm_path = cnnlstm_path or settings.CNNLSTM_MODEL_PATH
        xgb_path = xgb_path or settings.XGB_MODEL_PATH
        labels_path = labels_path or settings.LABELS_MAP_PATH

        # Check if model files exist
        if not os.path.exists(labels_path):
            print(f"⚠️  Labels map not found: {labels_path}")
            print(f"⚠️  Run 'python -m app.services.train_model' to train first")
            PredictionService.is_loaded = False
            return

        # Load labels map
        with open(labels_path, "r", encoding="utf-8") as f:
            raw_map = json.load(f)
            PredictionService.labels_map = {int(k): v for k, v in raw_map.items()}

        num_classes = len(PredictionService.labels_map)
        print(f"📋 Labels loaded: {PredictionService.labels_map}")

        # Load CNN-LSTM
        if os.path.exists(cnnlstm_path):
            PredictionService.cnn_lstm_model = CNNLSTM(
                num_classes=num_classes,
                num_features=settings.NUM_FEATURES,
            )
            PredictionService.cnn_lstm_model.load_state_dict(
                torch.load(cnnlstm_path, map_location=torch.device("cpu"), weights_only=True)
            )
            PredictionService.cnn_lstm_model.eval()
            print(f"✅ CNN-LSTM model loaded: {cnnlstm_path}")
        else:
            print(f"⚠️  CNN-LSTM model not found: {cnnlstm_path}")

        # Load XGBoost
        if os.path.exists(xgb_path):
            PredictionService.xgb_model = xgb.XGBClassifier()
            PredictionService.xgb_model.load_model(xgb_path)
            print(f"✅ XGBoost model loaded: {xgb_path}")
        else:
            print(f"⚠️  XGBoost model not found: {xgb_path}")

        PredictionService.is_loaded = (
            PredictionService.cnn_lstm_model is not None
            and PredictionService.xgb_model is not None
        )

        if PredictionService.is_loaded:
            print(f"🚀 Ensemble prediction service ready!")
        else:
            print(f"⚠️  Prediction service partially loaded — some models missing")

    @staticmethod
    def predict(frames_2d: list[list[float]]) -> Tuple[str, float, float, float]:
        """
        Run ensemble inference on a gesture (sequence of frames).

        Args:
            frames_2d: List of frames, each frame is a list of 22 floats

        Returns:
            Tuple of (predicted_label, ensemble_confidence, cnn_conf, xgb_conf)
        """
        if not PredictionService.is_loaded:
            raise RuntimeError(
                "Models not loaded. Run 'python -m app.services.train_model' first."
            )

        settings = get_settings()
        data = np.array(frames_2d, dtype=np.float32)

        # Resample to expected frames
        resampled = PredictionService.resample_gesture(data, target=settings.EXPECTED_FRAMES)
        if resampled is None:
            raise ValueError("Gesture data too short — need at least 2 non-zero frames")

        # Zero-starting normalization
        normalized = resampled - resampled[0]

        # Prepare input shapes
        input_3d = normalized.reshape(1, settings.EXPECTED_FRAMES, settings.NUM_FEATURES)
        input_2d = normalized.reshape(1, -1)

        # CNN-LSTM prediction
        with torch.no_grad():
            tensor_input = torch.tensor(input_3d, dtype=torch.float32)
            cnn_output = PredictionService.cnn_lstm_model(tensor_input)
            cnn_probs = torch.softmax(cnn_output, dim=1).numpy()[0]

        # XGBoost prediction
        xgb_probs = PredictionService.xgb_model.predict_proba(input_2d)[0]

        # Soft voting (50:50)
        ensemble_probs = (cnn_probs + xgb_probs) / 2.0
        predicted_idx = int(np.argmax(ensemble_probs))
        ensemble_conf = float(ensemble_probs[predicted_idx])
        cnn_conf = float(cnn_probs[predicted_idx])
        xgb_conf = float(xgb_probs[predicted_idx])

        predicted_label = PredictionService.labels_map.get(predicted_idx, "unknown")

        return predicted_label, ensemble_conf, cnn_conf, xgb_conf
