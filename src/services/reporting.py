# -*- coding: utf-8 -*-
"""Helpers สำหรับ export รายงานผลตรวจและทะเบียนความเสี่ยง."""
from __future__ import annotations

import html
import io
import re
from datetime import datetime
from pathlib import Path

import xlsxwriter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..database import Connection, rows_to_dicts
from .common import ForbiddenError, NotFoundError, latest_run_id

_FONT_NAME = "NotoSansThai"
_FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NotoSansThai.ttf"
_FORMULA_PREFIXES = ("=", "+", "-", "@")
_THAI_MONTHS = (
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
)
_SUBDISTRICT_SLUGS = {
    "ท่าช้าง": "thachang",
    "ปิงโค้ง": "pingkhong",
    "โยนก": "yonok",
}


def _font_name() -> str:
    """ลงทะเบียนฟอนต์ไทยที่ bundle มากับแอปเพียงครั้งเดียวต่อ process."""
    if _FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_FONT_NAME, str(_FONT_PATH)))
    return _FONT_NAME


def _excel_safe(value):
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _as_dict(row) -> dict:
    return dict(row) if row is not None else {}


def _filename_token(value: str, fallback: str) -> str:
    """สร้าง token แบบ ASCII ที่ปลอดภัยกับชื่อไฟล์ทุกระบบปฏิบัติการ."""
    token = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value).strip()).strip("-_")
    return token.lower() or fallback


def _subdistrict_slug(name: str | None) -> str:
    if name in _SUBDISTRICT_SLUGS:
        return _SUBDISTRICT_SLUGS[name]
    return _filename_token(name or "", "unknown_subdistrict")


def risk_register_filename(rows: list[dict], generated_at: datetime) -> str:
    """ตั้งชื่อทะเบียนตามตำบลที่อยู่ในไฟล์ หรือ all_subdistricts เมื่อมีหลายตำบล."""
    subdistricts = {row.get("subdistrict") for row in rows if row.get("subdistrict")}
    scope = _subdistrict_slug(next(iter(subdistricts))) if len(subdistricts) == 1 else "all_subdistricts"
    return f"finrisk_risk_register_{scope}_{generated_at:%Y%m%d_%H%M%S}.xlsx"


def audit_report_filename(data: dict, extension: str) -> str:
    """ตั้งชื่อรายงานด้วย project_id, ตำบล และ report_id ที่อ้างอิงกลับได้แน่นอน."""
    project_id = _filename_token(data["project_id"], "project")
    subdistrict = _subdistrict_slug(data.get("subdistrict"))
    return f"finrisk_audit_report_{project_id}_{subdistrict}_{data['report_id']}.{extension}"


def _thai_date(value: str | None) -> str:
    """แสดงวันรายงานด้วยปีพุทธศักราช โดยรับ timestamp ของฐานข้อมูลได้."""
    if not value:
        return "-"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return f"{parsed.day} {_THAI_MONTHS[parsed.month - 1]} {parsed.year + 543}"


def _scope_clause(conn: Connection, user: dict, column: str) -> tuple[str, list]:
    from ..auth import scope_subdistrict_ids

    allowed = scope_subdistrict_ids(conn, user)
    if allowed is None:
        return "", []
    if not allowed:
        return " AND 1 = 0", []
    return f" AND {column} IN ({','.join('?' * len(allowed))})", list(allowed)


def risk_register_rows(conn: Connection, user: dict) -> list[dict]:
    """คืนข้อมูลทะเบียนความเสี่ยงของรอบล่าสุด โดยบังคับ scope ระดับตำบล."""
    run_id = latest_run_id(conn)
    if run_id is None:
        return []
    scope_sql, scope_params = _scope_clause(conn, user, "p.subdistrict_id")
    rows = conn.execute(
        f"""SELECT v.project_id, v.project_name, v.subdistrict, v.budget_year,
                   v.risk_score, v.risk_level, v.matrix_level, v.summary_text,
                   v.factor_code, v.factor_name, v.legal_ref, v.triggered, v.computable,
                   v.observed_value, v.threshold_used, v.evidence_text,
                   v.likelihood, v.impact, v.matrix_score, v.risk_band
            FROM v_project_risk_detail v
            JOIN projects p ON p.project_id = v.project_id
            WHERE 1 = 1 {scope_sql}
            ORDER BY v.subdistrict, v.budget_year DESC, v.project_id, v.factor_code""",
        scope_params,
    ).fetchall()
    return rows_to_dicts(rows)


