#include <Arduino.h>
#include <MPU9250_asukiaaa.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiProv.h>

const char *service_name = "PROV_ESP32_C3";
const char *pop = "123456";

bool is_connected = false;

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

// ★ เปลี่ยน IP ให้ตรงกับ backend server ในเครือข่ายเดียวกัน
const String SERVER_URL = "http://192.168.88.51:8000";

const int PIN_LED_R = 8;
const int PIN_LED_G = 9;
const int PIN_LED_B = 10;
const int PIN_BTN_R = 5;

const int FLEX_PIN_R[5] = {0, 1, -1, 3, 4};
const int ADS_CHANNEL_MID = 1;

Adafruit_ADS1115 ads;
bool adsReady = false;
MPU9250_asukiaaa mpu;

struct GloveData {
  int flex[5];
  float accel[3];
  float gyro[3];
};

void readSensors(GloveData &d);
void sendData(const GloveData &d);

void setLEDColor(bool r, bool g, bool b) {
  digitalWrite(PIN_LED_R, r ? HIGH : LOW);
  digitalWrite(PIN_LED_G, g ? HIGH : LOW);
  digitalWrite(PIN_LED_B, b ? HIGH : LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BTN_R, INPUT);
  
  pinMode(PIN_LED_R, OUTPUT);
  pinMode(PIN_LED_G, OUTPUT);
  pinMode(PIN_LED_B, OUTPUT);

  setLEDColor(HIGH, LOW, LOW); // Red while connecting

  Wire.begin(6, 7);
  mpu.setWire(&Wire);
  mpu.beginAccel();
  mpu.beginGyro();

  if (ads.begin(0x48)) {
    ads.setGain(GAIN_ONE);
    adsReady = true;
    Serial.println("ADS1115 ready!");
  } else {
    Serial.println("WARNING: ADS1115 not found!");
  }

  // WiFi Provisioning
  WiFi.onEvent(SysProvEvent);
  WiFiProv.beginProvision(NETWORK_PROV_SCHEME_BLE,
                          NETWORK_PROV_SCHEME_HANDLER_FREE_BTDM,
                          NETWORK_PROV_SECURITY_1, pop, service_name);
}

void readSensors(GloveData &d) {
  if (mpu.accelUpdate() == 0) {
    d.accel[0] = mpu.accelX();
    d.accel[1] = mpu.accelY();
    d.accel[2] = mpu.accelZ();
  } else {
    d.accel[0] = 0; d.accel[1] = 0; d.accel[2] = 0;
  }
  
  if (mpu.gyroUpdate() == 0) {
    d.gyro[0] = mpu.gyroX();
    d.gyro[1] = mpu.gyroY();
    d.gyro[2] = mpu.gyroZ();
  } else {
    d.gyro[0] = 0; d.gyro[1] = 0; d.gyro[2] = 0;
  }

  for (int i = 0; i < 5; i++) {
    if (FLEX_PIN_R[i] >= 0) {
      d.flex[i] = analogRead(FLEX_PIN_R[i]);
    } else if (adsReady) {
      int16_t adsVal = ads.readADC_SingleEnded(ADS_CHANNEL_MID);
      d.flex[i] = constrain(map(adsVal, 0, 26400, 0, 4095), 0, 4095);
    } else {
      d.flex[i] = 0;
    }
  }
}

void sendData(const GloveData &d) {
  if (is_connected) {
    HTTPClient http;
    http.begin(SERVER_URL + "/api/glove/test/sensors");
    http.addHeader("Content-Type", "application/json");

    String jsonBody = "{";
    jsonBody += "\"flex\":[" + String(d.flex[0]) + "," + String(d.flex[1]) + "," + String(d.flex[2]) + "," + String(d.flex[3]) + "," + String(d.flex[4]) + "],";
    jsonBody += "\"accel\":[" + String(d.accel[0], 2) + "," + String(d.accel[1], 2) + "," + String(d.accel[2], 2) + "],";
    jsonBody += "\"gyro\":[" + String(d.gyro[0], 2) + "," + String(d.gyro[1], 2) + "," + String(d.gyro[2], 2) + "]";
    jsonBody += "}";

    Serial.println("Sending data: " + jsonBody);

    int httpResponseCode = http.POST(jsonBody);
    if (httpResponseCode > 0) {
      String response = http.getString();
      Serial.printf("[HTTP %d] %s\n", httpResponseCode, response.c_str());
    } else {
      Serial.printf("[HTTP Error] %d\n", httpResponseCode);
    }
    http.end();
  } else {
    Serial.println("WiFi not connected!");
  }
}

int prevState = LOW;

void loop() {
  static bool was_connected = false;
  if (is_connected && !was_connected) {
    setLEDColor(LOW, HIGH, LOW); // Green when ready
    was_connected = true;
  }

  int currState = digitalRead(PIN_BTN_R);
  
  // Button pressed (transition LOW -> HIGH)
  if (currState == HIGH && prevState == LOW) {
    setLEDColor(LOW, LOW, HIGH); // Blue while sending
    
    GloveData d;
    readSensors(d);
    sendData(d);
    
    setLEDColor(LOW, HIGH, LOW); // Back to green
  }
  
  prevState = currState;
  delay(50); // Debounce & loop delay
}