"""
Training script for CNN-LSTM + XGBoost ensemble model.

Usage:
    python -m app.services.train_model

Reads CSV data from DATASET_DIR, trains both models, and saves them
to app/models_trained/.
"""

import numpy as np
import pandas as pd
import os
import json
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader
from scipy.interpolate import interp1d
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, precision_score, recall_score, f1_score
import xgboost as xgb

from app.config import get_settings

settings = get_settings()

# ======================================================
# 1. Configuration
# ======================================================
DATA_DIR = settings.DATASET_DIR
EXPECTED_FRAMES = settings.EXPECTED_FRAMES
NUM_FEATURES = settings.NUM_FEATURES

OUTPUT_DIR = "app/models_trained"
os.makedirs(OUTPUT_DIR, exist_ok=True)

PYTORCH_MODEL_PATH = os.path.join(OUTPUT_DIR, "gesture_model_best_cnnlstm.pth")
XGB_MODEL_PATH = os.path.join(OUTPUT_DIR, "gesture_model_best_xgb.json")
LABELS_FILE = os.path.join(OUTPUT_DIR, "labels_map.json")


# ======================================================
# 2. CNN-LSTM Model Definition
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
# 3. Data Loading Utilities
# ======================================================
def resample_gesture(data, target=70):
    """Resample gesture data to a fixed number of frames via interpolation."""
    data_np = np.array(data)
    non_zero_data = data_np[~np.all(data_np == 0, axis=1)]
    current_len = non_zero_data.shape[0]
    if current_len < 2:
        return None
    old_x = np.linspace(0, current_len - 1, num=current_len)
    new_x = np.linspace(0, current_len - 1, num=target)
    f = interp1d(old_x, non_zero_data, axis=0, kind='linear', fill_value="extrapolate")
    return f(new_x)


def load_dataset(data_dir, expected_frames):
    """Load all CSV gesture data and return X (3D), y, and labels map."""
    if not os.path.exists(data_dir):
        print(f"[!] Dataset directory not found: {data_dir}")
        return None, None, None

    folder_names = sorted([
        d for d in os.listdir(data_dir)
        if os.path.isdir(os.path.join(data_dir, d))
    ])

    if not folder_names:
        print(f"[!] No gesture folders found in {data_dir}")
        return None, None, None

    labels_map = {i: name for i, name in enumerate(folder_names)}
    inv_labels_map = {v: k for k, v in labels_map.items()}

    print("--- Detected Labels ---")
    for k, v in labels_map.items():
        print(f"  [{k}] : {v}")

    X, y = [], []
    print(f"\n--- Loading & Resampling to {expected_frames} frames ---")
    for label_name in labels_map.values():
        path = os.path.join(data_dir, label_name)
        files = [f for f in os.listdir(path) if f.endswith('.csv')]
        print(f"  {label_name}: {len(files)} files")
        for file in files:
            try:
                df = pd.read_csv(os.path.join(path, file))
                resampled = resample_gesture(df.values, target=expected_frames)
                if resampled is not None:
                    normalized = resampled - resampled[0]  # Zero-Starting
                    X.append(normalized)
                    y.append(inv_labels_map[label_name])
            except Exception:
                pass

    if not X:
        print("[!] No valid data loaded")
        return None, None, None

    return np.array(X, dtype=np.float32), np.array(y, dtype=np.int64), labels_map


