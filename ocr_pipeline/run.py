# -*- coding: utf-8 -*-
"""CLI หลักของ ocr_pipeline — parse → normalize → validate → emit ต่อ 1 เอกสาร

    python -m ocr_pipeline.run --from-ocr pipeline/ocr_output/thachang67_standin \
        --subdistrict ท่าช้าง --municipality เทศบาลตำบลท่าช้าง --year 2567 \
        --source ท่าช้าง67.pdf --run-id t67_standin

    (โหมด production: --pdf <file> --extractor typhoon — OCR แล้ว cache ลง work/<run_id>/ocr/)

ผลลัพธ์ใน work/<run_id>/: manifest.json, out.csv, out_prior_year.csv,
review/queue.csv, run_report.json · exit code: pass=0, fail=1, needs_review=2
"""
import argparse
import csv
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


from ocr_pipeline.emit import write_out, write_review
from ocr_pipeline.normalize import Reference, normalize_rows
from ocr_pipeline.parse import parse_ocr_dir
from ocr_pipeline.validate import EXIT_CODE, check_equations, overall_status

DEFAULT_CONFIG = {
    "fuzzy": {"threshold": 92, "margin": 3},
    "gate": {"max_fuzzy_pct": 10, "max_unmatched": 0, "money_tol": 0.01},
    "paths": {"reference": "ocr_pipeline/reference", "work": "ocr_pipeline/work"},
}


