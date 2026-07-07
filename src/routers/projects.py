# -*- coding: utf-8 -*-
"""/projects — โครงการจัดซื้อจัดจ้าง + risk score ล่าสุด"""
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user, scope_subdistrict_ids
from ..database import get_db, rows_to_dicts

router = APIRouter(prefix="/projects", tags=["projects"])


def _latest_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT run_id FROM assessment_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    return row["run_id"] if row else None


@router.get("")
def list_projects(
    budget_year: int | None = Query(default=None),
    subdistrict_id: int | None = Query(default=None),
    risk_level: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    run_id = _latest_run_id(conn)
    where, params = [], []

    # scope ตาม role
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
               s.risk_score, s.risk_level, s.factors_triggered
        FROM projects p
        LEFT JOIN project_risk_scores s
               ON s.project_id = p.project_id AND s.run_id = ?
        {where_sql}
        ORDER BY s.risk_score DESC NULLS LAST, p.project_id
    """
    rows = conn.execute(sql, [run_id, *params]).fetchall()
    return rows_to_dicts(rows)


@router.get("/{project_id}")
def get_project(
    project_id: str,
    user: dict = Depends(get_current_user),
    conn: sqlite3.Connection = Depends(get_db),
):
    p = conn.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    if p is None:
        raise HTTPException(status_code=404, detail="ไม่พบโครงการ")

    allowed = scope_subdistrict_ids(conn, user)
    if allowed is not None and p["subdistrict_id"] not in allowed:
        raise HTTPException(status_code=403, detail="ไม่มีสิทธิ์เข้าถึงโครงการนอกตำบลของคุณ")

    run_id = _latest_run_id(conn)
    score = conn.execute(
        "SELECT * FROM project_risk_scores WHERE project_id = ? AND run_id = ?",
        (project_id, run_id),
    ).fetchone()
    factors = conn.execute(
        """SELECT r.factor_code, f.name_th, f.severity, r.triggered, r.computable,
                  r.observed_value, r.threshold_used, r.evidence_text
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
