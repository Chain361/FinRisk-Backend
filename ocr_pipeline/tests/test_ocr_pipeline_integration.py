# -*- coding: utf-8 -*-
"""Integration tests (S6): DoD ของ S2–S5 ต้อง reproduce ได้ — ไม่ใช้ network

รัน CLI จริงผ่าน subprocess (work dir ชั่วคราวต่อ test session — ไม่แตะ ocr_pipeline/work)
"""
import csv
import json
import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
GOLD = "standardized_data/financial_report_ALL_master.csv"


def _run(args, **kw):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    kw_env = dict(env, **kw.pop("env", {}))
    return subprocess.run([sys.executable, "-m", *args], cwd=REPO_ROOT,
                          capture_output=True, text=True, encoding="utf-8", errors="replace", env=kw_env, **kw)



@pytest.fixture(scope="module")
def workspace(tmp_path_factory):
    """config ชี้ work → โฟลเดอร์ชั่วคราว แล้วรัน standin ก่อน ตามด้วยชุดเต็ม (ลำดับตาม S3)"""
    work = tmp_path_factory.mktemp("work")
    cfg = tmp_path_factory.mktemp("cfg") / "config.yaml"
    cfg.write_text(
        "fuzzy: {threshold: 92, margin: 3}\n"
        "gate:  {max_fuzzy_pct: 10, max_unmatched: 0, money_tol: 0.01}\n"
        f"paths: {{reference: ocr_pipeline/reference, work: {work}}}\n",
        encoding="utf-8")
    common = ["--subdistrict", "ท่าช้าง", "--municipality", "เทศบาลตำบลท่าช้าง",
              "--year", "2567", "--source", "ท่าช้าง67.pdf", "--config", str(cfg)]
    r1 = _run(["ocr_pipeline.run", "--from-ocr", "pipeline/ocr_output/thachang67_standin",
               *common, "--run-id", "t67_standin"])
    r2 = _run(["ocr_pipeline.run", "--from-ocr", "pipeline/ocr_output/thachang67",
               *common, "--run-id", "t67_full"])
    return {"work": work, "cfg": cfg, "standin": r1, "full": r2}


# ---------------------------------------------------------------- S2 coverage

def test_coverage_gold_72_of_72():
    from ocr_pipeline.eval.coverage import run
    os.chdir(REPO_ROOT)
    res = run(GOLD, "ocr_pipeline/reference")
    assert res["pairs"] == 72 and res["rows"] == 264
    assert res["ladder"].get("exact", 0) + res["ladder"].get("alias", 0) == 72
    assert res["ladder"].get("fuzzy", 0) == 0 and res["ladder"].get("unmatched", 0) == 0
    assert res["problems"] == []
    assert res["detail"] == {"line_item": 184, "subtotal": 38, "total": 42}


# ---------------------------------------------------------------- S3 standin: 100% ทุกตัว

