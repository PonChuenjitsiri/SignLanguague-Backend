#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <Preferences.h>
#include <Wire.h>
#include <vector>
#include <Adafruit_ADS1X15.h>

// --- WiFi & HTTP ---
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiProv.h>

HardwareSerial HC12(1);
#define HC12_RX 20
#define HC12_TX 21

const int PIN_LED = 10;
const int PIN_BTN_R = 5; // Right button (on right hand glove)

// --- Flex Sensor Pins (Right Hand) ---
// Finger order: [0]=Pinky, [1]=Ring, [2]=Middle(ADS), [3]=Index, [4]=Thumb
const int FLEX_PIN_R[5] = {0, 1, -1, 3, 4}; // -1 = ADS1115
const int ADS_CHANNEL_MID = 1; // ADS1115 channel A0 for middle finger

Adafruit_ADS1115 ads;

// =====================================================
// Config
// =====================================================
const char *service_name = "PROV_ESP32_C3";
const char *pop = "123456";

// ★ เปลี่ยน IP ให้ตรงกับ backend server ในเครือข่ายเดียวกัน
const String SERVER_URL = "http://bai-back.onepointfive.life";
const String DEVICE_ID = "default";

// Intervals
const unsigned long HEARTBEAT_INTERVAL = 5000; // 5 seconds
const unsigned long BOTH_BTN_HOLD_MS = 2000;   // hold both 2s = stop
const unsigned long LONG_PRESS_MS = 3000;      // hold 3s = calibrate
const unsigned long SENSOR_INTERVAL = 20;      // 50Hz sampling

// --- Thresholds ---
const float T_ACCEL = 0.25;
const float T_GYRO = 20.0;
int t_flex = 300;

int flexMin[5] = {0, 0, 0, 0, 0};
int flexMax[5] = {4095, 4095, 4095, 4095, 4095};
bool isCalibrated = false;

Preferences preferences;

struct GloveData {
  uint16_t flex[5];
  int16_t accel[3];
  int16_t gyro[3];
};

MPU9250_asukiaaa mpu;
bool adsReady = false;

// HC12 Commands
const uint8_t CMD_START = 0xA1;
const uint8_t CMD_STOP = 0xA2;
const uint8_t CMD_CAL_LEFT = 0xA3; // ใหม่: สั่งซ้าย calibrate
const uint8_t CMD_DATA = 0xD1;
const uint8_t CMD_END = 0xD2;
const uint8_t SIG_CANCEL = 0xEE; // left btn short press → clear

// HC12 Calibration updates from left hand
const uint8_t CAL_OPEN = 0xC1;
const uint8_t CAL_CLOSE = 0xC2;
const uint8_t CAL_DONE = 0xC3;

// Buffers
std::vector<GloveData> bufL, bufR;
GloveData lastDataR;
GloveData zeroData = {{0, 0, 0, 0, 0}, {0, 0, 0}, {0, 0, 0}};

// State machine
enum State {
  IDLE,
  RECORDING,
  RECEIVING_LEFT,
  CALIBRATING_RIGHT,
  CALIBRATING_LEFT
};
State currentState = IDLE;

// WiFi
bool is_connected = false;

// Button state
unsigned long btnPressStart = 0;
bool isBtnHeld = false;
bool actionTriggered = false;

// Heartbeat timer
unsigned long lastHeartbeat = 0;

// Both-button hold tracking
unsigned long bothBtnStart = 0;
bool bothBtnActive = false;

// Left button signal from left hand (via HC12)
bool leftBtnPressed = false;

// Calibration tracking
int calRound = 0;
String calStep = "";

// =====================================================
// WiFi Provisioning Event Handler
// =====================================================
void SysProvEvent(arduino_event_t *sys_event) {
  switch (sys_event->event_id) {
  case ARDUINO_EVENT_PROV_START:
    Serial.println("\nProvisioning Started. Open 'ESP BLE Provisioning' App!");
    Serial.print("Device Name: ");
    Serial.println(service_name);
    break;
  case ARDUINO_EVENT_WIFI_STA_GOT_IP:
    Serial.print("\nConnected! IP: ");
    Serial.println(WiFi.localIP());
    is_connected = true;
    break;
  case ARDUINO_EVENT_PROV_CRED_RECV:
    Serial.println("\nReceived Wi-Fi credentials...");
    break;
  case ARDUINO_EVENT_PROV_END:
    Serial.println("\nProvisioning Ended.");
    break;
  default:
    break;
  }
}