def load_config(path: str = "ocr_pipeline/config.yaml") -> dict:
    """อ่าน config.yaml — ใช้ PyYAML ถ้ามี, ไม่มีก็ parser ขั้นต่ำ (รองรับ flow-style ตาม config นี้)"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not os.path.exists(path):
        return cfg
    text = open(path, encoding="utf-8").read()
    try:
        import yaml
        loaded = yaml.safe_load(text) or {}
    except ImportError:
        loaded = _mini_yaml(text)
    for k, v in loaded.items():
        if isinstance(v, dict):
            cfg.setdefault(k, {}).update(v)
        else:
            cfg[k] = v
    return cfg


def _mini_yaml(text: str) -> dict:
    """parser ขั้นต่ำสำหรับ 'key: {a: 1, b: 2}' ต่อบรรทัด (โครงของ config.yaml นี้)"""
    def scalar(s):
        s = s.strip()
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return s
    out = {}
    for line in text.splitlines():
        line = line.split("#")[0].rstrip()
        m = re.match(r"^(\w+):\s*\{(.*)\}\s*$", line)
        if m:
            out[m.group(1)] = {k.strip(): scalar(v) for k, v in
                               (kv.split(":", 1) for kv in m.group(2).split(","))}
    return out


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- cross-document checks

def _load_out_values(out_path: str, ref: Reference) -> dict:
    """out.csv → {(statement, code): value} (resolve ชื่อ canonical ด้วย ladder เดิม)"""
    vals = {}
    for r in csv.DictReader(open(out_path, encoding="utf-8-sig")):
        code = ref.resolve_canonical(r["รายการบัญชี"])
        if code:
            vals[(r["ประเภทงบ"], code)] = float(r["มูลค่า"])
    return vals


def _other_runs(work_dir: str, run_id: str):
    for mf in glob.glob(os.path.join(work_dir, "*", "manifest.json")):
        try:
            m = json.load(open(mf, encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if m.get("run_id") == run_id:
            continue
        out_path = os.path.join(os.path.dirname(mf), "out.csv")
        if os.path.exists(out_path):
            yield m, out_path


def cross_run_check(matched, meta, work_dir, run_id, ref, tol):
    """เทียบกับ run อื่นของ (ตำบล, ปี) เดียวกันใน work/ — สองการสกัดอิสระของเอกสารเดียวกัน
    ขัดกัน = OCR อย่างน้อยหนึ่งทางเพี้ยน → กักแถวนั้นไป review (precision-first, ห้าม auto-fix)"""
    baseline = {}
    for m, out_path in _other_runs(work_dir, run_id):
        mm = m.get("meta", {})
        if mm.get("subdistrict") == meta["subdistrict"] and mm.get("year") == meta["year"]:
            baseline.update(_load_out_values(out_path, ref))
    if not baseline:
        return matched, [], {"checked": 0, "mismatch": 0}
    keep, quarantined, checked, mismatch = [], [], 0, 0
    for r in matched:
        # คีย์แบบเดียวกับฝั่ง baseline (resolve จากชื่อ canonical) — กันรหัสคนละระดับของชื่อเดียวกัน
        key = (r["statement_type"], ref.resolve_canonical(r["canonical"]))
        if key in baseline:
            checked += 1
            if abs(float(r["value"]) - baseline[key]) > tol:
                mismatch += 1
                quarantined.append({**r, "reason": "cross_run_mismatch",
                                    "baseline_value": baseline[key]})
                continue
        keep.append(r)
    return keep, quarantined, {"checked": checked, "mismatch": mismatch}


def cross_year_check(matched, meta, work_dir, run_id, ref, tol):
    """check ข้อ 6: ค่าคอลัมน์ปีก่อนในเอกสาร vs out.csv ของปี year−1 (ถ้ามีใน work/)"""
    prev = {}
    for m, out_path in _other_runs(work_dir, run_id):
        mm = m.get("meta", {})
        if mm.get("subdistrict") == meta["subdistrict"] and int(mm.get("year", 0)) == int(meta["year"]) - 1:
            prev.update(_load_out_values(out_path, ref))
    checked = mismatch = 0
    if prev:
        for r in matched:
            if r["prior_value"] is None:
                continue
            key = (r["statement_type"], ref.resolve_canonical(r["canonical"]))
            if key in prev:
                checked += 1
                if abs(float(r["prior_value"]) - prev[key]) > tol:
                    mismatch += 1
    return {"checked": checked, "mismatch": mismatch}


# ---------------------------------------------------------------- main

def run_pipeline(args, cfg) -> int:
    ref_dir = cfg["paths"]["reference"]
    work_dir = cfg["paths"]["work"]
    run_dir = os.path.join(work_dir, args.run_id)
    os.makedirs(run_dir, exist_ok=True)
    ref = Reference(ref_dir)
    meta = {"subdistrict": args.subdistrict, "municipality": args.municipality,
            "year": args.year, "source": args.source}

    manifest = {
        "run_id": args.run_id, "pdf_sha256": None, "ocr_source": None, "pages": 0,
        "extractor": {"name": "from-ocr", "version": None},
        "reference": {"coa_sha256": sha256_file(os.path.join(ref_dir, "chart_of_accounts.csv")),
                      "aliases_sha256": sha256_file(os.path.join(ref_dir, "account_aliases.csv"))},
        "meta": meta,
        "stages": {"extract": "pending", "parse": "pending", "normalize": "pending",
                   "validate": "pending", "emit": "pending"},
    }

    # ---- Stage 1: extract (--from-ocr = ข้าม OCR — ทางเดียวที่ใช้ทดสอบ, D7)
    if args.from_ocr:
        ocr_dir = args.from_ocr
        manifest["ocr_source"] = ocr_dir
        manifest["stages"]["extract"] = "skipped"
    else:
        from ocr_pipeline.extractors import get_extractor
        ex = get_extractor(args.extractor)
        manifest["pdf_sha256"] = sha256_file(args.pdf)
        manifest["extractor"] = {"name": ex.name, "version": ex.version}
        ocr_dir = os.path.join(run_dir, "ocr")
        os.makedirs(ocr_dir, exist_ok=True)
        for pg in ex.extract(args.pdf):
            with open(os.path.join(ocr_dir, f"page_{pg.page:02d}.md"), "w", encoding="utf-8") as f:
                f.write(pg.markdown)
        manifest["ocr_source"] = ocr_dir
        manifest["stages"]["extract"] = "done"

    # ---- Stage 2: parse
    raw_rows, n_pages = parse_ocr_dir(ocr_dir)
    manifest["pages"] = n_pages
    manifest["stages"]["parse"] = "done"

    # ---- Stage 3: normalize (matching ladder)
    fz = cfg["fuzzy"]
    matched, review = normalize_rows(raw_rows, ref, fz["threshold"], fz["margin"])
    ladder = Counter(r["method"] for r in matched)
    ladder["unmatched"] = sum(1 for r in review if r["reason"] == "unmatched")
    manifest["stages"]["normalize"] = "done"

    # ---- Stage 4: validate (gate) — cross-run/cross-year + สมการบัญชี
    tol = cfg["gate"]["money_tol"]
    matched, quarantined, cross_run = cross_run_check(matched, meta, work_dir, args.run_id, ref, tol)
    for q in quarantined:
        review.append({
            "raw_name": q["raw_name"], "page": q["page"], "note": q["note"],
            "values": [q["value"]] + ([q["prior_value"]] if q["prior_value"] is not None else []),
            "layout_hint": q.get("layout_hint", ""), "candidates": [],
            "reason": f"cross_run_mismatch (ค่าใน run อื่นของตำบล/ปีเดียวกัน = {q['baseline_value']})",
        })
    cross_year = cross_year_check(matched, meta, work_dir, args.run_id, ref, tol)
    quarantined_keys = {(q["statement_type"], q["category"]) for q in quarantined
                        if q["detail_level"] == "line_item"}
    checks = check_equations(matched, quarantined_keys, tol)
    status = overall_status(checks, ladder, cfg["gate"],
                            quarantined=len(quarantined),
                            cross_year_mismatch=cross_year["mismatch"])
    manifest["stages"]["validate"] = status if status != "needs_review" else "needs_review"

    # ---- Stage 5: emit (unmatched/quarantined ไม่เข้า output — D5)
    out_path = os.path.join(run_dir, "out.csv")
    rows_emitted = write_out(matched, meta, out_path)
    rows_to_review = write_review(review, os.path.join(run_dir, "review"))
    manifest["stages"]["emit"] = "done"

    report = {
        "run_id": args.run_id, "status": status,
        "ladder": {k: ladder.get(k, 0) for k in ("exact", "alias", "fuzzy", "unmatched")},
        "rows_emitted": rows_emitted, "rows_to_review": rows_to_review,
        "quarantined": len(quarantined),
        "validation": checks,
        "cross_year": cross_year, "cross_run": cross_run,
    }
    with open(os.path.join(run_dir, "run_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(os.path.join(run_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[{status}] emit {rows_emitted} แถว → {out_path} | review {rows_to_review} แถว | ladder {dict(report['ladder'])}")
    for c in checks:
        if c["result"] != "pass":
            print(f"  [{c['result']}] {c['check']} — {c.get('detail', '')}"
                  + (f" got={c.get('got')} expected={c.get('expected')}" if "got" in c else ""))
    return EXIT_CODE[status]


def main() -> None:
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-ocr", help="โฟลเดอร์ page_NN.md ที่ OCR ไว้แล้ว")
    src.add_argument("--pdf", help="PDF ต้นฉบับ (โหมด production — ต้องมี extractor)")
    ap.add_argument("--extractor", default="typhoon")
    ap.add_argument("--subdistrict", required=True)
    ap.add_argument("--municipality", required=True)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--config", default="ocr_pipeline/config.yaml")
    args = ap.parse_args()

    cfg = load_config(args.config)
    sys.exit(run_pipeline(args, cfg))


if __name__ == "__main__":
    main()