def test_standin_run_passes(workspace):
    assert workspace["standin"].returncode == 0, workspace["standin"].stdout
    report = json.load(open(workspace["work"] / "t67_standin" / "run_report.json", encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["rows_emitted"] == 43 and report["rows_to_review"] == 0
    assert report["ladder"]["fuzzy"] == 0 and report["ladder"]["unmatched"] == 0
    assert all(c["result"] == "pass" for c in report["validation"])


def test_standin_evaluate_100(workspace):
    from ocr_pipeline.eval.evaluate import run
    os.chdir(REPO_ROOT)
    res = run(str(workspace["work"] / "t67_standin" / "out.csv"), GOLD,
              2567, "ท่าช้าง", "ocr_pipeline/reference")
    assert res["recall"] == 1.0 and res["precision"] == 1.0
    assert all(v == 1.0 for v in res["accuracy"].values()), res["diffs"]


# ---------------------------------------------------------------- S3 ชุดเต็ม 33 หน้า: ชนะ v1 ด้วย gate

def test_full_run_beats_v1_baseline(workspace):
    """baseline v1: 51 แถว, recall 97.7%, precision 82.4%, มูลค่า 97.6%
    v2: precision = 100%, recall ≥ 97.7%, มูลค่า = 100% บนแถวที่ emit (spec S3)"""
    from ocr_pipeline.eval.evaluate import run
    os.chdir(REPO_ROOT)
    res = run(str(workspace["work"] / "t67_full" / "out.csv"), GOLD,
              2567, "ท่าช้าง", "ocr_pipeline/reference")
    assert res["precision"] == 1.0, res["extra"]              # แถวเกินห้ามเข้า out.csv
    assert res["recall"] >= 42 / 43                            # ≥ 97.7%
    assert res["accuracy"]["มูลค่า"] == 1.0, res["diffs"]      # 100% บนแถวที่ emit
    assert res["accuracy"]["หมวดหมู่"] == 1.0
    assert res["accuracy"]["ระดับรายละเอียด"] == 1.0

    report = json.load(open(workspace["work"] / "t67_full" / "run_report.json", encoding="utf-8"))
    # แถวเกินของ v1 (งบแสดงการเปลี่ยนแปลงฯ หน้า 11) + ค่า OCR เพี้ยนที่ gate จับได้ → review
    assert report["rows_to_review"] >= 9
    assert report["quarantined"] == 1                          # รายได้ภาษีจัดสรร (555 vs 565)
    assert report["cross_run"]["mismatch"] == 1
    review = list(csv.DictReader(open(workspace["work"] / "t67_full" / "review" / "queue.csv",
                                      encoding="utf-8-sig")))
    assert any(r["reason"].startswith("cross_run_mismatch") for r in review)


# ---------------------------------------------------------------- S4 validate gate

def test_validate_pass_on_standin(workspace):
    r = _run(["ocr_pipeline.validate", str(workspace["work"] / "t67_standin" / "out.csv"),
              "--config", str(workspace["cfg"])])
    assert r.returncode == 0, r.stdout


def test_validate_fail_on_tampered_digit(workspace, tmp_path):
    rows = list(csv.DictReader(open(workspace["work"] / "t67_standin" / "out.csv",
                                    encoding="utf-8-sig")))
    n = 0
    for r in rows:
        if r["รายการบัญชี"] == "เงินสดและรายการเทียบเท่าเงินสด":
            r["มูลค่า"] = "266235855.88"                       # แก้เลข 1 หลัก
            n += 1
    assert n == 1
    p = tmp_path / "tampered.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    r = _run(["ocr_pipeline.validate", str(p), "--config", str(workspace["cfg"])])
    assert r.returncode == 1, r.stdout                         # สมการครบแต่ไม่ลงตัว → fail


def test_validate_needs_review_on_summary_doc(workspace, tmp_path):
    rows = list(csv.DictReader(open(workspace["work"] / "t67_standin" / "out.csv",
                                    encoding="utf-8-sig")))
    keep = [r for r in rows if not (r["หมวดหมู่"] == "หนี้สินหมุนเวียน"
                                    and r["ระดับรายละเอียด"] == "line_item")]
    assert len(keep) < len(rows)
    p = tmp_path / "summary.csv"
    with open(p, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(keep)
    r = _run(["ocr_pipeline.validate", str(p), "--config", str(workspace["cfg"])])
    assert r.returncode == 2, r.stdout                         # ขาดแถว (เอกสารสรุป) → needs_review


# ---------------------------------------------------------------- batch runner

def test_batch_merges_only_gated_runs(tmp_path):
    """โฟลเดอร์รวมหลายเอกสาร + batch.csv → รวมเฉพาะ run ที่ pass เป็น CSV เดียว
    (สอง run ของ (ตำบล, ปี) เดียวกัน: ชุดเต็มโดน cross-run quarantine → needs_review → ไม่รวม)"""
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "batch.csv").write_text(
        "pdf,ตำบล,เทศบาล,ปีงบประมาณ,run_id,ocr_dir\n"
        ",ท่าช้าง,เทศบาลตำบลท่าช้าง,2567,b_standin,pipeline/ocr_output/thachang67_standin\n"
        ",ท่าช้าง,เทศบาลตำบลท่าช้าง,2567,b_full,pipeline/ocr_output/thachang67\n",
        encoding="utf-8-sig")
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "fuzzy: {threshold: 92, margin: 3}\n"
        "gate:  {max_fuzzy_pct: 10, max_unmatched: 0, money_tol: 0.01}\n"
        f"paths: {{reference: ocr_pipeline/reference, work: {tmp_path / 'work'}}}\n",
        encoding="utf-8")
    r = _run(["ocr_pipeline.batch", str(folder), "--config", str(cfg)])
    assert r.returncode == 2, r.stdout + r.stderr        # มี needs_review ที่ไม่ถูกรวม

    merged = list(csv.DictReader(open(tmp_path / "work" / "batch"
                                      / "financial_report_batch_master.csv", encoding="utf-8-sig")))
    assert len(merged) == 43                              # เฉพาะ run ที่ pass
    gold_cols = csv.DictReader(open(os.path.join(REPO_ROOT, GOLD), encoding="utf-8-sig")).fieldnames
    assert list(merged[0].keys()) == gold_cols            # คอลัมน์ตรง master เป๊ะ
    report = json.load(open(tmp_path / "work" / "batch" / "batch_report.json", encoding="utf-8"))
    assert [x["status"] for x in report["runs"]] == ["pass", "needs_review"]


# ---------------------------------------------------------------- S5 downstream (L2)

def test_downstream_five_values_on_standin(workspace):
    from ocr_pipeline.eval.eval_downstream import run
    os.chdir(REPO_ROOT)
    results = run(str(workspace["work"] / "t67_standin" / "out.csv"), GOLD,
                  2567, "ท่าช้าง", "ocr_pipeline/reference")
    assert len(results) == 5
    assert all(r["ok"] for r in results), results
