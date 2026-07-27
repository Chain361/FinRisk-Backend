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

## ทำไมไม่ใช้ RAG (vector embedding)

RAG แบบคลาสสิก (chunk เอกสาร → embed → semantic search → ยัด context ให้ LLM) **ไม่จำเป็นสำหรับ v1** เพราะคำถามที่ chatbot ต้องตอบทั้งหมด (ดู `legal_linkage_plan.md` §5.3) ตอบได้ตรงจาก structured query ของข้อมูลที่มีอยู่แล้วใน PostgreSQL — ไม่มีเอกสารยาวที่ต้อง chunk/ค้นหาแบบ fuzzy

ข้อดีของทางนี้เทียบกับ RAG:
- **แม่นกว่า** — ไม่มีโอกาส "ดึง chunk ผิด" หรือ LLM เดามาตรากฎหมายเอง (มี guardrail บังคับห้ามเดาด้วย — ดูหัวข้อ system prompt ด้านล่าง)
- **ไม่ต้องเพิ่ม infra** — ไม่ต้องมี vector DB, ไม่ต้องรัน embedding pipeline
- **ตรวจสอบย้อนกลับได้** — คำตอบทุกอันสืบไปหา SQL query จริงได้เสมอ (ผ่าน `tool_calls` ที่ response คืนกลับมาด้วย)

**เผื่อไว้สำหรับอนาคต**: ตาราง `document_chunks` (มีคอลัมน์ `embedding`) สร้างไว้แล้วใน schema แต่ยังไม่ใช้งาน (`embedding IS NULL` ทั้งหมด) — ถ้าวันหน้ามีเอกสารเต็มฉบับยาวๆ ที่ query ตรงไม่ได้ (เช่น ตัวบทกฎหมายทั้งฉบับ) ค่อยทำ embedding จริงตอนนั้น

## Tool-calling orchestration

แทนที่จะให้ LLM เขียน SQL หรือแตะ database เอง — เราสร้าง **tool 5 ตัว** ที่แต่ละตัว "ห่อ" service function ที่มีอยู่แล้วในระบบ (ตัวเดียวกับที่ router ปกติเรียก):

| Tool | เรียก service function | ใช้ตอบคำถามประเภท |
| :--- | :--- | :--- |
| `list_projects` | `services/projects.py::list_projects_view` | ค้นหาโครงการโดยยังไม่รู้ project_id |
| `get_project` | `services/projects.py::project_summary_view` | รายละเอียดโครงการ + risk score |
| `get_project_legal` | `services/legal.py::project_legal_view` | ความเสี่ยง + ข้อกฎหมายที่เกี่ยวข้อง |
| `get_project_documents` | `services/documents.py::project_documents_view` | เอกสารที่มี/ขาด + findings |
| `list_laws` | `services/legal.py::list_laws` | รายการกฎหมาย/มาตราทั้งหมด (reference) |

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
6. Endpoint คืน `{"reply": "...", "tool_calls": [...]}` — `tool_calls` ส่งกลับไปให้ frontend แสดงเป็น chip โปร่งใสใต้ข้อความ bot ด้วย (ผู้ใช้เห็นว่า bot ไปดึงข้อมูลจากไหนมาตอบ)

### หัวใจของ guardrail: scope guard เป็น deterministic ไม่ใช่ prompt engineering

ต่อให้ prompt injection หรือ Gemini "พยายาม" ขอโครงการนอกตำบล ระบบก็ปฏิเสธได้เสมอ เพราะการเช็คสิทธิ์เกิดที่ **ชั้นโค้ด Python ปกติ** (`scope_subdistrict_ids` ใน service function เดิม) ไม่ได้ขึ้นกับว่า LLM จะทำตามกติกาที่บอกไว้ใน system prompt หรือเปล่า — ยืนยันแล้วด้วย curl จริงตอน verify PR: `auditor1` (ตำบลท่าช้าง) ถามโครงการ `MOCK-CON-002` (ตำบลโยนก) → Gemini เรียก tool ให้ตามที่ถูกขอ แต่ tool คืน error กลับมา บอทเลยตอบว่าไม่มีสิทธิ์เข้าถึง ไม่ใช่ข้อมูลจริง

### System prompt — กติกา 3 ข้อ

1. ตอบจากผลลัพธ์ tool เท่านั้น ห้ามเดา/แต่งข้อมูล
2. ถ้า `legal_refs` ว่าง ต้องใช้ `legal_ref_note` ที่ backend ส่งมาตรงๆ ("ยังไม่มีการเชื่อมโยงข้อกฎหมายในระบบ") ห้ามเดามาตรากฎหมายเอง
3. แยก `computable=0` ("ข้อมูลไม่พอประเมิน") ออกจาก `triggered=0` ("ไม่พบความเสี่ยง") ให้ชัดเจน ห้ามตีความปนกัน

กติกาข้อ 2–3 มาจาก guardrail ที่ `docs/legal_linkage_plan.md` §5.2 ออกแบบไว้แล้วสำหรับ human-facing UI — เอามาบังคับ LLM ด้วยเหตุผลเดียวกัน

## ขอบเขตปัจจุบัน / follow-up

- role ที่ใช้ได้: `admin`, `project_auditor`, `risk_analyst` (mirror `CHATBOT_ROLES` ฝั่ง frontend) — chatbot สำหรับ `public_user` (guardrail จำกัดเฉพาะข้อมูล open-data) ยังไม่ทำ
- ไม่มี conversation history เก็บใน DB — ถ้าต้องการ audit trail การถาม-ตอบ เป็นงาน follow-up แยก
- ไม่ streaming — รอ Gemini ตอบครบก่อนส่งกลับ frontend
