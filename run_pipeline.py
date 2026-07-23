# -*- coding: utf-8 -*-
"""run_pipeline.py — Master runner แบบคำสั่งเดียวสำหรับ demo operator

    python run_pipeline.py                       # รันครบ: batch → validate → promote → seed
    python run_pipeline.py --dry-run             # OCR + validate เท่านั้น — ไม่แตะ DB/CSV
    python run_pipeline.py --enable-rag          # + รัน Law RAG plugin (stub)
    python run_pipeline.py --input-dir <folder>  # โฟลเดอร์ PDF + batch.csv (default: raw_financial_statements)

3-Tier OCR fallback (ไม่ต้องติดตั้งอะไรเพิ่มถ้ามี OCR cache แล้ว):
  Tier 1: pdftoppm บน PATH + TYPHOON_OCR_API_KEY ใน .env → OCR สด
  Tier 2: ใช้ OCR cache ใน ocr_pipeline/work/<run_id>/ocr/ → offline 100%
  Tier 3: Docker + --env-file .env (image: fraud-risk-pipeline-v2)

ความปลอดภัยข้อมูล: backup fraud_risk.db + financial_report_ALL_master.csv ก่อนเขียน
และ auto-rollback ทั้งคู่เมื่อขั้นใดล้มเหลว (กัน DB/CSV แตกแถวกัน)
สรุปผลทุกครั้งเขียนลง pipeline_run.log
"""
import argparse
import datetime
import importlib.util
import os
import shutil
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
os.chdir(REPO_ROOT)  # path ใน config/pipeline เป็น relative จาก repo root

DB_PATH = os.path.join(REPO_ROOT, "fraud_risk.db")
MASTER_CSV = os.path.join(REPO_ROOT, "standardized_data", "financial_report_ALL_master.csv")
LOG_PATH = os.path.join(REPO_ROOT, "pipeline_run.log")
DEFAULT_INPUT_DIR = os.path.join(REPO_ROOT, "raw_financial_statements")
DOCKER_IMAGE = "fraud-risk-pipeline-v2"

_log_lines = []


def log(msg: str) -> None:
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} | {msg}"
    print(msg)
    _log_lines.append(line)


def flush_log() -> None:
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write("\n".join(_log_lines) + "\n" + "-" * 60 + "\n")


# ---------------------------------------------------------------- pre-flight

def load_dotenv(path: str = ".env") -> None:
    """โหลด .env แบบเบา ๆ (KEY=VALUE ต่อบรรทัด) — ไม่ทับ env ที่ตั้งไว้แล้ว"""
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def docker_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def preflight(input_dir: str):
    """เลือก tier ตาม flowchart ใน implementation plan → ("tier1"|"tier2"|"docker"|"error", detail)"""
    from ocr_pipeline.batch import _cached_ocr_dir, read_batch_csv
    from ocr_pipeline.run import load_config

    load_dotenv()
    has_poppler = shutil.which("pdftoppm") is not None
    has_key = bool(os.getenv("TYPHOON_OCR_API_KEY"))
    has_pkg = importlib.util.find_spec("typhoon_ocr") is not None

    if has_poppler and has_key and has_pkg:
        return "tier1", "พบ pdftoppm + TYPHOON_OCR_API_KEY + typhoon-ocr — OCR สดจาก PDF"

    work_dir = load_config()["paths"]["work"]
    jobs = read_batch_csv(input_dir)
    cached = [j["run_id"] for j in jobs
              if j["ocr_dir"] or _cached_ocr_dir(work_dir, j["run_id"])]
    if cached:
        note = "" if len(cached) == len(jobs) else \
            f" (มี cache {len(cached)}/{len(jobs)} ไฟล์ — ไฟล์ที่เหลือจะถูกนับเป็น fail แบบ isolate)"
        return "tier2", f"ใช้ OCR cache เดิมใน ocr_pipeline/work/ — offline 100%{note}"

    if docker_available():
        if os.path.exists(".env"):
            return "docker", "ไม่มี poppler/cache บนเครื่อง — สลับไปรันใน Docker (--env-file .env)"
        return "error", ("พบ Docker แต่ไม่มีไฟล์ .env — สร้างไฟล์ .env ที่ repo root แล้วใส่บรรทัด:\n"
                         "  TYPHOON_OCR_API_KEY=<คีย์ของคุณ>  (สมัครฟรีที่ opentyphoon.ai)")
    return "error", (
        "รันไม่ได้: ไม่มี poppler (pdftoppm), ไม่มี OCR cache และไม่มี Docker\n"
        "ทางแก้ (เลือกอย่างใดอย่างหนึ่ง):\n"
        "  1) Windows: ดาวน์โหลด poppler จาก https://github.com/oschwartz10612/poppler-windows/releases\n"
        "     แตก zip แล้วเพิ่มโฟลเดอร์ Library\\bin ลง PATH\n"
        "  2) ติดตั้ง Docker Desktop แล้วรันใหม่ (สคริปต์จะจัดการต่อให้เอง)\n"
        "  3) ขอโฟลเดอร์ OCR cache (ocr_pipeline/work/) จากทีม แล้ววางไว้ตาม path เดิม")


def run_in_docker(argv) -> int:
    """Tier 3 — รันตัวเองใน container (สร้างคำสั่งใน Python — ใช้ได้ทั้ง Windows/Mac/Linux)"""
    cmd = ["docker", "run", "--rm", "--env-file", ".env",
           "-v", f"{REPO_ROOT}:/app", "-w", "/app",
           DOCKER_IMAGE, "python", "run_pipeline.py"] + argv
    log(f"[docker] {' '.join(cmd)}")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        log(f"[docker] ล้มเหลว (exit {res.returncode}) — ถ้ายังไม่มี image ให้ build ก่อน:\n"
            f"  docker build -f ocr_pipeline/Dockerfile -t {DOCKER_IMAGE} .")
    return res.returncode


