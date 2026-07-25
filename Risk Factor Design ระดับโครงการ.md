# Risk Factor Design — Project Level (ระดับโครงการ)

เอกสารนี้ระบุรายละเอียดของ Risk Factors สำหรับใช้ใน Risk Engine ระดับโครงการ (Scope: `project`) เพื่อให้ AI และระบบตรวจสอบสามารถดึงไปใช้งานหรือนำไปเพาะเมล็ดพันธุ์ (Seed) ลงฐานข้อมูล `risk_factors` ได้โดยตรง

---

## 1. Risk Factors Definition

### A1: ส่วนลดผิดปกติ (Abnormal Discount)
* **Code:** `A1`
* **Scope:** `project`
* **Name (TH):** ส่วนลดผิดปกติ
* **Name (EN):** Abnormal Discount
* **Severity:** `medium` (ธงเหลือง)
* **Description:** ส่วนลดจากราคากลางต่ำกว่าเกณฑ์ปกติมากเกินไป เสี่ยงต่อการทิ้งงานหรือปรับลดสเปก/คุณภาพงานในภายหลัง (เช่น ตัวอย่างกรณีโครงการก่อสร้างถนนที่เสนอส่วนลดสูงถึง 20.5%)
* **Data Requirements:** ข้อมูลโครงการจัดซื้อจัดจ้าง (`projects`) คอลัมน์ `reference_price` (ราคากลาง) และ `contract_value` (วงเงินสัญญา)

#### Formula
$$\text{Discount Rate} = \frac{\text{reference\_price} - \text{contract\_value}}{\text{reference\_price}} > 0.15 \ (15\%)$$

#### Database Configuration (JSON)
```json
{
  "factor_code": "A1",
  "scope": "project",
  "name_th": "ส่วนลดผิดปกติ",
  "severity": "medium",
  "params_json": {
    "discount_pct_min": 0.15
  }
}
```

#### Evaluation Criteria
* **Trigger:** อัตราส่วนลดที่เสนอต่ำกว่าราคากลาง เกินกว่า $15\%$ (หรือ `price_ratio < 0.85`)

---

### A2: ส่วนลดน้อยผิดปกติ (Abnormally Low Discount)
* **Code:** `A2`
* **Scope:** `project`
* **Name (TH):** ส่วนลดน้อยผิดปกติ
* **Name (EN):** Abnormally Low Discount
* **Severity:** `high` (ธงแดง)
* **Description:** ชนะการประกวดราคาด้วยราคาที่ใกล้เคียงกับราคากลางมาก (ส่วนลดน้อยมากหรือไม่มีเลย) สะท้อนถึงการไม่มีการแข่งขันที่แท้จริง เอื้อประโยชน์ต่อผู้รับเหมาบางราย หรือตั้งราคากลางมารองรับราคาที่ตกลงกันไว้ล่วงหน้า
* **Data Requirements:** ข้อมูลโครงการจัดซื้อจัดจ้าง (`projects`) คอลัมน์ `reference_price` (ราคากลาง) และ `contract_value` (วงเงินสัญญา)

#### Formula
$$\text{Contract to Reference Price Ratio} = \frac{\text{contract\_value}}{\text{reference\_price}} \ge 0.99 \text{ and } \le 1.00$$

#### Database Configuration (JSON)
```json
{
  "factor_code": "A2",
  "scope": "project",
  "name_th": "ส่วนลดน้อยผิดปกติ",
  "severity": "high",
  "params_json": {
    "ratio_min": 0.99,
    "ratio_max": 1.00
  }
}
```

#### Evaluation Criteria
* **Trigger:** วงเงินสัญญาคิดเป็น $99\% - 100\%$ ของราคากลาง (หรือ `price_ratio` อยู่ในช่วง `[0.99, 1.00]`)

---

### A3: ราคากลางชนงบพอดี (Reference Price Matching Budget)
* **Code:** `A3`
* **Scope:** `project`
* **Name (TH):** ราคากลางชนงบพอดี
* **Name (EN):** Reference Price Matching Budget
* **Severity:** `medium`
* **Description:** ราคากลางตั้งขึ้นมาเท่ากับหรือใกล้เคียงกับวงเงินงบประมาณอย่างน่าสงสัย ซ้ำๆ กันในหน่วยงานเดียวกัน แสดงว่าเป็นการดึงตัวเลขงบประมาณมาตั้งเป็นราคากลาง แทนที่จะคำนวณจากราคาต้นทุนจริง
* **Data Requirements:** ข้อมูลโครงการจัดซื้อจัดจ้าง (`projects`) คอลัมน์ `reference_price` (ราคากลาง), `budget_amount` (วงเงินงบประมาณ) และ `dept_name` (ชื่อหน่วยงานย่อย/ฝ่าย) *หมายเหตุ: สำหรับ อบต.ปิงโค้ง ที่ไม่มีข้อมูลฝ่าย จะตรวจสอบสะสมระดับ อบต. แทน*

