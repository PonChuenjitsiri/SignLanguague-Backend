#include <Adafruit_ADS1X15.h>
#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <Preferences.h>
#include <Wire.h>
#include <vector>


HardwareSerial HC12(1);
#define HC12_RX 20
#define HC12_TX 21
#define PIN_BUTTON 5

// --- RGB LED Pins ---
#define PIN_LED_B 10
#define PIN_LED_G 9
#define PIN_LED_R 8

// --- Flex Sensor Pins (Left Hand) ---
const int FLEX_PIN_L[5] = {0, 1, -1, 3, 4}; // -1 = ADS1115
const int ADS_CHANNEL_MID = 3;
const uint8_t SIG_VBAT = 0xEB;
const int ADS_CH_VBAT = 1;
const float VBAT_RATIO = 2.0f;

const unsigned long VBAT_INTERVAL = 5000;
unsigned long lastVbatSend = 0;

Adafruit_ADS1115 ads;

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
const uint8_t CMD_CAL_LEFT = 0xA3;
const uint8_t CMD_ABORT = 0xA4;
const uint8_t CMD_DATA = 0xD1;
const uint8_t CMD_END = 0xD2;
const uint8_t SIG_CANCEL = 0xEE;

const uint8_t CAL_OPEN = 0xC1;
const uint8_t CAL_CLOSE = 0xC2;
const uint8_t CAL_DONE = 0xC3;

const unsigned long LONG_PRESS_MS = 3000;

unsigned long btnPressStart = 0;
bool isBtnHeld = false;
bool actionTriggered = false;

// =====================================================
// RGB LED Control
// =====================================================
void setLED(bool r, bool g, bool b) {
  digitalWrite(PIN_LED_R, r ? HIGH : LOW);
  digitalWrite(PIN_LED_G, g ? HIGH : LOW);
  digitalWrite(PIN_LED_B, b ? HIGH : LOW);
}

void blinkRGB(bool r, bool g, bool b, int times, int duration) {
  for (int i = 0; i < times; i++) {
    setLED(r, g, b);
    delay(duration);
    setLED(0, 0, 0);
    if (i < times - 1)
      delay(duration);
  }
}

// =====================================================
// Flash Memory & Utils
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
  }
  preferences.end();
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

void sendCalUpdate(uint8_t calCmd, uint8_t round) {
  HC12.write(CMD_CAL_LEFT);
  HC12.write(calCmd);
  HC12.write(round);
  delay(10);
}

// =====================================================
// Calibrate LEFT hand
// =====================================================
void calibrateLeft() {
  Serial.println("\n=== CALIBRATION MODE (LEFT HAND) ===");
  blinkRGB(1, 0, 1, 5, 100); // สีม่วง 5 ที

  long sumOpen[5] = {0, 0, 0, 0, 0};
  long sumClose[5] = {0, 0, 0, 0, 0};

  for (int round = 1; round <= 5; round++) {
    Serial.println("   [ACTION] OPEN hand -> Press Button");
    setLED(1, 0, 1);
    sendCalUpdate(CAL_OPEN, round);
    waitForUserAction();
    {
      int rawF[5];
      readFlexSensors(rawF);
      for (int i = 0; i < 5; i++)
        sumOpen[i] += rawF[i];
    }
    setLED(0, 0, 0);
    delay(100);

    Serial.println("   [ACTION] CLOSE hand -> Press Button");
    setLED(1, 0, 1);
    sendCalUpdate(CAL_CLOSE, round);
    waitForUserAction();
    {
      int rawF[5];
      readFlexSensors(rawF);
      for (int i = 0; i < 5; i++)
        sumClose[i] += rawF[i];
    }

    blinkRGB(1, 0, 1, 2, 100);
  }

  for (int i = 0; i < 5; i++) {
    flexMin[i] = sumOpen[i] / 5;
    flexMax[i] = sumClose[i] / 5;
    if (flexMin[i] == flexMax[i])
      flexMax[i] += 1;
  }
  t_flex = 10;
  isCalibrated = true;
  saveCalibrationToFlash();

  sendCalUpdate(CAL_DONE, 5);
  blinkRGB(0, 1, 0, 3, 200); // กระพริบเขียว 3 ทีเสร็จสิ้น
  setLED(0, 0, 1);           // กลับไปโหมด IDLE สีน้ำเงิน

  while (digitalRead(PIN_BUTTON) == HIGH)
    delay(10);
  isBtnHeld = false;
  actionTriggered = false;
}

void sendDataToMaster() {
  setLED(0, 1, 0); // โชว์สีเขียวค้างตอนส่งข้อมูล
  for (size_t i = 0; i < storage.size(); i++) {
    HC12.write(CMD_DATA);
    HC12.write((uint8_t *)&storage[i], sizeof(GloveData));
    delay(10);
  }
  HC12.write(CMD_END);
  storage.clear();
  setLED(0, 0, 1); // ส่งเสร็จกลับเป็นสีน้ำเงิน
}

