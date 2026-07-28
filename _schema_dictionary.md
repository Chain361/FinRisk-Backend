# Format กลาง — ข้อมูลโครงการจัดซื้อจัดจ้าง (Data Dictionary)

หนึ่งแถวต่อหนึ่งโครงการ ชื่อคอลัมน์อังกฤษ snake_case ใช้ร่วมกันทั้ง 3 ตำบล ครอบคลุมปีงบ 2566–2568 (98 โครงการ) วันที่ทั้งหมดแปลงเป็น ISO ค.ศ. (YYYY-MM-DD) ตัวเลขไม่มี comma

## ไฟล์

- `ตำบลท่าช้าง/projects_thachang_standard.csv` (29 โครงการ)
- `ตำบลปิงโค้ง/projects_pingkhong_standard.csv` (30 โครงการ)
- `ตำบลโยนก/projects_yonok_standard.csv` (39 โครงการ)
- `projects_ALL_master.csv` — รวม 3 ตำบล (สำหรับคำนวณ risk / dashboard)

## คอลัมน์

| คอลัมน์ | ไทย | ที่มา / หมายเหตุ |
|---|---|---|
| subdistrict, district, province | ตำบล อำเภอ จังหวัด | ปิงโค้ง: อำเภอ-จังหวัดเติมจากที่ตั้งตำบล (ไม่มีในต้นฉบับ) |
| budget_year | ปีงบประมาณ (พ.ศ.) | 2566–2568 |
| project_id | เลขที่โครงการ e-GP | key หลัก |
| project_name | ชื่อโครงการ | |
| project_type | ประเภทโครงการ | จ้างก่อสร้าง / ซื้อ / จ้างทำของฯ |
| dept_name, dept_sub_name | หน่วยงาน | ปิงโค้ง: ว่าง (ไม่มีในต้นฉบับ) |
| purchase_method, purchase_method_group | วิธีการจัดหา | e-bidding / คัดเลือก / เฉพาะเจาะจง |
| announce_date, transaction_date | วันประกาศ / วันทำรายการ | ISO ค.ศ.; "-" ในต้นฉบับ = ว่าง |
| budget_amount | งบประมาณโครงการ (project_money) | บาท |
| reference_price | ราคากลาง (price_build) | บาท |
| contract_value | วงเงินสัญญารวม (sum_price_agree) | บาท |
| price_ratio | สัญญา÷ราคากลาง (4 ตำแหน่ง) | คำนวณใหม่ทุกแถวให้สูตรเดียวกัน; ว่างถ้าค่าใดเป็น 0 |
| project_status, contract_status | สถานะ | ปิงโค้ง: ไม่มี contract_status |
| contract_no, contract_date, contract_finish_date | ข้อมูลสัญญา | ปิงโค้ง: ว่าง |
| contract_duration_days | ระยะเวลาสัญญา (วัน) | คำนวณจากวันที่สัญญา |
| winner_name, winner_tin | ผู้รับจ้าง + เลขผู้เสียภาษี | ปิงโค้ง: ไม่มี TIN |

## ข้อควรระวังต่อการวิเคราะห์ความเสี่ยง (ข้อมูลโครงการ)

- **ไฟล์ต้นฉบับ 2 ไฟล์ถูกตัดท้าย** (โครงการท่าช้าง66.csv, โครงการโยนก66.csv) — แถวสุดท้ายของแต่ละไฟล์ข้อมูลท้ายแถวหายไป (flag ไว้ใน data_quality_note; ตำบล/ปี เติมจากบริบทไฟล์แล้ว)
- **ปิงโค้ง** เป็นข้อมูลสรุป: ไม่มีหน่วยงาน วันที่ พิกัด TIN และเลขสัญญา → ตัวชี้วัดที่ใช้วันที่/พิกัด (เช่น จัดจ้างท้ายปีงบ, ความหนาแน่นพื้นที่) คำนวณได้เฉพาะท่าช้างกับโยนก
- **fraud_risk_flag ว่าง ≠ FALSE** — ท่าช้าง/โยนกยังไม่เคยถูก label
- ปิงโค้ง 68039298502: งบประมาณและวงเงินสัญญา = 0 ตามต้นฉบับ (ถูก flag "ราคากลางสูง/ต่ำกว่างบประมาณ" อยู่แล้ว)
- winner_tin บางแถวถูกปกปิดบางส่วน (มี xxxx) — ใช้ winner_name ประกอบเมื่อจับคู่ผู้รับจ้างซ้ำ
- พิกัดโยนกหลายโครงการเป็นจุดเดียวกัน (พิกัดตำบล ไม่ใช่ที่ตั้งจริงของงาน) — ระวังเมื่อวิเคราะห์เชิงพื้นที่

