#include <Adafruit_ADS1X15.h>
#include <Arduino.h>
#include <HTTPClient.h>
#include <MPU9250_asukiaaa.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h> // 🌟 เพิ่มไลบรารีสำหรับ HTTPS
#include <WiFiProv.h>
#include <Wire.h>
#include <vector>

HardwareSerial HC12(1);
#define HC12_RX 20
#define HC12_TX 21
#define PIN_BTN_R 5

// --- RGB LED Pins ---
#define PIN_LED_B 10
#define PIN_LED_G 9
#define PIN_LED_R 8

const int FLEX_PIN_R[5] = {4, 3, -1, 1, 0};
const int ADS_CHANNEL_MID = 3;
const uint8_t SIG_VBAT = 0xEB;
const int ADS_CH_VBAT = 1;
const float VBAT_RATIO = 2.0;

float leftVoltage = -1.0f;

Adafruit_ADS1115 ads;

const char *service_name = "PROV_ESP32_C3";
const char *pop = "123456";

const String SERVER_URL = "https://smb.pon-hub.com";
String DEVICE_ID = "default";

const unsigned long HEARTBEAT_INTERVAL = 5000;
const unsigned long STOP_HOLD_MS = 2000;
const unsigned long LONG_PRESS_MS = 3000;
const unsigned long SENSOR_INTERVAL = 20;

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

std::vector<GloveData> bufL, bufR;
GloveData lastDataR;
GloveData zeroData = {{0, 0, 0, 0, 0}, {0, 0, 0}, {0, 0, 0}};

enum State {
  IDLE,
  RECORDING,
  RECEIVING_LEFT,
  CALIBRATING_RIGHT,
  CALIBRATING_LEFT
};
State currentState = IDLE;

bool is_connected = false;
bool is_registered = false;
unsigned long btnPressStart = 0;
bool isBtnHeld = false;
bool actionTriggered = false;
unsigned long lastHeartbeat = 0;

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
// HTTP Helpers (อัปเดต HTTPS และเพิ่มฟังก์ชัน Register)
// =====================================================

// 🌟 อัปเดตฟังก์ชันลงทะเบียน 🌟
void registerDeviceWithBackend() {
  if (WiFi.status() == WL_CONNECTED) {
    WiFiClientSecure secureClient;
    secureClient.setInsecure();

    HTTPClient http;
    String registerUrl = SERVER_URL + "/api/devices/";

    http.begin(secureClient, registerUrl);
    http.addHeader("Content-Type", "application/json");

    String body = "{\"device_id\":\"" + DEVICE_ID + "\"}";

    Serial.println("\n[System] Registering Device ID: " + DEVICE_ID);
    int code = http.POST(body);

    if (code > 0) {
      if (code == 201 || code == 200) {
        Serial.println("🎉 [SUCCESS] Device registered on Backend!");
        is_registered = true; // 👈 เพิ่มบรรทัดนี้
      } else if (code == 400) {
        Serial.println("ℹ️ [INFO] Device already registered.");
        is_registered = true; // 👈 เพิ่มบรรทัดนี้
      } else {
        Serial.println("⚠️ [WARN] Unexpected code: " + String(code));
      }
    } else {
      Serial.println("❌ [ERROR] Registration failed. Code: " + String(code));
    }
    http.end();
  }
}

// 🌟 อัปเดต HTTP Post ให้ใช้ WiFiClientSecure 🌟
bool httpPost(String path, String jsonBody) {
  if (!is_connected)
    return false;

  WiFiClientSecure secureClient;
  secureClient.setInsecure(); // ข้ามตรวจสอบ SSL

  HTTPClient http;
  http.begin(secureClient, SERVER_URL + path); // ใช้ secureClient ผูกกับ URL
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);

  int code = http.POST(jsonBody);
  http.end();

  return (code >= 200 && code < 300);
}

void sendHeartbeat() {
  float rightV = readBatteryVoltage();
  String body = "{\"device_id\":\"" + DEVICE_ID + "\"," +
                "\"right_voltage\":" + String(rightV, 3) + "," +
                "\"left_voltage\":" + String(leftVoltage, 3) + "}";
  httpPost("/api/glove/heartbeat", body);
}

void apiCalibrateStart(String hand) {
  httpPost("/api/glove/calibrate/start",
           "{\"device_id\":\"" + DEVICE_ID + "\",\"hand\":\"" + hand + "\"}");
}

