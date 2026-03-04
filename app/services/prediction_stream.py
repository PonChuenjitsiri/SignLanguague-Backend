"""
Prediction stream — reads ESP32 serial data and predicts gestures live.

Protocol:
  START_SIGNAL         → Glove starts capturing gesture
  S v1 v2 ... v22      → First data frame (22 values, S prefix)
  v1 v2 ... v22        → Middle data frames
  v1 v2 ... v22 E      → Last data frame (E suffix)
  STOP_SIGNAL          → Done, send collected data to prediction model
"""

import serial
import threading
import time
import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv

from app.services.prediction_service import PredictionService
from app.services.sign_language_service import SignLanguageService
from app.services.sentence_buffer import sentence_buffer, BufferedWord
from app.database import get_database

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM3")
BAUD_RATE = 115200


def parse_raw_frames(raw_text: str) -> list[list[float]]:
    """
    Parse raw ESP32 data block into a list of 22-float frames.

    Strips 'S' and 'E' markers, keeps only lines with exactly 22 numeric values.
    Works for both serial and REST API input.
    """
    frames = []
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [x for x in line.split() if x not in ["S", "E"]]
        if len(parts) == 22:
            try:
                frames.append([float(x) for x in parts])
            except ValueError:
                continue
    return frames


class PredictionStreamService:
    """Serial port prediction stream — listens for ESP32 gestures and predicts live."""

    def __init__(self):
        self.ser = None
        self.is_running = False
        self.thread = None
        self.status_msg = "Idle"
        self.last_prediction = None

        # Async event loop for DB/buffer operations from sync serial thread
        self.loop = asyncio.new_event_loop()
        self.async_thread = threading.Thread(target=self._start_async_loop, daemon=True)
        self.async_thread.start()

    def _start_async_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self):
        if self.is_running:
            return False, "Prediction stream is already running."
        if not PredictionService.is_loaded:
            return False, "Models not loaded. Cannot start live prediction."

        self.is_running = True
        self.status_msg = "Starting..."
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True, "Started"

    def stop(self):
        if not self.is_running:
            return False, "Prediction stream is not running."
        self.is_running = False
        self.status_msg = "Stopping..."
        if self.thread:
            self.thread.join(timeout=2)
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.status_msg = "Stopped"
        return True, "Stopped"

    def get_status(self):
        return {
            "is_running": self.is_running,
            "status": self.status_msg,
            "last_prediction": self.last_prediction,
        }

    def _process_prediction_async(self, frames_2d):
        """Run async prediction from synchronous serial thread."""
        asyncio.run_coroutine_threadsafe(self._handle_prediction(frames_2d), self.loop)

    async def _handle_prediction(self, frames_2d):
        """Predict gesture, buffer word, log to DB."""
        try:
            predicted_sign, ensemble_conf, cnn_conf, xgb_conf = PredictionService.predict(frames_2d)
            print(f"  [PREDICT] {predicted_sign} (Conf: {ensemble_conf:.2f})")

            # Look up by label (handles variants like no_right → no)
            sign_entry = await SignLanguageService.find_by_label(predicted_sign)

            word = BufferedWord(
                word=predicted_sign,
                confidence=ensemble_conf,
                titleThai=sign_entry.get("titleThai") if sign_entry else None,
                titleEng=sign_entry.get("titleEng") if sign_entry else None,
            )
            await sentence_buffer.add_word(word)

            # Log
            db = get_database()
            await db["prediction_logs"].insert_one({
                "predicted_sign": predicted_sign,
                "confidence": ensemble_conf,
                "cnn_lstm_confidence": cnn_conf,
                "xgboost_confidence": xgb_conf,
                "num_frames": len(frames_2d),
                "source": "serial",
                "created_at": datetime.utcnow(),
            })

            self.last_prediction = {
                "sign": predicted_sign,
                "confidence": ensemble_conf,
                "titleThai": sign_entry.get("titleThai") if sign_entry else None,
            }
            self.status_msg = f"Predicted: {predicted_sign} ({ensemble_conf:.2f})"

        except Exception as e:
            print(f"  [PREDICT ERROR] {e}")
            self.status_msg = f"Prediction error: {e}"

    def _run_loop(self):
        """Main serial read loop."""
        try:
            self.ser = serial.Serial()
            self.ser.port = SERIAL_PORT
            self.ser.baudrate = BAUD_RATE
            self.ser.timeout = 1
            self.ser.setDTR(False)
            self.ser.setRTS(False)
            self.ser.open()
            self.ser.reset_input_buffer()

            self.status_msg = f"Listening on {SERIAL_PORT}"
            print(f"[STREAM] {self.status_msg}")

            raw_buffer = []
            is_reading = False

            while self.is_running:
                if self.ser.in_waiting > 0:
                    try:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    except Exception:
                        continue
                else:
                    time.sleep(0.01)
                    continue

                if not line:
                    continue

                # --- Protocol ---

                if "START_SIGNAL" in line:
                    # Glove started capturing gesture
                    self.status_msg = "Capturing gesture..."
                    raw_buffer = []
                    is_reading = True

                elif "STOP_SIGNAL" in line:
                    # Glove stopped → predict with collected frames
                    if is_reading and len(raw_buffer) >= 5:
                        self.status_msg = f"Predicting ({len(raw_buffer)} frames)..."
                        self._process_prediction_async(raw_buffer.copy())
                    elif is_reading:
                        self.status_msg = f"Too short ({len(raw_buffer)} frames), skipped"

                    is_reading = False
                    raw_buffer = []

                elif is_reading:
                    # Data line: strip S/E markers, parse 22 values
                    parts = [x for x in line.split() if x not in ["S", "E"]]
                    if len(parts) == 22:
                        try:
                            raw_buffer.append([float(x) for x in parts])
                        except ValueError:
                            pass

        except Exception as e:
            self.status_msg = f"Serial Error: {e}"
            print(f"[STREAM ERROR] {e}")
            self.is_running = False
        finally:
            if self.ser and self.ser.is_open:
                self.ser.close()


# Singleton
prediction_stream = PredictionStreamService()
