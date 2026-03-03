import serial
import pandas as pd
import numpy as np
import os, time
from datetime import datetime
from scipy.interpolate import interp1d

import os
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = "COM9"
BAUD_RATE = 115200
DATA_DIR = "dataset"

def delete_last_file(name, gesture):
    path = os.path.join(DATA_DIR, gesture)
    if not os.path.exists(path): return
    
    prefix = f"{name}_{gesture}_"
    files = [os.path.join(path, f) for f in os.listdir(path) if f.startswith(prefix) and f.endswith('.csv')]
    
    if not files:
        print(f" [!] No files to delete for user '{name}' in '{gesture}'")
        return

    latest_file = max(files, key=os.path.getctime)
    try:
        os.remove(latest_file)
        print(f"\n [DELETE] Removed: {os.path.basename(latest_file)}")
        print(f" [STATUS] Current files for {name}: {get_user_seq(name, gesture)}")
    except Exception as e:
        print(f" [ERROR] Could not delete file: {e}")

def get_user_seq(name, gesture):
    path = os.path.join(DATA_DIR, gesture)
    if not os.path.exists(path): 
        return 0
    
    prefix = f"{name}_{gesture}_"
    
    count = len([f for f in os.listdir(path) if f.startswith(prefix) and f.endswith('.csv')])
    return count

def main():
    name = input("Enter User Name: ").strip() or "iq"
    gesture = input("Enter Gesture Label: ").strip() or "hello"
    
    try:
        ser = serial.Serial()
        ser.port = SERIAL_PORT
        ser.baudrate = BAUD_RATE
        ser.timeout = 1
        
        # Disable hardware flow control/reset signals
        ser.setDTR(False)
        ser.setRTS(False)
        
        # Open the port safely
        ser.open()
        
        # Clear any leftover junk data in the buffer
        ser.reset_input_buffer()
        print(f"\n[READY] Collecting '{gesture}' for {name}")
        print(f"[STATUS] Current files: {get_user_seq(name, gesture)}")
        print("--------------------------------------------------")

        raw_buffer = []
        is_reading_data = False

        while True:
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
            except:
                continue
                
            if not line: continue

            if "DELETE_SIGNAL" in line:
                delete_last_file(name, gesture)
                print("\nReady for next take...")
                raw_buffer = []
                is_reading_data = False

            elif "START_SIGNAL" in line:
                print(f"[*] Recording...", end="", flush=True)
                raw_buffer = []
                is_reading_data = True
            
            elif "CANCEL_SIGNAL" in line:
                print(" -> [CANCELLED]")
                is_reading_data = False
                raw_buffer = []

            elif "DISCARD_SIGNAL" in line:
                print(" -> [DISCARDED: Too Short]")
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
                print(f" [OK] Received {actual_frames} raw frames.")
                
                if actual_frames >= 5:
                    
                    if raw_buffer is not None:
                        date_str = datetime.now().strftime("%m%d%y")
                        seq = get_user_seq(name, gesture) + 1
                        gesture_dir = os.path.join(DATA_DIR, gesture)
                        os.makedirs(gesture_dir, exist_ok=True)
                        filename = f"{name}_{gesture}_{date_str}_{seq:03d}.csv"
                        filepath = os.path.join(DATA_DIR, gesture, filename)
                        
                        cols = [f'L_F{i}' for i in range(1,6)] + ['L_Ax','L_Ay','L_Az','L_Gx','L_Gy','L_Gz'] + \
                               [f'R_F{i}' for i in range(1,6)] + ['R_Ax','R_Ay','R_Az','R_Gx','R_Gy','R_Gz']
                        
                        df = pd.DataFrame(raw_buffer, columns=cols)
                        df.to_csv(filepath, index=False)

                        print("\n" + "="*40)
                        print(f" [FLEX MAX] Gesture: {gesture}")
                        print("-" * 40)
                        
                        # แยก List ของคอลัมน์ที่ต้องการ
                        left_flex = [f'L_F{i}' for i in range(1, 6)]
                        right_flex = [f'R_F{i}' for i in range(1, 6)]
                        
                        # หาค่า Max
                        max_df = df.max()
                        
                        # แสดงผลแบบแบ่งฝั่ง ซ้าย | ขวา
                        print("  LEFT HAND (F1-F5)  |  RIGHT HAND (F1-F5)")
                        left_vals = ", ".join([f"{max_df[c]:4.0f}" for c in left_flex])
                        right_vals = ", ".join([f"{max_df[c]:4.0f}" for c in right_flex])
                        print(f"  {left_vals}  |  {right_vals}")
                        print("="*40)
                        
                        print(f" [TOTAL] {name} - {gesture}: {get_user_seq(name, gesture)} files")
                    else:
                         print(" [ERROR] Data empty after trimming zeros.")
                else:
                    print(" [ERROR] Raw data too short, not saved.")
                
                is_reading_data = False
                print("\nReady for next take...")

    except KeyboardInterrupt:
        print("\nExit...")
        if 'ser' in locals() and ser.is_open: ser.close()
    except Exception as e:
        print(f"\nError: {e}")

if __name__ == "__main__":
    main()