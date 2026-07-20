# -*- coding: utf-8 -*-
"""
seed_database.py — Local Budget Fraud Risk Assistant
=====================================================
สร้าง SQLite database + seed ข้อมูล + รัน risk engine ครั้งแรก + validate
ตาม data_model_design.md (อัปเดต ก.ค. 2569)

วิธีรัน (ต้องมีไฟล์ CSV อยู่โฟลเดอร์เดียวกับ script):
    python seed_database.py                      # สร้าง fraud_risk.db
    python seed_database.py --db mydb.db         # ระบุชื่อ db เอง
    python seed_database.py --force              # ลบ db เดิมแล้วสร้างใหม่

Input:
    projects_ALL_master.csv           (97 แถว → 96 โครงการหลัง dedup)
    financial_report_ALL_master.csv   (337 แถว)

ใช้ Python stdlib เท่านั้น (sqlite3, csv) — ไม่ต้องติดตั้ง package เพิ่ม
"""

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
from datetime import datetime

# บังคับ stdout เป็น UTF-8 เพื่อให้ print อักขระพิเศษ (§, →, —) บน Windows cp874 ได้
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECTS_CSV = os.path.join(BASE_DIR, "standardized_data", "projects_ALL_master.csv")
FINANCIAL_CSV = os.path.join(BASE_DIR, "standardized_data", "financial_report_ALL_master.csv")

# ---------------------------------------------------------------------------
# 1. DDL (data_model_design.md §3–§8) — เรียงตามลำดับ dependency
# ---------------------------------------------------------------------------

DDL = """
PRAGMA foreign_keys = ON;

CREATE TABLE subdistricts (
    subdistrict_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name_th          TEXT NOT NULL UNIQUE,
    municipality_name TEXT,
    district         TEXT,
    province         TEXT,
    data_completeness_note TEXT
);

CREATE TABLE vendors (
    vendor_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    tin         TEXT,
    tin_masked  INTEGER DEFAULT 0,
    UNIQUE(name)
);

-- บทบาทผู้ใช้ (ที่มา: roles.md — source of truth; สิทธิ์/scope บังคับที่ app layer ดู src/auth.py)
CREATE TABLE roles (
    role_code       TEXT PRIMARY KEY,
    display_name_th TEXT NOT NULL,
    description     TEXT
);

CREATE TABLE users (
    user_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    display_name   TEXT,
    role           TEXT NOT NULL REFERENCES roles(role_code),
    subdistrict_id INTEGER REFERENCES subdistricts(subdistrict_id),
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE projects (
    project_id        TEXT PRIMARY KEY,
    subdistrict_id    INTEGER NOT NULL REFERENCES subdistricts(subdistrict_id),
    budget_year       INTEGER NOT NULL,
    project_name      TEXT NOT NULL,
    project_type      TEXT,
    dept_name         TEXT,
    dept_sub_name     TEXT,
    purchase_method   TEXT,
    purchase_method_group TEXT,
    announce_date     TEXT,
    transaction_date  TEXT,
    budget_amount     REAL,
    reference_price   REAL,
    contract_value    REAL,
    price_ratio       REAL,
    project_status    TEXT,
    contract_no       TEXT,
    contract_date     TEXT,
    contract_finish_date TEXT,
    contract_duration_days INTEGER,
    contract_status   TEXT,
    vendor_id         INTEGER REFERENCES vendors(vendor_id),
    data_quality_note TEXT,
    source_file       TEXT
);
CREATE INDEX idx_projects_sub_year ON projects(subdistrict_id, budget_year);
CREATE INDEX idx_projects_vendor   ON projects(vendor_id);

CREATE TABLE financial_statements (
    fs_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subdistrict_id   INTEGER NOT NULL REFERENCES subdistricts(subdistrict_id),
    fiscal_year      INTEGER NOT NULL,
    statement_type   TEXT NOT NULL,
    category         TEXT,
    account_item     TEXT NOT NULL,
    note_no          TEXT,
    value            REAL,
    unit             TEXT,
    detail_level     TEXT CHECK (detail_level IN ('line_item','subtotal','total','indicator','reference')),
    data_quality_note TEXT,
    source_file      TEXT,
    UNIQUE(subdistrict_id, fiscal_year, statement_type, category, account_item)
);
CREATE INDEX idx_fs_sub_year_type ON financial_statements(subdistrict_id, fiscal_year, statement_type);

CREATE TABLE risk_factors (
    factor_code   TEXT PRIMARY KEY,
    scope         TEXT NOT NULL CHECK (scope IN ('project','annual')),
    name_th       TEXT NOT NULL,
    description   TEXT NOT NULL,
    formula       TEXT NOT NULL,
    params_json   TEXT NOT NULL DEFAULT '{}',
    weight        REAL NOT NULL DEFAULT 1.0,
    severity      TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('low','medium','high')),
    data_requirement TEXT,
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE assessment_runs (
    run_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at       TEXT NOT NULL DEFAULT (datetime('now')),
    triggered_by TEXT,
    factor_config_snapshot TEXT,
    note         TEXT
);

CREATE TABLE project_risk_results (
    result_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES assessment_runs(run_id),
    project_id    TEXT NOT NULL REFERENCES projects(project_id),
    factor_code   TEXT NOT NULL REFERENCES risk_factors(factor_code),
    triggered     INTEGER NOT NULL CHECK (triggered IN (0,1)),
    computable    INTEGER NOT NULL DEFAULT 1,
    observed_value REAL,
    threshold_used TEXT,
    evidence_text TEXT,
    UNIQUE(run_id, project_id, factor_code)
);
CREATE INDEX idx_prr_project ON project_risk_results(project_id, run_id);

CREATE TABLE project_risk_scores (
    score_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL REFERENCES assessment_runs(run_id),
    project_id  TEXT NOT NULL REFERENCES projects(project_id),
    risk_score  REAL NOT NULL,
    risk_level  TEXT NOT NULL CHECK (risk_level IN ('low','medium','high')),
    factors_triggered INTEGER NOT NULL,
    factors_not_computable INTEGER NOT NULL DEFAULT 0,
    summary_text TEXT,
    UNIQUE(run_id, project_id)
);

CREATE TABLE annual_risk_results (
    result_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id        INTEGER NOT NULL REFERENCES assessment_runs(run_id),
    subdistrict_id INTEGER NOT NULL REFERENCES subdistricts(subdistrict_id),
    fiscal_year   INTEGER NOT NULL,
    factor_code   TEXT NOT NULL REFERENCES risk_factors(factor_code),
    triggered     INTEGER NOT NULL CHECK (triggered IN (0,1)),
    computable    INTEGER NOT NULL DEFAULT 1,
    risk_level    TEXT CHECK (risk_level IN ('low','medium','high')),
    observed_value REAL,
    threshold_used TEXT,
    evidence_text TEXT,
    UNIQUE(run_id, subdistrict_id, fiscal_year, factor_code)
);

CREATE TABLE app_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT
);

CREATE TABLE audit_assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT NOT NULL REFERENCES projects(project_id),
    assigned_to   INTEGER NOT NULL REFERENCES users(user_id),
    assigned_by   INTEGER NOT NULL REFERENCES users(user_id),
    priority      TEXT CHECK (priority IN ('low','medium','high')),
    status        TEXT NOT NULL DEFAULT 'assigned' CHECK (status IN ('assigned','in_progress','submitted','reviewed')),
    due_date      TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX idx_assign_auditor ON audit_assignments(assigned_to, status);

CREATE TABLE audit_reports (
    report_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES audit_assignments(assignment_id),
    work_process  TEXT,
    objective     TEXT,
    likelihood    INTEGER CHECK (likelihood BETWEEN 1 AND 5),
    impact        INTEGER CHECK (impact BETWEEN 1 AND 5),
    impact_score  INTEGER CHECK (impact_score BETWEEN 1 AND 5),
    risk_level    INTEGER CHECK (risk_level BETWEEN 1 AND 5),
    findings      TEXT,
    submitted_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE auditor_feedback (
    feedback_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id    TEXT NOT NULL REFERENCES projects(project_id),
    user_id       INTEGER NOT NULL REFERENCES users(user_id),
    comment       TEXT NOT NULL,
    manual_risk_score INTEGER CHECK (manual_risk_score BETWEEN 1 AND 5),
    created_at    TEXT DEFAULT (datetime('now'))
);

-- บันทึกการเข้าถึงของผู้ใช้ (accountability trail) — ใครทำอะไรกับ resource ไหน เมื่อไหร่
-- เขียนโดย middleware ตอน runtime (src/audit_log.py) เริ่มว่างเปล่าใน seed; append-only (ไม่มี UPDATE/DELETE)
-- username/role เก็บแบบ denormalize เพื่อคง snapshot ณ เวลาที่เกิด action (role อาจเปลี่ยนภายหลัง)
CREATE TABLE access_log (
    log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT,
    role          TEXT,
    action        TEXT NOT NULL,        -- login / view_list / view_detail / export / other (derive จาก method+path)
    method        TEXT NOT NULL,
    path          TEXT NOT NULL,
    resource_type TEXT,                 -- project / risk / subdistrict / financial / audit (derive จาก path)
    resource_id   TEXT,
    status_code   INTEGER,
    ip            TEXT,
    user_agent    TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_access_log_user_time ON access_log(username, created_at);
CREATE INDEX idx_access_log_time      ON access_log(created_at);

CREATE VIEW v_subdistrict_dashboard AS
SELECT s.name_th AS subdistrict, p.budget_year,
       COUNT(*)                              AS project_count,
       SUM(p.budget_amount)                  AS total_budget,
       SUM(CASE WHEN prs.risk_level='high' THEN 1 ELSE 0 END) AS high_risk_count,
       AVG(prs.risk_score)                   AS avg_risk_score
FROM projects p
JOIN subdistricts s ON s.subdistrict_id = p.subdistrict_id
LEFT JOIN project_risk_scores prs ON prs.project_id = p.project_id
   AND prs.run_id = (SELECT MAX(run_id) FROM assessment_runs)
GROUP BY s.name_th, p.budget_year;

CREATE VIEW v_project_risk_detail AS
SELECT p.project_id, p.project_name, s.name_th AS subdistrict, p.budget_year,
       prs.risk_score, prs.risk_level, prs.summary_text,
       prr.factor_code, rf.name_th AS factor_name,
       prr.triggered, prr.computable, prr.observed_value, prr.evidence_text
FROM projects p
JOIN subdistricts s ON s.subdistrict_id = p.subdistrict_id
LEFT JOIN project_risk_scores prs ON prs.project_id = p.project_id
   AND prs.run_id = (SELECT MAX(run_id) FROM assessment_runs)
LEFT JOIN project_risk_results prr ON prr.project_id = p.project_id AND prr.run_id = prs.run_id
LEFT JOIN risk_factors rf ON rf.factor_code = prr.factor_code;

CREATE VIEW v_budget_trend AS
SELECT s.name_th AS subdistrict, f.fiscal_year, f.statement_type, f.category,
       f.account_item, f.value, f.unit
FROM financial_statements f
JOIN subdistricts s ON s.subdistrict_id = f.subdistrict_id
WHERE f.detail_level IN ('subtotal','total') AND f.unit = 'บาท';

CREATE VIEW v_annual_risk AS
SELECT s.name_th AS subdistrict, ar.fiscal_year,
       ar.factor_code, rf.name_th AS factor_name, rf.severity,
       ar.risk_level, ar.triggered, ar.computable,
       ar.observed_value, ar.evidence_text
FROM annual_risk_results ar
JOIN subdistricts s ON s.subdistrict_id = ar.subdistrict_id
JOIN risk_factors rf ON rf.factor_code = ar.factor_code
WHERE ar.run_id = (SELECT MAX(run_id) FROM assessment_runs);
"""

