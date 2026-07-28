# Chatbot Architecture (issue #41)

> โค้ดจริงอยู่ที่ `src/services/chatbot.py` (orchestration) + `src/routers/chatbot.py` (endpoint)
> เอกสารนี้อธิบาย "ทำไม" และ "อย่างไร" ประกอบโค้ด — ถ้าโค้ดกับเอกสารขัดกัน ให้ยึดโค้ดเป็นหลักแล้วแก้เอกสารตาม

## โมเดล

**Gemini 2.5 Flash** ผ่าน Google AI Studio API key — SDK คือ `google-genai`

ตั้งค่าที่ `src/config.py`:
```python
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")   # ไม่มี default ที่ใช้งานได้จริง
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
```
เปลี่ยนรุ่นโมเดลได้ผ่าน env var `GEMINI_MODEL` โดยไม่ต้องแก้โค้ด — ถ้า `GEMINI_API_KEY` ว่าง `POST /chatbot` ตอบ 503 ทันที (ไม่พยายามเรียก API)

## ขอบเขตที่ใช้ / ไม่ใช้ RAG

**คำถามส่วนใหญ่ไม่ใช้ RAG** — คำถามที่ chatbot ต้องตอบเกือบทั้งหมด (ดู `legal_linkage_plan.md` §5.3) ตอบได้ตรงจาก structured query ของข้อมูลที่มีอยู่แล้วใน PostgreSQL ผ่าน tool 5 ตัวด้านล่าง ซึ่งดีกว่าการค้นแบบ semantic ทุกด้าน:

- **แม่นกว่า** — ไม่มีโอกาส "ดึง chunk ผิด" หรือ LLM เดามาตรากฎหมายเอง (มี guardrail บังคับห้ามเดาด้วย — ดูหัวข้อ system prompt ด้านล่าง)
- **ตรวจสอบย้อนกลับได้** — คำตอบทุกอันสืบไปหา SQL query จริงได้เสมอ (ผ่าน `tool_calls` ที่ response คืนกลับมาด้วย)

**สิ่งที่ structured query ตอบไม่ได้** คือคำถามที่คำตอบอยู่ใน "เนื้อความ" ของเอกสารซึ่งไม่เคยถูก normalize ลงคอลัมน์ใด เช่น "บรรทัดที่ 7 ของตาราง BOQ ใน ปร.4 ราคาต่อหน่วยเท่าไร" — `summary_text` เป็นสรุป 2–3 บรรทัดที่คนเขียน และ `extracted_json` เก็บเฉพาะ field ที่ risk engine ใช้ ตรงนี้จึงเพิ่มชั้น RAG เข้ามา **เฉพาะกรณีนี้กรณีเดียว** (แผนเต็ม: `rag_pinecone_plan.md`)

> **สถานะปัจจุบัน: ชั้น RAG ต่อเข้า chatbot แล้ว** — ingest (`scripts/ingest_documents.py`: OCR ปร.4/5/6 →
> chunk → Pinecone index `pr-documents`, `multilingual-e5-large` 1024 dim), retrieval
> (`src/services/retrieval.py`), tool ตัวที่ 6 (`search_document_text`), `citations` ใน response
> และ `GET /projects/{id}/documents/search` ทำครบแล้ว — เหลือ calibrate `RAG_MIN_SCORE` กับ chunk จริง
> (`python -m scripts.calibrate_rag`) และตั้ง env บน Vercel ดู `rag_pinecone_plan.md` §0.1
>
> tool ตัวที่ 6 เป็น **ทางเลือกสุดท้าย ไม่ใช่ทางหลัก**: คำถามเรื่อง risk score / เอกสารขาด-ไม่ขาด /
> ข้อกฎหมาย ต้องเดินผ่าน tool เดิมเสมอ (บังคับผ่าน `description` ของ tool ที่บอกด้วยว่า**เมื่อไรไม่ควรใช้**)
> และคำตอบที่อ้างเนื้อความเอกสารต้องมี citation (doc_type_code, doc_no, page_no) เสมอ — หลักการเดียวกับ
> ที่ห้ามอ้างมาตรากฎหมายนอก `legal_refs` เพราะผู้ใช้เป็นเจ้าหน้าที่ตรวจสอบที่ต้องเปิดเอกสารจริงไปยืนยันได้
>
> **feature flag:** `PINECONE_API_KEY` ว่าง = tool ตัวที่ 6 **ไม่ถูกประกาศให้ Gemini เลย**
> (`retrieval.rag_enabled()` → `chatbot._tools()`) chatbot ทำงานครบด้วย tool เดิม 5 ตัวเหมือนเดิม

