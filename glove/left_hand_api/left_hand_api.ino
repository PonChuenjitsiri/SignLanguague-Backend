#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <Preferences.h>
#include <Wire.h>
#include <vector>
#include <Adafruit_ADS1X15.h>

HardwareSerial HC12(1);
#define HC12_RX 20
#define HC12_TX 21
#define PIN_BUTTON 5
#define PIN_LED 10

// --- Flex Sensor Pins (Left Hand) — reversed from right ---
// Finger order: [0]=Thumb, [1]=Index, [2]=Middle(ADS), [3]=Ring, [4]=Pinky
const int FLEX_PIN_L[5] = {0, 1, -1, 3, 4}; // -1 = ADS1115
const int ADS_CHANNEL_MID = 1; // ADS1115 channel A0 for middle finger

Adafruit_ADS1115 ads;

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
GloveData lastData;
std::vector<GloveData> storage;
bool isRecording = false;

// HC12 Commands
const uint8_t CMD_START = 0xA1;
const uint8_t CMD_STOP = 0xA2;
const uint8_t CMD_CAL_LEFT = 0xA3; // Master → start left calibration
const uint8_t CMD_DATA = 0xD1;
const uint8_t CMD_END = 0xD2;
const uint8_t SIG_CANCEL = 0xEE;

// HC12 Calibration update bytes (Left → Right)
const uint8_t CAL_OPEN = 0xC1;
const uint8_t CAL_CLOSE = 0xC2;
const uint8_t CAL_DONE = 0xC3;

const unsigned long LONG_PRESS_MS = 3000;

unsigned long btnPressStart = 0;
bool isBtnHeld = false;
bool actionTriggered = false;

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
  pinMode(PIN_LED, OUTPUT);
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
  while (digitalRead(PIN_BUTTON) == HIGH)
    delay(10);
  delay(100);
  while (digitalRead(PIN_BUTTON) == LOW)
    delay(10);
  delay(100);
  while (digitalRead(PIN_BUTTON) == HIGH)
    delay(10);
  delay(100);
}

bool checkMovement(GloveData current) {
  if (storage.empty())
    return true;
  for (int i = 0; i < 5; i++)
    if (abs((int)current.flex[i] - (int)lastData.flex[i]) > t_flex)
      return true;
  for (int k = 0; k < 3; k++) {
    if (abs(current.accel[k] - lastData.accel[k]) > (T_ACCEL * 100))
      return true;
    if (abs(current.gyro[k] - lastData.gyro[k]) > (T_GYRO * 100))
      return true;
  }
  return false;
}

// Read all 5 flex sensors into raw[5]
void readFlexSensors(int raw[5]) {
  for (int i = 0; i < 5; i++) {
    if (FLEX_PIN_L[i] >= 0) {
      raw[i] = analogRead(FLEX_PIN_L[i]);
    } else if (adsReady) {
      int16_t adsVal = ads.readADC_SingleEnded(ADS_CHANNEL_MID);
      raw[i] = constrain(map(adsVal, 0, 26400, 0, 4095), 0, 4095);
    } else {
      raw[i] = 0;
    }
  }
}

// =====================================================
// Send calibration update to right hand (→ right → API)
// =====================================================
void sendCalUpdate(uint8_t calCmd, uint8_t round) {
  HC12.write(CMD_CAL_LEFT); // header
  HC12.write(calCmd);       // CAL_OPEN / CAL_CLOSE / CAL_DONE
  HC12.write(round);        // round number
  delay(10);
}

