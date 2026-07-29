# -*- coding: utf-8 -*-
"""Smoke test — ยืนยันว่า app boot ได้และ endpoint หลักทำงานกับ fraud_risk.db"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db_connected"] is True


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


def test_projects_search_by_name_partial_case_insensitive():
    """ค้นโครงการด้วยชื่อ (บางส่วน/ไม่สนตัวพิมพ์) — ใช้เมื่อผู้ใช้ไม่รู้ project_id (เช่น จาก chatbot)"""
    admin = {"X-Username": "admin"}
    all_projects = client.get("/projects", headers=admin).json()
    assert all_projects

    target = all_projects[0]
    needle = target["project_name"][:6]
    result = client.get("/projects", headers=admin, params={"project_name": needle.upper()})
    assert result.status_code == 200
    names = [p["project_name"] for p in result.json()]
    assert names  # ต้องเจออย่างน้อย 1 รายการ แม้ query เป็นตัวพิมพ์ใหญ่ต่างจากต้นฉบับ
    assert any(p["project_id"] == target["project_id"] for p in result.json())
    assert all(needle.lower() in n.lower() for n in names)

    no_match = client.get("/projects", headers=admin, params={"project_name": "ไม่มีโครงการนี้แน่นอน-xyz"})
    assert no_match.status_code == 200
    assert no_match.json() == []


def test_projects_search_by_name_matches_all_keywords_any_order():
    """ชื่อโครงการจริงเป็นประโยคยาวมีคำแทรก (เช่น 'ภายใน หมู่ที่ 9') — ค้นด้วยคำสำคัญหลายคำ (คั่นด้วย
    เว้นวรรค) ต้องแมตช์ทุกคำโดยไม่สนลำดับ/ระยะห่างในชื่อจริง ไม่ใช่ต้องเป็นวลีต่อเนื่องเป๊ะๆ"""
    admin = {"X-Username": "admin"}
    result = client.get(
        "/projects", headers=admin, params={"project_name": "ถนนดินลูกรัง บ้านป่ายาง"}
    )
    assert result.status_code == 200
    names = [p["project_name"] for p in result.json()]
    assert names
    assert all("ถนนดินลูกรัง" in n and "บ้านป่ายาง" in n for n in names)


def test_risk_summary_uses_project_filters_without_bypassing_scope():
    """summary ต้องนับชุดเดียวกับ /projects และ filter ตำบลต้องไม่ข้าม scope."""
    admin = {"X-Username": "admin"}
    params = {"subdistrict_id": 1, "budget_year": 2568, "risk_level": "medium"}

    projects = client.get("/projects", headers=admin, params=params)
    summary = client.get("/risk/summary", headers=admin, params=params)
    assert projects.status_code == summary.status_code == 200
    assert summary.json()["total"] == len(projects.json())

    # auditor1 อยู่ตำบลท่าช้าง (id=1); ขอ summary ของตำบลอื่นต้องไม่ได้ข้อมูล
    outside_scope = client.get(
        "/risk/summary", headers={"X-Username": "auditor1"}, params={"subdistrict_id": 2}
    )
    assert outside_scope.status_code == 200
    assert outside_scope.json() == {"total": 0, "by_level": {}}


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
    # risk_analyst เข้าได้ (เห็นเฉพาะงานที่ได้รับมอบหมาย — seed_assignments() มี 1 งาน demo ต่อตำบล)
    r = client.get("/audit/assignments", headers={"X-Username": "analyst1"})
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["status"] in ("waiting_acceptance", "in_progress", "pending_approval")
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
    from src.database import db_session

    with db_session() as con:
        assert con.execute("SELECT COUNT(*) FROM roles").fetchone()[0] == 6


def test_wrong_password():
    r = client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401


def test_auditor_can_create_assignment_with_history():
    """Assignment data belongs to the backend and is visible to the assignee."""
    from src.database import db_session

    auditor_headers = {"X-Username": "auditor1"}
    analysts = client.get("/audit/assignments/assignees", headers=auditor_headers)
    assert analysts.status_code == 200
    analyst = analysts.json()[0]
    assert analyst["entity_type"] == "user"
    assert analyst["user_label"] == f"user:{analyst['username']}"
    assert analyst["role"] == "risk_analyst"

    projects = client.get("/projects", headers=auditor_headers).json()
    already_assigned = {
        item["project_id"]
        for item in client.get("/audit/assignments", headers=auditor_headers).json()
        if item["status"] != "completed"
    }
    project = next(p for p in projects if p["project_id"] not in already_assigned)
    response = client.post(
        "/audit/assignments",
        headers=auditor_headers,
        json={
            "project_id": str(project["project_id"]),
            "assignee_id": analyst["user_id"],
            "priority": "high",
            "note": "ตรวจสอบเอกสารสัญญา",
            "due_date": "2026-08-01",
        },
    )
    assert response.status_code == 201
    assignment_id = response.json()["assignment_id"]

    try:
        detail = client.get(f"/audit/assignments/{assignment_id}", headers=auditor_headers)
        assert detail.status_code == 200
        assert detail.json()["assignment"]["status"] == "waiting_acceptance"
        assert detail.json()["assignment"]["assignee_entity_type"] == "user"
        assert detail.json()["assignment"]["assignee_user_label"] == f"user:{analyst['username']}"
        assert detail.json()["status_history"][0]["new_status"] == "waiting_acceptance"

        analyst_headers = {"X-Username": analyst["username"]}
        mine = client.get("/audit/assignments/my", headers=analyst_headers)
        assert mine.status_code == 200
        assert any(item["assignment_id"] == assignment_id for item in mine.json())

        accepted = client.patch(
            f"/audit/assignments/{assignment_id}/status",
            headers=analyst_headers,
            json={"status": "accepted"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["status"] == "accepted"

        denied_delete = client.delete(f"/audit/assignments/{assignment_id}", headers=analyst_headers)
        assert denied_delete.status_code == 403

        denied_auditor_delete = client.delete(f"/audit/assignments/{assignment_id}", headers=auditor_headers)
        assert denied_auditor_delete.status_code == 403

        deleted = client.delete(f"/audit/assignments/{assignment_id}", headers={"X-Username": "admin"})
        assert deleted.status_code == 204

        missing = client.get(f"/audit/assignments/{assignment_id}", headers={"X-Username": "admin"})
        assert missing.status_code == 404
    finally:
        with db_session() as con:
            con.execute("DELETE FROM notifications WHERE ref_type = 'assignment' AND ref_id = ?", (str(assignment_id),))
            con.execute("DELETE FROM assignment_status_history WHERE assignment_id = ?", (assignment_id,))
            con.execute("DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))
            con.commit()


def test_assignment_attachments_and_clarifications():
    """Evidence upload (BYTEA-in-DB) + clarification thread — scope guard, extension/size validation."""
    from src.database import db_session

    auditor_headers = {"X-Username": "auditor1"}  # ท่าช้าง
    analysts = client.get("/audit/assignments/assignees", headers=auditor_headers).json()
    analyst = next(a for a in analysts if a["username"] == "analyst1")

    projects = client.get("/projects", headers=auditor_headers).json()
    already_assigned = {
        item["project_id"]
        for item in client.get("/audit/assignments", headers=auditor_headers).json()
        if item["status"] != "completed"
    }
    project = next(p for p in projects if p["project_id"] not in already_assigned)
    created = client.post(
        "/audit/assignments",
        headers=auditor_headers,
        json={
            "project_id": str(project["project_id"]),
            "assignee_id": analyst["user_id"],
            "note": "ตรวจสอบเอกสารประกอบ",
        },
    )
    assert created.status_code == 201
    assignment_id = created.json()["assignment_id"]
    analyst_headers = {"X-Username": "analyst1"}
    other_subdistrict_headers = {"X-Username": "auditor2"}  # ปิงโค้ง — ต้องไม่มีสิทธิ์เห็นงานนี้

    try:
        # นามสกุลไฟล์ไม่อนุญาต → 422
        rejected_ext = client.post(
            f"/audit/assignments/{assignment_id}/attachments",
            headers=analyst_headers,
            files={"file": ("malware.exe", b"binary", "application/octet-stream")},
        )
        assert rejected_ext.status_code == 422

        # ไฟล์เกิน 10MB → 413
        too_big = client.post(
            f"/audit/assignments/{assignment_id}/attachments",
            headers=analyst_headers,
            files={"file": ("big.pdf", b"0" * (10 * 1024 * 1024 + 1), "application/pdf")},
        )
        assert too_big.status_code == 413

        # อัปโหลดไฟล์จริง (analyst แนบหลักฐาน)
        pdf_bytes = b"%PDF-1.4 fake evidence content"
        uploaded = client.post(
            f"/audit/assignments/{assignment_id}/attachments",
            headers=analyst_headers,
            files={"file": ("evidence.pdf", pdf_bytes, "application/pdf")},
        )
        assert uploaded.status_code == 201
        attachment = uploaded.json()
        assert attachment["file_name"] == "evidence.pdf"
        assert attachment["file_size"] == len(pdf_bytes)
        assert "file_content" not in attachment
        attachment_id = attachment["attachment_id"]

        # auditor (เจ้าของงานฝั่งมอบหมาย) เห็นไฟล์และดาวน์โหลดได้ bytes ตรงตัว
        listed = client.get(f"/audit/assignments/{assignment_id}/attachments", headers=auditor_headers)
        assert listed.status_code == 200
        assert len(listed.json()) == 1

        downloaded = client.get(
            f"/audit/assignments/{assignment_id}/attachments/{attachment_id}/download",
            headers=auditor_headers,
        )
        assert downloaded.status_code == 200
        assert downloaded.content == pdf_bytes

        # scope guard — auditor ตำบลอื่นเห็น/ดาวน์โหลด/ลบไม่ได้
        assert client.get(
            f"/audit/assignments/{assignment_id}/attachments", headers=other_subdistrict_headers
        ).status_code == 403
        assert client.get(
            f"/audit/assignments/{assignment_id}/attachments/{attachment_id}/download",
            headers=other_subdistrict_headers,
        ).status_code == 403
        assert client.delete(
            f"/audit/assignments/{assignment_id}/attachments/{attachment_id}",
            headers=other_subdistrict_headers,
        ).status_code == 403

        # auditor (ไม่ใช่คนอัปโหลด, ไม่ใช่ admin) ลบไฟล์คนอื่นไม่ได้
        assert client.delete(
            f"/audit/assignments/{assignment_id}/attachments/{attachment_id}", headers=auditor_headers
        ).status_code == 403

        # เจ้าของไฟล์ (analyst) ลบไฟล์ตัวเองได้
        deleted = client.delete(
            f"/audit/assignments/{assignment_id}/attachments/{attachment_id}", headers=analyst_headers
        )
        assert deleted.status_code == 204
        assert client.get(f"/audit/assignments/{assignment_id}/attachments", headers=auditor_headers).json() == []

        # clarification thread — 2 ทาง, เรียงตามลำดับที่ส่ง
        ask = client.post(
            f"/audit/assignments/{assignment_id}/clarifications",
            headers=analyst_headers,
            json={"message_text": "ขอเอกสารราคากลางเพิ่มเติมได้ไหมครับ"},
        )
        assert ask.status_code == 201
        reply = client.post(
            f"/audit/assignments/{assignment_id}/clarifications",
            headers=auditor_headers,
            json={"message_text": "ส่งให้แล้วในระบบ e-GP ครับ"},
        )
        assert reply.status_code == 201

        thread = client.get(f"/audit/assignments/{assignment_id}/clarifications", headers=analyst_headers)
        assert thread.status_code == 200
        messages = thread.json()
        assert len(messages) == 2
        assert messages[0]["message_text"] == "ขอเอกสารราคากลางเพิ่มเติมได้ไหมครับ"
        assert messages[1]["created_by_display_name"]

        # scope guard เดียวกันกับ clarifications
        assert client.get(
            f"/audit/assignments/{assignment_id}/clarifications", headers=other_subdistrict_headers
        ).status_code == 403
        assert client.post(
            f"/audit/assignments/{assignment_id}/clarifications",
            headers=other_subdistrict_headers,
            json={"message_text": "ไม่ควรเห็น"},
        ).status_code == 403

        # แจ้งเตือนถูกสร้างให้อีกฝ่ายเมื่อโพสต์ข้อความ (analyst ถาม → แจ้ง auditor ผู้มอบหมาย)
        notif = client.get("/notifications", headers=auditor_headers).json()
        assert any(
            n["type"] == "clarification" and n["ref_id"] == str(assignment_id)
            for n in notif["notifications"]
        )
    finally:
        with db_session() as con:
            con.execute("DELETE FROM assignment_attachments WHERE assignment_id = ?", (assignment_id,))
            con.execute("DELETE FROM assignment_clarifications WHERE assignment_id = ?", (assignment_id,))
            con.execute("DELETE FROM notifications WHERE ref_type = 'assignment' AND ref_id = ?", (str(assignment_id),))
            con.execute("DELETE FROM assignment_status_history WHERE assignment_id = ?", (assignment_id,))
            con.execute("DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))
            con.commit()


def test_admin_risk_engine_run_role_gate():
    admin = {"X-Username": "admin"}
    before = client.get("/risk/summary", headers=admin).json()["total"]

    r = client.post("/admin/risk-engine/run", headers={"X-Username": "auditor1"})
    assert r.status_code == 403

    r = client.post("/admin/risk-engine/run", headers=admin)
    assert r.status_code == 200
    body = r.json()
    assert body["project_count"] == before
    assert body["annual_count"] > 0

    after = client.get("/risk/summary", headers=admin).json()["total"]
    assert after == before  # แค่รันซ้ำ ไม่ได้เพิ่มโครงการ — จำนวนควรเท่าเดิม


def test_admin_log_retention_archives_deletes_and_respects_hold():
    from src.database import db_session
    from src.log_retention import ensure_log_retention_schema

    admin = {"X-Username": "admin"}
    now = datetime.now(timezone.utc)
    archive_time = (now - timedelta(days=120)).strftime("%Y-%m-%d %H:%M:%S")
    delete_time = (now - timedelta(days=400)).strftime("%Y-%m-%d %H:%M:%S")
    usernames = (
        "pytest_retention_archive",
        "pytest_retention_delete",
        "pytest_retention_hold",
    )
    error_messages = (
        "pytest old error token=secret123456789 person@example.com 1234567890123",
        "pytest recent error token=secret123456789 person@example.com 1234567890123",
    )
    with db_session() as con:
        try:
            ensure_log_retention_schema(con)
            con.commit()
        except RuntimeError as exc:
            pytest.skip(str(exc))

    log_ids: list[int] = []
    try:
        with db_session() as con:
            placeholders = ",".join("?" * len(usernames))
            con.execute(f"DELETE FROM access_log WHERE username IN ({placeholders})", list(usernames))
            stale_ids = [
                row["original_log_id"]
                for row in con.execute(
                    f"SELECT original_log_id FROM access_log_archive WHERE username IN ({placeholders})",
                    list(usernames),
                ).fetchall()
            ]
            if stale_ids:
                stale_placeholders = ",".join("?" * len(stale_ids))
                con.execute(
                    f"DELETE FROM access_log_holds WHERE log_id IN ({stale_placeholders})",
                    stale_ids,
                )
            con.execute(
                f"DELETE FROM access_log_archive WHERE username IN ({placeholders})",
                list(usernames),
            )
            for message in error_messages:
                con.execute("DELETE FROM error_debug_log WHERE message LIKE ?", (f"%{message[:18]}%",))
            for username, created_at in [
                ("pytest_retention_archive", archive_time),
                ("pytest_retention_delete", delete_time),
                ("pytest_retention_hold", delete_time),
            ]:
                row = con.execute(
                    """INSERT INTO access_log
                       (username, role, action, method, path, resource_type,
                        resource_id, status_code, ip, user_agent, created_at)
                       VALUES (?, 'admin', 'view_detail', 'GET', ?, 'project',
                               'PYTEST', 200, '127.0.0.1', 'pytest', ?)
                       RETURNING log_id""",
                    (username, f"/projects/{username}", created_at),
                ).fetchone()
                log_ids.append(row["log_id"])
            con.execute(
                """INSERT INTO error_debug_log
                   (level, logger_name, message, error_type, method, path,
                    status_code, username, created_at)
                   VALUES ('error', 'pytest', ?, 'ValueError', 'GET',
                           '/projects/pytest-old-error', 500, 'admin', ?)""",
                (error_messages[0], (now - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S")),
            )
            con.execute(
                """INSERT INTO error_debug_log
                   (level, logger_name, message, error_type, method, path,
                    status_code, username, created_at)
                   VALUES ('error', 'pytest', ?, 'ValueError', 'GET',
                           '/projects/pytest-recent-error', 500, 'admin', ?)""",
                (error_messages[1], (now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")),
            )
            con.commit()

        hold = client.post(
            "/admin/log-retention/holds",
            headers=admin,
            json={
                "log_id": log_ids[2],
                "reason": "pytest investigation hold",
                "case_reference": "PYTEST-CASE-001",
            },
        )
        assert hold.status_code == 201

        denied = client.post("/admin/log-retention/run", headers={"X-Username": "auditor1"})
        assert denied.status_code == 403

        run = client.post("/admin/log-retention/run", headers=admin)
        assert run.status_code == 200, run.text
        body = run.json()
        assert body["hot_days"] == 90
        assert body["archive_days"] == 365
        assert body["error_debug_days"] == 30
        assert body["archived_count"] >= 3
        assert body["deleted_count"] >= 1
        assert body["error_debug_deleted_count"] >= 1

        archived = client.get(
            "/audit/access-log/archive",
            headers=admin,
            params={"username": "pytest_retention_archive"},
        )
        assert archived.status_code == 200
        assert archived.json()["total"] == 1
        assert archived.json()["items"][0]["path"] == "/projects/pytest_retention_archive"

        held = client.get(
            "/audit/access-log/archive",
            headers=admin,
            params={"username": "pytest_retention_hold"},
        )
        assert held.status_code == 200
        assert held.json()["total"] == 1

        deleted = client.get(
            "/audit/access-log/archive",
            headers=admin,
            params={"username": "pytest_retention_delete"},
        )
        assert deleted.status_code == 200
        assert deleted.json()["total"] == 0

        with db_session() as con:
            placeholders = ",".join("?" * len(log_ids))
            remaining_hot = con.execute(
                f"SELECT COUNT(*) FROM access_log WHERE log_id IN ({placeholders})",
                log_ids,
            ).fetchone()[0]
            assert remaining_hot == 0
            error_rows = con.execute(
                """SELECT message FROM error_debug_log
                   WHERE message IN (?, ?) ORDER BY message""",
                error_messages,
            ).fetchall()
            assert [row["message"] for row in error_rows] == [error_messages[1]]
    finally:
        with db_session() as con:
            if log_ids:
                placeholders = ",".join("?" * len(log_ids))
                con.execute(f"DELETE FROM access_log_holds WHERE log_id IN ({placeholders})", log_ids)
                con.execute(
                    f"DELETE FROM access_log_archive WHERE original_log_id IN ({placeholders})",
                    log_ids,
                )
                con.execute(f"DELETE FROM access_log WHERE log_id IN ({placeholders})", log_ids)
            for message in error_messages:
                con.execute("DELETE FROM error_debug_log WHERE message = ?", (message,))
            con.commit()


def test_admin_data_upload():
    from src.database import db_session

    admin = {"X-Username": "admin"}
    thachang = next(
        s for s in client.get("/subdistricts", headers=admin).json() if s["name_th"] == "ท่าช้าง"
    )
    csv_bytes = (
        "subdistrict,district,province,budget_year,project_id,project_name,project_type,"
        "dept_name,dept_sub_name,purchase_method,purchase_method_group,announce_date,"
        "transaction_date,budget_amount,reference_price,contract_value,price_ratio,"
        "project_status,contract_no,contract_date,contract_finish_date,"
        "contract_duration_days,contract_status,winner_name,winner_tin,latitude,longitude,"
        "fraud_risk_flag,fraud_risk_issues,data_quality_note,source_file\n"
        "ท่าช้าง,บางกล่ำ,สงขลา,2568,TEST-PYTEST-UPLOAD-001,ทดสอบ pytest upload,ซื้อ,"
        "กองคลัง,,e-bidding,e-bidding,1/10/2568,1/10/2568,500000,495000,490000,0.99,"
        "เสร็จสิ้น,C-001,1/10/2568,30/10/2568,30,เสร็จสิ้น,บริษัททดสอบ จำกัด,"
        "1234567890123,-,-,-,-,-,test.csv\n"
    ).encode("utf-8")

    try:
        # non-admin ทำไม่ได้
        r = client.post(
            "/admin/data/upload",
            headers={"X-Username": "auditor1"},
            data={"subdistrict_id": thachang["subdistrict_id"]},
            files={"projects_csv": ("test.csv", csv_bytes, "text/csv")},
        )
        assert r.status_code == 403

        # อัปโหลดสำเร็จ
        r = client.post(
            "/admin/data/upload",
            headers=admin,
            data={"subdistrict_id": thachang["subdistrict_id"]},
            files={"projects_csv": ("test.csv", csv_bytes, "text/csv")},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["projects_inserted"] == 1
        assert body["projects_skipped_duplicate"] == []

        # โครงการเห็นได้ผ่าน endpoint ปกติจริง
        detail = client.get("/projects/TEST-PYTEST-UPLOAD-001", headers=admin)
        assert detail.status_code == 200

        # อัปโหลดซ้ำ — ต้องข้าม ไม่ crash
        r = client.post(
            "/admin/data/upload",
            headers=admin,
            data={"subdistrict_id": thachang["subdistrict_id"]},
            files={"projects_csv": ("test.csv", csv_bytes, "text/csv")},
        )
        assert r.status_code == 200
        assert r.json()["projects_inserted"] == 0
        assert r.json()["projects_skipped_duplicate"] == ["TEST-PYTEST-UPLOAD-001"]

        # subdistrict ไม่ตรงกับข้อมูลในไฟล์ → 422
        pingkhong = next(
            s for s in client.get("/subdistricts", headers=admin).json() if s["name_th"] == "ปิงโค้ง"
        )
        r = client.post(
            "/admin/data/upload",
            headers=admin,
            data={"subdistrict_id": pingkhong["subdistrict_id"]},
            files={"projects_csv": ("test.csv", csv_bytes, "text/csv")},
        )
        assert r.status_code == 422

        # ไม่แนบไฟล์เลย → 422
        r = client.post(
            "/admin/data/upload", headers=admin, data={"subdistrict_id": thachang["subdistrict_id"]}
        )
        assert r.status_code == 422
    finally:
        with db_session() as con:
            con.execute("DELETE FROM projects WHERE project_id = ?", ("TEST-PYTEST-UPLOAD-001",))
            con.commit()


def test_approval_chain_full_flow():
    """#14: under_review -> pending_approval (auditor) -> completed/revision_requested (regional_supervisor)
    auditor เปลี่ยนตรง under_review -> completed เองไม่ได้แล้ว (ต้องผ่านผู้บังคับบัญชา)"""
    from src.database import db_session

    auditor_headers = {"X-Username": "auditor1"}
    analyst_headers = {"X-Username": "analyst1"}
    supervisor_headers = {"X-Username": "supervisor1"}

    projects = client.get("/projects", headers=auditor_headers).json()
    already_assigned = {
        item["project_id"]
        for item in client.get("/audit/assignments", headers=auditor_headers).json()
        if item["status"] != "completed"
    }
    project = next(p for p in projects if p["project_id"] not in already_assigned)

    analyst = client.get("/audit/assignments/assignees", headers=auditor_headers).json()[0]
    created = client.post(
        "/audit/assignments",
        headers=auditor_headers,
        json={
            "project_id": str(project["project_id"]),
            "assignee_id": analyst["user_id"],
            "priority": "high",
            "note": "ทดสอบ approval chain",
        },
    )
    assert created.status_code == 201
    assignment_id = created.json()["assignment_id"]

    def set_status(headers, status, note=None):
        payload = {"status": status}
        if note is not None:
            payload["note"] = note
        return client.patch(f"/audit/assignments/{assignment_id}/status", headers=headers, json=payload)

    try:
        # เดินสถานะจนถึง under_review
        for headers, status in [
            (analyst_headers, "accepted"),
            (analyst_headers, "in_progress"),
            (analyst_headers, "ready_for_review"),
            (auditor_headers, "under_review"),
        ]:
            r = set_status(headers, status)
            assert r.status_code == 200, r.text
            assert r.json()["status"] == status

        # auditor ปิดงานเองตรงๆ ไม่ได้อีกต่อไป
        r = set_status(auditor_headers, "completed")
        assert r.status_code == 409

        # auditor ส่งขออนุมัติได้
        r = set_status(auditor_headers, "pending_approval")
        assert r.status_code == 200
        assert r.json()["status"] == "pending_approval"

        # risk_analyst เปลี่ยนสถานะขั้นอนุมัติไม่ได้
        r = set_status(analyst_headers, "completed")
        assert r.status_code == 409

        # regional_supervisor ตีกลับโดยไม่ใส่เหตุผล -> 400
        r = set_status(supervisor_headers, "revision_requested")
        assert r.status_code == 400

        # regional_supervisor ตีกลับพร้อมเหตุผล -> ผ่าน
        r = set_status(supervisor_headers, "revision_requested", note="เอกสารไม่ครบ กรุณาแนบสัญญาเพิ่ม")
        assert r.status_code == 200
        assert r.json()["status"] == "revision_requested"

        # เดินสถานะกลับไป pending_approval อีกครั้งแล้วอนุมัติ
        for headers, status in [
            (analyst_headers, "in_progress"),
            (analyst_headers, "ready_for_review"),
            (auditor_headers, "under_review"),
            (auditor_headers, "pending_approval"),
        ]:
            r = set_status(headers, status)
            assert r.status_code == 200, r.text

        r = set_status(supervisor_headers, "completed")
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

        history = client.get(f"/audit/assignments/{assignment_id}", headers=auditor_headers).json()
        approver_entries = [
            h for h in history["status_history"]
            if h["new_status"] == "completed" and h["changed_by_username"] == "supervisor1"
        ]
        assert approver_entries, "ต้องมีหลักฐานผู้อนุมัติ+เวลาใน assignment_status_history"
    finally:
        with db_session() as con:
            con.execute("DELETE FROM notifications WHERE ref_type = 'assignment' AND ref_id = ?", (str(assignment_id),))
            con.execute("DELETE FROM assignment_status_history WHERE assignment_id = ?", (assignment_id,))
            con.execute("DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))
            con.commit()


def test_notifications_created_on_assignment_and_read_flow():
    """#19: POST /audit/assignments แจ้งเตือนผู้รับงาน + GET/PATCH ของตัวเองเท่านั้น"""
    from src.database import db_session

    auditor_headers = {"X-Username": "auditor1"}
    analyst_headers = {"X-Username": "analyst1"}

    projects = client.get("/projects", headers=auditor_headers).json()
    already_assigned = {
        item["project_id"]
        for item in client.get("/audit/assignments", headers=auditor_headers).json()
        if item["status"] != "completed"
    }
    project = next(p for p in projects if p["project_id"] not in already_assigned)
    analyst = client.get("/audit/assignments/assignees", headers=auditor_headers).json()[0]

    before = client.get("/notifications", headers=analyst_headers).json()["unread_count"]

    created = client.post(
        "/audit/assignments",
        headers=auditor_headers,
        json={"project_id": str(project["project_id"]), "assignee_id": analyst["user_id"],
              "priority": "normal", "note": "ทดสอบ notification"},
    )
    assert created.status_code == 201
    assignment_id = created.json()["assignment_id"]

    try:
        after = client.get("/notifications", headers=analyst_headers).json()
        assert after["unread_count"] == before + 1
        mine = [n for n in after["notifications"] if n["ref_type"] == "assignment" and n["ref_id"] == str(assignment_id)]
        assert len(mine) == 1
        notification_id = mine[0]["notification_id"]
        assert mine[0]["read_at"] is None

        # อ่านของคนอื่นไม่ได้
        r = client.patch(f"/notifications/{notification_id}/read", headers=auditor_headers)
        assert r.status_code == 403

        # อ่านที่ไม่มีจริง -> 404
        r = client.patch("/notifications/999999999/read", headers=analyst_headers)
        assert r.status_code == 404

        # เจ้าของอ่านได้
        r = client.patch(f"/notifications/{notification_id}/read", headers=analyst_headers)
        assert r.status_code == 200

        after_read = client.get("/notifications", headers=analyst_headers).json()
        assert after_read["unread_count"] == before
    finally:
        with db_session() as con:
            con.execute("DELETE FROM notifications WHERE ref_type = 'assignment' AND ref_id = ?", (str(assignment_id),))
            con.execute("DELETE FROM assignment_status_history WHERE assignment_id = ?", (assignment_id,))
            con.execute("DELETE FROM assignments WHERE assignment_id = ?", (assignment_id,))
            con.commit()