float readBatteryVoltage() {
  if (!adsReady)
    return -1.0f;
  int16_t raw = ads.readADC_SingleEnded(ADS_CH_VBAT);
  return (raw * 0.125f / 1000.0f) * VBAT_RATIO;
}

void sendVbatToMaster() {
  float v = readBatteryVoltage();
  if (v < 0)
    return;
  int16_t mv = (int16_t)(v * 1000.0f);
  HC12.write(SIG_VBAT);
  HC12.write((uint8_t)(mv >> 8));
  HC12.write((uint8_t)(mv & 0xFF));
}

void setup() {
  Serial.begin(115200);
  HC12.begin(115200, SERIAL_8N1, HC12_RX, HC12_TX);
  analogReadResolution(12);

  pinMode(PIN_BUTTON, INPUT);
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);

  Wire.begin(6, 7);
  mpu.setWire(&Wire);
  mpu.beginAccel();
  mpu.beginGyro();

  if (ads.begin(0x48)) {
    ads.setGain(GAIN_ONE);
    adsReady = true;
  }

  loadCalibrationFromFlash();
  setLED(0, 0, 1); // IDLE สีน้ำเงิน
  Serial.println("--- LEFT HAND (API) READY ---");

  delay(300); // ป้องกันบั๊กกดปุ่มตอนเปิดเครื่อง
  while (digitalRead(PIN_BUTTON) == HIGH)
    delay(10);
  isBtnHeld = false;
  actionTriggered = false;
}

void loop() {
  if (HC12.available()) {
    uint8_t cmd = HC12.read();
    if (cmd == CMD_START) {
      isRecording = true;
      storage.clear();
      memset(&lastData, 0, sizeof(GloveData));
      setLED(1, 0, 0); // RECORDING สีแดง
    } else if (cmd == CMD_STOP) {
      isRecording = false;
      sendDataToMaster();
    } else if (cmd == CMD_ABORT) {
      isRecording = false;
      storage.clear();
      memset(&lastData, 0, sizeof(GloveData));
      blinkRGB(1, 1, 0, 3, 150); // กระพริบเหลือง 3 ที (โดนยกเลิก)
      setLED(0, 0, 1);           // กลับไปสีน้ำเงิน
    }
  }

  if (millis() - lastVbatSend >= VBAT_INTERVAL) {
    lastVbatSend = millis();
    sendVbatToMaster();
  }

  if (isRecording) {
    static uint32_t last_scan = 0;
    if (millis() - last_scan >= 20) {
      last_scan = millis();
      if (mpu.accelUpdate() == 0 && mpu.gyroUpdate() == 0) {
        GloveData d;
        readMPU(d);
        int rawF[5];
        readFlexSensors(rawF);
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
    if (storage.size() >= 300) {
      isRecording = false;
      setLED(0, 0, 1);
    }
  }

  // =========================================
  // ระบบปุ่มกดมือซ้าย (แก้ไขบั๊กกดค้างแล้วลั่น)
  // =========================================
  int reading = digitalRead(PIN_BUTTON);
  static uint32_t lastDebounceTime = 0;
  static int lastReading = LOW;
  static int btnState = LOW;

  if (reading != lastReading)
    lastDebounceTime = millis();
  if ((millis() - lastDebounceTime) > 50) {
    if (reading != btnState)
      btnState = reading;
  }
  lastReading = reading;

  if (btnState == HIGH) {
    if (!isBtnHeld) {
      isBtnHeld = true;
      btnPressStart = millis();
      actionTriggered = false;
    } else {
      unsigned long heldTime = millis() - btnPressStart;

      // กดค้าง 3 วิ → calibrate
      if (heldTime > LONG_PRESS_MS && !actionTriggered) {
        if (!isRecording) {
          actionTriggered = true; // 🌟 ล็อคไว้
          calibrateLeft();
        }
      }
    }
  } else {
    // 🌟 จังหวะยกนิ้วออกจากปุ่ม 🌟
    if (isBtnHeld) {
      if (!actionTriggered && (millis() - btnPressStart > 50)) {
        // กดสั้น → ยกเลิกท่าทาง
        if (isRecording) {
          storage.clear();
          memset(&lastData, 0, sizeof(GloveData));
          HC12.write(SIG_CANCEL);
          blinkRGB(1, 1, 0, 3, 100); // กระพริบเหลือง 3 ที
          setLED(1, 0, 0);           // เปิดสีแดงรอกดอัดต่อ
        }
      }
      isBtnHeld = false; // 🌟 รีเซ็ตปุ่มที่นี่ที่เดียว
    }
  }
}