import json
import torch
import torch.nn as nn
import numpy as np
import xgboost as xgb
from scipy.interpolate import interp1d

# นำเข้า Model Manager ที่เราเพิ่งสร้าง
from app.services.model_manager import model_manager

# ======================================================
# 1. นิยามโครงสร้าง CNN-LSTM (ต้องมีไว้เพื่อโหลด Weights)
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
        x = x.permute(0, 2, 1)
        x = self.pool1(self.relu(self.bn1(self.conv1(x))))
        x = self.pool2(self.relu(self.bn2(self.conv2(x))))
        x = x.permute(0, 2, 1)
        lstm_out, _ = self.lstm(x)
        out = self.fc(self.dropout(lstm_out[:, -1, :]))
        return out


# ======================================================
# 2. Prediction Service
# ======================================================
class PredictionService:
    def __init__(self):
        # เก็บโมเดลที่โหลดแล้วไว้ใน RAM (Memory Cache) จะได้เร็ว
        self.loaded_models = {}

    def load_model(self, model_name: str):
        """โหลดโมเดลเข้า RAM ถ้ายังไม่เคยโหลด"""
        if model_name in self.loaded_models:
            return  # ถ้าโหลดแล้ว ข้ามไปเลย

        print(f"[PredictionService] Loading model '{model_name}' into memory...")
        
        # 1. ไปขอดาวน์โหลดจาก MinIO (ถ้ามีในเครื่องแล้วมันจะแค่ส่ง Path กลับมา)
        paths = model_manager.download_model_if_needed(model_name)

        # 2. โหลด Labels
        with open(paths["labels"], "r", encoding="utf-8") as f:
            labels_map = json.load(f)
        num_classes = len(labels_map)

        # 3. โหลด PyTorch (CNN-LSTM)
        cnn_lstm_model = CNNLSTM(num_classes=num_classes)
        cnn_lstm_model.load_state_dict(torch.load(paths["pth"], map_location=torch.device('cpu'), weights_only=True))
        cnn_lstm_model.eval()

        # 4. โหลด XGBoost
        xgb_model = xgb.XGBClassifier()
        xgb_model.load_model(paths["xgb"])

        # 5. เก็บลง Cache
        self.loaded_models[model_name] = {
            "cnn_lstm": cnn_lstm_model,
            "xgb": xgb_model,
            "labels_map": labels_map
        }
        print(f"[PredictionService] Model '{model_name}' is ready to use!")

    def _resample_gesture(self, data, target=70):
        """ฟังก์ชันเตรียมข้อมูลให้อยู่ในฟอร์ม 70 เฟรม"""
        data_np = np.array(data)
        non_zero_data = data_np[~np.all(data_np == 0, axis=1)]
        current_len = non_zero_data.shape[0]
        if current_len < 2:
            return None
        old_x = np.linspace(0, current_len - 1, num=current_len)
        new_x = np.linspace(0, current_len - 1, num=target)
        f = interp1d(old_x, non_zero_data, axis=0, kind='linear', fill_value="extrapolate")
        return f(new_x)

    def predict(self, model_name: str, raw_data: list):
        """ทำนายผลโดยใช้ชื่อโมเดลที่ระบุ"""
        # 1. โหลดโมเดล (ถ้าโหลดแล้วมันจะใช้จาก Cache ทันที)
        self.load_model(model_name)
        models = self.loaded_models[model_name]

        # 2. Preprocess ข้อมูล
        resampled = self._resample_gesture(raw_data)
        if resampled is None:
            return {"error": "ข้อมูลไม่เพียงพอในการทำนาย"}
        
        normalized = resampled - resampled[0] # Zero-Starting
        
        # เตรียม Data สำหรับเข้า Model
        X_3d = np.array([normalized], dtype=np.float32)
        X_2d = X_3d.reshape(1, -1)

        # 3. ให้ CNN-LSTM ทำนาย
        inputs_tensor = torch.tensor(X_3d)
        with torch.no_grad():
            outputs_cnn = models["cnn_lstm"](inputs_tensor)
            probs_cnn = torch.softmax(outputs_cnn, dim=1).numpy()[0]

        # 4. ให้ XGBoost ทำนาย
        probs_xgb = models["xgb"].predict_proba(X_2d)[0]

        # 5. Ensemble (Soft Voting 50:50)
        ensemble_probs = (probs_cnn + probs_xgb) / 2.0
        predicted_idx = int(np.argmax(ensemble_probs))
        confidence = float(ensemble_probs[predicted_idx])

        # 6. แปลง Index เป็นชื่อท่าทาง
        predicted_label = models["labels_map"][str(predicted_idx)]

        return {
            "model_used": model_name,
            "prediction": predicted_label,
            "confidence": round(confidence * 100, 2)
        }

# สร้าง Instance ไว้เรียกใช้
prediction_service = PredictionService()