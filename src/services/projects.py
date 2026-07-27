# -*- coding: utf-8 -*-
"""
projects.py (service) — รายการโครงการ + สรุปโครงการรายตัว

ย้ายมาจาก src/routers/projects.py เพื่อให้ chatbot tool เรียก logic เดียวกับ
router ได้โดยไม่ก็อป SQL ซ้ำ (ตาม pattern ของ services/legal.py, services/documents.py)
"""
import sqlite3

from ..database import rows_to_dicts
from .common import NotFoundError, ForbiddenError, latest_run_id


def list_projects_view(
    conn: sqlite3.Connection,
    user: dict,
    budget_year: int | None = None,
    subdistrict_id: int | None = None,
    risk_level: str | None = None,
) -> list[dict]:
    # import ในฟังก์ชันเพื่อเลี่ยง circular import (auth → database → services)
    from ..auth import scope_subdistrict_ids

    run_id = latest_run_id(conn)
    where, params = [], []

    allowed = scope_subdistrict_ids(conn, user)
    if allowed is not None:
        if not allowed:
            return []
        where.append(f"p.subdistrict_id IN ({','.join('?' * len(allowed))})")
        params += allowed

    if subdistrict_id is not None:
        where.append("p.subdistrict_id = ?")
        params.append(subdistrict_id)
    if budget_year is not None:
        where.append("p.budget_year = ?")
        params.append(budget_year)
    if risk_level is not None:
        where.append("s.risk_level = ?")
        params.append(risk_level)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    sql = f"""
        SELECT p.project_id, p.project_name, p.budget_year, p.subdistrict_id,
               p.project_type, p.purchase_method_group,
               p.budget_amount, p.reference_price, p.contract_value, p.price_ratio,
               s.risk_score, s.risk_level, s.matrix_level, s.factors_triggered
        FROM projects p
        LEFT JOIN project_risk_scores s
               ON s.project_id = p.project_id AND s.run_id = ?
        {where_sql}
        ORDER BY s.risk_score DESC NULLS LAST, p.project_id
    """
    rows = conn.execute(sql, [run_id, *params]).fetchall()
    return rows_to_dicts(rows)


def project_summary_view(conn: sqlite3.Connection, project_id: str, user: dict) -> dict:
    """โครงการ (ทุกคอลัมน์) + risk score ล่าสุด + risk factor รายตัว

    หมายเหตุ: ไม่ใช้ services.common.load_project_in_scope เพราะฟังก์ชันนั้นคืนคอลัมน์ย่อยชุดหนึ่ง
    (ออกแบบไว้ให้ legal/documents service ใช้) แต่ payload นี้ต้องคง `SELECT *` เดิมของ router
    ไม่ให้ field หายไปจาก response เดิม
    """
    # import ในฟังก์ชันเพื่อเลี่ยง circular import (auth → database → services)
    from ..auth import scope_subdistrict_ids

    p = conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    if p is None:
        raise NotFoundError("ไม่พบโครงการ")

    allowed = scope_subdistrict_ids(conn, user)
    if allowed is not None and p["subdistrict_id"] not in allowed:
        raise ForbiddenError("ไม่มีสิทธิ์เข้าถึงโครงการนอกตำบลของคุณ")

    run_id = latest_run_id(conn)
    score = conn.execute(
        "SELECT * FROM project_risk_scores WHERE project_id = ? AND run_id = ?",
        (project_id, run_id),
    ).fetchone()
    factors = conn.execute(
        """SELECT r.factor_code, f.name_th, f.severity, f.impact_level, f.legal_ref, f.formula,
                  r.triggered, r.computable, r.observed_value, r.threshold_used, r.evidence_text,
                  r.likelihood, r.impact, r.matrix_score, r.risk_band
           FROM project_risk_results r
           JOIN risk_factors f ON f.factor_code = r.factor_code
           WHERE r.project_id = ? AND r.run_id = ?
           ORDER BY r.factor_code""",
        (project_id, run_id),
    ).fetchall()

    return {
        "project": dict(p),
        "risk_score": dict(score) if score else None,
        "risk_factors": rows_to_dicts(factors),
    }
