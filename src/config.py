# -*- coding: utf-8 -*-
"""
config.py — ค่าคอนฟิกกลางของ backend

อ่านค่าจาก environment variable ได้ (มี default ที่รันได้ทันทีในเครื่อง dev)
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# repo root = โฟลเดอร์แม่ของ src/
BASE_DIR = Path(__file__).resolve().parent.parent

# โหลดค่าจาก .env ถ้ามี (local dev เท่านั้น — production/Vercel ไม่มีไฟล์นี้ จึงเป็น no-op)
load_dotenv(BASE_DIR / ".env")

# connection string ของ PostgreSQL (สร้าง schema + seed ด้วย seed_database.py)
# ทีมใช้ shared dev DB ตัวเดียวกัน — ตั้ง DATABASE_URL ใน .env (ดู .env.example) ไม่งั้น fallback
# เป็น postgres ในเครื่องตัวเอง (ต้อง createdb finrisk_dev เอง ข้อมูลจะไม่ sync กับคนอื่น)
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/finrisk_dev")

# CORS: origin ของ frontend (คั่นด้วย comma) — localhost และ 127.0.0.1 เป็นคนละ origin ใน browser
DEFAULT_CORS_ORIGINS = ",".join(
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:4200",  # Angular dev server (ng serve)
        "http://127.0.0.1:4200",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
)
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",") if origin.strip()]

# JWT — ⚠️ ต้องตั้ง JWT_SECRET เป็นค่าสุ่มยาวๆ ผ่าน env var จริงก่อนขึ้น production
# ค่า default นี้ใช้ได้เฉพาะ local dev เท่านั้น (ดู main.py — มี warning log ถ้ายังใช้ default นี้)
JWT_SECRET_DEFAULT = "dev-only-insecure-secret-change-before-production"
JWT_SECRET = os.getenv("JWT_SECRET", JWT_SECRET_DEFAULT)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "480"))  # 8 ชั่วโมง (1 กะทำงาน)

# รหัสผ่านทุก mock user = "password123" เก็บเป็น bcrypt hash (มี salt ในตัว) — ดู CLAUDE.md หัวข้อ Auth
API_TITLE = "Local Budget Fraud Risk Assistant API"
API_VERSION = "0.1.0"

# Gemini API (Google AI Studio) — ใช้ขับเคลื่อน chatbot (src/services/chatbot.py)
# ⚠️ ต้องตั้ง env var เอง ไม่มี default ที่ใช้งานได้จริง — ถ้าว่างจะมี warning log ตอน startup
# (ดู main.py) และ POST /chatbot จะตอบ 503 จนกว่าจะตั้งค่า
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Rate limit ต่อ user บน POST /chatbot (กัน cost บานจาก Gemini API — ดู issue #32)
# นับแบบ sliding window ต่อ process เดียว (ดู src/rate_limit.py)
CHATBOT_RATE_LIMIT_PER_MINUTE = int(os.getenv("CHATBOT_RATE_LIMIT_PER_MINUTE", "10"))