#### Formula
$$\text{Price Gap Ratio} = \frac{|\text{reference\_price} - \text{budget\_amount}|}{\text{budget\_amount}} < 0.005 \ (0.5\%)$$
และเกิดเหตุการณ์นี้ซ้ำกันในหน่วยงานเดียวกัน $\ge 2$ ครั้ง

#### Database Configuration (JSON)
```json
{
  "factor_code": "A3",
  "scope": "project",
  "name_th": "ราคากลางชนงบพอดี",
  "severity": "medium",
  "params_json": {
    "gap_pct_max": 0.005,
    "min_occurrences": 2
  }
}
```

#### Evaluation Criteria
* **Trigger:** ส่วนต่างระหว่างราคากลางและวงเงินงบประมาณน้อยกว่า $0.5\%$ และพบซ้ำอย่างน้อย $2$ ครั้งขึ้นไปในหน่วยงานเดียวกัน

---

### D1: วงเงินหวุดหวิดใต้เกณฑ์เฉพาะเจาะจง (Project Value Just Below Specific Selection Threshold)
* **Code:** `D1` (หมวดหมู่ Splitting ซื้อจ้างแยกโครงการ)
* **Scope:** `project`
* **Name (TH):** วงเงินหวุดหวิดใต้เกณฑ์เฉพาะเจาะจง
* **Name (EN):** Project Value Just Below Specific Selection Threshold
* **Severity:** `medium`
* **Description:** การกระจุกตัวของโครงการจัดซื้อจัดจ้างด้วยวิธีเฉพาะเจาะจง (ไม่ต้องเข้าประกวดราคา e-bidding) ที่มีมูลค่างานอยู่ในช่วง 450,000 ถึง 499,999 บาท (หวุดหวิดเกณฑ์จำกัด 500,000 บาท) เพื่อประเมินพฤติกรรมการแบ่งซื้อแบ่งจ้างเพื่อหลีกเลี่ยงกระบวนการประกวดราคาแบบแข่งขันเสรี
* **Data Requirements:** ข้อมูลโครงการจัดซื้อจัดจ้าง (`projects`) คอลัมน์ `contract_value` (หรือ `budget_amount`) และ `purchase_method` (วิธีการจัดซื้อจัดจ้าง)

#### Formula
$$\text{Project Value} \in [450,000, 499,999] \text{ บาท และใช้ purchase\_method = 'เฉพาะเจาะจง'}$$

#### Database Configuration (JSON)
```json
{
  "factor_code": "D1",
  "scope": "project",
  "name_th": "วงเงินหวุดหวิดใต้เกณฑ์เฉพาะเจาะจง",
  "severity": "medium",
  "params_json": {
    "band_low": 450000.0,
    "band_high": 499999.0
  }
}
```

#### Evaluation Criteria
* **Trigger:** มีโครงการวิธีเฉพาะเจาะจงที่มีมูลค่าอยู่ในช่วง $450,000 - 499,999$ บาท ในจำนวนที่หนาแน่นผิดปกติ (สามารถตรวจสอบความผิดปกติเพิ่มได้จากรูป Histogram)

---

### F1: โครงการกระจุกตัวช่วงสิ้นปีงบประมาณ (Fiscal Year-End Concentration)
* **Code:** `F1` (หมวดหมู่ Timing)
* **Scope:** `project`
* **Name (TH):** โครงการกระจุกตัวช่วงสิ้นปีงบประมาณ
* **Name (EN):** Fiscal Year-End Concentration
* **Severity:** `medium`
* **Description:** มีการกระจุกตัวของโครงการที่ประกาศจัดซื้อจัดจ้างหรือทำสัญญาในช่วงสองเดือนสุดท้ายของปีงบประมาณ (สิงหาคม - กันยายน) เพื่อรีบเร่งใช้เงินงบประมาณที่ค้างอยู่ ชี้ถึงความเสี่ยงในการเร่งกระบวนการตรวจรับหรือประเมินงานโดยขาดความรอบคอบ
* **Data Requirements:** ข้อมูลโครงการจัดซื้อจัดจ้าง (`projects`) คอลัมน์ `announce_date` หรือ `transaction_date` *หมายเหตุ: สำหรับ อบต.ปิงโค้ง ข้อมูลนี้ไม่สามารถวิเคราะห์ได้เนื่องจากไม่มีข้อมูลวันที่บันทึก*

#### Formula
$$\text{Month of Project} \in [8, 9] \ (สิงหาคม \text{ หรือ } กันยายน)$$

#### Database Configuration (JSON)
```json
{
  "factor_code": "F1",
  "scope": "project",
  "name_th": "โครงการกระจุกตัวช่วงสิ้นปีงบประมาณ",
  "severity": "medium",
  "params_json": {
    "months": [8, 9]
  }
}
```