// =====================================================
// HTTP Helpers
// =====================================================
bool httpPost(String path, String jsonBody) {
  if (!is_connected)
    return false;

  HTTPClient http;
  http.begin(SERVER_URL + path);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);

  int code = http.POST(jsonBody);
  String resp = http.getString();
  http.end();

  if (code > 0) {
    Serial.printf("[HTTP %d] %s → %s\n", code, path.c_str(), resp.c_str());
    return (code >= 200 && code < 300);
  } else {
    Serial.printf("[HTTP ERROR] %s → %s\n", path.c_str(),
                  http.errorToString(code).c_str());
    return false;
  }
}

// =====================================================
// Heartbeat
// =====================================================
void sendHeartbeat() {
  httpPost("/api/glove/heartbeat", "{\"device_id\":\"" + DEVICE_ID + "\"}");
}

// =====================================================
// Calibration API
// =====================================================
void apiCalibrateStart(String hand) {
  httpPost("/api/glove/calibrate/start",
           "{\"device_id\":\"" + DEVICE_ID + "\",\"hand\":\"" + hand + "\"}");
}

void apiCalibrateUpdate(String step, int round) {
  httpPost("/api/glove/calibrate/update",
           "{\"device_id\":\"" + DEVICE_ID + "\",\"step\":\"" + step +
               "\",\"round\":" + String(round) + "}");
}

// =====================================================
// Gesture API
// =====================================================
void apiGestureStart() {
  httpPost("/api/glove/gesture/start", "{\"device_id\":\"" + DEVICE_ID + "\"}");
}

void apiGestureStop() {
  httpPost("/api/glove/gesture/stop", "{\"device_id\":\"" + DEVICE_ID + "\"}");
}

// =====================================================
// Send prediction data via HTTP
// =====================================================
void sendPredictRaw() {
  int maxFrames = max((int)bufL.size(), (int)bufR.size());
  if (maxFrames < 5) {
    Serial.println("DISCARD: too few frames");
    blinkLED(2, 50);
    return;
  }

  // Pad shorter buffer
  while (bufL.size() < maxFrames)
    bufL.push_back(bufL.size() > 0 ? bufL.back() : zeroData);
  while (bufR.size() < maxFrames)
    bufR.push_back(bufR.size() > 0 ? bufR.back() : zeroData);

  // Build raw_data string (S ... E format)
  String rawData = "";
  for (int i = 0; i < maxFrames; i++) {
    if (i == 0)
      rawData += "S ";
    rawData += d2s(bufL[i]) + " " + d2s(bufR[i]);
    if (i == maxFrames - 1)
      rawData += " E";
    rawData += "\n";
  }

  // Escape for JSON
  rawData.replace("\"", "\\\"");
  rawData.replace("\n", "\\n");

  String json = "{\"raw_data\":\"" + rawData + "\"}";

  Serial.printf("Sending %d frames to /predict/raw...\n", maxFrames);
  httpPost("/api/sensor-data/predict/raw", json);
  blinkLED(3, 100);
}

// =====================================================
// Flash Memory
// =====================================================
void saveCalibrationToFlash() {
  preferences.begin("glove-cal", false);
  preferences.putBytes("fMin", flexMin, sizeof(flexMin));
  preferences.putBytes("fMax", flexMax, sizeof(flexMax));
  preferences.putInt("tFlex", t_flex);
  preferences.putBool("isCal", true);
  preferences.end();
  Serial.println(">> Calibration Saved to Flash!");
}

void loadCalibrationFromFlash() {
  preferences.begin("glove-cal", true);
  isCalibrated = preferences.getBool("isCal", false);
  if (isCalibrated) {
    preferences.getBytes("fMin", flexMin, sizeof(flexMin));
    preferences.getBytes("fMax", flexMax, sizeof(flexMax));
    t_flex = preferences.getInt("tFlex", 200);
    Serial.println(">> Calibration Loaded from Flash!");
    Serial.printf(">> Flex Threshold: %d\n", t_flex);
  }
  preferences.end();
}