# ---------------------------------------------------------------------------
# 2. Risk factor seed config (§5.1 + §11.3)
# ---------------------------------------------------------------------------

RISK_FACTORS = [
    # --- ระดับโครงการ A1–F1 ---
    dict(factor_code="A1", scope="project", name_th="ส่วนลดผิดปกติ",
         description="ส่วนลดจากราคากลางสูงผิดปกติ (>15%) อาจสะท้อนการประมูลต่ำผิดปกติเพื่อชนะงานแล้วลดคุณภาพ/เบิกเพิ่มภายหลัง",
         formula="(reference_price - contract_value) / reference_price > discount_pct_min",
         params_json=json.dumps({"discount_pct_min": 0.15}),
         weight=1.0, severity="medium",
         data_requirement="reference_price, contract_value"),
    dict(factor_code="A2", scope="project", name_th="ส่วนลดน้อยผิดปกติ",
         description="ชนะที่ 99–100% ของราคากลาง อาจสะท้อนการล็อกสเปกหรือฮั้วประมูล",
         formula="price_ratio BETWEEN ratio_min AND ratio_max",
         params_json=json.dumps({"ratio_min": 0.99, "ratio_max": 1.00}),
         weight=1.0, severity="medium",
         data_requirement="price_ratio (contract_value, reference_price)"),
    dict(factor_code="A3", scope="project", name_th="ราคากลางชนงบพอดี",
         description="ราคากลางใกล้งบประมาณมาก (<0.5%) ซ้ำหลายโครงการในหน่วยงานเดียว อาจสะท้อนการตั้งราคากลางตามงบแทนการสืบราคาจริง",
         formula="ABS(reference_price - budget_amount)/budget_amount < gap_pct_max AND count in group >= min_occurrences (group = dept_name, fallback = subdistrict เมื่อ dept_name ว่าง)",
         params_json=json.dumps({"gap_pct_max": 0.005, "min_occurrences": 2}),
         weight=1.0, severity="medium",
         data_requirement="budget_amount, reference_price, dept_name (fallback: subdistrict)"),
    dict(factor_code="D1", scope="project", name_th="วงเงินหวุดหวิดใต้เกณฑ์เฉพาะเจาะจง",
         description="งบประมาณ 450,000–499,999 บาท หวุดหวิดใต้เพดานวิธีเฉพาะเจาะจง 500,000 อาจสะท้อนการซอยงบเลี่ยงการแข่งขัน",
         formula="budget_amount BETWEEN band_low AND band_high",
         params_json=json.dumps({"band_low": 450000, "band_high": 499999}),
         weight=1.0, severity="high",
         data_requirement="budget_amount"),
    dict(factor_code="F1", scope="project", name_th="จัดจ้างกระจุกตัวท้ายปีงบ",
         description="ทำรายการเดือน ส.ค.–ก.ย. (ท้ายปีงบ) อาจสะท้อนการเร่งใช้งบโดยไม่วางแผน",
         formula="MONTH(transaction_date) IN months",
         params_json=json.dumps({"months": [8, 9]}),
         weight=1.0, severity="low",
         data_requirement="transaction_date (ปิงโค้งไม่มี → computable=0)"),
    # --- ระดับงบรายปี Y1–Y3 (§11.3) ---
    dict(factor_code="Y1", scope="annual", name_th="อัตราการพึ่งพาตนเองทางการคลัง",
         description="(รายได้จัดเก็บเอง + รายได้รัฐจัดเก็บให้) / (รายได้รวม − เงินกู้) × 100 — ต่ำ = พึ่งพาเงินอุดหนุนสูง เปราะบางทางการคลัง (เงินกู้ไม่มีในข้อมูล → ถือเป็น 0)",
         formula="own_and_shared_revenue / (total_revenue - loan) * 100",
         params_json=json.dumps({
             "low_min_pct": 55.0, "high_max_pct": 30.0,
             "account_map": {
                 "own_and_shared_revenue": {
                     "statement_type": "งบแสดงผลการดำเนินงาน",
                     "items": [
                         "รายได้จากการจัดเก็บภาษี ค่าธรรมเนียม ค่าปรับ และใบอนุญาต",
                         "รายได้จากการขายสินค้าและบริการ",
                         "รายได้ของกิจการเฉพาะการและหน่วยงานภายใต้สังกัด",
                         "รายได้อื่น",
                         "รายได้ภาษีจัดสรร",
                         "ภาษี/ค่าธรรมเนียม/ค่าปรับท้องถิ่น",
                         "ภาษีจัดสรร",
                         "รายได้จากการขายและบริการ",
                         "รายได้เฉพาะกิจกรรม"]},
                 "total_revenue": {
                     "statement_type": "งบแสดงผลการดำเนินงาน",
                     "items": ["รวมรายได้", "รายได้รวม (total_revenues)"]},
                 "loan": {"items": []}}}, ensure_ascii=False),
         weight=1.0, severity="medium",
         data_requirement="งบแสดงผลการดำเนินงาน รายตำบลรายปี"),
    dict(factor_code="Y2", scope="annual", name_th="ดุลการดำเนินงานประจำปี",
         description="(รายได้ − ค่าใช้จ่าย) / รายได้รวม × 100 — ติดลบ = ขาดดุล; ใช้ดุลรวมทั้งงบเป็น proxy (ข้อมูลไม่แยกรายการประจำ/ลงทุน)",
         formula="operating_balance / total_revenue * 100",
         params_json=json.dumps({
             "low_min_pct": 15.0, "high_max_pct": 0.0,
             "account_map": {
                 "operating_balance": {
                     "statement_type": "งบแสดงผลการดำเนินงาน",
                     "items": ["รายได้สูง/(ต่ำ) กว่าค่าใช้จ่ายสุทธิ",
                               "กำไร(ขาดทุน)สุทธิ = รายได้รวม - รายจ่ายรวม - ดอกเบี้ย"]},
                 "total_revenue": {
                     "statement_type": "งบแสดงผลการดำเนินงาน",
                     "items": ["รวมรายได้", "รายได้รวม (total_revenues)"]}}}, ensure_ascii=False),
         weight=1.0, severity="high",
         data_requirement="งบแสดงผลการดำเนินงาน รายตำบลรายปี"),
    dict(factor_code="Y3", scope="annual", name_th="Cash Coverage Ratio",
         description="เงินสดและรายการเทียบเท่า / (ภาระผูกพัน + หนี้สินหมุนเวียน) — ต่ำกว่า 1 เท่า = เงินสดไม่พอจ่ายหนี้ระยะสั้น (ภาระผูกพันไม่มีในข้อมูล → ถือเป็น 0)",
         formula="cash / (commitments + current_liabilities)",
         params_json=json.dumps({
             "low_min_ratio": 5.0, "high_max_ratio": 1.0,
             "account_map": {
                 "cash": {
                     "statement_type": "งบแสดงฐานะการเงิน",
                     "items": ["เงินสดและรายการเทียบเท่าเงินสด"]},
                 "current_liabilities": {
                     "statement_type": "งบแสดงฐานะการเงิน",
                     "items": ["รวมหนี้สินหมุนเวียน", "หนี้สินหมุนเวียนรวม"]},
                 "commitments": {"items": []}}}, ensure_ascii=False),
         weight=1.0, severity="high",
         data_requirement="งบแสดงฐานะการเงิน รายตำบลรายปี"),
]