def test_notify_new_high_risk_projects_diff():
    """#19: risk-engine rerun แจ้งเตือน project_auditor เฉพาะโครงการที่เพิ่งกลาย high (ไม่ high ใน run ก่อน)"""
    from src.database import db_session
    from src.routers.admin import _notify_new_high_risk_projects

    with db_session() as con:
        row = con.execute("""
            SELECT prs.project_id, p.subdistrict_id
            FROM project_risk_scores prs
            JOIN projects p ON p.project_id = prs.project_id
            WHERE prs.run_id = (SELECT MAX(run_id) FROM assessment_runs)
            ORDER BY prs.risk_score DESC LIMIT 1
        """).fetchone()
        project_id, subdistrict_id = row["project_id"], row["subdistrict_id"]

        before_ids = {r["notification_id"] for r in con.execute(
            "SELECT notification_id FROM notifications WHERE ref_type = 'project' AND ref_id = ?", (project_id,)
        )}

        fake_run_ids = []
        try:
            prev_run_id = con.execute(
                "INSERT INTO assessment_runs (triggered_by, note) VALUES ('pytest','diff test') RETURNING run_id"
            ).fetchone()["run_id"]
            fake_run_ids.append(prev_run_id)
            con.execute(
                """INSERT INTO project_risk_scores (run_id, project_id, risk_score, risk_level, factors_triggered)
                   VALUES (?,?,?,?,?)""",
                (prev_run_id, project_id, 10.0, "low", 0),
            )

            new_run_id = con.execute(
                "INSERT INTO assessment_runs (triggered_by, note) VALUES ('pytest','diff test') RETURNING run_id"
            ).fetchone()["run_id"]
            fake_run_ids.append(new_run_id)
            con.execute(
                """INSERT INTO project_risk_scores (run_id, project_id, risk_score, risk_level, factors_triggered)
                   VALUES (?,?,?,?,?)""",
                (new_run_id, project_id, 90.0, "high", 3),
            )
            con.commit()

            _notify_new_high_risk_projects(con, con, new_run_id)
            con.commit()

            after_ids = {r["notification_id"] for r in con.execute(
                "SELECT notification_id FROM notifications WHERE ref_type = 'project' AND ref_id = ?", (project_id,)
            )}
            new_ids = after_ids - before_ids
            assert new_ids, "ควรมี notification ใหม่เมื่อโครงการเปลี่ยนจาก low -> high"

            auditor_ids = {r["user_id"] for r in con.execute(
                "SELECT user_id FROM users WHERE role='project_auditor' AND subdistrict_id = ?", (subdistrict_id,)
            )}
            placeholders = ",".join("?" * len(new_ids))
            notified_users = {r["user_id"] for r in con.execute(
                f"SELECT user_id FROM notifications WHERE notification_id IN ({placeholders})", list(new_ids)
            )}
            assert notified_users == auditor_ids

            # rerun ด้วย run_id เดิม (idempotent-ish check) ไม่ควร error ซ้ำ
            no_prev = con.execute(
                "SELECT run_id FROM assessment_runs ORDER BY run_id ASC LIMIT 1"
            ).fetchone()["run_id"]
            _notify_new_high_risk_projects(con, con, no_prev)  # run แรกสุด ไม่มี run ก่อนหน้า -> ไม่ error, ไม่ notify
            con.commit()
        finally:
            # ระวัง: "NOT IN (NULL)" ไม่ match อะไรเลยใน SQL — ถ้า before_ids ว่างต้องลบทั้งหมดตรงๆ
            if before_ids:
                placeholders = ",".join("?" * len(before_ids))
                con.execute(
                    f"DELETE FROM notifications WHERE ref_type = 'project' AND ref_id = ? "
                    f"AND notification_id NOT IN ({placeholders})",
                    [project_id] + list(before_ids),
                )
            else:
                con.execute(
                    "DELETE FROM notifications WHERE ref_type = 'project' AND ref_id = ?",
                    (project_id,),
                )
            for run_id in fake_run_ids:
                con.execute("DELETE FROM project_risk_scores WHERE run_id = ?", (run_id,))
                con.execute("DELETE FROM assessment_runs WHERE run_id = ?", (run_id,))
            con.commit()