// =====================================================
// Utilities
// =====================================================
void blinkLED(int times, int duration) {
  for (int i = 0; i < times; i++) {
    digitalWrite(PIN_LED, HIGH);
    delay(duration);
    digitalWrite(PIN_LED, LOW);
    if (i < times - 1)
      delay(duration);
  }
}

void readMPU(GloveData &d) {
  mpu.accelUpdate();
  mpu.gyroUpdate();
  d.accel[0] = (int16_t)(mpu.accelX() * 100);
  d.accel[1] = (int16_t)(mpu.accelY() * 100);
  d.accel[2] = (int16_t)(mpu.accelZ() * 100);
  d.gyro[0] = (int16_t)(mpu.gyroX() * 100);
  d.gyro[1] = (int16_t)(mpu.gyroY() * 100);
  d.gyro[2] = (int16_t)(mpu.gyroZ() * 100);
}

void waitForUserAction() {
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  delay(100);
  while (digitalRead(PIN_BTN_R) == LOW)
    delay(10);
  delay(100);
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  delay(100);
}

String d2s(GloveData d) {
  char b[128];
  snprintf(b, sizeof(b), "%d %d %d %d %d %.2f %.2f %.2f %.2f %.2f %.2f",
           d.flex[0], d.flex[1], d.flex[2], d.flex[3], d.flex[4],
           d.accel[0] / 100.0, d.accel[1] / 100.0, d.accel[2] / 100.0,
           d.gyro[0] / 100.0, d.gyro[1] / 100.0, d.gyro[2] / 100.0);
  return String(b);
}

// Read all 5 flex sensors into raw[5]
void readFlexSensors(int raw[5]) {
  for (int i = 0; i < 5; i++) {
    if (FLEX_PIN_R[i] >= 0) {
      raw[i] = analogRead(FLEX_PIN_R[i]);
    } else if (adsReady) {
      int16_t adsVal = ads.readADC_SingleEnded(ADS_CHANNEL_MID);
      raw[i] = constrain(map(adsVal, 0, 26400, 0, 4095), 0, 4095);
    } else {
      raw[i] = 0;
    }
  }
}

bool checkMovementR(GloveData current) {
  if (bufR.empty())
    return true;
  for (int i = 0; i < 5; i++)
    if (abs((int)current.flex[i] - (int)lastDataR.flex[i]) > t_flex)
      return true;
  for (int k = 0; k < 3; k++) {
    if (abs(current.accel[k] - lastDataR.accel[k]) > (T_ACCEL * 100))
      return true;
    if (abs(current.gyro[k] - lastDataR.gyro[k]) > (T_GYRO * 100))
      return true;
  }
  return false;
}

// =====================================================
// Calibrate RIGHT hand (local)
// =====================================================
void calibrateRight() {
  Serial.println("\n=== CALIBRATION MODE (RIGHT HAND) ===");
  currentState = CALIBRATING_RIGHT;
  apiCalibrateStart("right");
  blinkLED(5, 100);
  digitalWrite(PIN_LED, HIGH);

  long sumOpen[5] = {0, 0, 0, 0, 0};
  long sumClose[5] = {0, 0, 0, 0, 0};

  for (int round = 1; round <= 5; round++) {
    Serial.printf(">> ROUND %d/5\n", round);

    // --- Open hand ---
    Serial.println(" [ACTION] OPEN hand -> Press Button");
    apiCalibrateUpdate("open", round);
    waitForUserAction();
    digitalWrite(PIN_LED, LOW);
    { int rawF[5]; readFlexSensors(rawF);
      for (int i = 0; i < 5; i++) sumOpen[i] += rawF[i]; }
    Serial.println(" Read Open Done.");

    // --- Close hand ---
    Serial.println(" [ACTION] CLOSE hand -> Press Button");
    apiCalibrateUpdate("close", round);
    waitForUserAction();
    { int rawF[5]; readFlexSensors(rawF);
      for (int i = 0; i < 5; i++) sumClose[i] += rawF[i]; }
    Serial.println(" Read Close Done.");

    blinkLED(2, 100);
    if (round < 5)
      digitalWrite(PIN_LED, HIGH);
  }

  // Calculate results
  for (int i = 0; i < 5; i++) {
    flexMin[i] = sumOpen[i] / 5;
    flexMax[i] = sumClose[i] / 5;
    if (flexMin[i] == flexMax[i])
      flexMax[i] += 1;
    Serial.printf(" F%d Min: %d | Max: %d\n", i, flexMin[i], flexMax[i]);
  }
  t_flex = 10;
  isCalibrated = true;
  saveCalibrationToFlash();

  apiCalibrateUpdate("done", 5);
  Serial.println(">> RIGHT HAND CALIBRATION DONE!");
  blinkLED(3, 200);

  currentState = IDLE;
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  isBtnHeld = false;
  actionTriggered = false;
}

