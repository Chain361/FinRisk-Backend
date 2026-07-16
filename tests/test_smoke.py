# -*- coding: utf-8 -*-
"""Smoke test — ยืนยันว่า app boot ได้และ endpoint หลักทำงานกับ fraud_risk.db"""
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db_exists"] is True


def test_login_and_scope():
    # login mock — รหัสผ่านทุก user = password123
    r = client.post("/auth/login", json={"username": "thachang_user", "password": "password123"})
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["role"] == "local_executive"

    headers = {"X-Username": "thachang_user"}
    # local_executive เห็นเฉพาะตำบลตัวเอง (1 ตำบล)
    subs = client.get("/subdistricts", headers=headers).json()
    assert len(subs) == 1

    projects = client.get("/projects", headers=headers).json()
    assert all(p["subdistrict_id"] == user["subdistrict_id"] for p in projects)


def test_admin_sees_all():
    headers = {"X-Username": "admin"}
    subs = client.get("/subdistricts", headers=headers).json()
    assert len(subs) == 3
    summary = client.get("/risk/summary", headers=headers).json()
    assert summary["total"] > 0


def test_financial_statements_routes():
    headers = {"X-Username": "thachang_user"}

    r = client.get("/financial-statements", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert rows
    assert all(row["subdistrict_id"] == 1 for row in rows)

    r2 = client.get("/financials", headers=headers)
    assert r2.status_code == 200
    assert len(r2.json()) == len(rows)


def test_all_scope_roles_see_all_subdistricts():
    # regional_supervisor และ public_user เห็นทุกตำบล (data scope = ทุกตำบล ตาม roles.md)
    for username in ("supervisor1", "public1"):
        subs = client.get("/subdistricts", headers={"X-Username": username}).json()
        assert len(subs) == 3, username


def test_audit_assignments_role_gate():
    # risk_analyst เข้าได้ (เห็นเฉพาะงานที่ได้รับมอบหมาย — ตารางยังว่างใน seed)
    r = client.get("/audit/assignments", headers={"X-Username": "analyst1"})
    assert r.status_code == 200
    assert r.json() == []
    # local_executive / public_user ไม่มีสิทธิ์งาน assignment ตาม roles.md
    for username in ("thachang_user", "public1"):
        r = client.get("/audit/assignments", headers={"X-Username": username})
        assert r.status_code == 403, username


def test_public_user_cannot_view_audit_feedback():
    # public_user ไม่มีสิทธิ์ View Public Audit Information (ข้อมูลที่ถูกปิดไว้)
    r = client.get("/audit/feedback/any-id", headers={"X-Username": "public1"})
    assert r.status_code == 403
    # role อื่นดูได้ (ตารางยังว่าง → list ว่าง)
    r = client.get("/audit/feedback/any-id", headers={"X-Username": "auditor1"})
    assert r.status_code == 200


def test_roles_seeded():
    import sqlite3

    from src.config import DB_PATH

    con = sqlite3.connect(str(DB_PATH))
    try:
        assert con.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 6
    finally:
        con.close()


def test_wrong_password():
    r = client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
