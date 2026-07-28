# -*- coding: utf-8 -*-
"""
calibrate_rag.py — หาค่า `RAG_MIN_SCORE` ที่แยก "hit ที่ถูก" ออกจาก "hit ที่มั่ว" ได้จริง
(งาน #4.5 ของ docs/rag_pinecone_plan.md §10)

    python -m scripts.calibrate_rag                      # ใช้ชุดคำถามตั้งต้นของ MOCK-CON-001
    python -m scripts.calibrate_rag --questions my.json  # ชุดคำถามของตัวเอง
    python -m scripts.calibrate_rag --show-text          # พิมพ์เนื้อ chunk ให้ตรวจด้วยตา

ทำไมต้อง calibrate: `multilingual-e5-large` เทรนแบบ contrastive → cosine ถูกบีบอยู่ในช่วงแคบและสูง
คู่ข้อความที่**ไม่เกี่ยวกันเลย**ก็มักได้ 0.70–0.78 ค่า default 0.82 เป็นแค่การเดาที่สมเหตุสมผล
ถ้าไม่ calibrate จะมี 2 โหมดพังที่เงียบทั้งคู่: ต่ำไป = chunk มั่วไหลไปให้ Gemini ตอบ,
สูงไป = ผู้ใช้เห็น "ไม่พบข้อมูลในเอกสาร" ทั้งที่มีข้อมูลอยู่

วิธีตัดสินว่า hit ไหน "ถูก": ข้อความของ chunk มีคีย์เวิร์ดที่รู้คำตอบอยู่แล้วอย่างน้อย 1 ตัว
(คำถาม off-topic ในชุดตั้งต้นไม่มีคีย์เวิร์ด → ทุก hit ของมันคือ "มั่ว" ตามนิยาม ใช้วัดพื้นคะแนนของโมเดล)
⚠️ การตัดสินด้วยคีย์เวิร์ดเป็นตัวช่วย ไม่ใช่คำตัดสินสุดท้าย — `--show-text` แล้วดูด้วยตาก่อนเชื่อ

สคริปต์นี้ **ไม่แก้ไฟล์ใดๆ** อ่านอย่างเดียว (Pinecone read + Postgres read) — จะตั้งค่าจริงหรือไม่
ให้ไปแก้ `RAG_MIN_SCORE` ใน `.env` เอง
"""
import argparse
import json
import os
import statistics
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO_ROOT)

# .env ถูกโหลดโดย src.config ตอน import (shell env ชนะ .env เสมอ)
from src.config import PINECONE_API_KEY, RAG_MIN_SCORE  # noqa: E402
from src.database import db_session  # noqa: E402
from src.services import retrieval  # noqa: E402

# ชุดตั้งต้น: 5 คำถามที่รู้คำตอบ (จาก mock_documents/project_documents.csv) + 3 คำถาม off-topic
DEFAULT_QUESTIONS = [
    {"q": "ปริมาณพื้นคอนกรีตเสริมเหล็กกี่ตารางเมตร", "expect": ["1,850", "1850", "คอนกรีตเสริมเหล็ก"]},
    {"q": "Factor F ที่ใช้คำนวณราคากลางเท่าไร", "expect": ["1.3061", "Factor F", "แฟคเตอร์"]},
    {"q": "ค่างานต้นทุนของโครงการเท่าไร", "expect": ["3,980,000", "3980000", "ค่างานต้นทุน"]},
    {"q": "ราคากลางที่ประกาศจัดซื้อจัดจ้างเท่าไร", "expect": ["5,200,000", "5200000", "ราคากลาง"]},
    {"q": "งานฐานรากมีรายการอะไรบ้าง", "expect": ["ฐานราก"]},
    {"q": "วิธีทำต้มยำกุ้งน้ำข้น", "expect": []},
    {"q": "ตารางเดินรถไฟฟ้าสายสีเขียววันหยุด", "expect": []},
    {"q": "อัตราแลกเปลี่ยนเงินเยนวันนี้", "expect": []},
]


def judge(text: str, expect: list[str]) -> bool:
    return bool(expect) and any(k.lower() in (text or "").lower() for k in expect)


