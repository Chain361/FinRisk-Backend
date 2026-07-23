# -*- coding: utf-8 -*-
"""Smoke test — ยืนยันว่า app boot ได้และ endpoint หลักทำงานกับ fraud_risk.db"""
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db_exists"] is True


def test_meta():
    r = client.get("/meta")
    assert r.status_code == 200
    body = r.json()
    # data-as-of ต้องมาจาก seed (ไม่ใช่ null) เพื่อไม่ให้ frontend fallback เป็นวันที่ปัจจุบัน
    assert body["data_seeded_at"]
    assert body["fiscal_year_min"] == 2566
    assert body["fiscal_year_max"] == 2568


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
    # role อื่นดูได้ (project_id ไม่มีจริง → list ว่าง ไม่ใช่ 404)
    r = client.get("/audit/feedback/any-id", headers={"X-Username": "auditor1"})
    assert r.status_code == 200
    assert r.json() == []


def test_feedback_scope():
    # project_auditor เป็น scoped role — เห็น feedback เฉพาะโครงการในตำบลตัวเอง
    rows = client.get("/audit/feedback", headers={"X-Username": "auditor1"}).json()
    assert rows, "seed ต้องมี demo feedback ของตำบลท่าช้าง"
    thachang_projects = {
        p["project_id"]
        for p in client.get("/projects", headers={"X-Username": "auditor1"}).json()
    }
    assert all(row["project_id"] in thachang_projects for row in rows)

    # admin เห็นทุกตำบล — อย่างน้อยเท่ากับที่ auditor1 เห็น
    admin_rows = client.get("/audit/feedback", headers={"X-Username": "admin"}).json()
    assert len(admin_rows) >= len(rows)
    # ordering ตาม updated_at DESC
    updated = [row["updated_at"] for row in admin_rows]
    assert updated == sorted(updated, reverse=True)


def test_feedback_lifecycle():
    """draft → แก้ไข → submit → (แก้ต่อไม่ได้ 409, คนอื่นแก้ 403) → resolve → ลบเก็บกวาด
    ระวัง: test ใช้ fraud_risk.db จริง ต้องลบทุกแถวที่สร้างก่อนจบ"""
    auditor = {"X-Username": "auditor1"}
    project_id = client.get("/projects", headers=auditor).json()[0]["project_id"]
    created_ids = []
    try:
        # create draft — risk_score ถูกคำนวณ = โอกาส × ผลกระทบ
        r = client.post("/audit/feedback", headers=auditor, json={
            "project_id": project_id,
            "feedback_text": "ทดสอบ lifecycle (สร้างโดย smoke test)",
            "concern_level": "medium",
            "likelihood_score": 3,
            "impact_score": 4,
            "status": "draft",
        })
        assert r.status_code == 201
        fb = r.json()
        created_ids.append(fb["feedback_id"])
        assert fb["risk_score"] == 12
        assert fb["status"] == "draft"
        assert fb["submitted_at"] is None

        # แก้ไขได้ระหว่างเป็น draft
        r = client.patch(f"/audit/feedback/{fb['feedback_id']}", headers=auditor, json={
            "project_id": project_id,
            "feedback_text": "ทดสอบ lifecycle (แก้ไขแล้ว)",
            "concern_level": "high",
            "likelihood_score": 4,
            "impact_score": 4,
            "status": "submitted",
        })
        assert r.status_code == 200
        assert r.json()["status"] == "submitted"
        assert r.json()["submitted_at"] is not None

        # แก้หลัง submit → 409
        r = client.patch(f"/audit/feedback/{fb['feedback_id']}", headers=auditor, json={
            "project_id": project_id,
            "feedback_text": "แก้ไม่ได้แล้ว",
            "status": "draft",
        })
        assert r.status_code == 409

        # role นอก RESOLVE_ROLES แก้ของคนอื่น → 403 (ต้องเป็น draft ก่อนเช็ค owner? — เช็ค 409/403 ทั้งคู่ยอมรับได้
        # แต่ตาม router: เช็ค owner ก่อนสถานะ → 403)
        r = client.delete(f"/audit/feedback/{fb['feedback_id']}",
                          headers={"X-Username": "thachang_user"})
        assert r.status_code == 403

        # resolve โดย project_auditor
        r = client.patch(f"/audit/feedback/{fb['feedback_id']}/resolve", headers=auditor)
        assert r.status_code == 200
        assert r.json()["status"] == "resolved"
        assert r.json()["resolved_at"] is not None
    finally:
        # เก็บกวาด — auditor1 อยู่ใน RESOLVE_ROLES จึงลบได้แม้สถานะไม่ใช่ draft
        for fid in created_ids:
            client.delete(f"/audit/feedback/{fid}", headers=auditor)


def test_feedback_public_forbidden():
    # public_user ถูกกันทุก endpoint ของ feedback
    r = client.get("/audit/feedback", headers={"X-Username": "public1"})
    assert r.status_code == 403
    r = client.post("/audit/feedback", headers={"X-Username": "public1"}, json={
        "project_id": "x", "feedback_text": "no", "status": "draft",
    })
    assert r.status_code == 403


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