APP_CONFIG = [
    ("risk_level_medium_min", "30", "risk_score >= ค่านี้ → medium"),
    ("risk_level_high_min", "60", "risk_score > ค่านี้ → high"),
]

# บทบาทตาม roles.md (5 role) + admin สำหรับดูแลระบบ — สิทธิ์/scope บังคับที่ app layer (src/auth.py)
ROLES = [
    # (role_code, display_name_th, description)
    ("admin", "ผู้ดูแลระบบ",
     "ดูแลระบบทั้งหมด ตั้งค่า risk factors / app_config และจัดการผู้ใช้"),
    ("regional_supervisor", "ผู้บริหาร/ผู้กำกับดูแลระดับอำเภอ/จังหวัด",
     "เปรียบเทียบและติดตามความเสี่ยงของหลายพื้นที่ในระดับอำเภอ/จังหวัด"),
    ("local_executive", "ผู้บริหาร (นายก อบต. / ปลัด)",
     "ติดตามภาพรวมของตำบลเพื่อใช้ประกอบการอนุมัตินโยบายและกำกับการบริหารความเสี่ยง"),
    ("project_auditor", "ผู้ตรวจสอบโครงการ",
     "ตรวจสอบและจัดลำดับความสำคัญของโครงการที่มีความเสี่ยง พร้อมมอบหมายงานให้นักวิเคราะห์"),
    ("risk_analyst", "นักวิเคราะห์ข้อมูล / ทีมตรวจสอบภายใน",
     "รับงานตรวจสอบ วิเคราะห์ความเสี่ยง และจัดทำรายงานผล"),
    ("public_user", "ประชาชนทั่วไป",
     "ตรวจสอบความโปร่งใสของโครงการในหน่วยงานท้องถิ่น (ไม่เห็นข้อมูลที่ถูกปิดไว้ ไม่มีสิทธิ์แก้ไข)"),
]

