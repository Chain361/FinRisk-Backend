# -*- coding: utf-8 -*-
"""
config.py — ค่าคอนฟิกกลางของ backend

อ่านค่าจาก environment variable ได้ (มี default ที่รันได้ทันทีในเครื่อง dev)
"""
import os
from pathlib import Path

# repo root = โฟลเดอร์แม่ของ src/
BASE_DIR = Path(__file__).resolve().parent.parent

# ตำแหน่งไฟล์ SQLite (สร้างจาก seed_database.py)
DB_PATH = Path(os.getenv("FRAUD_RISK_DB", BASE_DIR / "fraud_risk.db"))

# CORS: origin ของ frontend (คั่นด้วย comma) — ปรับตอนต่อ frontend จริง
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")

# ข้อมูล login เป็น mock เท่านั้น (รหัสผ่านทุก user = "password123", hash แบบ sha256)
# ห้ามใช้รูปแบบนี้บน production — ดู CLAUDE.md หัวข้อ Auth
API_TITLE = "Local Budget Fraud Risk Assistant API"
API_VERSION = "0.1.0"