def audit_report_data(conn: Connection, report_id: int, user: dict) -> dict:
    """โหลดรายงานและข้อมูลประกอบ พร้อมตรวจสิทธิ์จากตำบลของโครงการ."""
    scope_sql, scope_params = _scope_clause(conn, user, "p.subdistrict_id")
    report = conn.execute(
        f"""SELECT r.*, a.project_id, a.status AS assignment_status, a.priority,
                   a.note AS assignment_note, p.project_name, p.budget_year,
                   p.budget_amount, p.dept_name, s.name_th AS subdistrict,
                   analyst.display_name AS analyst_name,
                   auditor.display_name AS auditor_name
            FROM audit_reports r
            JOIN assignments a ON a.assignment_id = r.assignment_id
            JOIN projects p ON p.project_id = a.project_id
            JOIN subdistricts s ON s.subdistrict_id = p.subdistrict_id
            JOIN users analyst ON analyst.user_id = a.assigned_to
            JOIN users auditor ON auditor.user_id = a.assigned_by
            WHERE r.report_id = ? {scope_sql}""",
        [report_id, *scope_params],
    ).fetchone()
    if report is None:
        exists = conn.execute("SELECT 1 FROM audit_reports WHERE report_id = ?", (report_id,)).fetchone()
        if exists:
            raise ForbiddenError("ไม่มีสิทธิ์เข้าถึงรายงานนอกพื้นที่ของคุณ")
        raise NotFoundError("ไม่พบรายงานผลตรวจ")

    data = _as_dict(report)
    feedback = conn.execute(
        """SELECT f.feedback_id, f.feedback_text, f.suggestions, f.concern_level,
                  f.likelihood_score, f.impact_score, f.status, f.submitted_at,
                  u.display_name AS auditor_name
           FROM auditor_feedback f
           JOIN users u ON u.user_id = f.user_id
           WHERE f.project_id = ? AND f.status IN ('submitted', 'resolved')
           ORDER BY f.submitted_at, f.feedback_id""",
        (data["project_id"],),
    ).fetchall()
    data["findings_items"] = rows_to_dicts(feedback)
    data["risk_factors"] = [
        row for row in risk_register_rows(conn, user) if row["project_id"] == data["project_id"]
    ]
    return data