def test_public_projects_export():
    """#21: export ข้อมูลเปิดภาครัฐ — csv/json format ถูกต้อง, format ผิด -> 400, ไม่มี field ภายในหลุด"""
    r = client.get("/public/projects/export", params={"format": "csv"}, headers={"X-Username": "public1"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment; filename=" in r.headers["content-disposition"]
    header_line = r.text.lstrip("﻿").splitlines()[0]
    assert header_line == "project_id,project_name,subdistrict,budget_year,budget_amount,risk_score,risk_level"
    assert "evidence_text" not in r.text
    assert "threshold_used" not in r.text

    r = client.get("/public/projects/export", params={"format": "json"}, headers={"X-Username": "public1"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert body["metadata"]["source"] == "FinRisk"
    assert body["metadata"]["license"]
    assert body["data"], "ต้องมีข้อมูลโครงการอย่างน้อย 1 แถว"
    row = body["data"][0]
    assert set(row.keys()) == {
        "project_id", "project_name", "subdistrict", "budget_year",
        "budget_amount", "risk_score", "risk_level",
    }

    r = client.get("/public/projects/export", params={"format": "xml"}, headers={"X-Username": "public1"})
    assert r.status_code == 400


def test_public_projects_export_role_gate():
    """#21: role ที่ปกติถูก scope ตำบล (project_auditor/risk_analyst/local_executive) เข้าถึงไม่ได้
    — endpoint นี้ไม่ผ่าน scope_subdistrict_ids จึงต้องจำกัดด้วย role แทน กันเห็นข้อมูลข้ามตำบล"""
    for username in ("auditor1", "analyst1", "thachang_user"):
        r = client.get("/public/projects/export", params={"format": "csv"}, headers={"X-Username": username})
        assert r.status_code == 403, username

    for username in ("admin", "supervisor1", "public1"):
        r = client.get("/public/projects/export", params={"format": "csv"}, headers={"X-Username": username})
        assert r.status_code == 200, username

def test_public_projects_export_feature_flag_grants_access():
    """role ที่ไม่อยู่ใน EXPORT_ROLES และไม่มี public_projects_export ต้องถูกปฏิเสธ"""
    from src.database import db_session

    username = "auditor1"

    # เก็บสิทธิ์เดิมไว้ แล้วเพิ่ม flag ชั่วคราวสำหรับทดสอบ
    with db_session() as con:
        row = con.execute(
            "SELECT allowed_features FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        original_features = list(row["allowed_features"] or [])

        con.execute(
            "UPDATE users SET allowed_features = ? WHERE username = ?",
            (["public_projects_export"], username),
        )
        con.commit()

    try:
        response = client.get(
            "/public/projects/export",
            params={"format": "json"},
            headers={"X-Username": username},
        )

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        assert response.json()["data"]
    finally:
        # คืนค่าเดิมเสมอ แม้ test ล้มเหลว
        with db_session() as con:
            con.execute(
                "UPDATE users SET allowed_features = ? WHERE username = ?",
                (original_features, username),
            )
            con.commit()