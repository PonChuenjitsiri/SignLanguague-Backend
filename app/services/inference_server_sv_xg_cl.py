import json
import serial
import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import xgboost as xgb
from scipy.interpolate import interp1d
import os
from gtts import gTTS
import pygame
import io

# ======================================================
# 1. Configuration
# ======================================================
SERIAL_PORT = "COM3"
BAUD_RATE = 115200
TARGET_FRAMES = 70  

# ชื่อไฟล์โมเดลทั้ง 2 ตัวที่ได้จากการเทรน
PYTORCH_MODEL_PATH = "gesture_model_best_cnnlstm.pth"
XGB_MODEL_PATH = "gesture_model_best_xgb.json"
LABELS_FILE = "labels_map.json"

TRANSLATION_DICT = {
    "come_here": "มา", "father": "พ่อ", "go": "ไป", "hello": "สวัสดี",
    "help": "ช่วยด้วย", "home": "บ้าน", "hungry": "หิวค่ะ", "hungry_left": "หิวครับ",
    "hurt": "เจ็บ", "i_am_full": "อิ่ม", "me": "ฉัน", "mother": "แม่",
    "no": "ไม่ครับ", "no_left": "ไม่ค่ะ", "sorry": "ขอโทษ", "telephone": "โทรศัพท์",
    "thanks": "ขอบคุณ", "toilet": "ห้องน้ำ", "wait": "รอ", "water": "น้ำ",
    "yes": "ใช่", "you": "คุณ",
}

# ======================================================
# 2. Initialize Audio 
# ======================================================
pygame.mixer.init()

def speak_thai(text):
    try:
        tts = gTTS(text=text, lang='th')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        pygame.mixer.music.load(fp)
        pygame.mixer.music.play()
    except Exception as e:
        print(f"Voice Error: {e}")

# ======================================================
# 3. Model Architecture & Load Weights
# ======================================================
class CNNLSTM(nn.Module):
    def __init__(self, num_classes):
        super(CNNLSTM, self).__init__()
        self.conv1 = nn.Conv1d(in_channels=22, out_channels=64, kernel_size=3, padding=1)
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

try:
    with open(LABELS_FILE, "r", encoding="utf-8") as f:
        loaded_labels = json.load(f)
        LABELS_MAP = {int(k): v for k, v in loaded_labels.items()}
        
    # โหลด CNN-LSTM
    cnn_model = CNNLSTM(num_classes=len(LABELS_MAP))
    cnn_model.load_state_dict(torch.load(PYTORCH_MODEL_PATH, map_location=torch.device('cpu')))
    cnn_model.eval()
    
    # โหลด XGBoost
    xgb_model = xgb.XGBClassifier()
    xgb_model.load_model(XGB_MODEL_PATH)
    
    print(f"--- Models Loaded Successfully ---")
    print(f"[1] {PYTORCH_MODEL_PATH}")
    print(f"[2] {XGB_MODEL_PATH}")
except Exception as e:
    print(f"Error loading models: {e}")
    exit()

# ======================================================
# 4. Core Prediction Logic (Ensemble)
# ======================================================
def resample_and_predict(data):
    data_np = np.array(data)
    current_len = data_np.shape[0]
    
    x_old = np.linspace(0, 1, current_len)
    x_new = np.linspace(0, 1, TARGET_FRAMES)
    
    resampled_data = []
    for col in range(22):
        f = interp1d(x_old, data_np[:, col], kind='linear', fill_value="extrapolate")
        resampled_data.append(f(x_new))
    
    resampled_np = np.array(resampled_data).T  # Shape: (70, 22)
    
    # ทำ Zero-Starting เพื่อให้ตรงกับตอนเทรน
    normalized_np = resampled_np - resampled_np[0]
    
    # --------------------------------------------------
    # ส่วนที่ 1: ดึงค่า Probability จาก CNN-LSTM
    # --------------------------------------------------
    tensor_3d = torch.tensor(normalized_np, dtype=torch.float32).unsqueeze(0) # Shape: (1, 70, 22)
    with torch.no_grad():
        cnn_out = cnn_model(tensor_3d)
        cnn_probs = torch.softmax(cnn_out, dim=1)[0].numpy()
        
    # --------------------------------------------------
    # ส่วนที่ 2: ดึงค่า Probability จาก XGBoost
    # --------------------------------------------------
    vector_2d = normalized_np.flatten().reshape(1, -1) # Shape: (1, 1540)
    xgb_probs = xgb_model.predict_proba(vector_2d)[0]
    
    # --------------------------------------------------
    # ส่วนที่ 3: ทำ Soft Voting Ensemble
    # --------------------------------------------------
    ensemble_probs = (cnn_probs + xgb_probs) / 2.0
    
    best_idx = np.argmax(ensemble_probs)
    final_conf = ensemble_probs[best_idx]
    
    return LABELS_MAP[best_idx], final_conf

# ======================================================
# 5. Main Serial Loop
# ======================================================
def main():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
        ser.flushInput()
        print(f"\n--- Ensemble Inference Server Ready on {SERIAL_PORT} ---")
        print("Waiting for gesture signal...")

        gesture_buffer = []
        is_collecting = False

        while True:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if not line: continue

            if "START_SIGNAL" in line:
                print("\n[*] Detecting...", end="", flush=True)
                gesture_buffer = []
                is_collecting = True

            elif "CANCEL_SIGNAL" in line:
                print(" -> [CANCELLED]")
                is_collecting = False
                gesture_buffer = []

            elif is_collecting and (line.startswith("S ") or (line and line[0].isdigit())):
                parts = [x for x in line.split() if x not in ["S", "E"]]
                if len(parts) == 22:
                    gesture_buffer.append([float(x) for x in parts])
                    print(".", end="", flush=True)

            elif "SUCCESS_SIGNAL" in line:
                actual_frames = len(gesture_buffer)
                print(f" Done ({actual_frames} frames)")
                
                if actual_frames >= 10:
                    label_en, conf = resample_and_predict(gesture_buffer)
                    thai_text = TRANSLATION_DICT.get(label_en, "ไม่ทราบท่าทางค่ะ")
                    
                    print(f"\n" + "="*40)
                    print(f" RESULT  : {thai_text} ({label_en})")
                    print(f" CONF    : {conf*100:.2f}% (Ensemble)")
                    print("="*40)
                    
                    # คุณอาจจะต้องปรับ Threshold ตรงนี้ (ของเดิม 0.45) 
                    # เพราะพอเฉลี่ย 2 โมเดล ค่าความมั่นใจอาจจะไม่โดดทะลุ 90% บ่อยเหมือนตอนใช้โมเดลเดียว
                    if conf > 0.45:
                        speak_thai(thai_text)
                    else:
                        print("[!] Confidence too low to speak.")
                else:
                    print("\n[!] Error: Gesture too short.")
                
                is_collecting = False
                print("\nReady for next gesture...")

    except KeyboardInterrupt:
        print("\nServer Exit...")
    except Exception as e:
        print(f"\nSerial/Main Error: {e}")

if __name__ == "__main__":
    main()