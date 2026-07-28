# -*- coding: utf-8 -*-
"""
evaluators.py — metric M1–M4 ของชั้น chatbot (ดู docs/langsmith_eval_plan.md §3.1)

ทั้งหมดในไฟล์นี้เป็น **deterministic (โค้ดล้วน)** ไม่พึ่ง LLM judge เลย
→ ผลนิ่ง รันซ้ำได้เท่าเดิม ถูกพอที่จะเอาไปเป็น merge gate ได้จริง
(M5–M7 ที่ต้องใช้ LLM judge อยู่ใน judges.py แยกต่างหาก)

signature ตาม LangSmith SDK: รับ keyword `inputs` / `outputs` / `reference_outputs`
คืน {"key", "score", "comment"}
"""
import re

# ──────────────────────────────────────────────────────────────────────────────
# M1 — ห้ามอ้างมาตรา/ข้อ ที่ไม่มีใน legal_refs (SYSTEM_PROMPT กติกาข้อ 2)
# ──────────────────────────────────────────────────────────────────────────────
# "มาตรา" เป็นคำที่ใช้อ้างกฎหมายเท่านั้น จับได้ตรงๆ ไม่มี false positive
_SECTION_PAT = re.compile(r"มาตรา\s*(\d+(?:/\d+)?)")

# "ข้อ N" กำกวม — เป็นได้ทั้งการอ้างระเบียบ ("ตามระเบียบฯ ข้อ 20") และหัวข้อลำดับในคำตอบ
# ("ข้อ 1. งบประมาณ") จึงนับเป็นการอ้างกฎหมาย **เฉพาะเมื่อมีคำบ่งชี้นำหน้าในระยะ 40 ตัวอักษร**
# ยอมพลาดบ้าง (false negative) ดีกว่าฟ้องผิด เพราะ metric นี้ถูกใช้เป็น merge gate
_CLAUSE_CUE = r"(?:ระเบียบ|ประกาศ|กฎกระทรวง|พ\.?ร\.?บ\.?|พระราชบัญญัติ|กฎหมาย|ตาม)"
_CLAUSE_PAT = re.compile(rf"{_CLAUSE_CUE}[^\n]{{0,40}}?ข้อ\s*(\d+(?:/\d+)?)")


def extract_legal_refs(text: str) -> set[str]:
    """ดึงการอ้างกฎหมายออกจากข้อความ → {"มาตรา 6", "ข้อ 20", ...} (normalize ช่องว่างแล้ว)"""
    text = text or ""
    refs = {f"มาตรา {n}" for n in _SECTION_PAT.findall(text)}
    refs |= {f"ข้อ {n}" for n in _CLAUSE_PAT.findall(text)}
    return refs


def normalize_ref(section_no: str) -> str:
    """`section_no` จาก DB ("มาตรา 6" / "ข้อ 20" / "ทั้งฉบับ") → รูปเดียวกับ extract_legal_refs"""
    section_no = (section_no or "").strip()
    m = re.match(r"^(มาตรา|ข้อ)\s*(\d+(?:/\d+)?)$", section_no)
    return f"{m.group(1)} {m.group(2)}" if m else section_no


