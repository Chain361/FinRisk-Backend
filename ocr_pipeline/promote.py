# -*- coding: utf-8 -*-
"""
promote.py — Utility to promote ocr_pipeline batch extraction output into standardized_data
==========================================================================================
อ่าน batch extraction output (default: ocr_pipeline/work/batch/financial_report_batch_master.csv)
แล้วอัปเดตลง standardized_data/financial_report_ALL_master.csv พร้อมสำรองข้อมูลเดิม

วิธีรัน:
    python -m ocr_pipeline.promote                                # promote Default batch output
    python -m ocr_pipeline.promote --batch-file path/to/batch.csv  # promote ระบุไฟล์
    python -m ocr_pipeline.promote --seed                         # promote + รัน seed_database.py --force
    python -m ocr_pipeline.promote --dry-run                      # ตรวจสอบการทำงานโดยไม่เขียนไฟล์
"""

import argparse
import csv
import os
import shutil
import subprocess
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_BATCH_CSV = os.path.join(REPO_ROOT, "ocr_pipeline", "work", "batch", "financial_report_batch_master.csv")
DEFAULT_TARGET_CSV = os.path.join(REPO_ROOT, "standardized_data", "financial_report_ALL_master.csv")

OUT_COLS = [
    "ตำบล", "เทศบาล", "ปีงบประมาณ", "ประเภทงบ", "หมวดหมู่", "รายการบัญชี",
    "หมายเหตุ", "มูลค่า", "หน่วย", "ระดับรายละเอียด", "หมายเหตุคุณภาพข้อมูล", "ไฟล์ต้นฉบับ"
]


def load_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        sys.exit(f"ไม่พบไฟล์ {path}")
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def save_csv(path: str, rows: list[dict]):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLS)
        writer.writeheader()
        writer.writerows(rows)


def promote(batch_file: str, target_file: str, seed: bool = False, dry_run: bool = False, mode: str = "upsert"):
    print(f"[Promote] อ่าน batch CSV: {batch_file}")
    batch_rows = load_csv(batch_file)
    if not batch_rows:
        sys.exit("ไฟล์ batch ไม่มีข้อมูล — ยกเลิกการ promote")

    # ตรวจสอบคอลัมน์
    first_keys = list(batch_rows[0].keys())
    for col in OUT_COLS:
        if col not in first_keys:
            sys.exit(f"คอลัมน์ {col} หายไปจาก {batch_file}")

    # ดึงรายคู่ (ตำบล, ปีงบประมาณ) ที่มีใน batch output
    batch_pairs = set((r["ตำบล"].strip(), r["ปีงบประมาณ"].strip()) for r in batch_rows)
    print(f"[Promote] พบข้อมูลใหม่สำหรับ (ตำบล, ปีงบประมาณ): {sorted(list(batch_pairs))}")

    existing_rows = load_csv(target_file) if os.path.exists(target_file) else []
    
    if mode == "upsert":
        # เก็บแถวที่ไม่ใช่ (ตำบล, ปีงบประมาณ) ที่ตรงกับ batch
        retained_rows = [r for r in existing_rows if (r["ตำบล"].strip(), r["ปีงบประมาณ"].strip()) not in batch_pairs]
        merged_rows = retained_rows + batch_rows
    else:  # replace all
        merged_rows = batch_rows

    print(f"[Promote] แถวเดิม: {len(existing_rows)} แถว | แถวใหม่หลังรวม: {len(merged_rows)} แถว")

    if dry_run:
        print("[Promote] --dry-run: ไม่ได้ทำการเขียนไฟล์จริง")
        return

    # สร้าง backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{target_file}.bak.{timestamp}"
    if os.path.exists(target_file):
        shutil.copy2(target_file, backup_path)
        print(f"[Promote] สำรองไฟล์เดิมไปที่: {backup_path}")

    # บันทึกไฟล์ target
    save_csv(target_file, merged_rows)
    print(f"[Promote] บันทึกข้อมูลลง {target_file} เรียบร้อยแล้ว")

    # รัน seed_database.py --force ถ้าสั่ง --seed
    if seed:
        print("[Promote] รัน seed_database.py --force ...")
        cmd = [sys.executable, os.path.join(REPO_ROOT, "seed_database.py"), "--force"]
        res = subprocess.run(cmd, cwd=REPO_ROOT)
        if res.returncode != 0:
            sys.exit(f"seed_database.py ล้มเหลว (exit code {res.returncode})")
        print("[Promote] seed_database.py สำเร็จ!")


def promote_batch(batch_file: str = None, target_file: str = None,
                  seed: bool = False, dry_run: bool = False, mode: str = "upsert"):
    """API สำหรับเรียกจากโค้ด (run_pipeline.py) — ค่า default เดียวกับ CLI
    หมายเหตุ: ข้อผิดพลาดภายใน promote() ยก SystemExit — ผู้เรียกต้อง catch เพื่อ rollback"""
    promote(batch_file or DEFAULT_BATCH_CSV, target_file or DEFAULT_TARGET_CSV,
            seed=seed, dry_run=dry_run, mode=mode)


def main():
    parser = argparse.ArgumentParser(description="Promote ocr_pipeline batch results to standardized_data CSV")
    parser.add_argument("--batch-file", default=DEFAULT_BATCH_CSV, help="ไฟล์ CSV ผลลัพธ์จาก ocr_pipeline batch")
    parser.add_argument("--target-file", default=DEFAULT_TARGET_CSV, help="ไฟล์ปลายทาง standardized_data CSV")
    parser.add_argument("--seed", action="store_true", help="รัน python seed_database.py --force หลัง promote")
    parser.add_argument("--dry-run", action="store_true", help="แสดงผลการทำงานโดยไม่เขียนไฟล์")
    parser.add_argument("--mode", choices=["upsert", "replace"], default="upsert", help="upsert: แทนที่ตาม (ตำบล, ปี), replace: แทนที่ทั้งหมด")
    args = parser.parse_args()

    promote(args.batch_file, args.target_file, seed=args.seed, dry_run=args.dry_run, mode=args.mode)


if __name__ == "__main__":
    main()