// =====================================================
// Handle left hand calibration updates (via HC12)
// =====================================================
void handleLeftCalibrationUpdate(uint8_t cmd, uint8_t round) {
  currentState = CALIBRATING_LEFT;

  if (cmd == CAL_OPEN) {
    Serial.printf("[LEFT CAL] Round %d → open\n", round);
    apiCalibrateUpdate("open", round);
  } else if (cmd == CAL_CLOSE) {
    Serial.printf("[LEFT CAL] Round %d → close\n", round);
    apiCalibrateUpdate("close", round);
  } else if (cmd == CAL_DONE) {
    Serial.println("[LEFT CAL] Done!");
    apiCalibrateUpdate("done", 5);
    currentState = IDLE;
  }
}

// =====================================================
// setup()
// =====================================================
void setup() {
  Serial.begin(115200);

  // WiFi Provisioning
  WiFi.onEvent(SysProvEvent);
  WiFiProv.beginProvision(NETWORK_PROV_SCHEME_BLE,
                          NETWORK_PROV_SCHEME_HANDLER_FREE_BTDM,
                          NETWORK_PROV_SECURITY_1, pop, service_name);

  HC12.begin(115200, SERIAL_8N1, HC12_RX, HC12_TX);
  analogReadResolution(12);

  pinMode(PIN_BTN_R, INPUT);
  pinMode(PIN_LED, OUTPUT);
  Wire.begin(6, 7);
  mpu.setWire(&Wire);
  mpu.beginAccel();
  mpu.beginGyro();

  // ADS1115 init
  if (ads.begin(0x48)) {
    ads.setGain(GAIN_ONE);
    adsReady = true;
    Serial.println("ADS1115 ready!");
  } else {
    Serial.println("WARNING: ADS1115 not found!");
  }

  Serial.println("\n--- MASTER (RIGHT HAND) READY ---");
  loadCalibrationFromFlash();
}