# ---------------------------------------------------------------- backup / rollback

def make_backups(skip: bool):
    if skip:
        log("[backup] ข้าม backup ตาม --skip-backup")
        return {}
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backups = {}
    for src in (DB_PATH, MASTER_CSV):
        if os.path.exists(src):
            dst = f"{src}.bak.{ts}"
            shutil.copy2(src, dst)
            backups[src] = dst
            log(f"[backup] {os.path.basename(src)} → {os.path.basename(dst)}")
    return backups


def rollback(backups: dict) -> None:
    for src, dst in backups.items():
        if os.path.exists(dst):
            shutil.copy2(dst, src)
            log(f"[rollback] คืนค่า {os.path.basename(src)} จาก {os.path.basename(dst)}")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Master pipeline runner: PDF → OCR → validate → promote → seed DB (คำสั่งเดียวจบ)")
    ap.add_argument("--input-dir", default=DEFAULT_INPUT_DIR,
                    help="โฟลเดอร์ที่มี PDF + batch.csv (default: raw_financial_statements)")
    ap.add_argument("--dry-run", action="store_true",
                    help="รัน OCR + validation เท่านั้น — ไม่เขียน DB/CSV")
    ap.add_argument("--enable-rag", action="store_true",
                    help="รัน Law RAG plugin (ตอนนี้เป็น stub)")
    ap.add_argument("--skip-backup", action="store_true", help="ไม่ต้องสร้าง backup ก่อนเขียน")
    ap.add_argument("--include-needs-review", action="store_true",
                    help="promote เอกสาร needs_review ด้วย (หลังคนตรวจ review/queue.csv แล้ว)")
    ap.add_argument("--include-fails", action="store_true",
                    help="promote เอกสาร fail ด้วย")
    args = ap.parse_args()
    t0 = time.time()
    log(f"=== run_pipeline start (input={args.input_dir}, dry_run={args.dry_run}) ===")

    # 0a. pre-flight: เลือก tier
    tier, detail = preflight(args.input_dir)
    log(f"[preflight] {tier}: {detail}")
    if tier == "error":
        flush_log()
        return 1
    if tier == "docker":
        rc = run_in_docker(sys.argv[1:])
        flush_log()
        return rc

    from ocr_pipeline.batch import process_batch
    from ocr_pipeline.promote import promote_batch
    from ocr_pipeline.validate import validate_batch

    # 0b. backup (ข้ามได้ตอน dry-run — ไม่มีการเขียน)
    backups = {} if args.dry_run else make_backups(args.skip_backup)

    try:
        # 1. batch OCR/parse/normalize/validate ต่อเอกสาร (error isolation ในตัว)
        summary = process_batch(args.input_dir, prefer_cached_ocr=(tier == "tier2"),
                                include_needs_review=args.include_needs_review,
                                include_fails=args.include_fails)

        # 1b. circuit breaker ระดับ batch — ก่อนแตะ DB
        gate = validate_batch(summary)
        log(f"[gate] pass_rate={gate['pass_rate']}% | promote={len(gate['promoted'])} | "
            f"held_back={[h['run_id'] + ':' + h['status'] for h in gate['held_back']]}")
        if not gate["ok"]:
            raise RuntimeError(f"circuit breaker: {gate['reason']}")

        if args.dry_run:
            promote_batch(dry_run=True)
            log(f"[dry-run] จบโดยไม่เขียน DB/CSV ({time.time() - t0:.1f}s)")
            flush_log()
            return 0

        # 2. promote merged CSV → standardized_data/
        promote_batch(seed=False)

        # 3. seed DB + risk engine (subprocess — seed_database.main() parse argv เอง)
        log("[seed] python seed_database.py --force")
        res = subprocess.run([sys.executable, "seed_database.py", "--force"], cwd=REPO_ROOT)
        if res.returncode != 0:
            raise RuntimeError(f"seed_database.py ล้มเหลว (exit {res.returncode})")

        # 4. plugins (isolate — plugin พังไม่ต้อง rollback DB ที่ seed สำเร็จแล้ว)
        from ocr_pipeline.plugins import get_plugins
        for p in get_plugins():
            if p.is_enabled(args):
                try:
                    import sqlite3
                    with sqlite3.connect(DB_PATH) as conn:
                        log(f"[plugin] {p.name()}: {p.run(conn)}")
                except Exception as e:
                    log(f"[plugin] {p.name()} ล้มเหลว (ไม่กระทบ DB): {e}")

        # 5. summary
        log(f"[done] promote {len(gate['promoted'])} เอกสาร ({summary['merged_rows']} แถว), "
            f"pass_rate {gate['pass_rate']}%, ใช้เวลา {time.time() - t0:.1f}s")
        log("ตรวจผลได้ที่: uvicorn src.main:app --reload → http://127.0.0.1:8000/docs")
        flush_log()
        return 0

    except (Exception, SystemExit) as e:  # promote() ใช้ sys.exit — ต้อง catch เพื่อ rollback
        code = e.code if isinstance(e, SystemExit) else None
        if isinstance(e, SystemExit) and code in (0, None):
            flush_log()
            return 0
        log(f"[error] {e}")
        rollback(backups)
        log("[error] pipeline ล้มเหลว — คืนค่า DB/CSV เรียบร้อย ดูรายละเอียดใน pipeline_run.log")
        flush_log()
        return 1


if __name__ == "__main__":
    sys.exit(main())