# mock users ตาม roles.md — 1 คนต่อ role + ครบ 3 ตำบลสำหรับทดสอบ scope; รหัสผ่านทุกคน: password123
MOCK_USERS = [
    ("admin", "ผู้ดูแลระบบ", "admin", None),
    ("supervisor1", "ผู้กำกับดูแลระดับอำเภอ/จังหวัด", "regional_supervisor", None),
    ("thachang_user", "นายก/ปลัด ทต.ท่าช้าง", "local_executive", "ท่าช้าง"),
    ("pingkhong_user", "นายก/ปลัด ทต.ปิงโค้ง", "local_executive", "ปิงโค้ง"),
    ("yonok_user", "นายก/ปลัด ทต.โยนก", "local_executive", "โยนก"),
    ("auditor1", "ผู้ตรวจสอบโครงการ ทต.ท่าช้าง", "project_auditor", "ท่าช้าง"),
    ("auditor2", "ผู้ตรวจสอบโครงการ ทต.ปิงโค้ง", "project_auditor", "ปิงโค้ง"),
    ("auditor3", "ผู้ตรวจสอบโครงการ ทต.โยนก",   "project_auditor", "โยนก"),
    ("analyst1", "นักวิเคราะห์ความเสี่ยง ทต.ท่าช้าง", "risk_analyst", "ท่าช้าง"),
    ("analyst2", "นักวิเคราะห์ความเสี่ยง ทต.ปิงโค้ง", "risk_analyst", "ปิงโค้ง"),
    ("analyst3", "นักวิเคราะห์ความเสี่ยง ทต.โยนก",   "risk_analyst", "โยนก"),
    ("public1", "ประชาชนทั่วไป", "public_user", None),
]

PINGKHONG_NOTE = ("ข้อมูลสรุป: ไม่มีหน่วยงาน วันที่ พิกัด TIN และเลขสัญญา — "
                  "factor ที่ใช้วันที่ (F1) คำนวณไม่ได้; งบการเงินมีเฉพาะระดับ subtotal")

# ---------------------------------------------------------------------------
# 3. Helpers
# ---------------------------------------------------------------------------

def read_csv_clean(path):
    """อ่าน CSV แบบกัน BOM + NUL byte (§9.2)"""
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8-sig").replace("\x00", "")
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0]
    data = [dict(zip(header, r)) for r in rows[1:] if any(c.strip() for c in r)]
    return data


def parse_date(v):
    """D/M/YYYY (ค.ศ.) → ISO YYYY-MM-DD; '-'/ว่าง → None (§9.3)
    รองรับทั้งรูปแบบ D/M/YYYY และ YYYY-MM-DD"""
    v = (v or "").strip()
    if not v or v == "-":
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    raise ValueError(f"ไม่รู้จักรูปแบบวันที่: {v!r}")


def to_float(v):
    """ค่าว่าง → None ห้ามแปลงเป็น 0 (§9.2)"""
    v = (v or "").strip()
    if not v or v == "-":
        return None
    return float(v.replace(",", ""))


def to_int(v):
    f = to_float(v)
    return int(f) if f is not None else None


def sha256(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def log(msg):
    print(f"  {msg}")

# ---------------------------------------------------------------------------
# 4. Seed (§9)
# ---------------------------------------------------------------------------

def seed_master_data(cur, proj_rows, fin_rows):
    # subdistricts: district/province จาก projects CSV, municipality จาก financial CSV
    subs = {}
    for r in proj_rows:
        name = r["subdistrict"].strip()
        if name and name not in subs:
            subs[name] = {"district": r["district"].strip() or None,
                          "province": r["province"].strip() or None}
    munis = {}
    for r in fin_rows:
        name = r["ตำบล"].strip()
        if name and name not in munis and r["เทศบาล"].strip():
            munis[name] = r["เทศบาล"].strip()
    for name, info in sorted(subs.items()):
        note = PINGKHONG_NOTE if name == "ปิงโค้ง" else None
        cur.execute(
            "INSERT INTO subdistricts (name_th, municipality_name, district, province, data_completeness_note) "
            "VALUES (?,?,?,?,?)",
            (name, munis.get(name), info["district"], info["province"], note))
    log(f"subdistricts: {len(subs)} แถว")

    sub_id = {name: cur.execute(
        "SELECT subdistrict_id FROM subdistricts WHERE name_th=?", (name,)).fetchone()[0]
        for name in subs}
    return sub_id


def seed_vendors(cur, proj_rows):
    """dedup ด้วย name; TIN เก็บ TEXT + tin_masked=1 ถ้าไม่สมบูรณ์ (§3.2, §9.3)"""
    for r in proj_rows:
        name = r["winner_name"].strip()
        if not name or name == "-":
            continue
        tin = r["winner_tin"].strip()
        if not tin or tin == "-":
            tin, masked = None, 1
        else:
            # TIN เสียจาก Excel (9.33543E+11) หรือปกปิดบางส่วน (xxxx) → masked
            masked = 1 if ("E+" in tin.upper() or "x" in tin.lower()) else 0
        cur.execute("INSERT OR IGNORE INTO vendors (name, tin, tin_masked) VALUES (?,?,?)",
                    (name, tin, masked))
    n = cur.execute("SELECT COUNT(*) FROM vendors").fetchone()[0]
    nm = cur.execute("SELECT COUNT(*) FROM vendors WHERE tin_masked=1").fetchone()[0]
    log(f"vendors: {n} ราย (TIN ไม่สมบูรณ์ {nm} ราย — dedup ด้วยชื่อ)")


def seed_projects(cur, proj_rows, sub_id):
    vendor_id = {name: vid for vid, name in
                 cur.execute("SELECT vendor_id, name FROM vendors").fetchall()}
    inserted, dups = 0, []
    for r in proj_rows:
        pid = r["project_id"].strip()
        if cur.execute("SELECT 1 FROM projects WHERE project_id=?", (pid,)).fetchone():
            dups.append(pid)  # โยนก 67119096755 ซ้ำ 2 แถว (§9.2)
            continue
        sub = r["subdistrict"].strip()
        rp, cv = to_float(r["reference_price"]), to_float(r["contract_value"])
        # price_ratio คำนวณใหม่ทุกแถว (§9.3): NULL ถ้าตัวใดเป็น 0/NULL
        ratio = round(cv / rp, 4) if (rp and cv) else None

        notes = []
        if sub == "ปิงโค้ง":
            notes.append("ข้อมูลสรุป ไม่มีวันที่/สัญญา/TIN")
        ba = to_float(r["budget_amount"])
        if (ba == 0) or (cv == 0):
            notes.append("งบประมาณ/วงเงินสัญญา = 0 ตามต้นฉบับ")
        # แถวต้นฉบับถูกตัดท้าย: ท่าช้าง/โยนก ปี 2566 ที่ข้อมูลท้ายแถวหาย (§9.3 + dictionary)
        if sub in ("ท่าช้าง", "โยนก") and r["budget_year"].strip() == "2566" \
                and not r["winner_name"].strip() and not r["contract_no"].strip():
            notes.append("แถวต้นฉบับถูกตัดท้าย (ข้อมูลท้ายแถวหายไป)")

        cur.execute("""INSERT INTO projects (project_id, subdistrict_id, budget_year, project_name,
            project_type, dept_name, dept_sub_name, purchase_method, purchase_method_group,
            announce_date, transaction_date, budget_amount, reference_price, contract_value,
            price_ratio, project_status, contract_no, contract_date, contract_finish_date,
            contract_duration_days, contract_status, vendor_id, data_quality_note, source_file)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            pid, sub_id[sub], to_int(r["budget_year"]), r["project_name"].strip(),
            r["project_type"].strip() or None,
            r["dept_name"].strip() or None, r["dept_sub_name"].strip() or None,
            r["purchase_method"].strip() or None, r["purchase_method_group"].strip() or None,
            parse_date(r["announce_date"]), parse_date(r["transaction_date"]),
            ba, rp, cv, ratio,
            r["project_status"].strip() or None,
            r["contract_no"].strip() or None,
            parse_date(r["contract_date"]), parse_date(r["contract_finish_date"]),
            to_int(r["contract_duration_days"]),
            r["contract_status"].strip() or None,
            vendor_id.get(r["winner_name"].strip()),
            "; ".join(notes) or None,
            "projects_ALL_master.csv"))
        inserted += 1
    log(f"projects: {inserted} โครงการ (ข้ามแถวซ้ำ {len(dups)} แถว: {', '.join(dups) or '-'})")


def seed_financial(cur, fin_rows, sub_id):
    for r in fin_rows:
        cur.execute("""INSERT INTO financial_statements (subdistrict_id, fiscal_year,
            statement_type, category, account_item, note_no, value, unit, detail_level,
            data_quality_note, source_file) VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
            sub_id[r["ตำบล"].strip()], to_int(r["ปีงบประมาณ"]),
            r["ประเภทงบ"].strip(), r["หมวดหมู่"].strip() or None,
            r["รายการบัญชี"].strip(), r["หมายเหตุ"].strip() or None,
            to_float(r["มูลค่า"]), r["หน่วย"].strip() or None,
            r["ระดับรายละเอียด"].strip() or None,
            r["หมายเหตุคุณภาพข้อมูล"].strip() or None,
            r["ไฟล์ต้นฉบับ"].strip() or None))
    log(f"financial_statements: {len(fin_rows)} แถว")


