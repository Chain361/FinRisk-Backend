# evals — วัดคุณภาพชั้น AI ด้วย LangSmith

แผนเต็มอยู่ที่ [`docs/langsmith_eval_plan.md`](../docs/langsmith_eval_plan.md)

## ตั้งค่าครั้งแรก

**ทุกคนใช้บัญชี LangSmith ของตัวเอง** — แผน Developer ฟรีให้ 1 seat/บัญชี (5k trace/เดือน)
พอสำหรับงานนี้ ส่วนการ invite เข้า workspace เดียวกันทั้งทีมต้องขึ้นแผน Plus ($39/seat/เดือน)
จึงยังไม่ทำตอนนี้

```bash
pip install -r requirements.txt          # ได้ langsmith มาด้วย
# สมัคร/ล็อกอินที่ smith.langchain.com → Settings → API Keys → สร้าง key ของตัวเอง
# ใส่ใน .env (ห้าม commit)
#   LANGSMITH_TRACING=true
#   LANGSMITH_API_KEY=<key ของตัวเอง>
#   LANGSMITH_PROJECT=finrisk-dev
python -m evals.datasets_io              # sync jsonl ขึ้นบัญชีตัวเอง (idempotent รันซ้ำได้)
```

> ผลที่ตามมาจากการแยกบัญชี: **dataset/experiment ของแต่ละคนอยู่คนละที่ เทียบข้ามคนไม่ได้**
> ทุกคนจึงต้องรัน `datasets_io` เองครั้งแรก และเวลาจะเทียบผลกันให้เอาตัวเลขมาคุยกันเอง
> (ตัวชุดข้อมูลยังตรงกันเป๊ะเพราะมาจาก jsonl ไฟล์เดียวกันใน git)
>
> ไม่อยากสมัครก็ได้ — `--local` รันได้ครบทุก metric โดยไม่ต้องมีบัญชี

## คำสั่งที่ใช้บ่อย

```bash
# chatbot — ต้องมี DB ที่ seed แล้ว + GEMINI_API_KEY
python -m evals.run_chatbot_eval --suite security          # ชุดที่สำคัญที่สุด รันก่อน
python -m evals.run_chatbot_eval --suite core
python -m evals.run_chatbot_eval --suite core --judges     # + RAG triad (LLM judge) — ยิง Gemini เพิ่ม
python -m evals.run_chatbot_eval --local                   # debug evaluator โดยไม่ส่งขึ้น cloud

# retrieval — ต้องมี PINECONE_API_KEY + ingest เอกสารแล้ว
python -m evals.run_retrieval_eval --dump                  # ① พิมพ์ chunk ออกมาให้คน label
python -m evals.run_retrieval_eval --sweep                 # ② หาค่า RAG_MIN_SCORE
python -m evals.run_retrieval_eval                         # ③ ส่ง experiment ขึ้น LangSmith

# evaluator เอง (ไม่แตะ DB/API ไม่ต้องมี LangSmith) — รันหลังแก้ evaluators.py หรือ jsonl
pytest tests/test_observability_evals.py -q
```

## metric ที่วัด

| Metric | ไฟล์ | เป็น merge gate? |
|--------|------|------------------|
| `no_hallucinated_legal_ref` (M1) | `evaluators.py` | ✅ ต้อง 1.0 |
| `scope_guard_holds` (M2) | `evaluators.py` | ✅ ต้อง 1.0 |
| `tool_selection_correct` (M3) | `evaluators.py` | เฝ้าดู (เป้า ≥ 0.90) |
| `citation_complete` (M4) | `evaluators.py` | เฝ้าดู (เป้า ≥ 0.95) |
| `tool_turns` | `evaluators.py` | เฝ้าดู (cost) |
| `recall_at_k` / `precision_at_k` / `mrr` | `retrieval_evaluators.py` | เฝ้าดู |
| `no_cross_scope_leak` | `retrieval_evaluators.py` | ✅ ต้อง 1.0 |
| `context_relevance` / `groundedness` (M6) / `answer_relevance` (RAG triad) | `judges.py` | เฝ้าดู (LLM judge — ไม่ block) |

