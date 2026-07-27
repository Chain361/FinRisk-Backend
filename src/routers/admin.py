# -*- coding: utf-8 -*-
"""/admin — นำเข้าข้อมูลรอบใหม่ + สั่งรัน risk engine ใหม่ (admin เท่านั้น)

ใช้ logic เดิมจาก seed_database.py ทั้งหมด (ห้ามแก้ตรรกะ risk ที่นี่ ตาม CLAUDE.md) —
router นี้แค่เป็นทางเข้าจาก HTTP มาเรียก seed_vendors/seed_projects/seed_financial/
run_project_engine/run_annual_engine ที่มีอยู่แล้ว

หมายเหตุ: ฟังก์ชันเหล่านี้ทุกตัวรับ **cursor** (ไม่ใช่ connection) เพราะข้างในเรียก
`cur.execute(...)` แล้วอ่าน `cur.description`/`cur.fetchall()` ต่อจาก cursor ตัวเดิม —
ต้องใช้ `conn.cursor()` เสมอ ห้ามส่ง `conn` เข้าไปตรงๆ
"""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from seed_database import (
    read_csv_clean_bytes,
    run_annual_engine,
    run_project_engine,
    seed_financial,
    seed_projects,
    seed_vendors,
)

from ..auth import require_roles
from ..database import Connection, get_db
from ..notify import create_notification
from ..schemas import DataUploadOut, RiskEngineRunOut

router = APIRouter(prefix="/admin", tags=["admin"])


def _notify_new_high_risk_projects(cur, conn: Connection, run_id: int) -> None:
    """แจ้งเตือน project_auditor ของตำบล เมื่อพบโครงการ risk_level='high' ใหม่ (ไม่ high ใน run ก่อนหน้า)
    เป็น query แบบ additive เท่านั้น — ไม่แตะ/ไม่ซ้ำ risk logic ใน seed_database.py ตามกติกา CLAUDE.md
    ถ้าไม่มี run ก่อนหน้า (run แรกของระบบ) จะไม่แจ้งเตือนเลย กัน flood ตอนเริ่มระบบ"""
    prev_run = cur.execute(
        "SELECT run_id FROM assessment_runs WHERE run_id < ? ORDER BY run_id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    if prev_run is None:
        return
    prev_run_id = prev_run["run_id"]
    newly_high = cur.execute(
        """SELECT cur_scores.project_id, p.project_name, p.subdistrict_id
           FROM project_risk_scores cur_scores
           JOIN projects p ON p.project_id = cur_scores.project_id
           WHERE cur_scores.run_id = ? AND cur_scores.risk_level = 'high'
             AND cur_scores.project_id NOT IN (
                 SELECT project_id FROM project_risk_scores
                 WHERE run_id = ? AND risk_level = 'high'
             )""",
        (run_id, prev_run_id),
    ).fetchall()
    for row in newly_high:
        auditors = cur.execute(
            "SELECT user_id FROM users WHERE role = 'project_auditor' AND subdistrict_id = ?",
            (row["subdistrict_id"],),
        ).fetchall()
        for auditor in auditors:
            create_notification(
                conn,
                auditor["user_id"],
                "high_risk",
                f"พบโครงการเสี่ยงสูงใหม่: {row['project_name']}",
                "project",
                row["project_id"],
            )


@router.post("/risk-engine/run", response_model=RiskEngineRunOut)
def run_risk_engine(
    user: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
):
    """คำนวณ risk score ใหม่จากข้อมูล projects/financial_statements ปัจจุบันในฐานข้อมูล
    (ไม่อ่าน CSV ใหม่ — ใช้หลัง /admin/data/upload หรือหลังแก้ risk_factors)"""
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO assessment_runs (triggered_by, note) VALUES (?, ?) RETURNING run_id, run_at",
        (user["username"], "manual run ผ่าน /admin/risk-engine/run"),
    )
    row = cur.fetchone()
    run_id, run_at = row["run_id"], row["run_at"]

    run_project_engine(cur, run_id)
    run_annual_engine(cur, run_id)
    _notify_new_high_risk_projects(cur, conn, run_id)
    conn.commit()

    project_count = cur.execute(
        "SELECT COUNT(*) AS n FROM project_risk_scores WHERE run_id = ?", (run_id,)
    ).fetchone()["n"]
    annual_count = cur.execute(
        "SELECT COUNT(*) AS n FROM annual_risk_results WHERE run_id = ?", (run_id,)
    ).fetchone()["n"]

    return RiskEngineRunOut(
        run_id=run_id,
        run_at=run_at,
        triggered_by=user["username"],
        project_count=project_count,
        annual_count=annual_count,
    )


