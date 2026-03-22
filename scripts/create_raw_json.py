import csv
import json
import os

files = [
    r"c:\Dev\SmartGlove-BE\app\dataset\hello\pon_hello_022626_009.csv",
    r"c:\Dev\SmartGlove-BE\app\dataset\me\pon_me_030326_001.csv",
    r"c:\Dev\SmartGlove-BE\app\dataset\hungry\pon_hungry_022626_025.csv"
]

output_dir = r"c:\Dev\SmartGlove-BE\test_payloads"
os.makedirs(output_dir, exist_ok=True)

for file_path in files:
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        continue
        
    with open(file_path, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        lines = []
        for row in reader:
            if not row: continue
            lines.append(" ".join(row))
            
    if not lines:
        continue
        
    raw_data_str = "S " + " ".join(lines[0].split()) + "\n"
    for i in range(1, len(lines) - 1):
        raw_data_str += " ".join(lines[i].split()) + "\n"
    raw_data_str += " ".join(lines[-1].split()) + " E"
    
    payload = {
        "raw_data": raw_data_str
    }
    
    base_name = os.path.basename(file_path).replace(".csv", ".json")
    out_path = os.path.join(output_dir, base_name)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=4)
        
    print(f"Created {out_path}")
