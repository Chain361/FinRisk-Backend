# -*- coding: utf-8 -*-
"""
retrieval_evaluators.py — metric ชั้น RAG (แผน §3.2)

วัด `search_document_text` โดดๆ ไม่ผ่าน LLM → ถูกกว่า เร็วกว่า และชี้สาเหตุได้ตรงกว่า
ใช้คู่กับ run_retrieval_eval.py --sweep เพื่อหาค่า RAG_MIN_SCORE ด้วยข้อมูล ไม่ใช่ค่าเดา
"""


def _relevant_ids(reference_outputs: dict) -> set[str]:
    return {str(x) for x in (reference_outputs.get("relevant_chunk_ids") or [])}


def recall_at_k(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """สัดส่วน chunk ที่ label ว่าเกี่ยวข้อง ที่ค้นเจอจริงใน top-k

    ตัวชี้ขาดของ RAG งานตรวจสอบ: พลาด chunk ที่ควรเจอ = ผู้ตรวจไม่เห็นหลักฐานที่มีอยู่จริง
    ซึ่งแย่กว่าการคืน chunk เกินมาหนึ่งอัน
    """
    reference_outputs = reference_outputs or {}
    relevant = _relevant_ids(reference_outputs)
    if not relevant:
        return {"key": "recall_at_k", "score": None, "comment": "ไม่มี label"}
    found = relevant & {str(i) for i in (outputs.get("chunk_ids") or [])}
    return {
        "key": "recall_at_k",
        "score": len(found) / len(relevant),
        "comment": f"เจอ {len(found)}/{len(relevant)} — ขาด {sorted(relevant - found)}",
    }


def precision_at_k(outputs: dict, reference_outputs: dict | None = None) -> dict:
    reference_outputs = reference_outputs or {}
    relevant = _relevant_ids(reference_outputs)
    returned = [str(i) for i in (outputs.get("chunk_ids") or [])]
    if not relevant:
        return {"key": "precision_at_k", "score": None, "comment": "ไม่มี label"}
    if not returned:
        return {"key": "precision_at_k", "score": 0.0, "comment": "ไม่คืน chunk เลย"}
    hit = sum(1 for i in returned if i in relevant)
    return {
        "key": "precision_at_k",
        "score": hit / len(returned),
        "comment": f"{hit}/{len(returned)} ที่คืนมาเกี่ยวข้องจริง",
    }


def mrr(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """1/อันดับของ chunk ที่ถูกตัวแรก — สะท้อนว่า chunk ที่ใช่ถูกดันขึ้นบนสุดไหม"""
    reference_outputs = reference_outputs or {}
    relevant = _relevant_ids(reference_outputs)
    if not relevant:
        return {"key": "mrr", "score": None, "comment": "ไม่มี label"}
    for rank, chunk_id in enumerate((outputs.get("chunk_ids") or []), start=1):
        if str(chunk_id) in relevant:
            return {"key": "mrr", "score": 1.0 / rank, "comment": f"เจอที่อันดับ {rank}"}
    return {"key": "mrr", "score": 0.0, "comment": "ไม่เจอ chunk ที่เกี่ยวข้องเลย"}


def no_cross_scope_leak(inputs: dict, outputs: dict, reference_outputs: dict | None = None) -> dict:
    """**ต้องได้ 1.0 เสมอ** — chunk ที่คืนต้องอยู่ในโครงการที่ผู้ใช้เห็นได้เท่านั้น

    ถ้าตัวนี้ตกแม้แต่ครั้งเดียว แปลว่า post-verify (retrieval._verify_and_enrich) มีรู
    ซึ่งร้ายแรงกว่าคุณภาพการค้นทุกตัวรวมกัน — ระบบนี้ผู้ใช้คือหน่วยตรวจสอบราชการ
    """
    reference_outputs = reference_outputs or {}
    allowed_projects = set(reference_outputs.get("allowed_project_ids") or [])
    if not allowed_projects:
        return {"key": "no_cross_scope_leak", "score": None, "comment": "ไม่ได้ระบุขอบเขตที่คาดหวัง"}
    leaked = sorted(
        {
            c.get("project_id")
            for c in (outputs.get("chunks") or [])
            if c.get("project_id") not in allowed_projects
        }
    )
    return {
        "key": "no_cross_scope_leak",
        "score": 0.0 if leaked else 1.0,
        "comment": f"⚠️ chunk นอกขอบเขตหลุด: {leaked}" if leaked else "ผ่าน",
    }


def empty_when_expected(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """คำถามที่ไม่ควรเจออะไร (nonsense / นอกเขต) ต้องคืนว่างจริง ไม่ใช่ยัด chunk มั่วมาให้"""
    reference_outputs = reference_outputs or {}
    if not reference_outputs.get("expect_empty"):
        return {"key": "empty_when_expected", "score": None, "comment": "ไม่เกี่ยวข้อง"}
    n = len(outputs.get("chunks") or [])
    return {
        "key": "empty_when_expected",
        "score": 1.0 if n == 0 else 0.0,
        "comment": "ผ่าน — คืนว่างตามที่ควร" if n == 0 else f"ไม่ควรคืน chunk แต่คืนมา {n}",
    }


RETRIEVAL_EVALUATORS = [
    recall_at_k,
    precision_at_k,
    mrr,
    no_cross_scope_leak,
    empty_when_expected,
]