**ตาราง `document_chunks`**: คอลัมน์ `embedding` ยังเป็น `NULL` ทั้งหมดและตั้งใจให้เป็นแบบนั้น — เวกเตอร์อยู่ที่ Pinecone และสร้างโดย Pinecone (integrated inference) ตารางนี้เก็บแค่ "สำเนาข้อความ" ไว้ debug และเผื่อย้ายไป pgvector วันที่ขึ้น infra ในประเทศ

## Tool-calling orchestration

แทนที่จะให้ LLM เขียน SQL หรือแตะ database เอง — เราสร้าง **tool 6 ตัว** ที่แต่ละตัว "ห่อ" service function ที่มีอยู่แล้วในระบบ (ตัวเดียวกับที่ router ปกติเรียก):

| Tool | เรียก service function | ใช้ตอบคำถามประเภท |
| :--- | :--- | :--- |
| `list_projects` | `services/projects.py::list_projects_view` | ค้นหาโครงการโดยยังไม่รู้ project_id |
| `get_project` | `services/projects.py::project_summary_view` | รายละเอียดโครงการ + risk score |
| `get_project_legal` | `services/legal.py::project_legal_view` | ความเสี่ยง + ข้อกฎหมายที่เกี่ยวข้อง |
| `get_project_documents` | `services/documents.py::project_documents_view` | เอกสารที่มี/ขาด + findings |
| `list_laws` | `services/legal.py::list_laws` | รายการกฎหมาย/มาตราทั้งหมด (reference) |
| `search_document_text` † | `services/retrieval.py::search_document_text` | เนื้อความในตัวเอกสาร ปร.4/5/6 ("ปร.5 ระบุอะไรบ้าง") |

† ประกาศเฉพาะเมื่อมี `PINECONE_API_KEY` — ตัวเดียวที่ข้อมูลไม่ได้มาจาก PostgreSQL ล้วน จึงเป็นตัวเดียวที่ต้องมี scope guard เพิ่มเป็น **สองชั้น** (pre-filter ที่ Pinecone + post-verify กับ PostgreSQL ดู `rag_pinecone_plan.md` §5) และเป็นตัวเดียวที่ทำให้ response มี `citations`

### ลำดับการทำงานต่อ 1 ข้อความ

1. Frontend ส่ง `{message, history}` มาที่ `POST /chatbot` (`history` คือบทสนทนาก่อนหน้าที่ **frontend ถือเอง** — backend ไม่เก็บ conversation state ใน DB)
2. `handle_message()` ส่ง `history + message` พร้อมรายชื่อ tool (function declarations) ไปให้ Gemini
3. Gemini ตอบกลับมาเป็นอย่างใดอย่างหนึ่ง:
   - ข้อความสุดท้าย (จบ loop) หรือ
   - "อยากเรียก tool ชื่อนี้ ด้วย argument นี้" (เช่น `get_project_legal(project_id="MOCK-CON-002")`)
4. ถ้าเป็น tool call — **backend เป็นคนรัน tool เอง** ผ่าน `_execute_tool(conn, user, name, args)`:
   - `conn`/`user` inject จากฝั่งเราเสมอ (ผูกกับ JWT ที่ authenticate ผ่าน `require_roles(...)` ไปแล้วตอนต้น request) — **Gemini ไม่มีทางส่ง `conn`/`user` มาเองได้**
   - เรียก service function จริง ซึ่งบังคับ `scope_subdistrict_ids(conn, user)` อยู่แล้วในตัว (ทุก service function เดิมของระบบ)
   - ถ้าโครงการนั้นอยู่นอกสิทธิ์ของ user → service raise `ForbiddenError`/`NotFoundError` → `_execute_tool` จับแล้วแปลงเป็น `{"error": "..."}` ส่งกลับให้ Gemini (ไม่ throw ออกไปนอก endpoint)
