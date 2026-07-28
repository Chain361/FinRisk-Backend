# -*- coding: utf-8 -*-
"""
datasets_io.py — โหลด/sync dataset ระหว่างไฟล์ jsonl ใน repo กับ LangSmith

**แหล่งความจริงคือไฟล์ jsonl ใน repo** ไม่ใช่ dataset ใน UI:
  - review ผ่าน PR ได้ (dataset คือ spec ของพฤติกรรม — ควรผ่านสายตาคนเหมือนโค้ด)
  - รอด reseed/redeploy เพราะอ้าง natural key (project_id, username) เหมือน RAG (แผน §4.2)
  - รันแบบ local (ไม่มี LANGSMITH_API_KEY) ได้ด้วยชุดข้อมูลเดียวกันเป๊ะ
"""
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import src.config  # noqa: F401 (เพื่อโหลด .env อัตโนมัติ)

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"


def load_jsonl(name: str) -> list[dict]:
    """`chatbot_core` → [{"id", "inputs", "outputs"}, ...] (ข้ามบรรทัดว่าง/คอมเมนต์)"""
    path = DATASETS_DIR / f"{name}.jsonl"
    if not path.is_file():
        raise FileNotFoundError(f"ไม่พบ dataset: {path}")
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name} บรรทัด {lineno} ไม่ใช่ JSON ที่ถูกต้อง: {exc}") from exc
    return out


def sync_to_langsmith(name: str, langsmith_dataset: str, description: str = "") -> int:
    """upsert jsonl ขึ้น LangSmith แบบ idempotent (ยึด `id` ใน jsonl เป็น key)

    รันซ้ำได้ไม่เกิด example ซ้ำ — ตัวอย่างที่ id เดิมจะถูกอัปเดตค่า inputs/outputs
    """
    from langsmith import Client

    client = Client()
    rows = load_jsonl(name)

    if client.has_dataset(dataset_name=langsmith_dataset):
        dataset = client.read_dataset(dataset_name=langsmith_dataset)
    else:
        dataset = client.create_dataset(dataset_name=langsmith_dataset, description=description)

    existing = {
        (ex.metadata or {}).get("source_id"): ex
        for ex in client.list_examples(dataset_id=dataset.id)
    }

    created = updated = 0
    for row in rows:
        source_id = row["id"]
        payload = dict(
            inputs=row["inputs"],
            outputs=row.get("outputs") or {},
            metadata={"source_id": source_id, "source_file": f"{name}.jsonl"},
        )
        found = existing.get(source_id)
        if found is None:
            client.create_example(dataset_id=dataset.id, **payload)
            created += 1
        else:
            client.update_example(example_id=found.id, **payload)
            updated += 1

    print(f"[{langsmith_dataset}] สร้างใหม่ {created} / อัปเดต {updated} (รวม {len(rows)} ตัวอย่าง)")
    return len(rows)


SYNC_PLAN = [
    ("chatbot_core", "finrisk-chatbot-core", "คำถามหลักของ auditor/analyst — ตรวจการเลือก tool และการอ้างกฎหมาย"),
    ("chatbot_security", "finrisk-chatbot-security", "scope guard + prompt injection — ต้องผ่าน 100% ก่อน merge"),
    ("retrieval_qrels", "finrisk-retrieval-qrels", "qrels ของ RAG — ใช้หา RAG_MIN_SCORE"),
]


def main() -> None:
    for name, langsmith_dataset, description in SYNC_PLAN:
        sync_to_langsmith(name, langsmith_dataset, description)


if __name__ == "__main__":
    main()