#### Evaluation Criteria
* **Trigger:** วันประกาศหรือวันทำธุรกรรมตรงกับเดือน $8$ (สิงหาคม) หรือเดือน $9$ (กันยายน) ของปีงบประมาณนั้นๆ
---

### L1: ขาดเอกสารราคากลาง ปร.4/ปร.5/ปร.6 (Missing Reference Price Documents)
* **Code:** `L1` (หมวดหมู่ Legal/Compliance — จาก docs/legal_linkage_plan.md)
* **Scope:** `project` — **เฉพาะ `project_type = 'จ้างก่อสร้าง'`** (gate ด้วย `risk_factors.applies_to_project_type`; ประเภทอื่นไม่เขียนแถวผล)
* **Severity:** `medium` | **Weight:** 1 (เท่ากับ factor อื่นไปก่อน)
* **Description:** งานก่อสร้างขาดเอกสารประกอบการกำหนดราคากลางที่ต้องมีตามประกาศคณะกรรมการราคากลางฯ ข้อ 20
* **Data Requirements:** `project_documents` × `document_types.required_for_project_type`

#### Evaluation Criteria
* **Computable = 1** ⇔ ทุก required doc_type มีแถว explicit ใน `project_documents` (status ใดก็ได้)
* **ไม่มีแถวเลย = ไม่เคยเก็บข้อมูลเอกสาร → computable = 0** (ห้ามตีความว่า "ขาดเอกสาร" — หลักเดียวกับ `fraud_risk_flag` ว่าง ≠ FALSE) → โครงการก่อสร้างจริงทั้งหมดเข้าเคสนี้ risk score เดิมไม่เพี้ยน
* **Trigger:** computable และมี required doc ≥ 1 แถวที่ `status='missing'`
* **Likelihood (5×5):** ตามจำนวนเอกสารที่ขาด — 1 ใบ → 3, 2 ใบ → 4, ≥3 ใบ → 5; impact = 3
* **Legal refs (factor_legal_map):** ประกาศคณะกรรมการราคากลางฯ ข้อ 20

---

### L2: พื้นที่ดำเนินการนอกกรอบอำนาจหน้าที่ (Out-of-Jurisdiction Project Area)
* **Code:** `L2` (หมวดหมู่ Legal/Compliance)
* **Scope:** `project` — เฉพาะ `จ้างก่อสร้าง` (gate เดียวกับ L1)
* **Severity:** `high` | **Weight:** 1
* **Description:** โครงการก่อสร้างในพื้นที่นอกเขตอำนาจหน้าที่ของเทศบาล เช่น เขตป่าสงวนแห่งชาติ โดยไม่ปรากฏการอนุญาต
* **Data Requirements:** `project_compliance.in_jurisdiction` (0/1/NULL)

#### Evaluation Criteria
* **Computable = 1** ⇔ `in_jurisdiction IS NOT NULL`; **Trigger** ⇔ `in_jurisdiction = 0`
* **Likelihood:** 4 เมื่อ trigger; impact = 4
* **Legal refs:** พรบ.วินัยการเงินการคลัง 2561 ม.65 + พรบ.ป่าสงวนแห่งชาติ ม.14 (⚠️ ฝ่ายกฎหมายยืนยันเลขมาตรา)

---

### L3: เนื้อหาเอกสารราคากลางมีพิรุธ (Suspicious Reference Price Document Content)
* **Code:** `L3` (หมวดหมู่ Legal/Compliance — optional ตามแผน แต่ implement แล้ว)
* **Scope:** `project` — เฉพาะ `จ้างก่อสร้าง`
* **Severity:** `medium` | **Weight:** 1
* **Description:** เอกสาร ปร.4/5/6 มีข้อสังเกต เช่น ปริมาณงานเกินแบบ, Factor F เกินเกณฑ์, ราคาประกาศไม่ตรงผลคำนวณ — นับจาก `document_findings`
* **Data Requirements:** `project_documents` (status='present') + `document_findings`

#### Evaluation Criteria
* **Computable = 1** ⇔ มีเอกสาร `status='present'` ≥ 1; **Trigger** ⇔ `document_findings` ≥ 1
* **Likelihood:** 1–2 findings → 3, ≥3 → 4; impact = 3
* **⚠️ Review gate:** v1 นับเฉพาะ findings `source='mock'/'manual'` — เมื่อเริ่มเขียนจาก OCR/LLM จริง ต้องเพิ่มคอลัมน์ review_status และนับเฉพาะที่ผู้ตรวจสอบ confirm (Mission §9) เพื่อไม่ให้ AI ขยับ risk score โดยไม่ผ่านคน
* **Legal refs:** พรบ.วินัยการเงินการคลัง 2561 ม.6 (ผ่าน factor_legal_map) + รายมาตราของแต่ละ finding (ผ่าน finding_legal_map)
