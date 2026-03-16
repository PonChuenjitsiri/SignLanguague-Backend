#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <Preferences.h>
#include <Wire.h>
#include <vector>
#include <Adafruit_ADS1X15.h>

HardwareSerial HC12(1);
#define HC12_RX 20
#define HC12_TX 21

const int PIN_LED = 10;
const int PIN_BTN_R = 5;

// --- Flex Sensor Pins (Right Hand) ---
// Finger order: [0]=Pinky, [1]=Ring, [2]=Middle(ADS), [3]=Index, [4]=Thumb
const int FLEX_PIN_R[5] = {0, 1, -1, 3, 4}; // -1 = ADS1115
const int ADS_CHANNEL_MID = 1;              // ADS1115 channel A0 for middle finger

Adafruit_ADS1115 ads;

// Intervals
const unsigned long LONG_PRESS_MS = 3000;
const unsigned long SENSOR_INTERVAL = 20;

// --- Thresholds ---
const float T_ACCEL = 0.25;
const float T_GYRO = 20.0;
int t_flex = 10;

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
const uint8_t CMD_CAL_LEFT = 0xA3;
const uint8_t CMD_DATA = 0xD1;
const uint8_t CMD_END = 0xD2;

// Custom custom signals for Serial flow
const uint8_t SIG_DELETE = 0xED;
const uint8_t SIG_CANCEL = 0xEE;

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

unsigned long btnPressStart = 0;
bool isBtnHeld = false;
bool actionTriggered = false;

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
    t_flex = preferences.getInt("tFlex", 10);
    Serial.println(">> Calibration Loaded from Flash!");
    Serial.printf(">> Flex Threshold: %d\n", t_flex);
  }
  preferences.end();
}

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
// Output Data to Serial (for Python Extractor)
// =====================================================
void outputDataToSerial() {
  int maxFrames = max((int)bufL.size(), (int)bufR.size());
  if (maxFrames < 5) {
    Serial.println("SYS: DISCARD: too few frames");
    blinkLED(2, 50);
    return;
  }

  // Pad shorter buffer
  while (bufL.size() < maxFrames)
    bufL.push_back(bufL.size() > 0 ? bufL.back() : zeroData);
  while (bufR.size() < maxFrames)
    bufR.push_back(bufR.size() > 0 ? bufR.back() : zeroData);

  Serial.println("SYS: START_DATA");
  for (int i = 0; i < maxFrames; i++) {
    String row = "";
    if (i == 0)
      row += "S ";
    row += d2s(bufL[i]) + " " + d2s(bufR[i]);
    if (i == maxFrames - 1)
      row += " E";
    
    // Print actual data over serial port for Python script
    Serial.println(row);
  }
  Serial.println("SYS: END_DATA");
  blinkLED(3, 100);
}

