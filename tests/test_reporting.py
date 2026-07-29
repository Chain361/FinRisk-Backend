# -*- coding: utf-8 -*-
"""Regression tests for audit-report and risk-register exports."""
import io
import re
import zipfile

from fastapi.testclient import TestClient

from src.database import _connect
from src.main import app
from src.services.reporting import risk_register_rows

client = TestClient(app)


def _create_report_for_subdistrict(subdistrict_id: int) -> int:
    """Create one temporary report and return its id; callers must delete it in finally."""
    conn = _connect()
    try:
        assignment = conn.execute(
            """SELECT a.assignment_id
               FROM assignments a
               JOIN projects p ON p.project_id = a.project_id
               WHERE p.subdistrict_id = ?
               ORDER BY a.assignment_id
               LIMIT 1""",
            (subdistrict_id,),
        ).fetchone()
        assert assignment is not None, "seed ต้องมี assignment ของตำบลทดสอบ"
        report_id = conn.execute(
            """INSERT INTO audit_reports
               (assignment_id, work_process, objective, likelihood, impact, impact_score,
                risk_level, findings)
               VALUES (?,?,?,?,?,?,?,?)
               RETURNING report_id""",
            (
                assignment["assignment_id"],
                "ทดสอบ export",
                "ยืนยันว่า export ได้",
                3,
                4,
                4,
                4,
                "รายงานชั่วคราวจาก regression test",
            ),
        ).fetchone()["report_id"]
        conn.commit()
        return report_id
    finally:
        conn.close()


def _delete_report(report_id: int) -> None:
    conn = _connect()
    try:
        conn.execute("DELETE FROM audit_reports WHERE report_id = ?", (report_id,))
        conn.commit()
    finally:
        conn.close()


def test_risk_register_export_is_xlsx_and_scoped():
    response = client.get(
        "/risk/register/export?format=xlsx",
        headers={"X-Username": "thachang_user", "Origin": "http://localhost:4200"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert re.search(
        r"attachment; filename=finrisk_risk_register_thachang_\d{8}_\d{6}\.xlsx$",
        response.headers["content-disposition"],
    )
    assert "content-disposition" in response.headers["access-control-expose-headers"].lower()
    workbook = zipfile.ZipFile(io.BytesIO(response.content))
    assert "xl/worksheets/sheet1.xml" in workbook.namelist()

    conn = _connect()
    try:
        user = dict(conn.execute("SELECT * FROM users WHERE username = 'thachang_user'").fetchone())
        rows = risk_register_rows(conn, user)
        project_ids = {row["project_id"] for row in rows}
        scoped_ids = {
            row["project_id"]
            for row in conn.execute("SELECT project_id FROM projects WHERE subdistrict_id = ?", (user["subdistrict_id"],))
        }
        assert project_ids
        assert project_ids <= scoped_ids
    finally:
        conn.close()

    invalid = client.get("/risk/register/export?format=pdf", headers={"X-Username": "thachang_user"})
    assert invalid.status_code == 400

    all_subdistricts = client.get("/risk/register/export?format=xlsx", headers={"X-Username": "admin"})
    assert all_subdistricts.status_code == 200
    assert re.search(
        r"attachment; filename=finrisk_risk_register_all_subdistricts_\d{8}_\d{6}\.xlsx$",
        all_subdistricts.headers["content-disposition"],
    )


def test_audit_report_export_formats_and_scope():
    report_id = _create_report_for_subdistrict(1)
    try:
        pdf = client.get(f"/audit/reports/{report_id}/export?format=pdf", headers={"X-Username": "auditor1"})
        assert pdf.status_code == 200
        assert pdf.headers["content-type"].startswith("application/pdf")
        assert pdf.content.startswith(b"%PDF")
        assert re.search(
            rf"attachment; filename=finrisk_audit_report_[a-z0-9_-]+_thachang_{report_id}\.pdf$",
            pdf.headers["content-disposition"],
        )

        xlsx = client.get(f"/audit/reports/{report_id}/export?format=xlsx", headers={"X-Username": "auditor1"})
        assert xlsx.status_code == 200
        assert xlsx.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert re.search(
            rf"attachment; filename=finrisk_audit_report_[a-z0-9_-]+_thachang_{report_id}\.xlsx$",
            xlsx.headers["content-disposition"],
        )
        assert "xl/worksheets/sheet1.xml" in zipfile.ZipFile(io.BytesIO(xlsx.content)).namelist()

        invalid = client.get(f"/audit/reports/{report_id}/export?format=csv", headers={"X-Username": "auditor1"})
        assert invalid.status_code == 400
        outside_scope = client.get(
            f"/audit/reports/{report_id}/export?format=pdf", headers={"X-Username": "auditor2"}
        )
        assert outside_scope.status_code == 403
        public_user = client.get(
            f"/audit/reports/{report_id}/export?format=pdf", headers={"X-Username": "public1"}
        )
        assert public_user.status_code == 403
    finally:
        _delete_report(report_id)


def test_project_auditor_creates_one_report_per_resolved_feedback():
    """WP report must come from one approved feedback and be exclusive to project auditors."""
    auditor = {"X-Username": "auditor1"}
    assignments = client.get("/audit/assignments", headers=auditor)
    assert assignments.status_code == 200
    assignment = next(
        row for row in assignments.json() if row["assigned_by_username"] == "auditor1"
    )
    feedback_id = None
    try:
        created = client.post(
            "/audit/feedback",
            headers=auditor,
            json={
                "project_id": assignment["project_id"],
                "feedback_text": "ข้อตรวจพบสำหรับสร้างรายงาน WP",
                "suggestions": "ติดตามการแก้ไขตามข้อเสนอแนะ",
                "concern_level": "high",
                "likelihood_score": 3,
                "impact_score": 4,
                "status": "submitted",
            },
        )
        assert created.status_code == 201
        feedback_id = created.json()["feedback_id"]

        resolved = client.patch(f"/audit/feedback/{feedback_id}/resolve", headers=auditor)
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved"

        preview = client.get(f"/audit/reports/from-feedback/{feedback_id}", headers=auditor)
        assert preview.status_code == 200
        assert preview.json()["report_id"] is None
        assert preview.json()["findings"] == "ข้อตรวจพบสำหรับสร้างรายงาน WP"
        assert preview.json()["likelihood"] == 3
        assert preview.json()["impact"] == 4

        saved = client.post(f"/audit/reports/from-feedback/{feedback_id}", headers=auditor)
        assert saved.status_code == 200, saved.text
        report_id = saved.json()["report_id"]
        assert report_id is not None

        saved_again = client.post(f"/audit/reports/from-feedback/{feedback_id}", headers=auditor)
        assert saved_again.status_code == 200
        assert saved_again.json()["report_id"] == report_id

        assert client.get(
            f"/audit/reports/from-feedback/{feedback_id}", headers={"X-Username": "admin"}
        ).status_code == 403
    finally:
        if feedback_id is not None:
            conn = _connect()
            try:
                conn.execute("DELETE FROM audit_reports WHERE feedback_id = ?", (feedback_id,))
                conn.execute("DELETE FROM auditor_feedback WHERE feedback_id = ?", (feedback_id,))
                conn.commit()
            finally:
                conn.close()
