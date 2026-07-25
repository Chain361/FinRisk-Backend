# -*- coding: utf-8 -*-
"""
documents.py (service) — ชั้นเอกสาร: document_types / project_documents / document_findings

ตอบคำถาม chatbot ได้ตรงจาก structured data (legal_linkage_plan §5.3):
  - "เอกสารใดระบุราคากลาง"  → provides_index
  - "มีเอกสารใดที่ยังขาดอยู่" → missing_doc_types
  - "โครงการนี้มีความเสี่ยงด้านใด (เชิงเอกสาร)" → findings ของแต่ละเอกสาร
"""
import sqlite3

from .common import load_project_in_scope, parse_json
from .legal import _findings_with_legal


def list_document_types(conn: sqlite3.Connection) -> list[dict]:
    """ประเภทเอกสาร (reference) — `provides` บอกว่าเอกสารนั้นระบุอะไร"""
    rows = conn.execute(
        "SELECT doc_type_code, name_th, description, required_for_project_type, provides_json "
        "FROM document_types ORDER BY doc_type_code"
    ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        item["provides"] = parse_json(r["provides_json"], [])
        out.append(item)
    return out


def project_documents_view(conn: sqlite3.Connection, project_id: str, user: dict) -> dict:
    """
    เอกสารทั้งหมดของโครงการ + สถานะ + รายการที่ยังขาด + findings (พร้อม legal refs inline)

    `has_document_data = False` = ยังไม่เคยเก็บข้อมูลเอกสารของโครงการนี้
    (ห้ามตีความว่า "ขาดเอกสาร" — หลักเดียวกับ `fraud_risk_flag` ว่าง ≠ FALSE)
    """
    project = load_project_in_scope(conn, project_id, user)  # scope guard

    types = {t["doc_type_code"]: t for t in list_document_types(conn)}
    required = [
        code
        for code, t in types.items()
        if t["required_for_project_type"]
        and t["required_for_project_type"] == project["project_type"]
    ]

    docs = conn.execute(
        """SELECT doc_id, doc_type_code, status, doc_no, doc_date, summary_text,
                  extracted_json, file_path, source
           FROM project_documents WHERE project_id = ? ORDER BY doc_type_code""",
        (project_id,),
    ).fetchall()

    findings_by_doc: dict[int, list[dict]] = {}
    for f in _findings_with_legal(conn, project_id):
        findings_by_doc.setdefault(f["doc_id"], []).append(f)

    documents, present_codes = [], set()
    for d in docs:
        t = types.get(d["doc_type_code"], {})
        if d["status"] == "present":
            present_codes.add(d["doc_type_code"])
        documents.append(
            {
                "doc_id": d["doc_id"],
                "doc_type_code": d["doc_type_code"],
                "doc_type_name": t.get("name_th"),
                "status": d["status"],
                "is_required": d["doc_type_code"] in required,
                "doc_no": d["doc_no"],
                "doc_date": d["doc_date"],
                "summary_text": d["summary_text"],
                "extracted": parse_json(d["extracted_json"], {}),
                "provides": t.get("provides", []),
                "file_path": d["file_path"],
                "source": d["source"],
                "findings": findings_by_doc.get(d["doc_id"], []),
            }
        )

    doc_status = {d["doc_type_code"]: d["status"] for d in docs}
    missing = [
        {
            "doc_type_code": code,
            "name_th": types[code]["name_th"],
            "provides": types[code]["provides"],
            # แยก "ไม่มีบันทึกเลย" ออกจาก "บันทึกไว้ว่าขาด/รอตรวจ"
            "reason": doc_status.get(code, "no_record"),
        }
        for code in required
        if code not in present_codes
    ]

    # "เอกสารใดระบุ X" — index จาก provides_json ของ **ทุก** ประเภทเอกสารที่เกี่ยวกับโครงการ
    provides_index: dict[str, list[dict]] = {}
    for code in required or list(types):
        for item in types[code]["provides"]:
            provides_index.setdefault(item, []).append(
                {
                    "doc_type_code": code,
                    "name_th": types[code]["name_th"],
                    "status": doc_status.get(code, "no_record"),
                }
            )

    return {
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "project_type": project["project_type"],
        "subdistrict_id": project["subdistrict_id"],
        "data_quality_note": project["data_quality_note"],
        "required_doc_types": required,
        "has_document_data": bool(docs),
        "documents": documents,
        "missing_doc_types": missing,
        "provides_index": provides_index,
        "findings_count": sum(len(v) for v in findings_by_doc.values()),
    }