def main() -> int:
    ap = argparse.ArgumentParser(description="calibrate RAG_MIN_SCORE กับ chunk จริงบน Pinecone")
    ap.add_argument("--project", default="MOCK-CON-001")
    ap.add_argument("--username", default="auditor3", help="ผู้ใช้ที่ใช้ยิงคำถาม (ต้องเห็นโครงการนี้ได้)")
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--questions", help="ไฟล์ JSON: [{\"q\": ..., \"expect\": [...]}]")
    ap.add_argument("--show-text", action="store_true", help="พิมพ์เนื้อ chunk เต็มของทุก hit")
    args = ap.parse_args()

    if not PINECONE_API_KEY:
        raise SystemExit("ต้องมี PINECONE_API_KEY (ใน .env หรือ env var) ก่อน")

    questions = DEFAULT_QUESTIONS
    if args.questions:
        with open(args.questions, encoding="utf-8") as f:
            questions = json.load(f)

    good: list[float] = []
    bad: list[float] = []

    with db_session() as conn:
        row = conn.execute(
            "SELECT user_id, username, display_name, role, subdistrict_id FROM users WHERE username = ?",
            (args.username,),
        ).fetchone()
        if row is None:
            raise SystemExit(f"ไม่พบผู้ใช้ {args.username}")
        user = dict(row)

        for item in questions:
            # min_score=0 → เห็นคะแนนดิบทุก hit (นี่คือเหตุผลที่ service รับ min_score เข้ามาได้)
            out = retrieval.search_document_text(
                conn, user, item["q"], project_id=args.project, top_k=args.top_k, min_score=0
            )
            kind = "รู้คำตอบ" if item["expect"] else "off-topic"
            print(f"\n▸ [{kind}] {item['q']}")
            if not out["chunks"]:
                print("   (ไม่มี hit เลย)")
                continue
            for c in out["chunks"]:
                ok = judge(c["text"], item["expect"])
                (good if ok else bad).append(c["score"])
                head = c["text"].replace("\n", " ⏎ ")[:70]
                print(f"   {'✅' if ok else '❌'} {c['score']:.4f}  {c['doc_type_code']}"
                      f" #{c['chunk_no']} หน้า {c['page_no']} | {head}")
                if args.show_text:
                    print("      " + c["text"].replace("\n", "\n      "))

    print("\n" + "=" * 78)
    if not good or not bad:
        print("ข้อมูลไม่พอสรุป — ต้องมีทั้ง hit ที่ถูกและที่มั่ว (เพิ่มคำถาม off-topic หรือแก้คีย์เวิร์ด)")
        return 1

    lo_good, hi_bad = min(good), max(bad)
    print(f"hit ที่ถูก  ({len(good):>3}): min={lo_good:.4f}  median={statistics.median(good):.4f}  max={max(good):.4f}")
    print(f"hit ที่มั่ว ({len(bad):>3}): min={min(bad):.4f}  median={statistics.median(bad):.4f}  max={hi_bad:.4f}")

    if lo_good > hi_bad:
        suggested = round((lo_good + hi_bad) / 2, 3)
        print(f"\n✅ สองกลุ่มแยกขาด (ช่องว่าง {lo_good - hi_bad:.4f}) → RAG_MIN_SCORE={suggested}")
    else:
        # ทับซ้อน: เลือกฝั่ง recall เพราะการตัด chunk ที่ถูกทิ้งไปเงียบๆ แพงกว่าการปล่อย chunk มั่วเข้าไป
        # (system prompt ข้อ 6 บังคับให้ Gemini ตอบเฉพาะจากข้อความใน chunk + มี citation ให้คนตรวจซ้ำ)
        suggested = round(lo_good - 0.005, 3)
        print(f"\n⚠️  สองกลุ่มทับซ้อนกัน (ถูกต่ำสุด {lo_good:.4f} < มั่วสูงสุด {hi_bad:.4f})")
        print(f"   → ตั้ง RAG_MIN_SCORE={suggested} (เอา recall ไว้ก่อน) แล้วดู chunk มั่วที่หลุดเข้ามาว่ารับได้ไหม")
        print("   ถ้ารับไม่ได้ ให้แก้ที่ต้นทาง (chunk เล็กลง / ทำซ้ำหัวตาราง) ไม่ใช่ดัน threshold ขึ้นอย่างเดียว")

    print(f"\nค่าปัจจุบันใน config: RAG_MIN_SCORE={RAG_MIN_SCORE}")
    print("ตั้งค่าจริงโดยเพิ่มบรรทัดนี้ใน .env:")
    print(f"    RAG_MIN_SCORE={suggested}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