void apiCalibrateUpdate(String step, int round) {
  httpPost("/api/glove/calibrate/update",
           "{\"device_id\":\"" + DEVICE_ID + "\",\"step\":\"" + step +
               "\",\"round\":" + String(round) + "}");
}

void apiGestureStart() {
  httpPost("/api/glove/gesture/start", "{\"device_id\":\"" + DEVICE_ID + "\"}");
}

void apiGestureStop() {
  httpPost("/api/glove/gesture/stop", "{\"device_id\":\"" + DEVICE_ID + "\"}");
}

String d2s(GloveData d) {
  char b[128];
  snprintf(b, sizeof(b), "%d %d %d %d %d %.2f %.2f %.2f %.2f %.2f %.2f",
           d.flex[0], d.flex[1], d.flex[2], d.flex[3], d.flex[4],
           d.accel[0] / 100.0, d.accel[1] / 100.0, d.accel[2] / 100.0,
           d.gyro[0] / 100.0, d.gyro[1] / 100.0, d.gyro[2] / 100.0);
  return String(b);
}

void sendPredictRaw() {
  int maxFrames = max((int)bufL.size(), (int)bufR.size());
  if (maxFrames < 5) {
    blinkRGB(1, 0, 0, 2, 100);
    return;
  }
  while (bufL.size() < maxFrames)
    bufL.push_back(bufL.size() > 0 ? bufL.back() : zeroData);
  while (bufR.size() < maxFrames)
    bufR.push_back(bufR.size() > 0 ? bufR.back() : zeroData);

  String rawData = "";
  for (int i = 0; i < maxFrames; i++) {
    if (i == 0)
      rawData += "S ";
    rawData += d2s(bufL[i]) + " " + d2s(bufR[i]);
    if (i == maxFrames - 1)
      rawData += " E";
    rawData += "\n";
  }
  rawData.replace("\"", "\\\"");
  rawData.replace("\n", "\\n");

  String json =
      "{\"device_id\":\"" + DEVICE_ID + "\",\"raw_data\":\"" + rawData + "\"}";
  Serial.printf("Sending %d frames to /predict/raw...\n", maxFrames);

  if (httpPost("/predict/",
               json)) { // ปรับ path เป็นไปตาม Backend ของคุณ (เช่น /api/predict)
    blinkRGB(0, 1, 0, 2, 100);
  } else {
    blinkRGB(1, 0, 0, 3, 100);
  }
}

// =====================================================
// WiFi Provisioning Event Handler
// =====================================================
void SysProvEvent(arduino_event_t *sys_event) {
  switch (sys_event->event_id) {
  case ARDUINO_EVENT_PROV_START:
    Serial.println("\nProvisioning Started. Open 'ESP BLE Provisioning' App!");
    break;
  case ARDUINO_EVENT_WIFI_STA_GOT_IP:
    Serial.print("\nConnected! IP: ");
    Serial.println(WiFi.localIP());
    is_connected = true;

    // ❌ ลบบรรทัด registerDeviceWithBackend(); ออกจากตรงนี้

    setLED(0, 0, 1); // สำเร็จแล้วเปิดสีน้ำเงิน
    break;
  case ARDUINO_EVENT_PROV_END:
    Serial.println("\nProvisioning Ended.");
    break;
  default:
    break;
  }
}

// =====================================================
// Hardware & Calibration Helpers
// =====================================================
float readBatteryVoltage() {
  if (!adsReady)
    return -1.0f;
  int16_t raw = ads.readADC_SingleEnded(ADS_CH_VBAT);
  return (raw * 0.125f / 1000.0f) * VBAT_RATIO;
}

