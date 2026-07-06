# Risk Factor Design — Annual Budget Level (ระดับงบรายปี)

เอกสารนี้ระบุรายละเอียดของ Risk Factors สำหรับใช้ใน Risk Engine ระดับงบรายปี/ตำบล (Scope: `annual`) เพื่อให้ AI และระบบตรวจสอบสามารถดึงไปใช้งานหรือนำไปเพาะเมล็ดพันธุ์ (Seed) ลงฐานข้อมูล `risk_factors` ได้โดยตรง

---

## 1. Risk Factors Definition

### Y1: อัตราการพึ่งพาตนเองทางการคลัง (Own-Source Revenue Ratio)
* **Code:** `Y1`
* **Scope:** `annual`
* **Name (TH):** อัตราการพึ่งพาตนเองทางการคลัง
* **Name (EN):** Own-Source Revenue Ratio
* **Severity:** `medium`
* **Description:** สัดส่วนรายได้ที่หน่วยงานจัดเก็บได้เอง เทียบกับรายได้ทั้งหมด สะท้อนถึงความอิสระและประสิทธิภาพในการบริหารการเงิน โดยเป้าหมายหลักคือการประเมินความเสี่ยงจากการพึ่งพาเงินอุดหนุนจากรัฐบาลกลางมากเกินไป
* **Data Requirements:** ข้อมูลจากงบการเงิน (`financial_statements`) ที่มีรายการบัญชี:
  1. รายได้ที่ท้องถิ่นจัดเก็บเอง (Local Own Revenue)
  2. รายได้ที่รัฐจัดเก็บให้/แบ่งให้ (Shared Revenue)
  3. รายได้ทั้งหมด (Total Revenue)
  4. เงินกู้ (Loan) — เพื่อใช้หักออกจากรายได้ทั้งหมด

#### Formula
$$\text{Own-Source Revenue Ratio} = \left( \frac{\text{รายได้ที่ท้องถิ่นจัดเก็บเอง + รายได้ที่รัฐจัดเก็บให้}}{\text{รายได้ทั้งหมด - เงินกู้}} \right) \times 100$$

#### Database Configuration (JSON)
```json
{
  "factor_code": "Y1",
  "scope": "annual",
  "name_th": "อัตราการพึ่งพาตนเองทางการคลัง",
  "severity": "medium",
  "params_json": {
    "high_independence_pct": 70.0,
    "medium_independence_low": 40.0,
    "medium_independence_high": 55.0,
    "low_independence_pct": 30.0
  }
}
```

#### Evaluation Criteria
* **ความเสี่ยงต่ำ (เสรีภาพทางการคลังสูง):** อัตราส่วนพึ่งพาตนเอง $\ge 70\%$
* **ความเสี่ยงปานกลาง:** อัตราส่วนพึ่งพาตนเอง $40\% - 55\%$
* **ความเสี่ยงสูง (เสรีภาพทางการคลังต่ำ):** อัตราส่วนพึ่งพาตนเอง $< 30\%$

---

### Y2: ดุลการดำเนินงานประจำปี (Annual Operating Balance)
* **Code:** `Y2`
* **Scope:** `annual`
* **Name (TH):** ดุลการดำเนินงานประจำปี
* **Name (EN):** Annual Operating Balance
* **Severity:** `high`
* **Description:** เครื่องชี้วัดฐานะทางการเงินขององค์กรปกครองส่วนท้องถิ่นหรือหน่วยงานรัฐ เพื่อแสดงถึงผลต่างระหว่างรายได้ประจำกับรายจ่ายประจำ ในรอบปีงบประมาณนั้นๆ
* **Data Requirements:** ข้อมูลจากงบการเงิน (`financial_statements`) ที่มีรายการบัญชี:
  1. รายได้ประจำ (Operating Revenue)
  2. รายจ่ายประจำ (Operating Expenditure)
  3. รายได้รวม (Total Revenue)

#### Formula
$$\text{Annual Operating Balance} = \left( \frac{\text{รายได้ประจำ - รายจ่ายประจำ}}{\text{รายได้รวม}} \right) \times 100$$

#### Database Configuration (JSON)
```json
{
  "factor_code": "Y2",
  "scope": "annual",
  "name_th": "ดุลการดำเนินงานประจำปี",
  "severity": "high",
  "params_json": {
    "surplus_threshold_pct": 15.0,
    "moderate_threshold_low": 5.0,
    "moderate_threshold_high": 10.0,
    "deficit_threshold_pct": 0.0
  }
}
```

#### Evaluation Criteria
* **ความเสี่ยงต่ำ (เงินออมสูง):** รายได้สูงกว่ารายจ่ายประจำ $> 15\%$ (มีเงินออมสะสมเข้าคลังมาก)
* **ความเสี่ยงปานกลาง:** รายได้สูงกว่ารายจ่ายประจำ $5\% - 10\%$
* **ความเสี่ยงสูง (ขาดดุลการคลัง):** ติดลบ (รายจ่ายประจำสูงกว่ารายได้ประจำ)

---

### Y3: สัดส่วนภาระหนี้สินและผูกพันต่อเงินสดคงเหลือ (Cash Coverage Ratio)
* **Code:** `Y3` (เดิมคือข้อ 4 ในเอกสารร่าง)
* **Scope:** `annual`
* **Name (TH):** สัดส่วนภาระหนี้สินและผูกพันต่อเงินสดคงเหลือ
* **Name (EN):** Ratio of Debt & Commitment to Remaining Cash
* **Severity:** `high`
* **Description:** เครื่องชี้วัดเสถียรภาพและความเสี่ยงทางการเงิน เพื่อประเมินความสามารถในการชำระหนี้หรือข้อผูกพันต่างๆ จากเงินสดและเงินฝากธนาคารคงเหลือ
* **Data Requirements:** ข้อมูลจากงบการเงิน (`financial_statements`) ที่มีรายการบัญชี:
  1. เงินสดและเงินฝากธนาคารคงเหลือ (Cash and Bank Deposits)
  2. ภาระผูกพันงบดุล (Balance Sheet Commitments)
  3. หนี้สินหมุนเวียน (Current Liabilities)

#### Formula
$$\text{Cash Coverage Ratio} = \frac{\text{เงินสดและเงินฝากธนาคารคงเหลือ}}{\text{ภาระผูกพันงบดุล + หนี้สินหมุนเวียน}}$$

#### Database Configuration (JSON)
```json
{
  "factor_code": "Y3",
  "scope": "annual",
  "name_th": "สัดส่วนภาระหนี้สินและผูกพันต่อเงินสดคงเหลือ",
  "severity": "high",
  "params_json": {
    "safe_ratio": 5.0,
    "warning_ratio_low": 1.5,
    "warning_ratio_high": 3.0,
    "risk_ratio": 1.0
  }
}
```

#### Evaluation Criteria
* **ความเสี่ยงต่ำ (เงินสดเหลือเฟือ):** อัตราเงินสดครอบคลุม $\ge 5$ เท่า
* **ความเสี่ยงปานกลาง:** อัตราเงินสดครอบคลุม $1.5 - 3$ เท่า
* **ความเสี่ยงสูง (ขาดสภาพคล่อง):** อัตราเงินสดครอบคลุม $< 1.0$ เท่า (มีความเสี่ยงสูงที่จะไม่มีสภาพคล่องชำระหนี้หรือคู่สัญญา)
