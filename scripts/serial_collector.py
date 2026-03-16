import serial
import serial.tools.list_ports
import time
import os
import json
import glob
from datetime import datetime

# ==========================================
# Config
# ==========================================
BAUD_RATE = 115200
DATA_DIR = "dataset"

def get_latest_file(directory):
    """Find the most recently created file in a directory."""
    files = glob.glob(os.path.join(directory, "*.csv"))
    if not files:
        return None
    return max(files, key=os.path.getctime)

def delete_latest_gesture(name, word):
    """Delete the most recently saved gesture file for the given user and word."""
    save_dir = os.path.join(DATA_DIR, word)
    if not os.path.exists(save_dir):
        print(f"⚠️ Directory {save_dir} does not exist.")
        return False
        
    latest_file = get_latest_file(save_dir)
    if latest_file:
        try:
            os.remove(latest_file)
            print(f"🗑️ DELETED latest recording: {os.path.basename(latest_file)}")
            return True
        except Exception as e:
            print(f"❌ Failed to delete {latest_file}: {e}")
            return False
    else:
        print("⚠️ No recordings found to delete.")
        return False

def get_next_sequence_number(save_dir, name, word):
    """Calculate the next sequence suffix (001, 002) for the current user and word."""
    files = glob.glob(os.path.join(save_dir, f"{name}_{word}_*.csv"))
    if not files:
        return 1
    
    max_seq = 0
    for f in files:
        basename = os.path.basename(f)
        # Assuming format: name_word_MMDDYY_SEQ.csv
        parts = basename.replace(".csv", "").split("_")
        if len(parts) >= 4:
            try:
                seq = int(parts[-1])
                if seq > max_seq:
                    max_seq = seq
            except ValueError:
                pass
    return max_seq + 1

def save_gesture(name, word, raw_lines):
    """Save the raw data lines into a CSV file matching the dataset format."""
    save_dir = os.path.join(DATA_DIR, word)
    os.makedirs(save_dir, exist_ok=True)
    
    # Generate filename: {name}_{word}_{MMDDYY}_{SEQ}.csv
    date_str = datetime.now().strftime("%m%d%y")
    seq_num = get_next_sequence_number(save_dir, name, word)
    filename = f"{name}_{word}_{date_str}_{seq_num:03d}.csv"
    filepath = os.path.join(save_dir, filename)
    
    headers = "L_F1,L_F2,L_F3,L_F4,L_F5,L_Ax,L_Ay,L_Az,L_Gx,L_Gy,L_Gz,R_F1,R_F2,R_F3,R_F4,R_F5,R_Ax,R_Ay,R_Az,R_Gx,R_Gy,R_Gz"
    
    valid_frames = 0
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(headers + "\n")
        
        for line in raw_lines:
            # Strip formatting markers
            clean_line = line.strip()
            if clean_line.startswith("S "):
                clean_line = clean_line[2:]
            if clean_line.endswith(" E"):
                clean_line = clean_line[:-2]
            clean_line = clean_line.strip()
            
            # Split by space and join with comma
            parts = clean_line.split()
            if len(parts) == 22:
                csv_row = ",".join(parts)
                f.write(csv_row + "\n")
                valid_frames += 1
                
    if valid_frames > 0:
        print(f"✅ SAVED: {filepath} ({valid_frames} frames)")
    else:
        os.remove(filepath)
        print("❌ FAILED TO SAVE: No valid 22-column frames found.")

def select_serial_port():
    """List available ports and let the user select one."""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("❌ No serial ports found. Please connect your ESP32.")
        return None
        
    print("\n--- Available Serial Ports ---")
    for i, port in enumerate(ports):
        print(f"[{i}] {port.device} - {port.description}")
        
    if len(ports) == 1:
        print(f"Automatically selecting {ports[0].device}")
        return ports[0].device
        
    while True:
        try:
            choice = int(input("\Select port number: "))
            if 0 <= choice < len(ports):
                return ports[choice].device
            print("Invalid choice.")
        except ValueError:
            print("Please enter a number.")

def main():
    print("========================================")
    print(" Smart Glove Serial Data Collector")
    print("========================================")
    
    name = input("Enter your Name (e.g., John): ").strip()
    if not name:
        name = "Unknown"
        
    word = input("Enter the Sign Language Word to record (e.g., hello): ").strip()
    if not word:
        print("❌ Word is required!")
        return
        
    port_name = select_serial_port()
    if not port_name:
        return
        
    try:
        ser = serial.Serial(port_name, BAUD_RATE, timeout=0.1)
        print(f"\n🔌 Connected to {port_name} at {BAUD_RATE} baud.")
        print(f"📁 Saving data to: {os.path.join(DATA_DIR, name, word)}")
        print("\n--- INSTRUCTIONS ---")
        print("👉 Press RIGHT Button to START recording.")
        print("👉 Press RIGHT Button again to STOP & SAVE.")
        print("👉 Press LEFT Button (while recording) to CANCEL current attempt.")
        print("👉 Press LEFT Button (while idle) to DELETE the last saved file.")
        print("--------------------\n")
        
    except serial.SerialException as e:
        print(f"❌ Could not open port {port_name}: {e}")
        return

    is_recording = False
    current_data = []
    
    try:
        while True:
            if ser.in_waiting > 0:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                    
                # Print all system/debug messages from ESP32
                if line.startswith("SYS:"):
                    sys_msg = line[4:].strip()
                    print(f"ESP32: {sys_msg}")
                    if "GESTURE START" in sys_msg:
                        print(f"▶️ RECORDING STARTED for '{word}'...")
                    elif "START_DATA" in sys_msg:
                        # This is the actual trigger that frames are about to be sent over Serial
                        is_recording = True
                        current_data = []
                    elif "END_DATA" in sys_msg:
                        if current_data:
                            print(f"\n⏹️ RECORDING STOPPED. Received {len(current_data)} frames.")
                            save_gesture(name, word, current_data)
                        else:
                            print("\n⚠️ Recording stopped but no valid frames received.")
                        is_recording = False
                        current_data = []
                    continue
                    
                # Handle control commands from Left Hand
                if line == "DELETE":
                    if not is_recording:
                        delete_latest_gesture(name, word)
                elif line == "CANCEL":
                    if is_recording:
                        print("🚫 RECORDING CANCELLED BY USER.")
                        is_recording = False
                        current_data = []
                
                # Process data frames (any line containing numbers)
                elif is_recording and (line[0].isdigit() or line.startswith("S ") or line.startswith("-")):
                    current_data.append(line)
                    print(f"  Received frame {len(current_data)}", end="\r")
                    
            time.sleep(0.01) # Small sleep to prevent 100% CPU
            
    except KeyboardInterrupt:
        print("\n🛑 Exiting Data Collector...")
    finally:
        if ser and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()