void saveCalibrationToFlash() {
  preferences.begin("glove-cal", false);
  preferences.putBytes("fMin", flexMin, sizeof(flexMin));
  preferences.putBytes("fMax", flexMax, sizeof(flexMax));
  preferences.putInt("tFlex", t_flex);
  preferences.putBool("isCal", true);
  preferences.end();
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

void calibrateRight() {
  Serial.println("\n=== CALIBRATION MODE (RIGHT HAND) ===");
  currentState = CALIBRATING_RIGHT;
  apiCalibrateStart("right");
  blinkRGB(1, 0, 1, 5, 100);

  long sumOpen[5] = {0, 0, 0, 0, 0};
  long sumClose[5] = {0, 0, 0, 0, 0};

  for (int round = 1; round <= 5; round++) {
    setLED(1, 0, 1);
    apiCalibrateUpdate("open", round);
    waitForUserAction();
    setLED(0, 0, 0);
    {
      int rawF[5];
      readFlexSensors(rawF);
      for (int i = 0; i < 5; i++)
        sumOpen[i] += rawF[i];
    }

    setLED(1, 0, 1);
    apiCalibrateUpdate("close", round);
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

  apiCalibrateUpdate("done", 5);
  blinkRGB(0, 1, 0, 3, 200);

  currentState = IDLE;
  setLED(0, 0, 1);
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  isBtnHeld = false;
  actionTriggered = false;
}

void handleLeftCalibrationUpdate(uint8_t cmd, uint8_t round) {
  currentState = CALIBRATING_LEFT;
  setLED(1, 0, 1);
  if (cmd == CAL_OPEN) {
    apiCalibrateUpdate("open", round);
  } else if (cmd == CAL_CLOSE) {
    apiCalibrateUpdate("close", round);
  } else if (cmd == CAL_DONE) {
    apiCalibrateUpdate("done", 5);
    currentState = IDLE;
    setLED(0, 0, 1);
  }
}

// =====================================================
// MAIN SETUP
// =====================================================
void setup() {
  Serial.begin(115200);

  WiFi.mode(WIFI_STA);

  // สร้าง DEVICE_ID จาก MAC Address
  String mac = WiFi.macAddress();
  mac.replace(":", "");
  DEVICE_ID = "GLOVE_" + mac;

  Serial.println("=================================");
  Serial.println("DEVICE ID: " + DEVICE_ID);
  Serial.println("=================================");

  pinMode(PIN_BTN_R, INPUT);
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);

  WiFi.onEvent(SysProvEvent);
  WiFiProv.beginProvision(NETWORK_PROV_SCHEME_BLE,
                          NETWORK_PROV_SCHEME_HANDLER_FREE_BTDM,
                          NETWORK_PROV_SECURITY_1, pop, service_name);

  HC12.begin(115200, SERIAL_8N1, HC12_RX, HC12_TX);
  analogReadResolution(12);

  Wire.begin(6, 7);
  mpu.setWire(&Wire);
  mpu.beginAccel();
  mpu.beginGyro();

  if (ads.begin(0x48)) {
    ads.setGain(GAIN_ONE);
    adsReady = true;
  }

  loadCalibrationFromFlash();
  Serial.println("\n--- MASTER (API) READY ---");

  delay(300);
  while (digitalRead(PIN_BTN_R) == HIGH)
    delay(10);
  isBtnHeld = false;
  actionTriggered = false;
}

// =====================================================
// MAIN LOOP
// =====================================================
void loop() {
  // --- แจ้งเตือนสถานะ WiFi ด้วยไฟกระพริบน้ำเงิน ---
  if (!is_connected) {
    static unsigned long lastBlink = 0;
    static bool ledState = false;
    if (millis() - lastBlink > 500) {
      lastBlink = millis();
      ledState = !ledState;
      setLED(0, 0, ledState);
    }
  }

  // 🌟 1. ดักการลงทะเบียนตรงนี้แทน (ปลอดภัยกว่า 100%)
  if (is_connected && !is_registered) {
    registerDeviceWithBackend();
    if (!is_registered) {
      delay(5000); // ถ้ายิงไม่ผ่าน ให้รอ 5 วิแล้ว loop หน้าค่อยยิงใหม่
    }
  }

  // 🌟 2. ดัก Heartbeat ห้ามยิงตอน RECORDING เด็ดขาด
  if (is_connected && is_registered && currentState == IDLE &&
      millis() - lastHeartbeat >= HEARTBEAT_INTERVAL) {
    lastHeartbeat = millis();
    sendHeartbeat();
  }

  if (HC12.available()) {
    uint8_t hdr = HC12.read();

    if (hdr == SIG_VBAT) {
      delay(5);
      if (HC12.available() >= 2) {
        uint8_t hi = HC12.read();
        uint8_t lo = HC12.read();
        int16_t mv = (int16_t)((hi << 8) | lo);
        leftVoltage = mv / 1000.0f;
      }
    } else if (hdr == SIG_CANCEL) {
      if (currentState == RECORDING) {
        bufL.clear();
        bufR.clear();
        memset(&lastDataR, 0, sizeof(GloveData));
        blinkRGB(1, 1, 0, 3, 100);
        setLED(1, 0, 0);
      }
    } else if (hdr == CMD_CAL_LEFT) {
      delay(10);
      if (HC12.available() >= 2) {
        uint8_t calCmd = HC12.read();
        uint8_t calRnd = HC12.read();
        if (calCmd == CAL_OPEN || calCmd == CAL_CLOSE) {
          apiCalibrateStart("left");
          handleLeftCalibrationUpdate(calCmd, calRnd);
        } else if (calCmd == CAL_DONE) {
          handleLeftCalibrationUpdate(calCmd, calRnd);
        }
      }
    } else if (hdr == CMD_DATA && currentState == RECEIVING_LEFT) {
      GloveData temp;
      if (HC12.readBytes((uint8_t *)&temp, sizeof(GloveData)) ==
          sizeof(GloveData)) {
        bufL.push_back(temp);
      }
    } else if (hdr == CMD_END && currentState == RECEIVING_LEFT) {
      sendPredictRaw();

      bufL.clear();
      bufR.clear();
      memset(&lastDataR, 0, sizeof(GloveData));
      HC12.write(CMD_START);
      currentState = RECORDING;
      setLED(1, 0, 0);
    }
  }

  // =========================================
  // ระบบปุ่มกดมือขวา (แก้ไขบั๊กกดค้างแล้วลั่น)
  // =========================================
  int readingR = digitalRead(PIN_BTN_R);
  static uint32_t lastDebounceTimeR = 0;
  static int lastReadingR = LOW;
  static int btnStateR = LOW;

  if (readingR != lastReadingR) {
    lastDebounceTimeR = millis();
  }
  if ((millis() - lastDebounceTimeR) > 50) {
    if (readingR != btnStateR) {
      btnStateR = readingR;
    }
  }
  lastReadingR = readingR;

  if (btnStateR == HIGH) {
    if (!isBtnHeld) {
      isBtnHeld = true;
      btnPressStart = millis();
      actionTriggered = false;
    } else {
      unsigned long heldMs = millis() - btnPressStart;

      // กดค้าง 2 วิ ตอนกำลังอัด = ยกเลิกคำนั้น
      if (heldMs > STOP_HOLD_MS && !actionTriggered) {
        if (currentState == RECORDING) {
          actionTriggered = true; // 🌟 ล็อคไว้ไม่ให้ทำงานซ้ำตอนปล่อยนิ้ว
          apiGestureStop();
          HC12.write(CMD_ABORT);
          bufL.clear();
          bufR.clear();
          memset(&lastDataR, 0, sizeof(GloveData));
          currentState = IDLE;
          blinkRGB(1, 1, 0, 3, 150); // เหลือง 3 ที
          setLED(0, 0, 1);           // กลับเป็นน้ำเงิน
        }
      }

      // กดค้าง 3 วิ ตอนอยู่ว่างๆ = ตั้งค่าเซนเซอร์
      if (heldMs > LONG_PRESS_MS && !actionTriggered) {
        if (currentState == IDLE && is_connected) {
          actionTriggered = true; // 🌟 ล็อคไว้ไม่ให้ทำงานซ้ำ
          calibrateRight();
        }
      }
    }
  } else {
    // 🌟 จังหวะยกนิ้วออกจากปุ่ม 🌟
    if (isBtnHeld) {
      if (!actionTriggered && (millis() - btnPressStart > 50)) {
        if (currentState == IDLE && is_connected) {
          // -> เริ่มอัด
          currentState = RECORDING;
          bufL.clear();
          bufR.clear();
          memset(&lastDataR, 0, sizeof(GloveData));
          HC12.write(CMD_START);
          apiGestureStart();
          setLED(1, 0, 0); // แดง
        } else if (currentState == RECORDING) {
          // -> หยุดอัด
          currentState = RECEIVING_LEFT;
          HC12.write(CMD_STOP);
          setLED(0, 1, 0); // เขียวค้าง รอข้อมูล
        }
      }
      isBtnHeld = false; // 🌟 รีเซ็ตปุ่มที่นี่ที่เดียวเท่านั้น!
    }
  }
  // =========================================

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
    if (bufR.size() > 300) {
      currentState = RECEIVING_LEFT;
      HC12.write(CMD_STOP);
      setLED(0, 1, 0);
    }
  }
}