// =====================================================
// loop()
// =====================================================
void loop() {
  // --- WiFi connect notice ---
  static bool was_connected = false;
  if (is_connected && !was_connected) {
    Serial.println("WiFi connected! Glove running...");
    was_connected = true;
  }

  // =========================================
  // Heartbeat every 5 seconds
  // =========================================
  if (is_connected && millis() - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    lastHeartbeat = millis();
    sendHeartbeat();
  }

  // =========================================
  // Read HC12 (left hand messages)
  // =========================================
  if (HC12.available()) {
    uint8_t hdr = HC12.read();

    // Left hand cancel/clear signal
    if (hdr == SIG_CANCEL) {
      if (currentState == RECORDING) {
        Serial.println("[LEFT BTN] Clear data → restart recording");
        bufL.clear();
        bufR.clear();
        blinkLED(2, 100);
        // Stay in RECORDING — user can redo gesture
      }
    }
    // Left hand calibration updates
    else if (hdr == CMD_CAL_LEFT) {
      // Next byte = calibration sub-command, then round
      delay(10);
      if (HC12.available() >= 2) {
        uint8_t calCmd = HC12.read();
        uint8_t calRnd = HC12.read();

        if (calCmd == CAL_OPEN || calCmd == CAL_CLOSE) {
          apiCalibrateStart("left"); // ensure started
          handleLeftCalibrationUpdate(calCmd, calRnd);
        } else if (calCmd == CAL_DONE) {
          handleLeftCalibrationUpdate(calCmd, calRnd);
        }
      }
    }
    // Left hand data frame (during RECEIVING_LEFT)
    else if (hdr == CMD_DATA && currentState == RECEIVING_LEFT) {
      GloveData temp;
      if (HC12.readBytes((uint8_t *)&temp, sizeof(GloveData)) ==
          sizeof(GloveData)) {
        bufL.push_back(temp);
      }
    }
    // Left hand data complete
    else if (hdr == CMD_END && currentState == RECEIVING_LEFT) {
      Serial.println("Left data received. Sending to backend...");
      sendPredictRaw();
      bufL.clear();
      bufR.clear();
      currentState =
          RECORDING; // Stay in gesture session, ready for next gesture
    }
  }

  // =========================================
  // Right button handling
  // =========================================
  int btnR = digitalRead(PIN_BTN_R);

  if (btnR == HIGH) {
    if (!isBtnHeld) {
      isBtnHeld = true;
      btnPressStart = millis();
      actionTriggered = false;
    } else {
      // Long press 3s → calibrate right
      if (millis() - btnPressStart > LONG_PRESS_MS && !actionTriggered) {
        if (currentState == IDLE) {
          actionTriggered = true;
          calibrateRight();
          isBtnHeld = false;
          btnPressStart = millis();
          return;
        }
      }
    }
  } else {
    // Button released
    if (isBtnHeld) {
      if (!actionTriggered && (millis() - btnPressStart > 50)) {
        // Short press
        if (currentState == IDLE) {
          // → Start gesture session
          currentState = RECORDING;
          bufL.clear();
          bufR.clear();
          HC12.write(CMD_START); // Tell left hand to start recording
          apiGestureStart();
          Serial.println(">> GESTURE START");
          blinkLED(1, 100);
        } else if (currentState == RECORDING) {
          // → Stop recording right + request left data → send to backend
          currentState = RECEIVING_LEFT;
          HC12.write(CMD_STOP); // Tell left hand to send data
          Serial.println(">> Waiting for left hand data...");
          blinkLED(1, 100);
        }
      }
      isBtnHeld = false;
    }
  }

  // =========================================
  // Check both-button hold (2s → gesture stop)
  // Left hand sends a special signal when both buttons held
  // For simplicity: left button held will send continuous SIG_CANCEL
  // If right button is also held → both buttons → gesture stop
  // =========================================
  // Both buttons held detection:
  // Right button is held AND we receive SIG_CANCEL from left while held
  if (isBtnHeld && leftBtnPressed && currentState == RECORDING) {
    if (!bothBtnActive) {
      bothBtnActive = true;
      bothBtnStart = millis();
    } else if (millis() - bothBtnStart >= BOTH_BTN_HOLD_MS) {
      // Both held 2s → stop gesture session
      Serial.println(">> BOTH BUTTONS 2s → GESTURE STOP");
      apiGestureStop();
      currentState = IDLE;
      bufL.clear();
      bufR.clear();
      HC12.write(CMD_STOP);
      blinkLED(5, 100);
      bothBtnActive = false;
      leftBtnPressed = false;
      isBtnHeld = false;
      actionTriggered = true;
      return;
    }
  } else {
    bothBtnActive = false;
    leftBtnPressed = false;
  }

  // =========================================
  // Sensor recording (50Hz)
  // =========================================
  if (currentState == RECORDING) {
    static uint32_t last_scan = 0;
    if (millis() - last_scan >= SENSOR_INTERVAL) {
      last_scan = millis();
      if (mpu.accelUpdate() == 0 && mpu.gyroUpdate() == 0) {
        GloveData d;
        readMPU(d);
        int rawF[5]; readFlexSensors(rawF);
        for (int i = 0; i < 5; i++) {
          if (isCalibrated) {
            int clipped = constrain(rawF[i], min(flexMin[i], flexMax[i]),
                                    max(flexMin[i], flexMax[i]));
            d.flex[i] = map(clipped, flexMin[i], flexMax[i], 0, 100);
          } else {
            d.flex[i] = rawF[i];
          }
        }
        if (checkMovementR(d)) {
          bufR.push_back(d);
          lastDataR = d;
        }
      }
    }
    // Frame limit
    if (bufR.size() > 300) {
      currentState = RECEIVING_LEFT;
      HC12.write(CMD_STOP);
    }
  }
}