// =====================================================
// Calibrate LEFT hand
// Triggered by holding left button 3s
// Sends calibration steps via HC12 to right hand → right hand → API
// =====================================================
void calibrateLeft() {
  Serial.println("\n=== CALIBRATION MODE (LEFT HAND) ===");
  blinkLED(5, 100);

  long sumOpen[5] = {0, 0, 0, 0, 0};
  long sumClose[5] = {0, 0, 0, 0, 0};

  for (int round = 1; round <= 5; round++) {
    Serial.printf(">> ROUND %d/5\n", round);

    // --- Open hand ---
    Serial.println("   [ACTION] OPEN hand -> Press Button");
    sendCalUpdate(CAL_OPEN, round); // notify right hand → API
    waitForUserAction();
    { int rawF[5]; readFlexSensors(rawF);
      for (int i = 0; i < 5; i++) sumOpen[i] += rawF[i]; }

    // --- Close hand ---
    Serial.println("   [ACTION] CLOSE hand -> Press Button");
    sendCalUpdate(CAL_CLOSE, round); // notify right hand → API
    waitForUserAction();
    { int rawF[5]; readFlexSensors(rawF);
      for (int i = 0; i < 5; i++) sumClose[i] += rawF[i]; }

    blinkLED(2, 100);
  }

  // Calculate results
  Serial.println("\n=== CALIBRATION RESULTS ===");
  for (int i = 0; i < 5; i++) {
    flexMin[i] = sumOpen[i] / 5;
    flexMax[i] = sumClose[i] / 5;
    if (flexMin[i] == flexMax[i])
      flexMax[i] += 1;
    Serial.printf("  F%d Min: %d | Max: %d\n", i, flexMin[i], flexMax[i]);
  }
  t_flex = 10;
  isCalibrated = true;
  saveCalibrationToFlash();

  // Notify right hand → API: calibration done
  sendCalUpdate(CAL_DONE, 5);
  Serial.println(">> LEFT HAND CALIBRATION DONE!");

  blinkLED(3, 200);
  while (digitalRead(PIN_BUTTON) == HIGH)
    delay(10);
  isBtnHeld = false;
  actionTriggered = false;
}

// =====================================================
// Send recorded data to right hand (master)
// =====================================================
void sendDataToMaster() {
  Serial.printf("Sending %d frames to master...\n", storage.size());
  for (size_t i = 0; i < storage.size(); i++) {
    HC12.write(CMD_DATA);
    HC12.write((uint8_t *)&storage[i], sizeof(GloveData));
    delay(10);
  }
  HC12.write(CMD_END);
  Serial.println("Send Complete");
  storage.clear();
}

// =====================================================
// setup()
// =====================================================
void setup() {
  Serial.begin(115200);
  HC12.begin(115200, SERIAL_8N1, HC12_RX, HC12_TX);
  analogReadResolution(12);

  pinMode(PIN_BUTTON, INPUT);
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

  Serial.println("--- LEFT HAND READY ---");
  loadCalibrationFromFlash();
}

// =====================================================
// loop()
// =====================================================
void loop() {
  // =========================================
  // HC12 commands from right hand (master)
  // =========================================
  if (HC12.available()) {
    uint8_t cmd = HC12.read();
    if (cmd == CMD_START) {
      isRecording = true;
      storage.clear();
      memset(&lastData, 0, sizeof(GloveData));
      Serial.println("CMD: START → Recording");
    } else if (cmd == CMD_STOP) {
      isRecording = false;
      Serial.println("CMD: STOP → Sending data...");
      sendDataToMaster();
    }
  }

  // =========================================
  // Sensor recording (50Hz)
  // =========================================
  if (isRecording) {
    static uint32_t last_scan = 0;
    if (millis() - last_scan >= 20) {
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
        if (checkMovement(d)) {
          storage.push_back(d);
          lastData = d;
        }
      }
    }
  }

  // =========================================
  // Left button handling
  // =========================================
  static uint32_t lastDebounceTime = 0;
  static int lastReading = LOW;
  static int btnState = LOW;
  
  int reading = digitalRead(PIN_BUTTON);
  if (reading != lastReading) {
    lastDebounceTime = millis();
  }
  if ((millis() - lastDebounceTime) > 50) {
    if (reading != btnState) {
      btnState = reading;
    }
  }
  lastReading = reading;

  if (btnState == HIGH) {
    if (!isBtnHeld) {
      isBtnHeld = true;
      btnPressStart = millis();
      actionTriggered = false;
    } else {
      unsigned long heldTime = millis() - btnPressStart;
      
      // Continuous "button held" signal for 2-button stop logic
      static unsigned long lastHeldSignal = 0;
      if (heldTime > 500 && heldTime < LONG_PRESS_MS) {
        if (millis() - lastHeldSignal > 100) {
          HC12.write(0xEF); // SIG_LEFT_HELD
          lastHeldSignal = millis();
        }
      }

      // Long press 3s → calibrate left hand
      if (heldTime > LONG_PRESS_MS && !actionTriggered) {
        if (!isRecording) {
          actionTriggered = true;
          calibrateLeft();
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
        // Short press → send cancel/clear signal to right hand
        HC12.write(SIG_CANCEL);
        Serial.println("Sent CANCEL/CLEAR to master");
        // If recording, also clear local data
        if (isRecording) {
          storage.clear();
          memset(&lastData, 0, sizeof(GloveData));
          Serial.println("Local data cleared — redo gesture");
        }
      }
      isBtnHeld = false;
    }
  }
}
