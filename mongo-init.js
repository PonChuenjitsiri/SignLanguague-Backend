// Create the application database and user
db = db.getSiblingDB("smart_glove");

db.createUser({
  user: "smartglove",
  pwd: "smartglove2026",
  roles: [{ role: "readWrite", db: "smart_glove" }],
});

// Create collections
db.createCollection("sign_languages");
db.createCollection("sensor_logs");

// Seed sample sign language data
db.sign_languages.insertMany([
  {
    titleThai: "สวัสดี",
    titleEng: "Hello",
    category: "Basic",
    signMethod: "พนมมือไว้ที่ระดับอก (ท่าไหว้ปกติ)",
    imageUrl: "",
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    titleThai: "ขอบคุณ",
    titleEng: "Thank you",
    category: "Basic",
    signMethod: "พนมมือแล้วก้มศีรษะเล็กน้อย",
    imageUrl: "",
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    titleThai: "ใช่",
    titleEng: "Yes",
    category: "Basic",
    signMethod: "กำมือแล้วพยักหน้า",
    imageUrl: "",
    created_at: new Date(),
    updated_at: new Date(),
  },
  {
    titleThai: "ไม่",
    titleEng: "No",
    category: "Basic",
    signMethod: "โบกมือไปมาหน้าอก",
    imageUrl: "",
    created_at: new Date(),
    updated_at: new Date(),
  },
]);

print("✅ Database initialized with sample data");
