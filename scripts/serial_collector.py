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
DATA_DIR = "data"

def get_latest_file(directory):
    """Find the most recently created file in a directory."""
    files = glob.glob(os.path.join(directory, "*.json"))
    if not files:
        return None
    return max(files, key=os.path.getctime)

def delete_latest_gesture(name, word):
    """Delete the most recently saved gesture file for the given user and word."""
    save_dir = os.path.join(DATA_DIR, name, word)
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

def save_gesture(name, word, raw_data_string):
    """Save the raw 'S ... E' data string into a JSON file."""
    save_dir = os.path.join(DATA_DIR, name, word)
    os.makedirs(save_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{word}_{timestamp}.json"
    filepath = os.path.join(save_dir, filename)
    
    data = {
        "word": word,
        "name": name,
        "timestamp": timestamp,
        "raw_data": raw_data_string
    }
    
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    print(f"✅ SAVED: {filepath}")

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
                    print(f"ESP32: {line[4:].strip()}")
                    if "GESTURE START" in line:
                        print(f"▶️ RECORDING STARTED for '{word}'...")
                        is_recording = True
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
                
                # Handle data framing directly outputted over serial
                elif line.startswith("S ") and line.endswith(" E"):
                    current_data.append(line)
                    print(f"  Received frame {len(current_data)}", end="\r")
                
                # Sometime the data comes row by row wrapped between SYS commands (as implemented in ESP)
                # Let's adjust for the fact that now it prints S ... E lines directly
                elif is_recording and len(line.split(' ')) >= 22: # Valid raw frame has ~22 parts (+ S and E)
                    pass # We handled it in the previous elif
                
                # Stop Logic (Normally handled by receiving the frames, but ESP outputs SYS: END_DATA)
                if line == "SYS: END_DATA":
                    if current_data:
                        print(f"\n⏹️ RECORDING STOPPED. Received {len(current_data)} frames.")
                        raw_data_string = "\n".join(current_data)
                        save_gesture(name, word, raw_data_string)
                    else:
                        print("\n⚠️ Recording stopped but no valid frames received.")
                    is_recording = False
                    current_data = []
                    
            time.sleep(0.01) # Small sleep to prevent 100% CPU
            
    except KeyboardInterrupt:
        print("\n🛑 Exiting Data Collector...")
    finally:
        if ser and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()
