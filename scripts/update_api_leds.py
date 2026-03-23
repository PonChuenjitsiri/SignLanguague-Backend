import os

def process_right_hand():
    path = r"c:\Dev\SmartGlove-BE\glove\right_hand_api\right_hand_api.ino"
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()

    # 1. Replace PIN_LED
    code = code.replace("const int PIN_LED = 10;", 
                        "const int PIN_LED_R = 8;\nconst int PIN_LED_G = 9;\nconst int PIN_LED_B = 10;\nbool curr_r = LOW, curr_g = LOW, curr_b = LOW;")
    
    # 2. Add setLEDColor and update blinkLED
    old_blink = """void blinkLED(int times, int duration) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_LED, HIGH);
    delay(duration);
    digitalWrite(PIN_LED, LOW);
    if (i < times - 1)
      delay(duration);
  }
}"""
    new_blink = """void setLEDColor(bool r, bool g, bool b) {
  curr_r = r; curr_g = g; curr_b = b;
  digitalWrite(PIN_LED_R, r ? HIGH : LOW);
  digitalWrite(PIN_LED_G, g ? HIGH : LOW);
  digitalWrite(PIN_LED_B, b ? HIGH : LOW);
}

void blinkRGB(int times, int duration, bool r, bool g, bool b) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_LED_R, r ? HIGH : LOW);
    digitalWrite(PIN_LED_G, g ? HIGH : LOW);
    digitalWrite(PIN_LED_B, b ? HIGH : LOW);
    delay(duration);
    digitalWrite(PIN_LED_R, LOW);
    digitalWrite(PIN_LED_G, LOW);
    digitalWrite(PIN_LED_B, LOW);
    if (i < times - 1) delay(duration);
  }
  setLEDColor(curr_r, curr_g, curr_b);
}

void updateStateLED() {
  if (!is_connected) {
    setLEDColor(LOW, LOW, HIGH); // Blue
    return;
  }
  switch(currentState) {
    case IDLE: setLEDColor(LOW, HIGH, LOW); break; // Green
    case RECORDING: setLEDColor(HIGH, LOW, LOW); break; // Red
    case RECEIVING_LEFT: setLEDColor(HIGH, HIGH, LOW); break; // Yellow
    case CALIBRATING_RIGHT:
    case CALIBRATING_LEFT: setLEDColor(HIGH, LOW, HIGH); break; // Magenta
  }
}"""
    code = code.replace(old_blink, new_blink)

    # 3. Replace waitForUserAction
    old_wait = """void waitForUserAction() {
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  delay(100);
  while (digitalRead(PIN_BTN_R) == LOW)
    delay(10);
  delay(100);
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  delay(100);
}"""
    new_wait = """void waitForUserAction() {
  while (digitalRead(PIN_BTN_R) == HIGH) {
    if (is_connected && millis() - lastHeartbeat >= HEARTBEAT_INTERVAL) {
      lastHeartbeat = millis(); sendHeartbeat();
    }
    delay(10);
  }
  delay(100);
  while (digitalRead(PIN_BTN_R) == LOW) {
    if (is_connected && millis() - lastHeartbeat >= HEARTBEAT_INTERVAL) {
      lastHeartbeat = millis(); sendHeartbeat();
    }
    delay(10);
  }
  delay(100);
  while (digitalRead(PIN_BTN_R) == HIGH) {
    if (is_connected && millis() - lastHeartbeat >= HEARTBEAT_INTERVAL) {
      lastHeartbeat = millis(); sendHeartbeat();
    }
    delay(10);
  }
  delay(100);
}"""
    code = code.replace(old_wait, new_wait)

    # 4. pin modes
    code = code.replace("pinMode(PIN_LED, OUTPUT);", 
                        "pinMode(PIN_LED_R, OUTPUT);\n  pinMode(PIN_LED_G, OUTPUT);\n  pinMode(PIN_LED_B, OUTPUT);")

    # 5. loop WiFi
    loop_target = """  // --- WiFi connect notice ---
  static bool was_connected = false;
  if (is_connected && !was_connected) {
    Serial.println("WiFi connected! Glove running...");
    was_connected = true;
  }"""
    loop_rep = loop_target + "\n  updateStateLED();"
    code = code.replace(loop_target, loop_rep)

    # 6. Blinks
    code = code.replace("blinkLED(2, 50);", "blinkRGB(2, 50, HIGH, LOW, LOW);") # discard
    code = code.replace("blinkLED(3, 100);", "blinkRGB(3, 100, LOW, HIGH, LOW);") # success raw
    code = code.replace("blinkLED(2, 100);", "blinkRGB(2, 100, HIGH, LOW, LOW);") # left cancel
    code = code.replace("blinkLED(4, 50);", "blinkRGB(4, 50, HIGH, HIGH, LOW);") # idle cancel
    
    code = code.replace('apiCalibrateStart("right");\n  blinkLED(5, 100);', 
                        'apiCalibrateStart("right");\n  blinkRGB(5, 100, HIGH, LOW, HIGH);')
    code = code.replace('HC12.write(CMD_STOP);\n      blinkLED(5, 100);',
                        'HC12.write(CMD_STOP);\n      blinkRGB(5, 100, LOW, LOW, HIGH);')
    
    code = code.replace("blinkLED(3, 200);", "blinkRGB(3, 200, LOW, HIGH, LOW);") # calib done
    
    code = code.replace('apiGestureStart();\n          Serial.println(">> GESTURE START");\n          blinkLED(1, 100);',
                        'apiGestureStart();\n          Serial.println(">> GESTURE START");\n          blinkRGB(1, 100, HIGH, LOW, LOW);')
    code = code.replace('Serial.println(">> Waiting for left hand data...");\n          blinkLED(1, 100);',
                        'Serial.println(">> Waiting for left hand data...");\n          blinkRGB(1, 100, HIGH, HIGH, LOW);')

    # digitalWrite
    code = code.replace("digitalWrite(PIN_LED, HIGH);", "setLEDColor(HIGH, LOW, HIGH);")
    code = code.replace("digitalWrite(PIN_LED, LOW);", "setLEDColor(curr_r, curr_g, curr_b);") 

    with open(path, "w", encoding="utf-8") as f:
        f.write(code)