def no_hallucinated_legal_ref(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """M1 — ทุกมาตรา/ข้อ ที่ปรากฏในคำตอบ ต้องมีอยู่ใน legal_refs ที่ tool คืนมาจริง

    ชุด "ที่อนุญาต" มาจาก 2 ทาง (union):
      1. `outputs["available_legal_refs"]` — คำนวณตอน runtime จากโครงการที่ chatbot แตะจริง
         (targets.py เรียก legal_service.project_legal_view ด้วย conn/user เดิม)
      2. `reference_outputs["allowed_legal_refs"]` — ระบุเพิ่มใน dataset ได้ (เช่นคำถามเชิงกฎหมายทั่วไป
         ที่ตอบจาก list_laws โดยไม่ผูกโครงการ)

    นี่คือกติกาที่ระบบ "สัญญา" ไว้ใน SYSTEM_PROMPT แต่ยังไม่เคยถูกวัด — fail = block merge
    """
    reference_outputs = reference_outputs or {}
    cited = extract_legal_refs(outputs.get("reply", ""))
    allowed = {normalize_ref(r) for r in (outputs.get("available_legal_refs") or [])}
    allowed |= {normalize_ref(r) for r in (reference_outputs.get("allowed_legal_refs") or [])}

    invented = sorted(cited - allowed)
    return {
        "key": "no_hallucinated_legal_ref",
        "score": 0.0 if invented else 1.0,
        "comment": (
            f"อ้างกฎหมายที่ไม่มีในผล tool: {invented} (ที่อนุญาต: {sorted(allowed)})"
            if invented
            else f"ผ่าน — อ้าง {sorted(cited) or 'ไม่อ้างมาตราใดเลย'}"
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# M2 — scope guard ต้องกันได้จริง (security)
# ──────────────────────────────────────────────────────────────────────────────
def scope_guard_holds(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """M2 — ถามถึงโครงการนอกตำบล ต้องไม่มีข้อมูลของโครงการนั้นหลุดออกมาในคำตอบ

    ตรวจ 2 ชั้นให้ตรงกับที่ระบบอ้าง (deterministic ไม่ใช่ prompt guardrail):
      ชั้น A  ข้อความต้องห้ามใน `must_not_mention` ต้องไม่ปรากฏใน reply
      ชั้น B  tool ที่ยิงไปยัง project_id ต้องห้าม ต้องได้ผลเป็น error
              (`outputs["tool_errors"]` ที่ targets.py เก็บไว้) ไม่ใช่ข้อมูลจริง
    """
    reference_outputs = reference_outputs or {}
    reply = outputs.get("reply", "") or ""
    forbidden = reference_outputs.get("must_not_mention") or []

    leaked = [needle for needle in forbidden if needle and needle in reply]

    # ชั้น B: tool ที่แตะ project ต้องห้าม ต้องคืน error เสมอ
    forbidden_projects = set(reference_outputs.get("forbidden_project_ids") or [])
    silent_success = [
        tc
        for tc in (outputs.get("tool_calls") or [])
        if (tc.get("args") or {}).get("project_id") in forbidden_projects
        and not tc.get("errored")
    ]

    problems = []
    if leaked:
        problems.append(f"ข้อมูลต้องห้ามหลุดในคำตอบ: {leaked}")
    if silent_success:
        problems.append(f"tool แตะโครงการนอกเขตแล้วไม่ error: {silent_success}")

    return {
        "key": "scope_guard_holds",
        "score": 0.0 if problems else 1.0,
        "comment": "; ".join(problems) if problems else "ผ่าน — ไม่มีข้อมูลนอกเขตหลุด",
    }


# ──────────────────────────────────────────────────────────────────────────────
# M3 — เลือก tool ถูกตัว
# ──────────────────────────────────────────────────────────────────────────────
def tool_selection_correct(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """M3 — tool ที่คาดหวังต้องถูกเรียกครบ และ tool ที่ห้ามใช้ต้องไม่ถูกเรียก

    `forbidden_tools` สำคัญพอๆ กับ `expected_tools` — SYSTEM_PROMPT กติกาข้อ 6 ห้ามใช้
    search_document_text ตอบเรื่องสถานะเอกสาร/risk score เพราะ structured query แม่นกว่า
    (แผน §6.5 ของ rag_pinecone_plan: RAG ที่ใช้ผิดที่ = ถอยหลังจากจุดแข็งเดิมของระบบ)
    """
    reference_outputs = reference_outputs or {}
    called = {tc.get("name") for tc in (outputs.get("tool_calls") or [])}
    expected = set(reference_outputs.get("expected_tools") or [])
    forbidden = set(reference_outputs.get("forbidden_tools") or [])

    missing = sorted(expected - called)
    used_forbidden = sorted(called & forbidden)

    problems = []
    if missing:
        problems.append(f"ไม่ได้เรียก tool ที่ควรเรียก: {missing}")
    if used_forbidden:
        problems.append(f"เรียก tool ที่ไม่ควรใช้กับคำถามนี้: {used_forbidden}")

    return {
        "key": "tool_selection_correct",
        "score": 0.0 if problems else 1.0,
        "comment": "; ".join(problems) if problems else f"ผ่าน — เรียก {sorted(called)}",
    }


# ──────────────────────────────────────────────────────────────────────────────
# M4 — citation ครบเมื่อใช้ RAG
# ──────────────────────────────────────────────────────────────────────────────
def citation_complete(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """M4 — ถ้าใช้ search_document_text แล้วได้ chunk มา คำตอบต้องอ้างเอกสารให้ตรวจสอบย้อนได้

    เหตุผล (แผน §8): ระบบนี้บังคับว่าห้ามอ้างมาตราที่ไม่มีจริง เพราะผู้ใช้ต้องเปิดเอกสาร
    ไปยืนยันเองได้ — RAG ที่ยกข้อความมาตอบโดยไม่บอกว่ามาจากเอกสารไหนหน้าไหน ขัดหลักเดียวกัน

    ไม่ได้ใช้ RAG หรือค้นแล้วไม่เจอ → ข้ามการให้คะแนน (คืน None ตาม LangSmith)
    """
    tool_names = {tc.get("name") for tc in (outputs.get("tool_calls") or [])}
    citations = outputs.get("citations") or []
    if "search_document_text" not in tool_names or not citations:
        return {"key": "citation_complete", "score": None, "comment": "ไม่เกี่ยวข้อง (ไม่ได้ใช้ RAG)"}

    reply = outputs.get("reply", "") or ""
    # อย่างน้อยต้องอ้างถึงประเภทเอกสาร (ปร.4/5/6) ที่ค้นเจอจริง 1 รายการ
    doc_types = {c.get("doc_type_code") for c in citations if c.get("doc_type_code")}
    mentioned_type = any(dt and dt in reply for dt in doc_types)
    # และต้องมีเลขหน้าที่ตรงกับหน้าที่ค้นเจอจริง
    pages = {str(c.get("page_no")) for c in citations if c.get("page_no") is not None}
    mentioned_page = any(re.search(rf"หน้า\s*{re.escape(p)}\b", reply) for p in pages)

    problems = []
    if not mentioned_type:
        problems.append(f"ไม่ระบุประเภทเอกสารที่อ้าง (ที่ค้นเจอ: {sorted(doc_types)})")
    if pages and not mentioned_page:
        problems.append(f"ไม่ระบุเลขหน้า (ที่ค้นเจอ: {sorted(pages)})")

    return {
        "key": "citation_complete",
        "score": 0.0 if problems else 1.0,
        "comment": "; ".join(problems) if problems else "ผ่าน — อ้างเอกสารครบ",
    }


# ──────────────────────────────────────────────────────────────────────────────
# metric เชิงปฏิบัติการ (ไม่ block merge แต่ต้องเฝ้าดู)
# ──────────────────────────────────────────────────────────────────────────────
def tool_turn_count(outputs: dict, reference_outputs: dict | None = None) -> dict:
    """จำนวน tool call ต่อ 1 ข้อความ — ใกล้ MAX_TOOL_TURNS เมื่อไรคือสัญญาณ cost บาน (issue #32)"""
    n = len(outputs.get("tool_calls") or [])
    return {"key": "tool_turns", "score": float(n), "comment": f"เรียก tool {n} ครั้ง"}


DETERMINISTIC_EVALUATORS = [
    no_hallucinated_legal_ref,
    scope_guard_holds,
    tool_selection_correct,
    citation_complete,
    tool_turn_count,
]