5. ผลลัพธ์ tool ถูกส่งกลับเข้า conversation แล้ววนกลับไปข้อ 2 — **สูงสุด 5 รอบ** (`MAX_TOOL_TURNS`) กัน loop ไม่รู้จบ (คุมค่าใช้จ่าย + latency)
6. Endpoint คืน `{"reply": "...", "tool_calls": [...], "citations": [...]}` — `tool_calls` ส่งกลับไปให้ frontend แสดงเป็น chip โปร่งใสใต้ข้อความ bot ด้วย (ผู้ใช้เห็นว่า bot ไปดึงข้อมูลจากไหนมาตอบ) ส่วน `citations` เป็น field ที่เพิ่มทีหลังแบบ additive (client เก่าเมินไปเฉยๆ) — มีค่าเฉพาะตอนที่เรียก `search_document_text` แต่ละรายการคือ `{project_id, doc_type_code, doc_no, page_no, chunk_no}` ที่ชี้ว่าเนื้อความมาจากเอกสารใบไหนหน้าไหน

### หัวใจของ guardrail: scope guard เป็น deterministic ไม่ใช่ prompt engineering

ต่อให้ prompt injection หรือ Gemini "พยายาม" ขอโครงการนอกตำบล ระบบก็ปฏิเสธได้เสมอ เพราะการเช็คสิทธิ์เกิดที่ **ชั้นโค้ด Python ปกติ** (`scope_subdistrict_ids` ใน service function เดิม) ไม่ได้ขึ้นกับว่า LLM จะทำตามกติกาที่บอกไว้ใน system prompt หรือเปล่า — ยืนยันแล้วด้วย curl จริงตอน verify PR: `auditor1` (ตำบลท่าช้าง) ถามโครงการ `MOCK-CON-002` (ตำบลโยนก) → Gemini เรียก tool ให้ตามที่ถูกขอ แต่ tool คืน error กลับมา บอทเลยตอบว่าไม่มีสิทธิ์เข้าถึง ไม่ใช่ข้อมูลจริง

### System prompt — กติกาหลัก

1. ตอบจากผลลัพธ์ tool เท่านั้น ห้ามเดา/แต่งข้อมูล
2. ถ้า `legal_refs` ว่าง ต้องใช้ `legal_ref_note` ที่ backend ส่งมาตรงๆ ("ยังไม่มีการเชื่อมโยงข้อกฎหมายในระบบ") ห้ามเดามาตรากฎหมายเอง
3. แยก `computable=0` ("ข้อมูลไม่พอประเมิน") ออกจาก `triggered=0` ("ไม่พบความเสี่ยง") ให้ชัดเจน ห้ามตีความปนกัน
4. ผลจาก `search_document_text` ให้ตอบโดยอ้างเฉพาะข้อความใน chunk ที่ได้รับ + ระบุ doc_type_code/doc_no/page_no ทุกครั้ง
5. `search_document_text` คืนผลว่าง = ตอบว่าไม่พบข้อความที่เกี่ยวข้อง **ห้าม**ถอยไปใช้ `summary_text` หรือความรู้ทั่วไปมาตอบแทน

(เลขข้อในโค้ดคือ 1–7 — ข้อ 4–5 ที่นี่ตรงกับข้อ 6–7 ใน `SYSTEM_PROMPT`)

กติกาข้อ 2–3 มาจาก guardrail ที่ `docs/legal_linkage_plan.md` §5.2 ออกแบบไว้แล้วสำหรับ human-facing UI — เอามาบังคับ LLM ด้วยเหตุผลเดียวกัน ส่วนข้อ 4–5 เป็นหลักเดียวกันในบริบทเอกสาร: OCR ภาษาไทยอ่านตัวเลขผิดได้ คำตอบจึงต้องชี้กลับไปที่หน้าเอกสารจริงให้คนตรวจซ้ำได้เสมอ

⚠️ prompt เป็นแค่ชั้นคุณภาพคำตอบ **ไม่ใช่ชั้นความปลอดภัย** — การกันข้อมูลข้ามตำบลของ `search_document_text` อยู่ที่ post-verify ใน `retrieval.py` ซึ่งเป็นโค้ด Python + SQL ล้วน ไม่ขึ้นกับว่า LLM หรือ Pinecone จะทำตัวดีหรือไม่

## ขอบเขตปัจจุบัน / follow-up

- role ที่ใช้ได้: `admin`, `project_auditor`, `risk_analyst` (mirror `CHATBOT_ROLES` ฝั่ง frontend) — chatbot สำหรับ `public_user` (guardrail จำกัดเฉพาะข้อมูล open-data) ยังไม่ทำ
- ไม่มี conversation history เก็บใน DB — ถ้าต้องการ audit trail การถาม-ตอบ เป็นงาน follow-up แยก
- ไม่ streaming — รอ Gemini ตอบครบก่อนส่งกลับ frontend
