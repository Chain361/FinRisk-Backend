# -*- coding: utf-8 -*-
"""
run_chatbot_eval.py — รัน experiment ของ chatbot บน LangSmith

    python -m evals.run_chatbot_eval                    # รันทั้ง core + security
    python -m evals.run_chatbot_eval --suite security   # เฉพาะชุด security
    python -m evals.run_chatbot_eval --local            # ไม่ต้องมี LANGSMITH_API_KEY (พิมพ์ผลออก stdout)

⚠️ ยิง Gemini + Pinecone จริง — มีค่าใช้จ่ายและถูก rate limit ได้ (`CHATBOT_RATE_LIMIT_PER_MINUTE`
   ไม่มีผลตรงนี้เพราะเรียก service ตรง ไม่ผ่าน router) ตั้ง --concurrency ต่ำๆ ถ้าโดน 429 จาก Gemini
"""
import argparse
import subprocess
import sys
from inspect import signature
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from evals.datasets_io import load_jsonl  # noqa: E402
from evals.evaluators import DETERMINISTIC_EVALUATORS  # noqa: E402
from evals.judges import TRIAD_EVALUATORS  # noqa: E402
from evals.targets import chatbot_target  # noqa: E402

SUITES = {
    "core": ("chatbot_core", "finrisk-chatbot-core"),
    "security": ("chatbot_security", "finrisk-chatbot-security"),
}

# metric ที่ถือเป็น merge gate — ต่ำกว่านี้คือ fail (แผน §4)
GATE = {"no_hallucinated_legal_ref": 1.0, "scope_guard_holds": 1.0}


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001 — metadata ไม่ควรทำให้ eval ล้ม
        return "unknown"


def _run_metadata() -> dict:
    """ใส่ทุกอย่างที่ทำให้ผลเปลี่ยนได้ลง metadata — ไม่งั้นเทียบ experiment ข้ามรอบไม่ได้
    ว่าอะไรทำให้ metric ขยับ (โมเดลเปลี่ยน? threshold เปลี่ยน? โค้ดเปลี่ยน?)"""
    from src.config import GEMINI_MODEL, RAG_MIN_SCORE, RAG_TOP_K

    return {
        "git_sha": _git_sha(),
        "gemini_model": GEMINI_MODEL,
        "rag_min_score": RAG_MIN_SCORE,
        "rag_top_k": RAG_TOP_K,
    }


def _evaluators_for(suite: str, judges: bool) -> list:
    """เลือกชุด evaluator — RAG triad (LLM judge) ต่อท้ายเมื่อ --judges เท่านั้น

    ข้ามชุด security: triad โดยเฉพาะ answer_relevance จะให้คะแนนต่ำกับการ 'ปฏิเสธเพราะ
    นอกขอบเขต' ซึ่งเป็นพฤติกรรมที่ถูกต้องของชุดนั้น — วัดแล้ว mislead (ดู judges.py)
    """
    if judges and suite != "security":
        return [*DETERMINISTIC_EVALUATORS, *TRIAD_EVALUATORS]
    return DETERMINISTIC_EVALUATORS


def run_local(suite: str, judges: bool = False) -> int:
    """รันโดยไม่ต้องมี LangSmith — ใช้ตอน debug evaluator หรือตอนยังไม่มีคีย์"""
    file_name, _ = SUITES[suite]
    rows = load_jsonl(file_name)
    evaluators = _evaluators_for(suite, judges)
    failures = 0
    for row in rows:
        outputs = chatbot_target(row["inputs"])
        print(f"\n── {row['id']} ── {row['inputs']['message'][:60]}")
        print(f"   reply: {outputs['reply'][:160]}")
        for evaluator in evaluators:
            # LLM judge รับ `inputs` ด้วย, deterministic ไม่รับ — ส่งตามที่ signature ประกาศ
            # (บน LangSmith cloud SDK ทำให้อัตโนมัติ ตรงนี้เลียนแบบให้ --local ทำงานเหมือนกัน)
            kwargs = {"outputs": outputs, "reference_outputs": row.get("outputs") or {}}
            if "inputs" in signature(evaluator).parameters:
                kwargs["inputs"] = row["inputs"]
            result = evaluator(**kwargs)
            if result["score"] is None:
                continue
            gate = GATE.get(result["key"])
            failed = gate is not None and result["score"] < gate
            failures += bool(failed)
            print(f"   {'✗' if failed else '✓'} {result['key']}={result['score']}: {result['comment']}")
    print(f"\nสรุป: {'ไม่ผ่าน ' + str(failures) + ' รายการ' if failures else 'ผ่านทุก gate'}")
    return 1 if failures else 0


def run_langsmith(suite: str, concurrency: int, judges: bool = False) -> int:
    from langsmith import Client

    file_name, dataset_name = SUITES[suite]
    evaluators = _evaluators_for(suite, judges)
    results = Client().evaluate(
        chatbot_target,
        data=dataset_name,
        evaluators=evaluators,
        experiment_prefix=f"chatbot-{suite}",
        metadata={**_run_metadata(), "suite": suite, "judges": judges},
        max_concurrency=concurrency,
    )
    print(f"ส่งผลขึ้น LangSmith แล้ว — dataset: {dataset_name} ({file_name}.jsonl)")
    try:
        print(results.to_pandas().describe())
    except Exception:  # noqa: BLE001 — ไม่มี pandas ก็ไม่เป็นไร ผลอยู่บน LangSmith แล้ว
        pass
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=[*SUITES, "all"], default="all")
    parser.add_argument("--local", action="store_true", help="ไม่ส่งขึ้น LangSmith")
    parser.add_argument(
        "--judges",
        action="store_true",
        help="เพิ่ม RAG triad (LLM-as-judge: context_relevance/groundedness/answer_relevance) "
        "— ยิง Gemini เพิ่ม 3 ครั้ง/เคส, ไม่ใช่ merge gate, ข้ามชุด security อัตโนมัติ",
    )
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()

    suites = list(SUITES) if args.suite == "all" else [args.suite]
    exit_code = 0
    for suite in suites:
        print(f"\n===== suite: {suite} =====")
        exit_code |= (
            run_local(suite, args.judges)
            if args.local
            else run_langsmith(suite, args.concurrency, args.judges)
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
