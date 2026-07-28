# -*- coding: utf-8 -*-
"""
run_retrieval_eval.py — experiment ชั้น RAG + เครื่องมือหาค่า RAG_MIN_SCORE

    python -m evals.run_retrieval_eval --dump              # พิมพ์ top-k ของทุก query (ใช้ label qrels)
    python -m evals.run_retrieval_eval --sweep             # sweep min_score หลายค่าแล้วเทียบ recall/precision
    python -m evals.run_retrieval_eval                     # ส่ง experiment ขึ้น LangSmith

**ทำไมต้องมี --dump:** `relevant_chunk_ids` ใน retrieval_qrels.jsonl ต้องให้ "คน" ตัดสินว่า
chunk ไหนคือคำตอบที่ถูก — machine label ตัวเองแล้ววัดตัวเองไม่มีความหมาย
รัน --dump ครั้งเดียว คัด chunk_id ที่ถูกต้องใส่กลับลง jsonl แล้ว metric ทั้งหมดจึงเริ่มมีค่า

**ทำไมต้องมี --sweep:** ปิด blocker เดิมของโปรเจกต์ — `RAG_MIN_SCORE=0.82` เป็นค่าเดา
(ดู CLAUDE.md "สิ่งที่ยังไม่ทำ") sweep แล้วเลือกค่าที่ recall ยังสูงก่อน precision จะร่วง
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.datasets_io import load_jsonl  # noqa: E402
from evals.retrieval_evaluators import RETRIEVAL_EVALUATORS  # noqa: E402
from evals.targets import retrieval_target  # noqa: E402

DATASET_FILE = "retrieval_qrels"
DATASET_NAME = "finrisk-retrieval-qrels"
SWEEP_VALUES = [0.70, 0.75, 0.78, 0.80, 0.82, 0.85]


def dump() -> int:
    """พิมพ์ chunk ที่ค้นเจอของทุก query เพื่อให้คน label — บังคับ min_score=0 เพื่อเห็นของทั้งหมด"""
    for row in load_jsonl(DATASET_FILE):
        inputs = {**row["inputs"], "min_score": 0}
        out = retrieval_target(inputs)
        print(f"\n══ {row['id']} ── q={inputs['query']!r} project={inputs.get('project_id')}")
        if not out["chunks"]:
            print("   (ไม่พบ chunk)")
        for chunk in out["chunks"]:
            text = (chunk.get("text") or "").replace("\n", " ")[:110]
            print(
                f"   [{chunk['score']:.4f}] {chunk['chunk_id']}  "
                f"{chunk['doc_type_code']} หน้า {chunk['page_no']}\n        {text}"
            )
    print("\n→ คัด chunk_id ที่ตอบคำถามได้จริง ใส่กลับที่ relevant_chunk_ids ใน retrieval_qrels.jsonl")
    return 0


def sweep() -> int:
    """เทียบ recall/precision ที่ min_score หลายค่า บนชุด qrels เดียวกัน"""
    rows = [r for r in load_jsonl(DATASET_FILE) if (r.get("outputs") or {}).get("relevant_chunk_ids")]
    if not rows:
        print("⚠️ ยังไม่มี relevant_chunk_ids ใน qrels เลย — รัน --dump แล้ว label ก่อน")
        return 1

    print(f"{'min_score':>10} | {'recall':>7} | {'precision':>9} | {'mrr':>6}")
    print("-" * 44)
    best = []
    for threshold in SWEEP_VALUES:
        scores = {"recall_at_k": [], "precision_at_k": [], "mrr": []}
        for row in rows:
            out = retrieval_target({**row["inputs"], "min_score": threshold})
            for evaluator in RETRIEVAL_EVALUATORS:
                if evaluator.__name__ not in scores:
                    continue
                result = evaluator(outputs=out, reference_outputs=row["outputs"])
                if result["score"] is not None:
                    scores[result["key"]].append(result["score"])
        avg = {k: (sum(v) / len(v) if v else 0.0) for k, v in scores.items()}
        best.append((threshold, avg))
        print(
            f"{threshold:>10.2f} | {avg['recall_at_k']:>7.3f} | "
            f"{avg['precision_at_k']:>9.3f} | {avg['mrr']:>6.3f}"
        )

    print(
        "\n→ เลือกค่าสูงสุดที่ recall ยังไม่ตก แล้วตั้ง RAG_MIN_SCORE ใน .env "
        "พร้อมบันทึกผลนี้ไว้ที่ docs/rag_pinecone_plan.md §0.1"
    )
    return 0


def run_langsmith(concurrency: int) -> int:
    from langsmith import Client

    from src.config import RAG_MIN_SCORE, RAG_TOP_K

    Client().evaluate(
        retrieval_target,
        data=DATASET_NAME,
        evaluators=RETRIEVAL_EVALUATORS,
        experiment_prefix="retrieval",
        metadata={"rag_min_score": RAG_MIN_SCORE, "rag_top_k": RAG_TOP_K},
        max_concurrency=concurrency,
    )
    print(f"ส่งผลขึ้น LangSmith แล้ว — dataset: {DATASET_NAME}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dump", action="store_true", help="พิมพ์ top-k ของทุก query เพื่อ label")
    parser.add_argument("--sweep", action="store_true", help="sweep min_score หาค่าที่เหมาะสม")
    parser.add_argument("--concurrency", type=int, default=4)
    args = parser.parse_args()

    if args.dump:
        return dump()
    if args.sweep:
        return sweep()
    return run_langsmith(args.concurrency)


if __name__ == "__main__":
    raise SystemExit(main())