`score = None` = ไม่เกี่ยวข้องกับเคสนั้นจึงไม่ให้คะแนน (ไม่ใช่ error)

**RAG triad** (`judges.py`, เปิดด้วย `--judges`) — LLM-as-judge สามขา วัดคุณภาพ RAG แบบ
reference-free (ไม่ต้อง label qrels): `context_relevance` (chunk เกี่ยวกับคำถามไหม),
`groundedness`/M6 (คำตอบมีที่มาจาก chunk ไหม), `answer_relevance` (ตอบตรงคำถามไหม)
ยิง Gemini เพิ่ม 3 ครั้ง/เคส → **ไม่ใช่ merge gate** (ผลไม่นิ่ง) และ `--judges` **ข้ามชุด
security อัตโนมัติ** เพราะ answer_relevance จะทำโทษการปฏิเสธที่ถูกต้องของชุดนั้น
context_relevance/groundedness คืน `score=None` เมื่อเคสนั้นไม่ได้ใช้ RAG

ยังไม่ได้ทำ: M5 (computable=0 wording) และ M7 (empty-result honesty) — ดูแผน §3.1

## ข้อควรรู้เกี่ยวกับ dataset

- **แหล่งความจริงคือ `datasets/*.jsonl` ใน repo** ไม่ใช่ dataset ใน LangSmith UI
  แก้ไฟล์ → `python -m evals.datasets_io` → LangSmith ตามมา (upsert ตาม `id`)
  ⚠️ แก้ใน UI จะถูกทับหายเงียบๆ ตอนรัน sync รอบถัดไป
- ตำบลของ mock user สำคัญมากต่อความถูกต้องของชุดข้อมูล:

  | user | role | ตำบล | โครงการที่เห็นได้ |
  |------|------|------|-------------------|
  | `auditor1` / `analyst1` | project_auditor / risk_analyst | ท่าช้าง | `65127236035`, `65047072637`, `66027162573`, … |
  | `auditor2` / `analyst2` | " | ปิงโค้ง | `66069309678`, … |
  | `auditor3` / `analyst3` | " | โยนก | **`MOCK-CON-001`, `MOCK-CON-002`**, `66079021729`, … |

  > ⚠️ `MOCK-CON-001/002` อยู่ **ตำบลโยนก** — คำถามที่ต้องการให้ตอบสำเร็จต้องใช้ `auditor3`
  > ส่วน `auditor1` ถาม MOCK-CON-* คือเคส **security** (ต้องถูกปฏิเสธ)

- `relevant_chunk_ids` ใน `retrieval_qrels.jsonl` ยังว่างอยู่ทั้งหมด — ต้องให้คน label
  ผ่าน `--dump` ก่อน metric ชั้น retrieval จึงเริ่มมีความหมาย
  (chunk id เป็น natural key `project_id:doc_type_code:chunk_no` จึงรอด reseed)

## ข้อจำกัดที่ควรรู้

- `no_hallucinated_legal_ref` จับ `มาตรา N` ได้แม่น แต่ `ข้อ N` ใช้ heuristic (ต้องมีคำว่า
  ระเบียบ/ประกาศ/ตาม/กฎหมาย นำหน้าในระยะ 40 ตัวอักษร) เพื่อไม่ให้หัวข้อลำดับในคำตอบ
  ("ข้อ 1. งบประมาณ") ถูกนับเป็นการอ้างกฎหมาย — ยอม false negative ดีกว่าฟ้องผิด
  เพราะ metric นี้ถูกใช้เป็น merge gate
- `targets.py` ห่อ `chatbot_service._execute_tool` ชั่วคราวเพื่อเก็บผลดิบของ tool
  (เพราะ `handle_message` คืนแค่ reply/tool_calls/citations) — **ห่อจากฝั่ง eval เท่านั้น
  ไม่แตะโค้ด production** และคืนของเดิมเสมอเมื่อจบ
- eval ยิง Gemini/Pinecone จริงและใช้ **shared dev Postgres ตัวเดียวกับทุกคน** —
  อย่ารัน full suite พร้อมกันหลายคน โดน 429 ให้ลด `--concurrency` (ค่า default 2)