@router.post("/data/upload", response_model=DataUploadOut)
async def upload_data(
    subdistrict_id: int = Form(...),
    projects_csv: UploadFile | None = File(default=None),
    financial_csv: UploadFile | None = File(default=None),
    user: dict = Depends(require_roles("admin")),
    conn: Connection = Depends(get_db),
):
    """นำเข้าโครงการ/งบการเงินรอบใหม่ของตำบลที่มีอยู่แล้ว (ไม่สร้างตำบลใหม่)
    ฟอร์แมต CSV ต้องตรงกับ standardized_data/*.csv ตาม _schema_dictionary.md
    ข้อมูลใหม่จะยังไม่เห็นผลบน risk dashboard จนกว่าจะเรียก /admin/risk-engine/run ต่อ"""
    if projects_csv is None and financial_csv is None:
        raise HTTPException(status_code=422, detail="ต้องแนบไฟล์อย่างน้อย 1 ไฟล์ (projects_csv หรือ financial_csv)")

    cur = conn.cursor()
    sub = cur.execute(
        "SELECT subdistrict_id, name_th FROM subdistricts WHERE subdistrict_id = ?",
        (subdistrict_id,),
    ).fetchone()
    if sub is None:
        raise HTTPException(status_code=404, detail="ไม่พบตำบลนี้ในระบบ")
    sub_id = {sub["name_th"]: sub["subdistrict_id"]}

    projects_inserted, dups, financial_inserted = 0, [], 0
    try:
        if projects_csv is not None:
            proj_rows = read_csv_clean_bytes(await projects_csv.read())
            mismatched = {r.get("subdistrict", "").strip() for r in proj_rows} - {sub["name_th"], ""}
            if mismatched:
                raise HTTPException(
                    status_code=422,
                    detail=f"ไฟล์นี้มีข้อมูลตำบลอื่นปนอยู่ ({', '.join(mismatched)}) — ต้องอัปโหลดทีละตำบล",
                )
            seed_vendors(cur, proj_rows)
            projects_inserted, dups = seed_projects(cur, proj_rows, sub_id)

        if financial_csv is not None:
            fin_rows = read_csv_clean_bytes(await financial_csv.read())
            mismatched = {r.get("ตำบล", "").strip() for r in fin_rows} - {sub["name_th"], ""}
            if mismatched:
                raise HTTPException(
                    status_code=422,
                    detail=f"ไฟล์นี้มีข้อมูลตำบลอื่นปนอยู่ ({', '.join(mismatched)}) — ต้องอัปโหลดทีละตำบล",
                )
            financial_inserted = seed_financial(cur, fin_rows, sub_id)

        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except (KeyError, ValueError) as exc:
        conn.rollback()
        raise HTTPException(status_code=422, detail=f"ไฟล์ CSV รูปแบบไม่ถูกต้อง: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — insert ล้มเหลว (เช่น constraint) ต้อง rollback แล้วแจ้งชัดเจน
        conn.rollback()
        raise HTTPException(status_code=400, detail=f"นำเข้าข้อมูลไม่สำเร็จ: {exc}") from exc

    return DataUploadOut(
        subdistrict_id=subdistrict_id,
        projects_inserted=projects_inserted,
        projects_skipped_duplicate=dups,
        financial_rows_inserted=financial_inserted,
    )