def build_risk_register_xlsx(rows: list[dict], generated_at: datetime | None = None) -> bytes:
    """สร้างทะเบียนความเสี่ยง Excel โดยไม่ส่งค่า string ให้ Excel ประมวลผลเป็น formula."""
    generated_at = generated_at or datetime.now()
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    sheet = workbook.add_worksheet("ทะเบียนความเสี่ยง")
    title = workbook.add_format({"bold": True, "font_size": 16, "font_name": "Tahoma"})
    meta = workbook.add_format({"font_name": "Tahoma", "font_color": "#666666"})
    header = workbook.add_format({
        "bold": True, "font_name": "Tahoma", "font_color": "#FFFFFF",
        "bg_color": "#1F4E78", "border": 1, "text_wrap": True, "valign": "vcenter",
    })
    cell = workbook.add_format({"font_name": "Tahoma", "border": 1, "valign": "top"})
    number = workbook.add_format({"font_name": "Tahoma", "border": 1, "num_format": "#,##0.00"})
    high = workbook.add_format({"font_name": "Tahoma", "border": 1, "bg_color": "#FCE4D6", "valign": "top"})

    sheet.merge_range("A1:T1", "ทะเบียนความเสี่ยงโครงการ", title)
    sheet.merge_range("A2:T2", f"สร้างเมื่อ { _thai_date(generated_at.isoformat()) }", meta)
    columns = [
        ("รหัสโครงการ", "project_id", 16), ("ชื่อโครงการ", "project_name", 36),
        ("ตำบล", "subdistrict", 18), ("ปีงบประมาณ", "budget_year", 12),
        ("คะแนนความเสี่ยง", "risk_score", 15), ("ระดับความเสี่ยง", "risk_level", 15),
        ("รหัสปัจจัย", "factor_code", 14), ("ปัจจัยความเสี่ยง", "factor_name", 30),
        ("ประเมินได้", "computable", 12), ("เข้าเกณฑ์", "triggered", 12),
        ("ค่าที่พบ", "observed_value", 20), ("เกณฑ์", "threshold_used", 20),
        ("หลักฐาน", "evidence_text", 42), ("อ้างอิงกฎหมาย", "legal_ref", 25),
        ("โอกาส", "likelihood", 10), ("ผลกระทบ", "impact", 10),
        ("คะแนนเมทริกซ์", "matrix_score", 15), ("แถบความเสี่ยง", "risk_band", 15),
        ("ระดับเมทริกซ์", "matrix_level", 16), ("สรุป", "summary_text", 42),
    ]
    for index, (label, _, width) in enumerate(columns):
        sheet.write(3, index, label, header)
        sheet.set_column(index, index, width)
    sheet.set_row(3, 35)
    for row_index, row in enumerate(rows, 4):
        row_format = high if row.get("risk_level") == "high" else cell
        for col_index, (_, field, _) in enumerate(columns):
            value = _excel_safe(row.get(field))
            if field in {"risk_score", "matrix_score"} and value is not None:
                sheet.write_number(row_index, col_index, value, number)
            elif field in {"computable", "triggered"}:
                sheet.write(row_index, col_index, "ใช่" if value else "ไม่ใช่", row_format)
            else:
                sheet.write(row_index, col_index, value, row_format)
    sheet.autofilter(3, 0, max(3, len(rows) + 3), len(columns) - 1)
    sheet.freeze_panes(4, 0)
    workbook.close()
    return output.getvalue()


