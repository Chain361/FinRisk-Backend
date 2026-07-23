# -*- coding: utf-8 -*-
"""Stage 5 — Emit: matched rows → out.csv (คอลัมน์ตรง §9.4 เป๊ะ) + sidecar ปีก่อน + review queue"""
import csv
import os

OUT_COLS = ["ตำบล", "เทศบาล", "ปีงบประมาณ", "ประเภทงบ", "หมวดหมู่", "รายการบัญชี",
            "หมายเหตุ", "มูลค่า", "หน่วย", "ระดับรายละเอียด", "หมายเหตุคุณภาพข้อมูล", "ไฟล์ต้นฉบับ"]


def quality_note(row: dict) -> str:
    """ว่างเมื่อ exact/alias และชื่อดิบ = canonical; ไม่งั้น match=<method>(<score>); ชื่อในเอกสาร: <raw> (§5.5)"""
    if row["method"] in ("exact", "alias") and row["raw_name"] == row["canonical"]:
        return ""
    return f"match={row['method']}({row['score']}); ชื่อในเอกสาร: {row['raw_name']}"


def write_out(matched, meta: dict, out_path: str) -> int:
    """เขียน out.csv — หมายเหตุว่างเสมอ (D2), หน่วย=บาท, ไฟล์ต้นฉบับ=<source>#p<page>"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLS)
        w.writeheader()
        for r in matched:
            w.writerow({
                "ตำบล": meta["subdistrict"], "เทศบาล": meta["municipality"],
                "ปีงบประมาณ": meta["year"], "ประเภทงบ": r["statement_type"],
                "หมวดหมู่": r["category"], "รายการบัญชี": r["canonical"],
                "หมายเหตุ": "",                               # D2 — เขียนว่างเสมอ
                "มูลค่า": r["value"], "หน่วย": "บาท",
                "ระดับรายละเอียด": r["detail_level"],
                "หมายเหตุคุณภาพข้อมูล": quality_note(r),
                "ไฟล์ต้นฉบับ": f"{meta['source']}#p{r['page']}",
            })
    # sidecar มูลค่าปีก่อน — รูปแบบ v1 (ไว้ cross-year check ข้ามเอกสาร)
    side = out_path.replace(".csv", "_prior_year.csv")
    with open(side, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ประเภทงบ", "รายการบัญชี", "ปีงบประมาณ", "มูลค่า"])
        for r in matched:
            if r["prior_value"] is not None:
                w.writerow([r["statement_type"], r["canonical"], int(meta["year"]) - 1, r["prior_value"]])
    return len(matched)


def write_review(review, review_dir: str) -> int:
    """review/queue.csv — ชื่อดิบ, หน้า, ค่า, เหตุผล, top-3 candidates+score (D5: ห้ามเข้า output)"""
    os.makedirs(review_dir, exist_ok=True)
    path = os.path.join(review_dir, "queue.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["raw_name", "page", "note", "values", "reason", "layout_hint", "top3_candidates"])
        for r in review:
            cands = " | ".join(f"{c['name']}={c['score']}" for c in r.get("candidates", []))
            w.writerow([r["raw_name"], r["page"], r.get("note", ""),
                        ";".join(str(v) for v in r["values"]), r["reason"],
                        r.get("layout_hint", ""), cands])
    return len(review)
