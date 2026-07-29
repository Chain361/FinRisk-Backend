# -*- coding: utf-8 -*-
"""
judges.py — RAG triad (M5–M7 บางส่วน) แบบ LLM-as-judge (ดู docs/langsmith_eval_plan.md §3.1)

ต่างจาก evaluators.py (deterministic, ใช้เป็น merge gate) — ไฟล์นี้ยิง LLM เพื่อตัดสิน
คุณภาพเชิงความหมายที่ regex จับไม่ได้ ผลจึง **ไม่นิ่ง 100%** → ห้ามเอาไปเป็น merge gate
(GATE ใน run_chatbot_eval.py มีแค่ M1/M2) ใช้เป็น metric "เฝ้าดู" บน LangSmith เท่านั้น

RAG triad (นิยามตาม TruLens):
  • context_relevance — chunk ที่ค้นเจอเกี่ยวข้องกับคำถามไหม (ขา retrieval)
  • groundedness (M6)  — ทุกข้อความในคำตอบมีที่มาจาก chunk ที่ค้นเจอไหม (ขา generation)
  • answer_relevance   — คำตอบตอบตรงคำถามผู้ใช้ไหม (ขา end-to-end)

ทั้งสามตัวเป็น **reference-free** (ไม่ต้อง label เฉลยใน dataset) จึงเสริมกับ
retrieval_evaluators.py ที่ต้องมี qrels — และครอบคลุมคำถามที่ยังไม่ได้ label ด้วย

signature ตาม LangSmith SDK: รับ keyword `inputs`/`outputs`/`reference_outputs`
คืน {"key", "score", "comment"}  — score=None = ไม่เกี่ยวข้องกับเคสนั้น (เช่นไม่ได้ใช้ RAG)

⚠️ `import langsmith` ไม่มีในไฟล์นี้ตั้งใจ — judge เป็นแค่ฟังก์ชัน Python ที่ Client().evaluate
   เรียกได้ตรงๆ (ดู CLAUDE.md: langsmith import ได้เฉพาะ observability.py กับ evals/)
"""
import json
import re

# ── LLM judge backend — ใช้ Gemini ตัวเดียวกับ chatbot (ไม่มี langchain ใน repo) ──
# แยกเป็นฟังก์ชันเดียวเพื่อ monkeypatch ในเทสต์ได้ (เทสต์ไม่ยิง Gemini จริง)
_JUDGE_TEMPERATURE = 0  # อยากให้ผลนิ่งที่สุดเท่าที่ LLM จะทำได้


def _call_judge(prompt: str) -> dict:
    """ยิง Gemini แบบบังคับ JSON แล้วคืน {"score": float 0..1, "reason": str}

    import ภายในฟังก์ชันเพื่อไม่ให้ pytest ที่ import โมดูลนี้ต้องมี google-genai/คีย์
    (เทสต์ M-judge ที่แตะเฉพาะ branch score=None ไม่เคยเข้ามาถึงบรรทัดนี้)
    """
    from google import genai
    from google.genai import types

    from src.config import GEMINI_API_KEY, GEMINI_MODEL

    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=_JUDGE_TEMPERATURE,
            response_mime_type="application/json",
        ),
    )
    return _parse_verdict(resp.text)


def _parse_verdict(text: str) -> dict:
    """ทน output ที่มี ```json fence หรือมีข้อความห่อ — ดึงก้อน {...} ตัวแรกมา parse

    บังคับ score ให้อยู่ใน [0,1] เสมอ กัน judge คืน 0–100 หรือ 0–5 มาให้เพี้ยน
    """
    text = (text or "").strip()
    if not text:
        return {"score": 0.0, "reason": "judge คืนค่าว่าง"}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    obj = json.loads(m.group(0) if m else text)
    score = float(obj.get("score", 0.0))
    if score > 1.0:  # judge เผลอให้เป็นเปอร์เซ็นต์/สเกลอื่น
        score = score / 100.0 if score > 10 else score / 10.0
    return {"score": max(0.0, min(1.0, score)), "reason": str(obj.get("reason", ""))}


def _rag_context(outputs: dict) -> list[str]:
    """chunk text ที่ RAG คืนมาจริง (targets.chatbot_target เติมให้) — ตัดตัวว่างทิ้ง"""
    return [c for c in (outputs.get("retrieved_context") or []) if c and c.strip()]


def _na(key: str, comment: str) -> dict:
    return {"key": key, "score": None, "comment": comment}