def seed_risk_factors(cur):
    for f in RISK_FACTORS:
        cur.execute("""INSERT INTO risk_factors (factor_code, scope, name_th, description,
            formula, params_json, weight, severity, data_requirement)
            VALUES (?,?,?,?,?,?,?,?,?)""", (
            f["factor_code"], f["scope"], f["name_th"], f["description"], f["formula"],
            f["params_json"], f["weight"], f["severity"], f["data_requirement"]))
    log(f"risk_factors: {len(RISK_FACTORS)} factors (A1–F1 + Y1–Y3)")


def seed_users_config(cur, sub_id):
    # roles ต้องมาก่อน users (users.role FK → roles.role_code)
    cur.executemany("INSERT INTO roles (role_code, display_name_th, description) VALUES (?,?,?)",
                    ROLES)
    for username, display, role, sub in MOCK_USERS:
        cur.execute("""INSERT INTO users (username, password_hash, display_name, role, subdistrict_id)
            VALUES (?,?,?,?,?)""",
                    (username, sha256("password123"), display, role,
                     sub_id.get(sub) if sub else None))
    for key, value, desc in APP_CONFIG:
        cur.execute("INSERT INTO app_config (key, value, description) VALUES (?,?,?)",
                    (key, value, desc))
    log(f"roles: {len(ROLES)} | users: {len(MOCK_USERS)} (mock, รหัสผ่าน password123) | app_config: {len(APP_CONFIG)}")

# ---------------------------------------------------------------------------
# 5. Risk Engine — ระดับโครงการ (§10)
# ---------------------------------------------------------------------------