// =====================================================
// Calibrate RIGHT hand (local)
// =====================================================
void calibrateRight() {
  Serial.println("\n=== CALIBRATION MODE (RIGHT HAND) ===");
  currentState = CALIBRATING_RIGHT;
  blinkLED(5, 100);
  digitalWrite(PIN_LED, HIGH);

  long sumOpen[5] = {0, 0, 0, 0, 0};
  long sumClose[5] = {0, 0, 0, 0, 0};

  for (int round = 1; round <= 5; round++) {
    Serial.printf(">> ROUND %d/5\n", round);

    Serial.println(" [ACTION] OPEN hand -> Press Button");
    waitForUserAction();
    digitalWrite(PIN_LED, LOW);
    {
      int rawF[5];
      readFlexSensors(rawF);
      for (int i = 0; i < 5; i++)
        sumOpen[i] += rawF[i];
    }

    Serial.println(" [ACTION] CLOSE hand -> Press Button");
    waitForUserAction();
    {
      int rawF[5];
      readFlexSensors(rawF);
      for (int i = 0; i < 5; i++)
        sumClose[i] += rawF[i];
    }

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

  Serial.println(">> RIGHT HAND CALIBRATION DONE!");
  blinkLED(3, 200);

  currentState = IDLE;
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  isBtnHeld = false;
  actionTriggered = false;
}

// =====================================================
// setup()
// =====================================================
void setup() {
  Serial.begin(115200);
  
  HC12.begin(115200, SERIAL_8N1, HC12_RX, HC12_TX);
  analogReadResolution(12);

  pinMode(PIN_BTN_R, INPUT);
  pinMode(PIN_LED, OUTPUT);
  Wire.begin(6, 7);
  mpu.setWire(&Wire);
  mpu.beginAccel();
  mpu.beginGyro();

  if (ads.begin(0x48)) {
    ads.setGain(GAIN_ONE);
    adsReady = true;
    Serial.println("SYS: ADS1115 ready!");
  } else {
    Serial.println("SYS: WARNING: ADS1115 not found!");
  }

  Serial.println("SYS: --- MASTER (RIGHT HAND SERIAL MODE) READY ---");
  loadCalibrationFromFlash();
}

// =====================================================
// loop()
// =====================================================
void loop() {
  // --- Read HC12 (left hand messages) ---
  if (HC12.available()) {
    uint8_t hdr = HC12.read();

    // Left hand DELETE signal (IDLE mode clear)
    if (hdr == SIG_DELETE) {
      if (currentState == IDLE) {
        Serial.println("DELETE"); // Tells Python to delete last record
        blinkLED(2, 100);
      }
    }
    // Left hand CANCEL/CLEAR signal (RECORDING mode clear)
    else if (hdr == SIG_CANCEL) {
      if (currentState == RECORDING) {
        Serial.println("CANCEL"); // Tells Python to discard this session
        bufL.clear();
        bufR.clear();
        blinkLED(3, 100);
        // Stay in RECORDING so user can just restart the gesture immediately
      }
    }
    // Left hand calibration updates (logging only, no backend)
    else if (hdr == CMD_CAL_LEFT) {
      delay(10);
      if (HC12.available() >= 2) {
        uint8_t calCmd = HC12.read();
        uint8_t calRnd = HC12.read();
        currentState = CALIBRATING_LEFT;
        
        if (calCmd == CAL_OPEN) {
          Serial.printf("SYS: [LEFT CAL] Round %d → open\n", calRnd);
        } else if (calCmd == CAL_CLOSE) {
          Serial.printf("SYS: [LEFT CAL] Round %d → close\n", calRnd);
        } else if (calCmd == CAL_DONE) {
          Serial.println("SYS: [LEFT CAL] Done!");
          currentState = IDLE;
        }
      }
    }
    // Left hand data frame
    else if (hdr == CMD_DATA && currentState == RECEIVING_LEFT) {
      GloveData temp;
      if (HC12.readBytes((uint8_t *)&temp, sizeof(GloveData)) == sizeof(GloveData)) {
        bufL.push_back(temp);
      }
    }
    // Left hand data complete
    else if (hdr == CMD_END && currentState == RECEIVING_LEFT) {
      Serial.println("SYS: Left data received. Outputting to Serial...");
      outputDataToSerial();
      bufL.clear();
      bufR.clear();
      currentState = IDLE;
      Serial.println("SYS: Ready for next gesture...");
    }
  }

  // --- Right button handling ---
  int btnR = digitalRead(PIN_BTN_R);

  if (btnR == HIGH) {
    if (!isBtnHeld) {
      isBtnHeld = true;
      btnPressStart = millis();
      actionTriggered = false;
    } else {
      // Long press -> Calibration
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
    // Button Released (Short press)
    if (isBtnHeld) {
      if (!actionTriggered && (millis() - btnPressStart > 50)) {
        if (currentState == IDLE) {
          // -> Start Gesture Session
          currentState = RECORDING;
          bufL.clear();
          bufR.clear();
          HC12.write(CMD_START); 
          Serial.println("SYS: >> GESTURE START");
          blinkLED(1, 100);
        } else if (currentState == RECORDING) {
          // -> Stop Gesture Session
          currentState = RECEIVING_LEFT;
          HC12.write(CMD_STOP);
          Serial.println("SYS: >> GESTURE STOP. Waiting for left hand data...");
          blinkLED(1, 100);
        }
      }
      isBtnHeld = false;
    }
  }

  // --- Sensor recording (50Hz) ---
  if (currentState == RECORDING) {
    static uint32_t last_scan = 0;
    if (millis() - last_scan >= SENSOR_INTERVAL) {
      last_scan = millis();
      if (mpu.accelUpdate() == 0 && mpu.gyroUpdate() == 0) {
        GloveData d;
        readMPU(d);
        int rawF[5];
        readFlexSensors(rawF);
        for (int i = 0; i < 5; i++) {
          if (isCalibrated) {
            int clipped = constrain(rawF[i], min(flexMin[i], flexMax[i]), max(flexMin[i], flexMax[i]));
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