def build_audit_report_xlsx(data: dict) -> bytes:
    """สร้าง Excel รายงานผลตรวจ พร้อม sheet สรุป ข้อตรวจพบ และปัจจัยเสี่ยง."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    title = workbook.add_format({"bold": True, "font_size": 16, "font_name": "Tahoma"})
    label = workbook.add_format({"bold": True, "font_name": "Tahoma", "bg_color": "#D9EAF7", "border": 1})
    value = workbook.add_format({"font_name": "Tahoma", "border": 1, "text_wrap": True, "valign": "top"})
    header = workbook.add_format({"bold": True, "font_name": "Tahoma", "font_color": "#FFFFFF", "bg_color": "#1F4E78", "border": 1})

    summary = workbook.add_worksheet("สรุปรายงาน")
    summary.merge_range("A1:B1", "รายงานผลการตรวจสอบ", title)
    fields = [
        ("เลขที่รายงาน", f"FINRISK-{data['report_id']:04d}"),
        ("โครงการ", data["project_name"]), ("ตำบล", data["subdistrict"]),
        ("ปีงบประมาณ", data["budget_year"]), ("วันที่รายงาน", _thai_date(data.get("submitted_at"))),
        ("ผู้ตรวจสอบ", data.get("analyst_name") or "-"),
        ("ผู้มอบหมาย/ผู้พิจารณา", data.get("auditor_name") or "-"),
        ("กระบวนงาน", data.get("work_process") or "-"),
        ("วัตถุประสงค์", data.get("objective") or "-"),
        ("สรุปผล", data.get("findings") or "-"),
    ]
    for row_index, (name, field_value) in enumerate(fields, 2):
        summary.write(row_index, 0, name, label)
        summary.write(row_index, 1, _excel_safe(field_value), value)
    summary.set_column("A:A", 28)
    summary.set_column("B:B", 90)

    findings = workbook.add_worksheet("ข้อตรวจพบ")
    finding_columns = ["ลำดับ", "ผู้บันทึก", "ข้อตรวจพบ", "ข้อเสนอแนะ", "ระดับความกังวล", "คะแนนความเสี่ยง", "สถานะ"]
    for column, name in enumerate(finding_columns):
        findings.write(0, column, name, header)
    for row_index, item in enumerate(data["findings_items"], 1):
        values = [
            row_index, item.get("auditor_name"), item.get("feedback_text"), item.get("suggestions"),
            item.get("concern_level"),
            (item.get("likelihood_score") or 0) * (item.get("impact_score") or 0), item.get("status"),
        ]
        for column, field_value in enumerate(values):
            findings.write(row_index, column, _excel_safe(field_value), value)
    findings.set_column("A:A", 10)
    findings.set_column("B:B", 24)
    findings.set_column("C:D", 55)
    findings.set_column("E:G", 18)

    factors = workbook.add_worksheet("ปัจจัยความเสี่ยง")
    factor_columns = ["รหัส", "ปัจจัย", "ระดับ", "ผลประเมิน", "หลักฐาน", "อ้างอิงกฎหมาย"]
    for column, name in enumerate(factor_columns):
        factors.write(0, column, name, header)
    for row_index, item in enumerate(data["risk_factors"], 1):
        values = [
            item.get("factor_code"), item.get("factor_name"), item.get("risk_band") or item.get("risk_level"),
            "เข้าเกณฑ์" if item.get("triggered") else "ไม่เข้าเกณฑ์", item.get("evidence_text"), item.get("legal_ref"),
        ]
        for column, field_value in enumerate(values):
            factors.write(row_index, column, _excel_safe(field_value), value)
    factors.set_column("A:A", 14)
    factors.set_column("B:B", 32)
    factors.set_column("C:D", 18)
    factors.set_column("E:E", 55)
    factors.set_column("F:F", 28)
    workbook.close()
    return output.getvalue()


def _paragraph(value, style: ParagraphStyle) -> Paragraph:
    text = html.escape(str(value or "-"), quote=False).replace("\n", "<br/>")
    return Paragraph(text, style)


def build_audit_report_pdf(data: dict) -> bytes:
    """สร้างรายงาน PDF แบบ static ตามโครงบทสรุปและข้อตรวจพบในคู่มือ Performance Audit."""
    font = _font_name()
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, rightMargin=1.7 * cm, leftMargin=1.7 * cm,
        topMargin=2.8 * cm, bottomMargin=2.3 * cm,
        title=f"รายงานผลการตรวจสอบ {data['project_name']}", author="FinRisk",
    )
    styles = getSampleStyleSheet()
    heading = ParagraphStyle("ThaiHeading", parent=styles["Heading1"], fontName=font, fontSize=18, leading=25, alignment=TA_CENTER)
    subheading = ParagraphStyle("ThaiSubheading", parent=styles["Heading2"], fontName=font, fontSize=14, leading=20, spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("ThaiBody", parent=styles["BodyText"], fontName=font, fontSize=11, leading=18, spaceAfter=6)
    small = ParagraphStyle("ThaiSmall", parent=body, fontSize=9, leading=13)
    finding_title = ParagraphStyle("ThaiFinding", parent=body, fontSize=12, leading=18, backColor=colors.HexColor("#FFF2CC"), borderColor=colors.HexColor("#C9A500"), borderWidth=0.5, borderPadding=5, spaceBefore=12)

    def page_decoration(canvas, doc):
        canvas.saveState()
        canvas.setFont(font, 9)
        canvas.setFillColor(colors.HexColor("#444444"))
        canvas.drawString(1.7 * cm, A4[1] - 1.35 * cm, "FinRisk - รายงานผลการตรวจสอบ")
        canvas.setStrokeColor(colors.HexColor("#9E3D3D"))
        canvas.line(1.7 * cm, A4[1] - 1.55 * cm, A4[0] - 1.7 * cm, A4[1] - 1.55 * cm)
        footer = f"รายงานผลการตรวจสอบโครงการ {data['project_name']} | หน้า {doc.page}"
        canvas.setFont(font, 8)
        canvas.drawString(1.7 * cm, 1.2 * cm, footer)
        canvas.restoreState()

    metadata = [
        ["เลขที่รายงาน", f"FINRISK-{data['report_id']:04d}"],
        ["หน่วยรับตรวจ", data["subdistrict"]],
        ["โครงการ", data["project_name"]],
        ["ปีงบประมาณ", str(data["budget_year"])],
        ["วันที่รายงาน", _thai_date(data.get("submitted_at"))],
        ["ผู้ตรวจสอบ", data.get("analyst_name") or "-"],
        ["ผู้พิจารณา", data.get("auditor_name") or "-"],
    ]
    story = [
        Paragraph("รายงานผลการตรวจสอบ", heading),
        Paragraph(f"ผลการดำเนินโครงการ {html.escape(str(data['project_name']))}", ParagraphStyle("Project", parent=body, alignment=TA_CENTER)),
        Spacer(1, 0.25 * cm),
        Table(metadata, colWidths=[4.1 * cm, 12.0 * cm], style=TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font), ("FONTSIZE", (0, 0), (-1, -1), 10),
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#D9EAF7")), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#A6A6A6")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ])),
        Paragraph("บทสรุปผู้บริหาร", subheading),
        _paragraph(data.get("findings") or data.get("assignment_note"), body),
        Paragraph("บทที่ 1 บทนำ", subheading),
        _paragraph(f"กระบวนงาน: {data.get('work_process') or '-'}", body),
        _paragraph(f"วัตถุประสงค์: {data.get('objective') or '-'}", body),
        _paragraph(f"ขอบเขต: ตรวจสอบโครงการ {data['project_name']} ของ {data['subdistrict']}", body),
        PageBreak(),
        Paragraph("บทที่ 3 สรุปผลการตรวจสอบ และข้อเสนอแนะ", heading),
    ]
    if not data["findings_items"]:
        story.append(_paragraph("ยังไม่มีข้อตรวจพบที่ส่งแล้วสำหรับโครงการนี้", body))
    for index, item in enumerate(data["findings_items"], 1):
        score = (item.get("likelihood_score") or 0) * (item.get("impact_score") or 0)
        story.extend([
            _paragraph(f"ข้อตรวจพบ/ข้อสังเกตที่ {index}", finding_title),
            _paragraph("หลักเกณฑ์: ตรวจสอบตามระเบียบและหลักฐานที่เกี่ยวข้องกับโครงการ", body),
            _paragraph(f"สิ่งที่เป็นอยู่: {item.get('feedback_text') or '-'}", body),
            _paragraph("สาเหตุ: ยังไม่มีข้อมูลสาเหตุที่ผู้ตรวจบันทึกไว้", body),
            _paragraph(f"ผลกระทบ: ระดับความกังวล {item.get('concern_level') or '-'} (คะแนน {score})", body),
            _paragraph(f"ข้อเสนอแนะ: {item.get('suggestions') or '-'}", body),
        ])
    if data["risk_factors"]:
        story.append(Paragraph("ปัจจัยความเสี่ยงประกอบ", subheading))
        factor_rows = [[_paragraph("ปัจจัย", small), _paragraph("ผล", small), _paragraph("หลักฐาน", small)]]
        for item in data["risk_factors"]:
            factor_rows.append([
                _paragraph(item.get("factor_name"), small),
                _paragraph("เข้าเกณฑ์" if item.get("triggered") else "ไม่เข้าเกณฑ์", small),
                _paragraph(item.get("evidence_text"), small),
            ])
        story.append(Table(factor_rows, colWidths=[5.2 * cm, 2.3 * cm, 9.0 * cm], repeatRows=1, style=TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9EAF7")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#A6A6A6")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ])))
    document.build(story, onFirstPage=page_decoration, onLaterPages=page_decoration)
    return output.getvalue()