# ── context_relevance — ขา retrieval ของ triad ─────────────────────────────────
def context_relevance(inputs: dict, outputs: dict, reference_outputs: dict | None = None) -> dict:
    """สัดส่วน chunk ที่ค้นเจอซึ่งเกี่ยวข้องกับคำถามจริง (0..1)

    ต่างจาก precision_at_k (retrieval_evaluators.py) ตรงที่ **ไม่ต้องมี qrels** — LLM
    ตัดสินความเกี่ยวข้องจากเนื้อ chunk เทียบคำถามตรงๆ จึงใช้กับคำถามที่ยังไม่ได้ label ได้
    """
    chunks = _rag_context(outputs)
    if not chunks:
        return _na("context_relevance", "ไม่ได้ใช้ RAG / ไม่มี chunk")

    listed = "\n---\n".join(f"[{i}] {c}" for i, c in enumerate(chunks))
    verdict = _call_judge(
        "คุณเป็นผู้ประเมินคุณภาพการค้นเอกสาร ให้พิจารณาว่าแต่ละ chunk ด้านล่าง "
        "เกี่ยวข้องกับ 'คำถาม' หรือไม่ แล้วคืน JSON "
        '{"score": สัดส่วน chunk ที่เกี่ยวข้อง (0..1), "reason": เหตุผลสั้นๆ}\n\n'
        f"คำถาม: {inputs.get('message', '')}\n\nchunks:\n{listed}"
    )
    return {"key": "context_relevance", "score": verdict["score"], "comment": verdict["reason"]}


# ── groundedness (M6) — ขา generation ของ triad ────────────────────────────────
def groundedness(inputs: dict, outputs: dict, reference_outputs: dict | None = None) -> dict:
    """M6 — ทุกข้อความในคำตอบต้อง trace กลับไปหา chunk ที่ค้นเจอได้ (ไม่แต่งเติม)

    ผูกกับกติกา SYSTEM_PROMPT ข้อ 1 และหลักการเดียวกับ citation_complete: ระบบนี้ผู้ใช้
    ต้องเปิดเอกสารไปยืนยันเองได้ คำตอบที่มีข้อความลอยๆ ไม่มีที่มาจึงเป็นความเสี่ยง
    """
    chunks = _rag_context(outputs)
    if not chunks:
        return _na("groundedness", "ไม่ได้ใช้ RAG — groundedness ไม่เกี่ยวข้อง")

    context = "\n---\n".join(chunks)
    verdict = _call_judge(
        "คุณเป็นผู้ตรวจสอบความถูกต้อง ให้ค่า score 0..1 ว่า 'คำตอบ' มีหลักฐานรองรับใน "
        "'บริบท' มากแค่ไหน (1 = ทุกข้อความอ้างอิงได้จากบริบท, 0 = แต่งขึ้นเองไม่มีที่มา) "
        'คืน JSON {"score": 0..1, "reason": ระบุข้อความที่ไม่มีที่มา ถ้ามี}\n\n'
        f"บริบท:\n{context}\n\nคำตอบ:\n{outputs.get('reply', '')}"
    )
    return {"key": "groundedness", "score": verdict["score"], "comment": verdict["reason"]}


# ── answer_relevance — ขา end-to-end ของ triad ─────────────────────────────────
def answer_relevance(inputs: dict, outputs: dict, reference_outputs: dict | None = None) -> dict:
    """คำตอบตอบตรงคำถามผู้ใช้แค่ไหน (0..1) — reference-free

    ให้คะแนนได้แม้ไม่ได้ใช้ RAG (คำถามเชิง structured ก็ยังต้องตอบตรง) แต่ถ้าคำตอบเป็น
    การ 'ปฏิเสธเพราะนอกขอบเขต' โดยชอบ (เคส security) จะได้คะแนนต่ำโดยธรรมชาติ ซึ่งถูกต้อง
    ตามความหมายของ metric นี้ — จึงควรรันชุด core เท่านั้น (ดู run_chatbot_eval.py)
    """
    reply = outputs.get("reply", "") or ""
    if not reply.strip():
        return {"key": "answer_relevance", "score": 0.0, "comment": "คำตอบว่าง"}

    verdict = _call_judge(
        "ให้ค่า score 0..1 ว่า 'คำตอบ' ตอบตรง 'คำถาม' ของผู้ใช้แค่ไหน "
        "(1 = ตอบตรงและครบ, 0 = ไม่เกี่ยวข้อง) คืน JSON "
        '{"score": 0..1, "reason": เหตุผลสั้นๆ}\n\n'
        f"คำถาม:\n{inputs.get('message', '')}\n\nคำตอบ:\n{reply}"
    )
    return {"key": "answer_relevance", "score": verdict["score"], "comment": verdict["reason"]}


# RAG triad ครบชุด — ต่อท้าย DETERMINISTIC_EVALUATORS เมื่อรัน --judges
TRIAD_EVALUATORS = [context_relevance, groundedness, answer_relevance]
