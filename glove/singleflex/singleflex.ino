#include <Wire.h>
#include <Adafruit_ADS1X15.h> 

// สร้างออบเจกต์สำหรับ ADS1115
Adafruit_ADS1115 ads; 

// ==========================================
// 📌 ตั้งค่าขาต่างๆ สำหรับ ESP32-C3
// ==========================================
const int FLEX_PIN_47K_1 = 4;   // Flex 1: ขา Pin 4 (ใช้ R 47K)
const int FLEX_PIN_10K_A = 3;   // Flex 2: ขา Pin 3 (ใช้ R 10K)
const int FLEX_PIN_10K_C = 1;   // Flex 4: ขา Pin 1 (ใช้ R 10K)
const int FLEX_PIN_47K_2 = 0;   // Flex 5: ขา Pin 0 (ใช้ R 47K ตัวใหม่!) <--- แก้เป็น Pin 0

// 📌 ตั้งค่าช่องสำหรับ ADS1115
const int ADS_CHANNEL_A0 = 1;   // Flex 3: ช่อง A0 (ใช้ R 10K)

// 🌟 ระบุขา I2C
const int I2C_SDA = 6; 
const int I2C_SCL = 7; 

const float VCC = 3.3;            // แรงดันไฟของวงจร
const float R_DIV_47K = 47000.0;  // ค่า R 47K
const float R_DIV_10K = 10000.0;  // ค่า R 10K

void setup() {
  Serial.begin(115200); 
  delay(3000); // ให้เวลา ESP32-C3 ตั้งสติเชื่อมต่อ USB
  
  Serial.println("\n--- เริ่มการทดสอบ Flex Sensor 5 ตัว ---");
  Serial.println("กำลังค้นหา ADS1115...");

  // เริ่มต้น I2C ตามขาที่กำหนด
  Wire.begin(I2C_SDA, I2C_SCL);

  // สั่งเริ่มทำงาน ADS1115
  if (!ads.begin(0x48)) {
    Serial.println("❌ ไม่พบ ADS1115! ตรวจสอบสาย SDA (ขา 6) และ SCL (ขา 7)");
    while (1); 
  }
  
  ads.setGain(GAIN_ONE);
  Serial.println("✅ ADS1115 พร้อมทำงาน ลุยเลย!");
}

