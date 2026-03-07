#include <Arduino.h>
#include <Wire.h>
#include <MPU9250_asukiaaa.h>
#include <vector>
#include <Preferences.h>

HardwareSerial HC12(1);
#define HC12_RX 20
#define HC12_TX 21
#define PIN_BUTTON 5
#define PIN_LED 10 

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
GloveData lastData;
std::vector<GloveData> storage; 
bool isRecording = false;

const uint8_t CMD_START = 0xA1;
const uint8_t CMD_STOP  = 0xA2;
const uint8_t CMD_DATA  = 0xD1;
const uint8_t CMD_END   = 0xD2;
const uint8_t SIG_CANCEL = 0xEE;

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
    Serial.println(">> Flex Calibration Saved to Flash!");
}

void loadCalibrationFromFlash() {
    preferences.begin("glove-cal", true);
    isCalibrated = preferences.getBool("isCal", false);
    if (isCalibrated) {
        preferences.getBytes("fMin", flexMin, sizeof(flexMin));
        preferences.getBytes("fMax", flexMax, sizeof(flexMax));
        t_flex = preferences.getInt("tFlex", 200);
        Serial.println(">> Calibration Loaded from Flash!");
        Serial.printf(">> Flex Threshold is set to: %d\n", t_flex);
    }
    preferences.end();
}

void blinkLED(int times, int duration) {
    pinMode(PIN_LED, OUTPUT);
    for (int i = 0; i < times; i++) {
        digitalWrite(PIN_LED, HIGH); delay(duration);
        digitalWrite(PIN_LED, LOW); if (i < times - 1) delay(duration);
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
    while(digitalRead(PIN_BUTTON) == HIGH) delay(10); 
    delay(100); 
    while(digitalRead(PIN_BUTTON) == LOW) delay(10);
    delay(100); 
    while(digitalRead(PIN_BUTTON) == HIGH) delay(10); 
    delay(100); 
}

void calibrateSensors() {
    Serial.println("\n=== CALIBRATION MODE (LEFT HAND) ===");
    blinkLED(5, 100);

    long sumOpen[5] = {0,0,0,0,0};
    long sumClose[5] = {0,0,0,0,0};

    for (int round = 1; round <= 5; round++) {
        Serial.printf(">> ROUND %d/5\n", round);
        
        Serial.println("   [ACTION] OPEN hand -> Press Button");
        waitForUserAction();
        for(int i=0; i<5; i++) sumOpen[i] += analogRead(i); 
        
        Serial.println("   [ACTION] CLOSE hand -> Press Button");
        waitForUserAction();
        for(int i=0; i<5; i++) sumClose[i] += analogRead(i); 
        
        blinkLED(2, 100);
    }

    Serial.println("\n=== CALIBRATION RESULTS ===");
    for(int i=0; i<5; i++) {
        flexMin[i] = sumOpen[i] / 5;
        flexMax[i] = sumClose[i] / 5;
        if (flexMin[i] == flexMax[i]) flexMax[i] += 1; 
        Serial.printf("  F%d Raw Avg Min: %d | Avg Max: %d\n", i, flexMin[i], flexMax[i]);
    }

    t_flex = 200; 
    
    Serial.println("\n-----------------------------------------");
    Serial.println(">> Flex Mapped Range : 0 - 2000");
    Serial.printf(">> NEW Flex Threshold: %d (10%% of range)\n", t_flex);
    Serial.println("-----------------------------------------");

    isCalibrated = true;
    saveCalibrationToFlash();
    
    blinkLED(3, 200);
    while(digitalRead(PIN_BUTTON) == HIGH) delay(10);
    isBtnHeld = false;
    actionTriggered = false;
}

bool checkMovement(GloveData current) {
    if (storage.empty()) return true;
    for(int i=0; i<5; i++) if (abs((int)current.flex[i] - (int)lastData.flex[i]) > t_flex) return true;
    
    for(int k=0; k<3; k++) {
        if (abs(current.accel[k] - lastData.accel[k]) > (T_ACCEL * 100)) return true;
        if (abs(current.gyro[k] - lastData.gyro[k]) > (T_GYRO * 100)) return true;
    }
    return false;
}

void setup() {
    Serial.begin(115200);
    HC12.begin(115200, SERIAL_8N1, HC12_RX, HC12_TX);
    analogReadResolution(12);
    
    pinMode(PIN_BUTTON, INPUT);
    pinMode(PIN_LED, OUTPUT); 
    Wire.begin(6, 7);
    mpu.setWire(&Wire); mpu.beginAccel(); mpu.beginGyro();
    
    Serial.println("--- LEFT HAND READY ---");
    loadCalibrationFromFlash();
}

void sendDataToMaster() {
    Serial.print("Sending data: "); Serial.println(storage.size());
    for (size_t i = 0; i < storage.size(); i++) {
        HC12.write(CMD_DATA);
        HC12.write((uint8_t*)&storage[i], sizeof(GloveData));
        delay(10);
    }
    HC12.write(CMD_END);
    Serial.println("Send Complete");
    storage.clear();
}

void loop() {
    if (HC12.available()) {
        uint8_t cmd = HC12.read();
        if (cmd == CMD_START) {
            isRecording = true;
            storage.clear();
            memset(&lastData, 0, sizeof(GloveData));
            Serial.println("CMD: START");
        } 
        else if (cmd == CMD_STOP) {
            isRecording = false;
            Serial.println("CMD: STOP -> Sending Data...");
            sendDataToMaster();
        }
    }

    if (isRecording) {
        static uint32_t last_scan = 0;
        if (millis() - last_scan >= 20) { 
            last_scan = millis();
            if (mpu.accelUpdate() == 0 && mpu.gyroUpdate() == 0) {
                GloveData d;
                readMPU(d);
                for(int i=0; i<5; i++) {
                    int raw = analogRead(i);
                    if (isCalibrated) {
                        int clipped = constrain(raw, min(flexMin[i], flexMax[i]), max(flexMin[i], flexMax[i]));
                        // *** เปลี่ยน Range ขยายเป็น 0 - 2000 ***
                        d.flex[i] = map(clipped, flexMin[i], flexMax[i], 0, 2000);
                    } else {
                        d.flex[i] = raw;
                    }
                }
                if (checkMovement(d)) {
                    storage.push_back(d);
                    lastData = d;
                }
            }
        }
    }

    int btnState = digitalRead(PIN_BUTTON);
//    Serial.println(btnState);
    if (btnState == HIGH) { 
        if (!isBtnHeld) {
            isBtnHeld = true;
            btnPressStart = millis();
            actionTriggered = false;
        } else {
            if (millis() - btnPressStart > 3000 && !actionTriggered) {
                if (!isRecording) { 
                    actionTriggered = true;
                    calibrateSensors();
                    isBtnHeld = false;
                    btnPressStart = millis();
                    return;
                }
            }
        }
    } else { 
        if (isBtnHeld) {
            if (!actionTriggered && (millis() - btnPressStart > 50)) {
                HC12.write(SIG_CANCEL);
                Serial.println("Sent CANCEL/DELETE Signal");
                isRecording = false;
                storage.clear();
            }
            isBtnHeld = false;
        }
    }
}