def run_project_engine(cur, run_id):
    factors = {code: json.loads(pj) for code, pj in cur.execute(
        "SELECT factor_code, params_json FROM risk_factors WHERE scope='project' AND enabled=1")}
    cur.execute("""SELECT p.*, s.name_th AS sub_name FROM projects p
                   JOIN subdistricts s ON s.subdistrict_id = p.subdistrict_id""")
    cols = [c[0] for c in cur.description]
    projects = [dict(zip(cols, row)) for row in cur.fetchall()]

    # เตรียมกลุ่มสำหรับ A3: นับโครงการที่ gap < threshold ต่อกลุ่ม (dept_name, fallback ตำบล)
    p3 = factors.get("A3", {})
    gap_max, min_occ = p3.get("gap_pct_max", 0.005), p3.get("min_occurrences", 2)
    group_hits = {}
    for p in projects:
        if p["budget_amount"] and p["reference_price"]:
            gap = abs(p["reference_price"] - p["budget_amount"]) / p["budget_amount"]
            if gap < gap_max:
                key = p["dept_name"] or f"ตำบล:{p['sub_name']}"
                group_hits[key] = group_hits.get(key, 0) + 1

    def emit(pid, code, triggered, computable, observed, params, evidence):
        cur.execute("""INSERT INTO project_risk_results
            (run_id, project_id, factor_code, triggered, computable, observed_value,
             threshold_used, evidence_text) VALUES (?,?,?,?,?,?,?,?)""",
                    (run_id, pid, code, int(triggered), int(computable), observed,
                     json.dumps(params, ensure_ascii=False), evidence))

    for p in projects:
        pid = p["project_id"]
        rp, cv, ba = p["reference_price"], p["contract_value"], p["budget_amount"]

        # A1: ส่วนลด > 15%
        if "A1" in factors:
            th = factors["A1"]["discount_pct_min"]
            if rp and cv:
                disc = (rp - cv) / rp
                trig = disc > th
                emit(pid, "A1", trig, 1, round(disc, 4), factors["A1"],
                     f"ส่วนลด {disc*100:.1f}% " + (f"เกินเกณฑ์ {th*100:.0f}%" if trig else f"ไม่เกินเกณฑ์ {th*100:.0f}%"))
            else:
                emit(pid, "A1", 0, 0, None, factors["A1"], "ประเมินไม่ได้: ไม่มีราคากลางหรือวงเงินสัญญา")

        # A2: ชนะ 99–100% ของราคากลาง
        if "A2" in factors:
            lo, hi = factors["A2"]["ratio_min"], factors["A2"]["ratio_max"]
            ratio = p["price_ratio"]
            if ratio is not None:
                trig = lo <= ratio <= hi
                emit(pid, "A2", trig, 1, ratio, factors["A2"],
                     f"ราคาสัญญา = {ratio*100:.2f}% ของราคากลาง" + (f" อยู่ช่วง {lo*100:.0f}–{hi*100:.0f}% (ส่วนลดน้อยผิดปกติ)" if trig else ""))
            else:
                emit(pid, "A2", 0, 0, None, factors["A2"], "ประเมินไม่ได้: price_ratio ว่าง (ราคากลาง/สัญญาเป็น 0 หรือไม่มี)")

        # A3: ราคากลางชนงบ ซ้ำในกลุ่มเดียว
        if "A3" in factors:
            if ba and rp:
                gap = abs(rp - ba) / ba
                key = p["dept_name"] or f"ตำบล:{p['sub_name']}"
                trig = gap < gap_max and group_hits.get(key, 0) >= min_occ
                scope_txt = p["dept_name"] or f"ตำบล{p['sub_name']} (ไม่มีชื่อหน่วยงาน)"
                emit(pid, "A3", trig, 1, round(gap, 6), factors["A3"],
                     f"ราคากลางห่างงบ {gap*100:.2f}%" +
                     (f" และพบซ้ำ {group_hits.get(key)} โครงการใน {scope_txt}" if trig else ""))
            else:
                emit(pid, "A3", 0, 0, None, factors["A3"], "ประเมินไม่ได้: ไม่มีงบประมาณหรือราคากลาง")

        # D1: วงเงินหวุดหวิดใต้เกณฑ์เฉพาะเจาะจง
        if "D1" in factors:
            lo, hi = factors["D1"]["band_low"], factors["D1"]["band_high"]
            if ba is not None:
                trig = lo <= ba <= hi
                emit(pid, "D1", trig, 1, ba, factors["D1"],
                     f"งบประมาณ {ba:,.0f} บาท" + (f" อยู่ช่วง {lo:,}–{hi:,} (หวุดหวิดใต้เพดาน 500,000)" if trig else ""))
            else:
                emit(pid, "D1", 0, 0, None, factors["D1"], "ประเมินไม่ได้: ไม่มีงบประมาณ")

        # F1: เดือน ส.ค.–ก.ย.
        if "F1" in factors:
            months = factors["F1"]["months"]
            td = p["transaction_date"]
            if td:
                m = int(td[5:7])
                trig = m in months
                emit(pid, "F1", trig, 1, m, factors["F1"],
                     f"ทำรายการเดือน {m}" + (" (ท้ายปีงบ ส.ค.–ก.ย.)" if trig else ""))
            else:
                emit(pid, "F1", 0, 0, None, factors["F1"], "ประเมินไม่ได้: ไม่มีวันที่ทำรายการ")

    # รวมคะแนน (§5.4)
    med_min = float(cur.execute("SELECT value FROM app_config WHERE key='risk_level_medium_min'").fetchone()[0])
    high_min = float(cur.execute("SELECT value FROM app_config WHERE key='risk_level_high_min'").fetchone()[0])
    weights = {code: w for code, w in cur.execute(
        "SELECT factor_code, weight FROM risk_factors WHERE scope='project' AND enabled=1")}
    names = {code: n for code, n in cur.execute(
        "SELECT factor_code, name_th FROM risk_factors WHERE scope='project'")}

    for p in projects:
        pid = p["project_id"]
        rows = cur.execute("""SELECT factor_code, triggered, computable FROM project_risk_results
                              WHERE run_id=? AND project_id=?""", (run_id, pid)).fetchall()
        w_comp = sum(weights[c] for c, t, comp in rows if comp)
        w_trig = sum(weights[c] for c, t, comp in rows if comp and t)
        n_trig = sum(1 for c, t, comp in rows if comp and t)
        n_nc = sum(1 for c, t, comp in rows if not comp)
        score = round(100.0 * w_trig / w_comp, 1) if w_comp > 0 else 0.0
        level = "high" if score > high_min else ("medium" if score >= med_min else "low")
        summary = ", ".join(names[c] for c, t, comp in rows if comp and t) or "ไม่พบสัญญาณเสี่ยง"
        if n_nc:
            summary += f" (ประเมินไม่ได้ {n_nc} factor)"
        cur.execute("""INSERT INTO project_risk_scores (run_id, project_id, risk_score, risk_level,
            factors_triggered, factors_not_computable, summary_text) VALUES (?,?,?,?,?,?,?)""",
                    (run_id, pid, score, level, n_trig, n_nc, summary))
    n = cur.execute("SELECT COUNT(*) FROM project_risk_scores WHERE run_id=?", (run_id,)).fetchone()[0]
    log(f"project risk: {n} โครงการ ได้คะแนนครบ")

# ---------------------------------------------------------------------------
# 6. Risk Engine — ระดับงบรายปี Y1–Y3 (§11)
# ---------------------------------------------------------------------------

def sum_concept(cur, sid, fy, concept):
    """รวมค่า concept ตาม account_map — exact match เท่านั้น ห้าม LIKE (§11.4)
    คืน (value, found): items ว่าง → (0, True); หาแถวไม่เจอ → (None, False)"""
    items = concept.get("items", [])
    if not items:
        return 0.0, True
    q = """SELECT SUM(value), COUNT(*) FROM financial_statements
           WHERE subdistrict_id=? AND fiscal_year=? AND statement_type=? AND unit='บาท'
           AND account_item IN ({})""".format(",".join("?" * len(items)))
    total, cnt = cur.execute(q, [sid, fy, concept["statement_type"]] + items).fetchone()
    return (total, True) if cnt else (None, False)


def classify(value, params, kind):
    """map ค่า → risk_level ตามเกณฑ์ต่อเนื่อง §11.2"""
    if kind in ("Y1", "Y2"):
        lo, hi = params["low_min_pct"], params["high_max_pct"]
    else:
        lo, hi = params["low_min_ratio"], params["high_max_ratio"]
    if value >= lo:
        return "low"
    if value < hi:
        return "high"
    return "medium"