void loop() {
  Serial.println("--------------------------------------------------");

  // ==========================================
  // 🟢 1. อ่านค่าเซ็นเซอร์ตัวที่ 1 (R 47K) ผ่าน ESP32 [Pin 4]
  // ==========================================
  int adc1 = analogRead(FLEX_PIN_47K_1);
  float v1 = (adc1 / 4095.0) * VCC;
  float rFlex1 = 0.0;
  if (v1 > 0) rFlex1 = R_DIV_47K * ((VCC / v1) - 1.0);

  Serial.print("Flex 1 (47K) Pin "); Serial.print(FLEX_PIN_47K_1);
  Serial.print(" | ADC: "); Serial.print(adc1);
  Serial.print(" | Volts: "); Serial.print(v1, 2);
  Serial.print("V | Res: "); Serial.print(rFlex1, 1);
  Serial.print(" ohms --> ");
  if (v1 >= 3.25) Serial.println("❌ ALERT: สายหลุด/หักใน");
  else if (v1 <= 0.1) Serial.println("❌ ALERT: ช็อต/ไฟไม่เข้า");
  else Serial.println("✅ ปกติ");

  // ==========================================
  // 🔵 2. อ่านค่าเซ็นเซอร์ตัวที่ 2 (R 10K) ผ่าน ESP32 [Pin 3]
  // ==========================================
  int adc2 = analogRead(FLEX_PIN_10K_A);
  float v2 = (adc2 / 4095.0) * VCC;
  float rFlex2 = 0.0;
  if (v2 > 0) rFlex2 = R_DIV_10K * ((VCC / v2) - 1.0);

  Serial.print("Flex 2 (10K) Pin "); Serial.print(FLEX_PIN_10K_A);
  Serial.print(" | ADC: "); Serial.print(adc2);
  Serial.print(" | Volts: "); Serial.print(v2, 2);
  Serial.print("V | Res: "); Serial.print(rFlex2, 1);
  Serial.print(" ohms --> ");
  if (v2 >= 3.25) Serial.println("❌ ALERT: สายหลุด/หักใน");
  else if (v2 <= 0.1) Serial.println("❌ ALERT: ช็อต/ไฟไม่เข้า");
  else Serial.println("✅ ปกติ");

  // ==========================================
  // 🟣 3. อ่านค่าเซ็นเซอร์ตัวที่ 3 (R 10K) ผ่าน ADS1115 [ช่อง A0]
  // ==========================================
  int16_t adc3 = ads.readADC_SingleEnded(ADS_CHANNEL_A0); 
  float v3 = ads.computeVolts(adc3); 
  float rFlex3 = 0.0;
  if (v3 > 0 && v3 < VCC) rFlex3 = R_DIV_10K * ((VCC / v3) - 1.0);

  Serial.print("Flex 3 (10K) ADS A0 | ADC: "); Serial.print(adc3);
  Serial.print(" | Volts: "); Serial.print(v3, 2);
  Serial.print("V | Res: "); Serial.print(rFlex3, 1);
  Serial.print(" ohms --> ");
  if (v3 >= 3.25) Serial.println("❌ ALERT: สายหลุด/หักใน");
  else if (v3 <= 0.1) Serial.println("❌ ALERT: ช็อต/ไฟไม่เข้า");
  else Serial.println("✅ ปกติ");

  // ==========================================
  // 🟠 4. อ่านค่าเซ็นเซอร์ตัวที่ 4 (R 10K) ผ่าน ESP32 [Pin 1]
  // ==========================================
  int adc4 = analogRead(FLEX_PIN_10K_C);
  float v4 = (adc4 / 4095.0) * VCC;
  float rFlex4 = 0.0;
  if (v4 > 0) rFlex4 = R_DIV_10K * ((VCC / v4) - 1.0);

  Serial.print("Flex 4 (10K) Pin "); Serial.print(FLEX_PIN_10K_C);
  Serial.print(" | ADC: "); Serial.print(adc4);
  Serial.print(" | Volts: "); Serial.print(v4, 2);
  Serial.print("V | Res: "); Serial.print(rFlex4, 1);
  Serial.print(" ohms --> ");
  if (v4 >= 3.25) Serial.println("❌ ALERT: สายหลุด/หักใน");
  else if (v4 <= 0.1) Serial.println("❌ ALERT: ช็อต/ไฟไม่เข้า");
  else Serial.println("✅ ปกติ");

  // ==========================================
  // 🟡 5. อ่านค่าเซ็นเซอร์ตัวที่ 5 (R 47K) ผ่าน ESP32 [Pin 0]
  // ==========================================
  int adc5 = analogRead(FLEX_PIN_47K_2);
  float v5 = (adc5 / 4095.0) * VCC;
  float rFlex5 = 0.0;
  
  // สำคัญ: ใช้สูตรคูณด้วย R_DIV_47K สำหรับตัวนี้
  if (v5 > 0) rFlex5 = R_DIV_47K * ((VCC / v5) - 1.0);

  Serial.print("Flex 5 (47K) Pin "); Serial.print(FLEX_PIN_47K_2);
  Serial.print(" | ADC: "); Serial.print(adc5);
  Serial.print(" | Volts: "); Serial.print(v5, 2);
  Serial.print("V | Res: "); Serial.print(rFlex5, 1);
  Serial.print(" ohms --> ");
  if (v5 >= 3.25) Serial.println("❌ ALERT: สายหลุด/หักใน");
  else if (v5 <= 0.1) Serial.println("❌ ALERT: ช็อต/ไฟไม่เข้า");
  else Serial.println("✅ ปกติ");

  delay(500); 
}
