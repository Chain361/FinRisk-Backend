# -*- coding: utf-8 -*-
"""
config.py — ค่าคอนฟิกกลางของ backend

ลำดับความสำคัญของค่า: env var ที่ตั้งไว้ใน shell/แพลตฟอร์ม (เช่น Vercel) > `.env` ที่ repo root > default ในไฟล์นี้
ไฟล์ `.env` จึงเป็น "แหล่งหลัก" ตอน dev ในเครื่อง โดยไม่บังคับให้ต้องมี (ไม่มีก็ใช้ default)
`.env` อยู่ใน `.gitignore` — ห้าม commit คีย์ลง repo
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# repo root = โฟลเดอร์แม่ของ src/
BASE_DIR = Path(__file__).resolve().parent.parent

# โหลดค่าจาก .env ถ้ามี (local dev เท่านั้น — production/Vercel ไม่มีไฟล์นี้ จึงเป็น no-op)
# python-dotenv ไม่ override env ที่ตั้งไว้แล้ว → shell/Vercel ชนะ .env เสมอ
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

# Pinecone integrated-inference index — ค้นเนื้อหาเอกสารเต็ม (ดู docs/rag_pinecone_plan.md)
# ⚠️ PINECONE_API_KEY ว่าง = ไม่มี tool ค้นเอกสารให้ chatbot (ระบบเดิม tool 5 ตัวทำงานปกติ)
# ⚠️ โมเดล/dimension ถูกล็อกที่ตัว index ตอนสร้าง (multilingual-e5-large, 1024, cosine)
#    จึงไม่มี EMBED_MODEL/EMBED_DIM ที่นี่ — เปลี่ยนโมเดล = สร้าง index ใหม่ ไม่ใช่แก้ env
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY", "")
PINECONE_INDEX = os.getenv("PINECONE_INDEX", "pr-documents")
PINECONE_NAMESPACE = os.getenv("PINECONE_NAMESPACE", "pr-documents")
PINECONE_TEXT_FIELD = os.getenv("PINECONE_TEXT_FIELD", "text")  # ต้องตรงกับ field map ของ index
PINECONE_EMBED_MODEL = os.getenv("PINECONE_EMBED_MODEL", "multilingual-e5-large")  # ใช้ตอนนับ token เท่านั้น

# LangSmith — tracing/evaluation ของชั้น AI (ดู docs/langsmith_eval_plan.md)
# ⚠️ เปิด tracing = prompt, ผล tool (ชื่อโครงการ/ผู้ชนะ/งบ) และเนื้อความเอกสาร ปร.4/5/6
#    ถูกส่งขึ้น LangSmith cloud — ตอนนี้ตั้งใจเปิดเพราะยังเป็นข้อมูล mock (แผน §7 ทางเลือก A)
#    ก่อนขึ้น production กับข้อมูลจริงต้องทบทวนใหม่ (ปิด flag / hide inputs / self-hosted)
# ⚠️ ไม่มีคีย์ = ปิดสนิท ไม่ใช่ error — src/observability.py ทำ decorator ให้เป็น no-op
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "").strip().lower() in ("1", "true", "yes")
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "finrisk-dev")

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "6"))
# ⚠️ e5 เทรนแบบ contrastive → คู่ข้อความที่ไม่เกี่ยวกันเลยก็ได้ราว 0.70–0.78
#    ตั้งต่ำกว่านี้เท่ากับไม่กรอง ต้อง calibrate กับ chunk จริงอีกที (แผน §6.1, งาน #4.5)
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.82"))
# ลิมิตจริงของ multilingual-e5-large คือ 507 token/record และ truncate ส่วนเกิน "เงียบๆ"
RAG_MAX_CHUNK_TOKENS = int(os.getenv("RAG_MAX_CHUNK_TOKENS", "480"))
