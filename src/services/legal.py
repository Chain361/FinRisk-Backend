# -*- coding: utf-8 -*-
"""
legal.py (service) — ชั้นกฎหมาย: laws / law_sections / factor_legal_map

อ่านอย่างเดียว ไม่แตะตาราง risk เดิม (legal linkage เป็น metadata ที่แขวนกับ factor_code)
"""
import sqlite3

from .common import latest_run_id, load_project_in_scope, parse_json

# ข้อความตายตัวสำหรับ factor ที่ยัง triggered แต่ยังไม่ curate mapping กฎหมาย
# (legal_linkage_plan §5.2 — ห้ามให้ LLM เดา/แต่งมาตราเอง)
NO_LEGAL_MAPPING_NOTE = "ข้อบ่งชี้นี้ยังไม่มีการเชื่อมโยงข้อกฎหมายในระบบ (อยู่ระหว่างจัดทำ)"

# factor ที่ derive จากเนื้อหาเอกสาร → แนบ document_findings ไปใน payload ด้วย
FACTORS_WITH_DOCUMENT_FINDINGS = ("L3",)


def list_laws(conn: sqlite3.Connection) -> list[dict]:
    """รายการกฎหมาย + มาตรา/ข้อ ที่ curate ไว้ (reference data ไม่มี scope ตำบล)"""
    laws = {
        row["law_id"]: {**dict(row), "sections": []}
        for row in conn.execute(
            "SELECT law_id, law_code, law_name_th, law_type, year_be, source_file "
            "FROM laws ORDER BY law_id"
        )
    }
    sections = conn.execute(
        "SELECT section_id, law_id, section_no, section_title, section_summary, section_text "
        "FROM law_sections ORDER BY law_id, section_id"
    )
    for s in sections:
        parent = laws.get(s["law_id"])
        if parent is not None:
            parent["sections"].append(dict(s))
    return list(laws.values())


def _legal_refs_by_factor(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """factor_code → [มาตราที่ผูกไว้] (โหลดครั้งเดียว กัน N+1 query)"""
    out: dict[str, list[dict]] = {}
    rows = conn.execute(
        """SELECT m.factor_code, s.section_id, s.section_no, s.section_title,
                  s.section_summary, l.law_code, l.law_name_th, l.law_type, m.reason_text
           FROM factor_legal_map m
           JOIN law_sections s ON s.section_id = m.section_id
           JOIN laws l ON l.law_id = s.law_id
           ORDER BY m.factor_code, l.law_id, s.section_id"""
    )
    for r in rows:
        out.setdefault(r["factor_code"], []).append(
            {
                "section_id": r["section_id"],
                "law_code": r["law_code"],
                "law": r["law_name_th"],
                "law_type": r["law_type"],
                "section_no": r["section_no"],
                "section_title": r["section_title"],
                "summary": r["section_summary"],
                "reason": r["reason_text"],
            }
        )
    return out


def _findings_with_legal(conn: sqlite3.Connection, project_id: str) -> list[dict]:
    """ข้อสังเกตในเอกสารของโครงการ + มาตราที่ผูก (ใช้ประกอบ factor L3)"""
    findings = conn.execute(
        """SELECT f.finding_id, f.doc_id, d.doc_type_code, t.name_th AS doc_type_name,
                  f.finding_text, f.risk_category, f.observed_value, f.expected_value,
                  f.severity, f.source
           FROM document_findings f
           JOIN project_documents d ON d.doc_id = f.doc_id
           JOIN document_types t ON t.doc_type_code = d.doc_type_code
           WHERE d.project_id = ?
           ORDER BY f.finding_id""",
        (project_id,),
    ).fetchall()
    if not findings:
        return []

    ids = [f["finding_id"] for f in findings]
    refs: dict[int, list[dict]] = {}
    rows = conn.execute(
        f"""SELECT fm.finding_id, s.section_id, s.section_no, s.section_title,
                   s.section_summary, l.law_code, l.law_name_th, l.law_type, fm.reason_text
            FROM finding_legal_map fm
            JOIN law_sections s ON s.section_id = fm.section_id
            JOIN laws l ON l.law_id = s.law_id
            WHERE fm.finding_id IN ({",".join("?" * len(ids))})
            ORDER BY fm.finding_id, s.section_id""",
        ids,
    )
    for r in rows:
        refs.setdefault(r["finding_id"], []).append(
            {
                "section_id": r["section_id"],
                "law_code": r["law_code"],
                "law": r["law_name_th"],
                "law_type": r["law_type"],
                "section_no": r["section_no"],
                "section_title": r["section_title"],
                "summary": r["section_summary"],
                "reason": r["reason_text"],
            }
        )
    return [{**dict(f), "legal_refs": refs.get(f["finding_id"], [])} for f in findings]


def project_legal_view(
    conn: sqlite3.Connection,
    project_id: str,
    user: dict,
    only_triggered: bool = False,
) -> list[dict]:
    """
    payload เดียวจบสำหรับ chatbot: ผล risk factor ล่าสุด + action + ข้อกฎหมายที่เกี่ยวข้อง

    - ต้องมี `computable` เสมอ — chatbot ต้องแยก "ไม่เสี่ยง" (triggered=0, computable=1)
      ออกจาก "ข้อมูลไม่พอประเมิน" (computable=0) ตาม Mission Feature 4
    - factor ที่ triggered แต่ยังไม่มี mapping → `legal_refs=[]` + `legal_ref_note`
      (ข้อความตายตัวจาก backend ไม่ให้ LLM แต่งมาตราเอง)
    """
    load_project_in_scope(conn, project_id, user)  # scope guard
    run_id = latest_run_id(conn)
    if run_id is None:
        return []

    rows = conn.execute(
        """SELECT r.factor_code, f.name_th AS factor_name, f.description, f.severity,
                  f.impact_level, f.weight, f.legal_ref AS legal_ref_text,
                  f.action_suggestion, f.applies_to_project_type,
                  r.triggered, r.computable, r.observed_value, r.threshold_used,
                  r.evidence_text, r.likelihood, r.impact, r.matrix_score, r.risk_band
           FROM project_risk_results r
           JOIN risk_factors f ON f.factor_code = r.factor_code
           WHERE r.project_id = ? AND r.run_id = ?
           ORDER BY r.triggered DESC, r.factor_code""",
        (project_id, run_id),
    ).fetchall()

    refs_map = _legal_refs_by_factor(conn)
    findings = None  # lazy — query เอกสารเฉพาะเมื่อมี factor ที่ต้องใช้
    out: list[dict] = []
    for r in rows:
        if only_triggered and not r["triggered"]:
            continue
        item = dict(r)
        item["threshold_used"] = parse_json(r["threshold_used"], None)
        legal_refs = refs_map.get(r["factor_code"], [])
        item["legal_refs"] = legal_refs
        if not legal_refs and r["triggered"]:
            item["legal_ref_note"] = NO_LEGAL_MAPPING_NOTE
        if r["factor_code"] in FACTORS_WITH_DOCUMENT_FINDINGS:
            if findings is None:
                findings = _findings_with_legal(conn, project_id)
            item["findings"] = findings
        out.append(item)
    return out