def process_left_hand():
    path = r"c:\Dev\SmartGlove-BE\glove\left_hand_api\left_hand_api.ino"
    with open(path, "r", encoding="utf-8") as f:
        code = f.read()

    # 1. Replace PIN_LED
    code = code.replace("#define PIN_LED 10", 
                        "#define PIN_LED_R 8\n#define PIN_LED_G 9\n#define PIN_LED_B 10\nbool curr_r = LOW, curr_g = LOW, curr_b = LOW;")
    
    # 2. Add setLEDColor and update blinkLED
    old_blink = """void blinkLED(int times, int duration) {
  pinMode(PIN_LED, OUTPUT);
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_LED, HIGH);
    delay(duration);
    digitalWrite(PIN_LED, LOW);
    if (i < times - 1)
      delay(duration);
  }
}"""
    new_blink = """void setLEDColor(bool r, bool g, bool b) {
  curr_r = r; curr_g = g; curr_b = b;
  digitalWrite(PIN_LED_R, r ? HIGH : LOW);
  digitalWrite(PIN_LED_G, g ? HIGH : LOW);
  digitalWrite(PIN_LED_B, b ? HIGH : LOW);
}

void blinkRGB(int times, int duration, bool r, bool g, bool b) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_LED_R, r ? HIGH : LOW);
    digitalWrite(PIN_LED_G, g ? HIGH : LOW);
    digitalWrite(PIN_LED_B, b ? HIGH : LOW);
    delay(duration);
    digitalWrite(PIN_LED_R, LOW);
    digitalWrite(PIN_LED_G, LOW);
    digitalWrite(PIN_LED_B, LOW);
    if (i < times - 1) delay(duration);
  }
  setLEDColor(curr_r, curr_g, curr_b);
}

void updateStateLED() {
  if (isRecording) {
    setLEDColor(HIGH, LOW, LOW); // Red: Recording
  } else {
    setLEDColor(LOW, HIGH, LOW); // Green: IDLE
  }
}"""
    code = code.replace(old_blink, new_blink)

    # 3. Setup pins
    code = code.replace("pinMode(PIN_LED, OUTPUT);", 
                        "pinMode(PIN_LED_R, OUTPUT);\n  pinMode(PIN_LED_G, OUTPUT);\n  pinMode(PIN_LED_B, OUTPUT);")

    # 4. updateStateLED in loop
    code = code.replace("if (isRecording) {\n    static uint32_t", 
                        "updateStateLED();\n\n  if (isRecording) {\n    static uint32_t")

    # 5. blinks
    code = code.replace("blinkLED(5, 100);", "setLEDColor(HIGH, LOW, HIGH); blinkRGB(5, 100, HIGH, LOW, HIGH);")
    code = code.replace("blinkLED(2, 100);", "blinkRGB(2, 100, HIGH, LOW, HIGH);")
    code = code.replace("blinkLED(3, 200);", "blinkRGB(3, 200, LOW, HIGH, LOW);")

    code = code.replace("digitalWrite(PIN_LED, HIGH);", "setLEDColor(HIGH, LOW, HIGH);")
    code = code.replace("digitalWrite(PIN_LED, LOW);", "setLEDColor(curr_r, curr_g, curr_b);")

    with open(path, "w", encoding="utf-8") as f:
        f.write(code)

process_right_hand()
process_left_hand()
print("LED API REFAC DONE")
