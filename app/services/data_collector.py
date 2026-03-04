import serial
import pandas as pd
import numpy as np
import os, time
from datetime import datetime
import threading
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM3")
BAUD_RATE = 115200
DATA_DIR = "./app/dataset"

class DataCollectorService:
    def __init__(self):
        self.ser = None
        self.is_running = False
        self.thread = None
        self.name = "default"
        self.gesture = "unknown"
        self.status_msg = "Idle"

    def get_user_seq(self, name, gesture):
        path = os.path.join(DATA_DIR, gesture)
        if not os.path.exists(path): 
            return 0
        prefix = f"{name}_{gesture}_"
        count = len([f for f in os.listdir(path) if f.startswith(prefix) and f.endswith('.csv')])
        return count

    def delete_last_file(self, name, gesture):
        path = os.path.join(DATA_DIR, gesture)
        if not os.path.exists(path): return False
        prefix = f"{name}_{gesture}_"
        files = [os.path.join(path, f) for f in os.listdir(path) if f.startswith(prefix) and f.endswith('.csv')]
        if not files:
            return False
        latest_file = max(files, key=os.path.getctime)
        try:
            os.remove(latest_file)
            return True
        except Exception as e:
            print(f" [ERROR] Could not delete file: {e}")
            return False

    def start(self, name: str, gesture: str):
        if self.is_running:
            return False, "Collector is already running. Please stop it first."
        
        self.name = name
        self.gesture = gesture
        self.is_running = True
        self.status_msg = f"Starting collection for {name} - {gesture}..."
        
        self.thread = threading.Thread(target=self._run_loop, daemon=True)
        self.thread.start()
        return True, "Started"

    def stop(self):
        if not self.is_running:
            return False, "Collector is not running."
        
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
            "name": self.name,
            "gesture": self.gesture,
            "status": self.status_msg,
            "collected_files": self.get_user_seq(self.name, self.gesture)
        }

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
            
            self.status_msg = f"Listening on {SERIAL_PORT} for '{self.gesture}' by '{self.name}'"
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

                if "DELETE_SIGNAL" in line:
                    self.delete_last_file(self.name, self.gesture)
                    self.status_msg = "Deleted last file. Ready for next take..."
                    raw_buffer = []
                    is_reading_data = False

                elif "START_SIGNAL" in line:
                    self.status_msg = "Recording..."
                    raw_buffer = []
                    is_reading_data = True
                
                elif "CANCEL_SIGNAL" in line:
                    self.status_msg = "Cancelled. Ready for next take..."
                    is_reading_data = False
                    raw_buffer = []

                elif "DISCARD_SIGNAL" in line:
                    self.status_msg = "Discarded: Too Short. Ready for next take..."
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
                        date_str = datetime.now().strftime("%m%d%y")
                        seq = self.get_user_seq(self.name, self.gesture) + 1
                        gesture_dir = os.path.join(DATA_DIR, self.gesture)
                        os.makedirs(gesture_dir, exist_ok=True)
                        filename = f"{self.name}_{self.gesture}_{date_str}_{seq:03d}.csv"
                        filepath = os.path.join(DATA_DIR, self.gesture, filename)
                        
                        cols = [f'L_F{i}' for i in range(1,6)] + ['L_Ax','L_Ay','L_Az','L_Gx','L_Gy','L_Gz'] + \
                               [f'R_F{i}' for i in range(1,6)] + ['R_Ax','R_Ay','R_Az','R_Gx','R_Gy','R_Gz']
                        
                        df = pd.DataFrame(raw_buffer, columns=cols)
                        df.to_csv(filepath, index=False)

                        self.status_msg = f"Saved {filename} ({actual_frames} frames). Ready for next take..."
                        print(f"[DATA] Saved: {filepath}")
                    else:
                        self.status_msg = "Error: Raw data too short, not saved."
                    
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
collector_instance = DataCollectorService()
