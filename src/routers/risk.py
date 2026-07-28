# -*- coding: utf-8 -*-
"""/risk — ผลการประเมินความเสี่ยง (project + annual) และรายการ risk factor"""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from ..auth import get_current_user, scope_subdistrict_ids
from ..database import Connection, get_db, rows_to_dicts
from ..services.reporting import build_risk_register_xlsx, risk_register_rows

router = APIRouter(prefix="/risk", tags=["risk"])


def _latest_run_id(conn: Connection) -> int | None:
    row = conn.execute(
        "SELECT run_id FROM assessment_runs ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    return row["run_id"] if row else None


@router.get("/factors")
def list_factors(
    _: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    rows = conn.execute("SELECT * FROM risk_factors ORDER BY scope, factor_code").fetchall()
    return rows_to_dicts(rows)


@router.get("/annual")
def annual_results(
    user: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    run_id = _latest_run_id(conn)
    allowed = scope_subdistrict_ids(conn, user)
    where, params = ["a.run_id = ?"], [run_id]
    if allowed is not None:
        if not allowed:
            return []
        where.append(f"a.subdistrict_id IN ({','.join('?' * len(allowed))})")
        params += allowed
    sql = f"""
        SELECT a.subdistrict_id, s.name_th AS subdistrict, a.fiscal_year,
               a.factor_code, f.name_th AS factor_name, f.legal_ref, a.triggered, a.computable,
               a.risk_level, a.observed_value, a.threshold_used, a.evidence_text,
               a.likelihood, a.impact, a.matrix_score, a.risk_band
        FROM annual_risk_results a
        JOIN subdistricts s ON s.subdistrict_id = a.subdistrict_id
        JOIN risk_factors f ON f.factor_code = a.factor_code
        WHERE {" AND ".join(where)}
        ORDER BY a.subdistrict_id, a.fiscal_year, a.factor_code
    """
    return rows_to_dicts(conn.execute(sql, params).fetchall())


@router.get("/summary")
def summary(
    budget_year: int | None = Query(default=None),
    subdistrict_id: int | None = Query(default=None),
    risk_level: str | None = Query(default=None, pattern="^(low|medium|high)$"),
    user: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """นับจำนวนโครงการตามระดับความเสี่ยง (ใช้ทำ dashboard)"""
    run_id = _latest_run_id(conn)
    allowed = scope_subdistrict_ids(conn, user)
    where, params = ["s.run_id = ?"], [run_id]
    if allowed is not None:
        if not allowed:
            return {"total": 0, "by_level": {}}
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
    sql = f"""
        SELECT s.risk_level, COUNT(*) AS n
        FROM project_risk_scores s
        JOIN projects p ON p.project_id = s.project_id
        WHERE {" AND ".join(where)}
        GROUP BY s.risk_level
    """
    rows = conn.execute(sql, params).fetchall()
    by_level = {r["risk_level"]: r["n"] for r in rows}
    return {"total": sum(by_level.values()), "by_level": by_level}


@router.get("/register/export")
def export_risk_register(
    format: str = Query("xlsx"),
    user: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db),
):
    """ส่งออกทะเบียนความเสี่ยงของรอบประเมินล่าสุดตาม scope ของผู้ใช้."""
    if format != "xlsx":
        raise HTTPException(status_code=400, detail="format ต้องเป็น xlsx เท่านั้น")
    content = build_risk_register_xlsx(risk_register_rows(conn, user))
    filename = f"finrisk_risk_register_{date.today().isoformat()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
