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

class PredictionStreamService:
    def __init__(self):
        self.ser = None
        self.is_running = False
        self.thread = None
        self.status_msg = "Idle"
        # We need an event loop to run async database/buffer operations from the thread
        self.loop = asyncio.new_event_loop()
        
        # Start a background thread to process async tasks from the synchronous serial thread
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
        self.status_msg = "Starting live prediction stream..."
        
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
            "status": self.status_msg
        }

    def _process_prediction_async(self, frames_2d):
        """Wrapper to run async code inside the running event loop"""
        asyncio.run_coroutine_threadsafe(self._handle_prediction(frames_2d), self.loop)

    async def _handle_prediction(self, frames_2d):
        try:
            predicted_sign, ensemble_conf, cnn_conf, xgb_conf = PredictionService.predict(frames_2d)
            print(f" [PREDICT] {predicted_sign} (Conf: {ensemble_conf:.2f})")
            
            # Look up in DB for Thai title
            sign_entry = await SignLanguageService.find_by_title_eng(predicted_sign)

            # Build buffered word
            word = BufferedWord(
                word=predicted_sign,
                confidence=ensemble_conf,
                titleThai=sign_entry.get("titleThai") if sign_entry else None,
                titleEng=sign_entry.get("titleEng") if sign_entry else None,
            )

            # Add to sentence buffer
            await sentence_buffer.add_word(word)

            # Log prediction
            db = get_database()
            await db["prediction_logs"].insert_one({
                "predicted_sign": predicted_sign,
                "confidence": ensemble_conf,
                "cnn_lstm_confidence": cnn_conf,
                "xgboost_confidence": xgb_conf,
                "num_frames": len(frames_2d),
                "created_at": datetime.utcnow(),
            })
            self.status_msg = f"Last Predicted: {predicted_sign} ({ensemble_conf:.2f})"
        except Exception as e:
            print(f" [PREDICT ERROR] {e}")

    def _run_loop(self):
        try:
            self.ser = serial.Serial()
            self.ser.port = SERIAL_PORT
            self.ser.baudrate = BAUD_RATE
            self.ser.timeout = 1
            self.ser.setDTR(False)
            self.ser.setRTS(False)
            self.ser.open()
            self.ser.reset_input_buffer()
            
            self.status_msg = f"Listening on {SERIAL_PORT} for live predictions"
            print(self.status_msg)
            
            raw_buffer = []
            is_reading_data = False

            while self.is_running:
                if self.ser.in_waiting > 0:
                    try:
                        line = self.ser.readline().decode('utf-8', errors='ignore').strip()
                    except:
                        continue
                else:
                    time.sleep(0.01)
                    continue
                    
                if not line: continue

                if "START_SIGNAL" in line:
                    self.status_msg = "Reading gesture..."
                    raw_buffer = []
                    is_reading_data = True
                
                elif "CANCEL_SIGNAL" in line or "DISCARD_SIGNAL" in line:
                    self.status_msg = "Gesture discarded/cancelled"
                    is_reading_data = False
                    raw_buffer = []

                elif is_reading_data and (line.startswith("S ") or (line and line[0].isdigit()) or line.startswith("-")):
                    parts = [x for x in line.split() if x not in ["S", "E"]]
                    if len(parts) == 22:
                        try:
                            raw_buffer.append([float(x) for x in parts])
                        except ValueError:
                            pass

                elif "SUCCESS_SIGNAL" in line:
                    actual_frames = len(raw_buffer)
                    if actual_frames >= 5:
                        # Send the collected 2D frames to be predicted asynchronously
                        self._process_prediction_async(raw_buffer)
                    else:
                        self.status_msg = "Gesture too short for prediction"
                    
                    is_reading_data = False
                    raw_buffer = []

        except Exception as e:
            self.status_msg = f"Serial Error: {e}"
            print(self.status_msg)
            self.is_running = False
        finally:
            if self.ser and self.ser.is_open:
                self.ser.close()

# Singleton instance
prediction_stream = PredictionStreamService()