---

# Format กลาง — งบการเงินตำบล (Data Dictionary)

รูปแบบ **long / tidy** หนึ่งแถวต่อหนึ่งรายการต่อหนึ่งปี ใช้ร่วมกันได้ทั้ง 3 ตำบล และรองรับการเพิ่มปี/ตำบล/ประเภทงบใหม่ในอนาคตโดยไม่ต้องแก้โครงสร้าง

## คอลัมน์

| # | คอลัมน์ | ความหมาย | ตัวอย่าง |
|---|---------|----------|----------|
| 1 | ตำบล | ชื่อตำบล (ใช้ group/filter) | ท่าช้าง, ปิงโค้ง, โยนก |
| 2 | เทศบาล | ชื่อเต็มหน่วยงาน | เทศบาลตำบลท่าช้าง |
| 3 | ปีงบประมาณ | ปี พ.ศ. | 2566, 2567, 2568 |
| 4 | ประเภทงบ | ประเภทรายงาน | งบแสดงฐานะการเงิน / งบแสดงผลการดำเนินงาน / งบประมาณตามหมวด / สินทรัพย์ถาวรเพิ่มระหว่างปี / ตัวชี้วัดความเสี่ยง |
| 5 | หมวดหมู่ | กลุ่มบัญชี | สินทรัพย์หมุนเวียน, รายได้, ค่าใช้จ่าย ... |
| 6 | รายการบัญชี | ชื่อรายการ | เงินสดและรายการเทียบเท่าเงินสด |
| 7 | หมายเหตุ | เลขหมายเหตุประกอบงบ (ถ้ามี) | 4 |
| 8 | มูลค่า | ตัวเลข (numeric ล้วน ไม่มี comma) | 292678726.28 |
| 9 | หน่วย | บาท / ร้อยละ / เท่า | บาท |
| 10 | ระดับรายละเอียด | line_item / subtotal / total / indicator / reference | line_item |
| 11 | หมายเหตุคุณภาพข้อมูล | คำเตือน/ที่มา/การแก้ไข | ข้อมูลยอดรวม (ไม่มีรายการย่อย) |
| 12 | ไฟล์ต้นฉบับ | ไฟล์ที่ดึงข้อมูลมา | financial_report_thachang_2568.csv |

## วิธีเพิ่มข้อมูลใหม่ในอนาคต
เพิ่มเป็นแถวใหม่ต่อท้ายไฟล์ ตามคอลัมน์เดิม — ไม่ต้องสร้างไฟล์แยกต่อปี ระบบ filter ด้วย `ปีงบประมาณ` + `ตำบล` ได้ทันที ตำบลใหม่ = ใส่ชื่อในคอลัมน์ `ตำบล`; ประเภทงบใหม่ = ใส่ค่าใหม่ในคอลัมน์ `ประเภทงบ`

## ข้อควรระวังต่อการวิเคราะห์ความเสี่ยง
- **ปิงโค้ง** เป็น *ยอดรวม (subtotal)* ไม่มีรายการย่อยของสินทรัพย์/หนี้สิน (ดูคอลัมน์ระดับรายละเอียด) — เทียบรายรายการย่อยกับอีก 2 ตำบลไม่ได้ แต่เทียบระดับ subtotal/total ได้
- **ปิงโค้ง** มี `ประเภทงบ = งบประมาณตามหมวด` และ `สินทรัพย์ถาวรเพิ่มระหว่างปี` ที่อีก 2 ตำบลยังไม่มี
- แถวที่ `หน่วย ≠ บาท` (ร้อยละ/เท่า) เป็น indicator ที่คำนวณไว้แล้ว — อย่านำไปรวมยอดกับแถวบาท
- total_assets ปิงโค้ง 2567 ต้นฉบับพิมพ์ผิด ได้แก้เป็นผลรวมจริงแล้ว (บันทึกในหมายเหตุคุณภาพข้อมูล)
- ตรวจสอบแล้ว: สมการบัญชี 21/21 ผ่าน (สินทรัพย์=หนี้สิน+ทุน, รายได้−ค่าใช้จ่าย=สุทธิ)

## ไฟล์ที่ได้
- `financial_report_thachang_standard.csv` (2567–2568)
- `financial_report_pingkhong_standard.csv` (2566–2568)
- `financial_report_yonok_standard.csv` (2567–2568)
- `financial_report_ALL_master.csv` — รวมทั้ง 3 ตำบลในไฟล์เดียว (สำหรับวิเคราะห์เปรียบเทียบ)

