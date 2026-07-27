# -*- coding: utf-8 -*-
"""ข้อมูลเปิดภาครัฐ (Open Data, เกณฑ์ ITA) — เฉพาะข้อมูลระดับ dashboard ที่ public_user
เห็นได้อยู่แล้ว (project_id, project_name, subdistrict, budget_year, budget_amount,
risk_score, risk_level) ห้ามรวม field ภายใน เช่น evidence_text/threshold_used/factor-level
(อยู่ใน v_project_risk_detail) หรือ auditor_feedback/assignments/access_log"""
import csv
import io
import json
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..auth import require_roles
from ..database import Connection, get_db

router = APIRouter(prefix="/public", tags=["public"])

# เห็นทุกตำบลอยู่แล้วตาม roles.md (ไม่มี subdistrict scope) — endpoint นี้เป็น open data
# ไม่ผ่าน scope_subdistrict_ids ตั้งใจ จึงจำกัด role ตรงนี้แทน กัน role ที่ปกติถูก scope
# (project_auditor/risk_analyst/local_executive) เห็นข้อมูลข้ามตำบลผ่านทางอ้อม
EXPORT_ROLES = ("admin", "regional_supervisor", "public_user")
# อักขระที่ Excel/Sheets ตีความเป็นจุดเริ่มสูตร — ต้อง escape กัน formula injection ตอนเปิดไฟล์
_FORMULA_PREFIXES = ("=", "+", "-", "@")

EXPORT_SELECT = """
    SELECT p.project_id, p.project_name, s.name_th AS subdistrict, p.budget_year,
           p.budget_amount, prs.risk_score, prs.risk_level
    FROM projects p
    JOIN subdistricts s ON s.subdistrict_id = p.subdistrict_id
    LEFT JOIN project_risk_scores prs ON prs.project_id = p.project_id
        AND prs.run_id = (SELECT MAX(run_id) FROM assessment_runs)
    ORDER BY p.subdistrict_id, p.project_id
"""
EXPORT_FIELDS = [
    "project_id", "project_name", "subdistrict", "budget_year",
    "budget_amount", "risk_score", "risk_level",
]


def _csv_safe(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


@router.get("/projects/export")
def export_projects(
    format: str = Query(...),
    user: dict = Depends(require_roles(*EXPORT_ROLES)),
    conn: Connection = Depends(get_db),
):
    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="format ต้องเป็น csv หรือ json เท่านั้น")

    rows = conn.execute(EXPORT_SELECT).fetchall()
    data = [{field: row[field] for field in EXPORT_FIELDS} for row in rows]
    filename_date = date.today().isoformat()

    if format == "json":
        payload = {
            "metadata": {
                "source": "FinRisk",
                "license": "Open Government License",
                "license_url": "https://data.go.th/OpenGovernmentLicense",
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "data": data,
        }
        return Response(
            content=json.dumps(payload, ensure_ascii=False),
            media_type="application/json; charset=utf-8",
            headers={
                "Content-Disposition": f"attachment; filename=finrisk_projects_open_data_{filename_date}.json"
            },
        )

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    writer.writerows({field: _csv_safe(value) for field, value in row.items()} for row in data)
    return Response(
        # ใส่ UTF-8 BOM นำหน้า กันข้อความไทย (ชื่อตำบล/โครงการ) แสดงผลเพี้ยนตอนเปิดตรงด้วย Excel
        content="﻿" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=finrisk_projects_open_data_{filename_date}.csv"
        },
    )