# ======================================================
# 4. Training Pipeline
# ======================================================
def train():
    """Full training pipeline: CNN-LSTM + XGBoost + Ensemble evaluation."""

    X_3d, y, labels_map = load_dataset(DATA_DIR, EXPECTED_FRAMES)
    if X_3d is None:
        return

    num_classes = len(labels_map)

    # Save labels map
    with open(LABELS_FILE, "w", encoding="utf-8") as f:
        json.dump(labels_map, f, ensure_ascii=False, indent=4)
    print(f"\n[SAVED] Labels map -> {LABELS_FILE}")

    # Split data (same split for both models)
    X_train_3d, X_test_3d, y_train, y_test = train_test_split(
        X_3d, y, test_size=0.3, random_state=42, stratify=y
    )

    # Flatten for XGBoost
    X_train_2d = X_train_3d.reshape(X_train_3d.shape[0], -1)
    X_test_2d = X_test_3d.reshape(X_test_3d.shape[0], -1)

    print(f"\n--- Data Shapes ---")
    print(f"  CNN-LSTM: Train={X_train_3d.shape}, Test={X_test_3d.shape}")
    print(f"  XGBoost:  Train={X_train_2d.shape}, Test={X_test_2d.shape}")

    # DataLoaders
    train_dataset = TensorDataset(torch.tensor(X_train_3d), torch.tensor(y_train))
    test_dataset = TensorDataset(torch.tensor(X_test_3d), torch.tensor(y_test))
    train_loader = DataLoader(train_dataset, batch_size=32, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=32, shuffle=False)

    # --------------------------------------------------
    # Train CNN-LSTM
    # --------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Training CNN-LSTM (PyTorch)")
    print(f"{'='*50}")

    cnn_lstm_model = CNNLSTM(num_classes=num_classes, num_features=NUM_FEATURES)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.Adam(cnn_lstm_model.parameters(), lr=0.001)

    epochs = 100
    best_acc = 0.0

    for epoch in range(epochs):
        cnn_lstm_model.train()
        total_loss = 0
        for inputs, labels in train_loader:
            optimizer.zero_grad()
            outputs = cnn_lstm_model(inputs)
            loss = criterion(outputs, labels)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        # Validation
        cnn_lstm_model.eval()
        correct, total = 0, 0
        with torch.no_grad():
            for inputs, labels in test_loader:
                outputs = cnn_lstm_model(inputs)
                _, predicted = torch.max(outputs.data, 1)
                total += labels.size(0)
                correct += (predicted == labels).sum().item()

        val_acc = correct / total
        if (epoch + 1) % 10 == 0:
            print(f"  Epoch {epoch+1}/{epochs} | Loss: {total_loss/len(train_loader):.4f} | Val Acc: {val_acc*100:.2f}%")

        if val_acc > best_acc:
            best_acc = val_acc
            torch.save(cnn_lstm_model.state_dict(), PYTORCH_MODEL_PATH)

    print(f"[DONE] CNN-LSTM Best Val Accuracy: {best_acc*100:.2f}%")
    print(f"[SAVED] -> {PYTORCH_MODEL_PATH}")

    # Load best CNN-LSTM
    cnn_lstm_model.load_state_dict(torch.load(PYTORCH_MODEL_PATH, weights_only=True))
    cnn_lstm_model.eval()

    # --------------------------------------------------
    # Train XGBoost
    # --------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Training XGBoost")
    print(f"{'='*50}")

    xgb_model = xgb.XGBClassifier(
        n_estimators=100,
        learning_rate=0.1,
        max_depth=6,
        objective='multi:softprob',
        num_class=num_classes,
        eval_metric='mlogloss',
        random_state=42,
    )

    xgb_model.fit(
        X_train_2d, y_train,
        eval_set=[(X_test_2d, y_test)],
        verbose=10,
    )

    xgb_model.save_model(XGB_MODEL_PATH)
    print(f"[DONE] XGBoost saved -> {XGB_MODEL_PATH}")

    # --------------------------------------------------
    # Model Complexity / Parameters
    # --------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Model Complexity / Parameters")
    print(f"{'='*50}")

    # CNN-LSTM parameters
    cnn_lstm_params = sum(p.numel() for p in cnn_lstm_model.parameters() if p.requires_grad)
    print(f"  CNN-LSTM Trainable Parameters: {cnn_lstm_params:,}")

    # XGBoost approximate parameters (total nodes)
    try:
        xgb_nodes = len(xgb_model.get_booster().trees_to_dataframe())
        print(f"  XGBoost Total Nodes (Approx Params): {xgb_nodes:,}")
    except Exception as e:
        print(f"  XGBoost Total Nodes: N/A")

    # --------------------------------------------------
    # Ensemble Evaluation (Soft Voting)
    # --------------------------------------------------
    print(f"\n{'='*50}")
    print(f"Ensemble Evaluation (Soft Voting)")
    print(f"{'='*50}")

    # CNN-LSTM probabilities
    cnn_lstm_probs_list = []
    with torch.no_grad():
        for inputs, _ in test_loader:
            outputs = cnn_lstm_model(inputs)
            probs = torch.softmax(outputs, dim=1)
            cnn_lstm_probs_list.extend(probs.numpy())
    probs_cnn_lstm = np.array(cnn_lstm_probs_list)

    # XGBoost probabilities
    probs_xgboost = xgb_model.predict_proba(X_test_2d)

    # Soft voting (50:50)
    ensemble_probs = (probs_cnn_lstm + probs_xgboost) / 2.0

    preds_cnn_lstm = np.argmax(probs_cnn_lstm, axis=1)
    preds_xgboost = np.argmax(probs_xgboost, axis=1)
    preds_ensemble = np.argmax(ensemble_probs, axis=1)

    # Calculate Metrics for Ensemble
    acc = accuracy_score(y_test, preds_ensemble)
    precision = precision_score(y_test, preds_ensemble, average='weighted', zero_division=0)
    recall = recall_score(y_test, preds_ensemble, average='weighted', zero_division=0)
    f1 = f1_score(y_test, preds_ensemble, average='weighted', zero_division=0)
    cm = confusion_matrix(y_test, preds_ensemble)

    print(f"\n  CNN-LSTM Accuracy:        {accuracy_score(y_test, preds_cnn_lstm)*100:.2f}%")
    print(f"  XGBoost Accuracy:         {accuracy_score(y_test, preds_xgboost)*100:.2f}%")
    print(f"  Ensemble Accuracy:        {acc*100:.2f}%")

    print(f"\n--- Ensemble Evaluation Metrics ---")
    print(f"Accuracy:                {acc*100:.2f}%")
    print(f"Precision:               {precision*100:.2f}%")
    print(f"Recall (Sensitivity):    {recall*100:.2f}%")
    print(f"F1-Score:                {f1*100:.2f}%")

    print(f"\n--- Confusion Matrix ---")
    print(cm)

    print(f"\n--- Detailed Classification Report ---")
    print(classification_report(y_test, preds_ensemble, target_names=list(labels_map.values()), zero_division=0))

    print(f"\n✅ Training complete! Models saved to {OUTPUT_DIR}/")


if __name__ == "__main__":
    train()