---

# ชั้นกฎหมาย + เอกสาร (Legal Linkage — docs/legal_linkage_plan.md)

## ไฟล์ curate (input ของ seed)

| ไฟล์ | ตารางปลายทาง | หมายเหตุ |
| :---- | :---- | :---- |
| `legal_refs/laws.csv` | `laws` | 6 ฉบับ; `law_code` เป็น key อ้างอิงข้ามไฟล์ |
| `legal_refs/law_sections.csv` | `law_sections` | 9 มาตรา/ข้อ; `section_summary` เป็นสรุปเพื่อเดโม ⚠️ ให้ฝ่ายกฎหมายตรวจทานตัวบท/เลขมาตราก่อน production; `section_text` ว่างใน v1 |
| `legal_refs/factor_legal_map.csv` | `factor_legal_map` | อ้าง (law_code, section_no); v1 ครอบ D1, L1, L2, L3 — A1 ไม่มีกฎหมาย (ตามไฟล์ case), A2/A3 เป็น phase ถัดไป |
| `mock_documents/document_types.csv` | `document_types` | PR4/PR5/PR6; `provides_json` ใช้ตอบ "เอกสารใดระบุ X"; `required_for_project_type` ขับ L1 |
| `mock_documents/project_documents.csv` | `project_documents` (+`document_chunks` อัตโนมัติสำหรับ status=present) | MOCK-CON-001 ครบ 3 ใบ (present), MOCK-CON-002 ขาด 3 ใบ (**seed แถว status='missing' explicit** — ไม่มีแถว ≠ ขาด); คอลัมน์ `file_path` ชี้ไฟล์ใน `raw_documents/` ให้ชั้น RAG ใช้ (seed อ่านเข้า `project_documents.file_path` ตรงๆ — **ไม่มีโค้ดอื่นที่ UPDATE คอลัมน์นี้**) |
| `raw_documents/*.png` | `document_chunks` (ผ่าน `scripts/ingest_documents.py`) + Pinecone | ข้อความเต็มของเอกสาร ปร.4/5/6 — ingest **ลบ chunk เดิมของ doc_id นั้นแล้วเขียนทับ** (ของเดิมคือ `summary_text` ที่ seed ใส่ไว้เป็น chunk_no=1) `embedding` ยังเป็น NULL เสมอ เวกเตอร์อยู่ที่ Pinecone; ingest **ไม่แตะ `project_documents`** จึงไม่กระทบ L1/L3 — ดู `docs/rag_pinecone_plan.md` §4.4 ⚠️ **`src/services/retrieval.py` ไม่อ่านตารางนี้เลย** (ข้อความมาจาก Pinecone) เพราะ `seed_database.py --force` ล้างตารางนี้ทุก deploy — ตารางนี้มีไว้ debug/diff และเผื่อย้ายไป pgvector เท่านั้น |
| `mock_documents/document_findings.csv` | `document_findings` | `finding_key` (FND1–3) ใช้ join ภายใน CSV เท่านั้น ไม่ลง DB |
| `mock_documents/finding_legal_map.csv` | `finding_legal_map` | อ้าง finding_key + (law_code, section_no) |

## คอลัมน์ใหม่ใน `risk_factors`

| คอลัมน์ | ความหมาย |
| :---- | :---- |
| `applies_to_project_type` | NULL = ทุกประเภท; `'จ้างก่อสร้าง'` = engine ประเมินเฉพาะประเภทนี้ (ประเภทอื่นและ `project_type IS NULL` ไม่เขียนแถวผล — จงใจ) |
| `action_suggestion` | ข้อเสนอแนะรายข้อบ่งชี้จากไฟล์ case (A1, D1, L1–L3) |

## ข้อควรระวัง

- โครงการ mock: `project_id LIKE 'MOCK-%'`, `source_file='mock_legal_linkage.csv'`, `data_quality_note='MOCK สำหรับเดโม legal linkage'` — กรองออกด้วย query เดียว; frontend ควรแสดง badge MOCK
- engine **exclude MOCK จากการนับกลุ่ม A3** (กัน mock ที่ราคากลางชนงบพลิกผล A3 ของโครงการจริง)
- `document_findings.source` รับ 'ocr'/'llm' ใน CHECK แล้ว แต่ v1 seed เฉพาะ 'mock' — ก่อนใช้ OCR/LLM จริงต้องเพิ่ม review gate