def run_annual_engine(cur, run_id):
    factors = {code: json.loads(pj) for code, pj in cur.execute(
        "SELECT factor_code, params_json FROM risk_factors WHERE scope='annual' AND enabled=1")}
    # ทุก (ตำบล × ปี) ที่มีงบ → ต้องมีผลครบทุก factor ห้ามเงียบ (§11.4)
    sets = cur.execute("""SELECT DISTINCT subdistrict_id, fiscal_year FROM financial_statements
        WHERE statement_type IN ('งบแสดงผลการดำเนินงาน','งบแสดงฐานะการเงิน')
        ORDER BY subdistrict_id, fiscal_year""").fetchall()

    def emit(sid, fy, code, triggered, computable, level, observed, params, evidence):
        cur.execute("""INSERT INTO annual_risk_results (run_id, subdistrict_id, fiscal_year,
            factor_code, triggered, computable, risk_level, observed_value, threshold_used,
            evidence_text) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (run_id, sid, fy, code, int(triggered), int(computable), level,
                     observed, json.dumps({k: v for k, v in params.items() if k != "account_map"},
                                          ensure_ascii=False), evidence))

    for sid, fy in sets:
        # --- Y1 ---
        if "Y1" in factors:
            pr = factors["Y1"]; am = pr["account_map"]
            own, f1 = sum_concept(cur, sid, fy, am["own_and_shared_revenue"])
            total, f2 = sum_concept(cur, sid, fy, am["total_revenue"])
            loan, _ = sum_concept(cur, sid, fy, am["loan"])
            if not (f1 and f2) or total is None:
                emit(sid, fy, "Y1", 0, 0, None, None, pr, "ประเมินไม่ได้: หารายการรายได้ในงบไม่พบ")
            elif (total - loan) <= 0:
                emit(sid, fy, "Y1", 0, 0, None, None, pr, "ประเมินไม่ได้: รายได้รวม (หักเงินกู้) ≤ 0")
            else:
                v = own / (total - loan) * 100
                lv = classify(v, pr, "Y1")
                emit(sid, fy, "Y1", lv in ("medium", "high"), 1, lv, round(v, 2), pr,
                     f"พึ่งพาตนเอง {v:.1f}% ({'≥55% เสี่ยงต่ำ' if lv=='low' else ('30–55% เสี่ยงปานกลาง' if lv=='medium' else '<30% เสี่ยงสูง')}); เงินกู้ไม่มีข้อมูล ถือเป็น 0")

        # --- Y2 ---
        if "Y2" in factors:
            pr = factors["Y2"]; am = pr["account_map"]
            bal, f1 = sum_concept(cur, sid, fy, am["operating_balance"])
            total, f2 = sum_concept(cur, sid, fy, am["total_revenue"])
            if not (f1 and f2) or bal is None or total is None:
                emit(sid, fy, "Y2", 0, 0, None, None, pr, "ประเมินไม่ได้: หาแถวดุลดำเนินงาน/รายได้รวมไม่พบ")
            elif total <= 0:
                emit(sid, fy, "Y2", 0, 0, None, None, pr, "ประเมินไม่ได้: รายได้รวม ≤ 0")
            else:
                v = bal / total * 100
                lv = classify(v, pr, "Y2")
                emit(sid, fy, "Y2", lv in ("medium", "high"), 1, lv, round(v, 2), pr,
                     f"ดุลดำเนินงาน {v:.1f}% ของรายได้ ({'≥15% เสี่ยงต่ำ' if lv=='low' else ('0–15% เสี่ยงปานกลาง' if lv=='medium' else 'ขาดดุล เสี่ยงสูง')})")

        # --- Y3 ---
        if "Y3" in factors:
            pr = factors["Y3"]; am = pr["account_map"]
            cash, f1 = sum_concept(cur, sid, fy, am["cash"])
            liab, f2 = sum_concept(cur, sid, fy, am["current_liabilities"])
            commit, _ = sum_concept(cur, sid, fy, am["commitments"])
            if not (f1 and f2) or cash is None:
                emit(sid, fy, "Y3", 0, 0, None, None, pr, "ประเมินไม่ได้: หาแถวเงินสด/หนี้สินหมุนเวียนไม่พบ")
            elif (commit + (liab or 0)) <= 0:
                # ตัวส่วน ≤ 0 → เสี่ยงต่ำ (§11.1)
                emit(sid, fy, "Y3", 0, 1, "low", None, pr, "ไม่มีหนี้สินหมุนเวียน — เสี่ยงต่ำ")
            else:
                v = cash / (commit + liab)
                lv = classify(v, pr, "Y3")
                emit(sid, fy, "Y3", lv in ("medium", "high"), 1, lv, round(v, 2), pr,
                     f"Cash coverage {v:.2f} เท่า ({'≥5 เท่า เสี่ยงต่ำ' if lv=='low' else ('1–5 เท่า เสี่ยงปานกลาง' if lv=='medium' else '<1 เท่า เสี่ยงสูง')}); ภาระผูกพันไม่มีข้อมูล ถือเป็น 0")

    n = cur.execute("SELECT COUNT(*) FROM annual_risk_results WHERE run_id=?", (run_id,)).fetchone()[0]
    log(f"annual risk: {n} ผล ({len(sets)} ชุดตำบล×ปี × {len(factors)} factors)")

# ---------------------------------------------------------------------------
# 7. Validation (§9.5 + §11.5)
# ---------------------------------------------------------------------------

def validate(cur):
    ok = True

    def check(name, passed, detail=""):
        nonlocal ok
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))
        ok = ok and passed

    n_proj = cur.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    n_fs = cur.execute("SELECT COUNT(*) FROM financial_statements").fetchone()[0]
    check("1) จำนวนแถว: projects=96, financial_statements=337",
          n_proj == 96 and n_fs == 337, f"ได้ {n_proj}/{n_fs}")

    n = cur.execute("SELECT COUNT(*) FROM projects WHERE subdistrict_id IS NULL").fetchone()[0]
    check("2) ทุกโครงการ map ตำบลได้", n == 0)

    # 3) สมการบัญชี ต่อตำบลต่อปี — ปิงโค้งไม่มีแถวรวมหนี้สิน+ทุน ต้องบวกเอง
    eq_fail = []
    for sid, fy in cur.execute("""SELECT DISTINCT subdistrict_id, fiscal_year
            FROM financial_statements WHERE statement_type='งบแสดงฐานะการเงิน'"""):
        rows = dict(cur.execute("""SELECT account_item, value FROM financial_statements
            WHERE subdistrict_id=? AND fiscal_year=? AND statement_type='งบแสดงฐานะการเงิน'
            AND detail_level IN ('subtotal','total') AND unit='บาท'""", (sid, fy)).fetchall())
        ta = next((v for k, v in rows.items() if "สินทรัพย์รวม" in k or k == "รวมสินทรัพย์"), None)
        tle = next((v for k, v in rows.items() if ("หนี้สิน" in k and ("ส่วนทุน" in k or "สุทธิ" in k))), None)
        if tle is None:  # ปิงโค้ง: หนี้สินรวม + ทุนสะสม
            tl = next((v for k, v in rows.items() if k in ("หนี้สินรวม", "รวมหนี้สิน")), None)
            eq = next((v for k, v in rows.items() if "ทุน" in k and "หนี้" not in k), None)
            tle = (tl + eq) if (tl is not None and eq is not None) else None
        if ta is None or tle is None or abs(ta - tle) > 1.0:
            eq_fail.append((sid, fy, ta, tle))
    check("3) สมการบัญชี สินทรัพย์ = หนี้สิน+ทุน ทุกตำบลทุกปี", not eq_fail, str(eq_fail))

    n = cur.execute("""SELECT COUNT(*) FROM projects WHERE price_ratio IS NOT NULL
        AND ABS(price_ratio - contract_value/reference_price) >= 0.001""").fetchone()[0]
    check("4) price_ratio สอดคล้อง contract_value/reference_price", n == 0)

    n = cur.execute("""SELECT (SELECT COUNT(*) FROM projects WHERE budget_year NOT BETWEEN 2566 AND 2568)
        + (SELECT COUNT(*) FROM financial_statements WHERE fiscal_year NOT BETWEEN 2566 AND 2568)""").fetchone()[0]
    check("5) ปีงบอยู่ในช่วง 2566–2568", n == 0)

    # ทุกโครงการมีผลครบทุก enabled project factor (§10 "ห้ามเงียบ")
    n_pf = cur.execute("SELECT COUNT(*) FROM risk_factors WHERE scope='project' AND enabled=1").fetchone()[0]
    n_bad = cur.execute("""SELECT COUNT(*) FROM (SELECT project_id FROM project_risk_results
        WHERE run_id=(SELECT MAX(run_id) FROM assessment_runs)
        GROUP BY project_id HAVING COUNT(*) != ?)""", (n_pf,)).fetchone()[0]
    check(f"6) ทุกโครงการมีผลครบ {n_pf} project factors", n_bad == 0)

    # ทุก (ตำบล×ปีที่มีงบ) มีผลครบทุก annual factor
    n_af = cur.execute("SELECT COUNT(*) FROM risk_factors WHERE scope='annual' AND enabled=1").fetchone()[0]
    n_sets = cur.execute("""SELECT COUNT(*) FROM (SELECT DISTINCT subdistrict_id, fiscal_year
        FROM financial_statements
        WHERE statement_type IN ('งบแสดงผลการดำเนินงาน','งบแสดงฐานะการเงิน'))""").fetchone()[0]
    n_ar = cur.execute("""SELECT COUNT(*) FROM annual_risk_results
        WHERE run_id=(SELECT MAX(run_id) FROM assessment_runs)""").fetchone()[0]
    check(f"7) annual risk ครบ {n_sets} ชุด × {n_af} factors = {n_sets*n_af}", n_ar == n_sets * n_af, f"ได้ {n_ar}")

    # roles ครบตาม roles.md + admin และ user ที่ role เป็นแบบ scope ตำบลต้องมี subdistrict_id
    n_roles = cur.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
    n_scoped_null = cur.execute("""SELECT COUNT(*) FROM users
        WHERE role IN ('local_executive','project_auditor','risk_analyst')
        AND subdistrict_id IS NULL""").fetchone()[0]
    check("8) roles ครบ 6 role (roles.md + admin) และ user แบบ scope ตำบลมี subdistrict_id ครบ",
          n_roles == len(ROLES) and n_scoped_null == 0,
          f"roles={n_roles}, scoped-user ไม่มีตำบล={n_scoped_null}")

    return ok


def cross_check_pingkhong(cur):
    """§11.5: เทียบผล engine กับ indicator ที่คำนวณไว้แล้วในไฟล์ปิงโค้ง
    Y1 ≈ 100 − พึ่งพาเงินอุดหนุน, Y2 ≈ surplus margin"""
    print("\nCross-check ปิงโค้ง (engine vs indicator ในไฟล์):")
    sid = cur.execute("SELECT subdistrict_id FROM subdistricts WHERE name_th='ปิงโค้ง'").fetchone()[0]
    for fy in (2566, 2567, 2568):
        dep = cur.execute("""SELECT value FROM financial_statements WHERE subdistrict_id=? AND fiscal_year=?
            AND account_item='พึ่งพาเงินอุดหนุนรัฐ/รายได้รวม'""", (sid, fy)).fetchone()
        margin = cur.execute("""SELECT value FROM financial_statements WHERE subdistrict_id=? AND fiscal_year=?
            AND account_item='กำไรสุทธิ/รายได้รวม (surplus margin)'""", (sid, fy)).fetchone()
        y1 = cur.execute("""SELECT observed_value FROM annual_risk_results WHERE subdistrict_id=? AND fiscal_year=?
            AND factor_code='Y1' AND run_id=(SELECT MAX(run_id) FROM assessment_runs)""", (sid, fy)).fetchone()
        y2 = cur.execute("""SELECT observed_value FROM annual_risk_results WHERE subdistrict_id=? AND fiscal_year=?
            AND factor_code='Y2' AND run_id=(SELECT MAX(run_id) FROM assessment_runs)""", (sid, fy)).fetchone()
        if dep and y1 and y1[0] is not None:
            expect = 100 - dep[0]
            diff = abs(y1[0] - expect)
            print(f"  {fy} Y1={y1[0]:.1f}% vs (100−พึ่งพาอุดหนุน)={expect:.1f}% "
                  f"{'OK' if diff < 3 else 'ต่าง ' + format(diff, '.1f') + ' จุด (ตรวจ account_map)'}")
        if margin and y2 and y2[0] is not None:
            diff = abs(y2[0] - margin[0])
            print(f"  {fy} Y2={y2[0]:.1f}% vs surplus margin={margin[0]:.1f}% "
                  f"{'OK' if diff < 3 else 'ต่าง ' + format(diff, '.1f') + ' จุด (ตรวจ account_map)'}")

# ---------------------------------------------------------------------------
# 8. Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="สร้าง + seed + รัน risk engine ลง SQLite")
    ap.add_argument("--db", default=os.path.join(BASE_DIR, "fraud_risk.db"))
    ap.add_argument("--force", action="store_true", help="ลบ db เดิมก่อนสร้างใหม่")
    args = ap.parse_args()

    if os.path.exists(args.db):
        if args.force:
            os.remove(args.db)
        else:
            sys.exit(f"มี {args.db} อยู่แล้ว — ใช้ --force เพื่อสร้างใหม่")

    for f in (PROJECTS_CSV, FINANCIAL_CSV):
        if not os.path.exists(f):
            sys.exit(f"ไม่พบไฟล์ {f} — วาง CSV ไว้โฟลเดอร์เดียวกับ script")

    print("[1/5] อ่าน CSV (กัน BOM + NUL byte)")
    proj_rows = read_csv_clean(PROJECTS_CSV)
    fin_rows = read_csv_clean(FINANCIAL_CSV)
    log(f"projects_ALL_master: {len(proj_rows)} แถว | financial_report_ALL_master: {len(fin_rows)} แถว")

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()

    print("[2/5] สร้าง schema (DDL §3–§8)")
    cur.executescript(DDL)

    print("[3/5] Seed ตามลำดับ §9.1")
    sub_id = seed_master_data(cur, proj_rows, fin_rows)
    seed_vendors(cur, proj_rows)
    seed_projects(cur, proj_rows, sub_id)
    seed_financial(cur, fin_rows, sub_id)
    seed_risk_factors(cur)
    seed_users_config(cur, sub_id)
    con.commit()

    print("[4/5] รัน risk engine ครั้งแรก")
    snapshot = json.dumps(
        [dict(factor_code=r[0], scope=r[1], params_json=r[2], weight=r[3], severity=r[4], enabled=r[5])
         for r in cur.execute("SELECT factor_code, scope, params_json, weight, severity, enabled FROM risk_factors")],
        ensure_ascii=False)
    cur.execute("INSERT INTO assessment_runs (triggered_by, factor_config_snapshot, note) VALUES (?,?,?)",
                ("system", snapshot, "initial seed run"))
    run_id = cur.lastrowid
    run_project_engine(cur, run_id)
    run_annual_engine(cur, run_id)
    con.commit()

    print("[5/5] Validation (§9.5)")
    ok = validate(cur)
    cross_check_pingkhong(cur)

    # สรุปภาพรวม
    print("\nสรุป risk (run ล่าสุด):")
    for row in cur.execute("""SELECT s.name_th, prs.risk_level, COUNT(*) FROM project_risk_scores prs
        JOIN projects p ON p.project_id=prs.project_id
        JOIN subdistricts s ON s.subdistrict_id=p.subdistrict_id
        WHERE prs.run_id=? GROUP BY s.name_th, prs.risk_level ORDER BY s.name_th""", (run_id,)):
        print(f"  {row[0]}: {row[1]} = {row[2]} โครงการ")

    con.close()
    if not ok:
        sys.exit("\nVALIDATION FAILED — ตรวจรายการ [FAIL] ด้านบน")
    print(f"\nเสร็จสมบูรณ์ → {args.db}")


if __name__ == "__main__":
    main()
