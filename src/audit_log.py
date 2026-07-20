# -*- coding: utf-8 -*-
"""
audit_log.py — บันทึกการเข้าถึงของผู้ใช้ (access / activity log)

เป้าหมาย: accountability สำหรับหน่วยงานราชการ — ตรวจย้อนได้ว่า "ใครเข้าดู/ทำอะไร
กับ resource ไหน เมื่อไหร่" เขียนโดย middleware ใน main.py หลัง response พร้อมแล้ว

หลักการ:
- **best-effort เสมอ** — การบันทึก log ต้องไม่ทำให้ request พัง ถ้าเขียนไม่สำเร็จ
  (เช่น filesystem อ่านอย่างเดียวบน serverless) ให้เงียบ ๆ ข้ามไป
- **append-only** — insert อย่างเดียว ไม่มี update/delete (กันลบร่องรอย)
- เก็บ username/role แบบ denormalize เพื่อคง snapshot ณ เวลาเกิด action
"""
import logging
import sqlite3

log = logging.getLogger("finrisk.audit")

# path ที่ไม่ต้องบันทึก (noise: health check, docs, preflight, static)
_SKIP_PREFIXES = ("/health", "/docs", "/openapi", "/redoc", "/favicon", "/static")

# map path segment แรก → ชนิด resource ที่มนุษย์อ่านเข้าใจ
_RESOURCE_MAP = {
    "projects": "project",
    "risk": "risk",
    "subdistricts": "subdistrict",
    "financials": "financial",
    "audit": "audit",
    "auth": "auth",
}


def should_log(method: str, path: str) -> bool:
    """True เมื่อ request นี้ควรถูกบันทึก (ข้าม preflight + endpoint noise)"""
    if method == "OPTIONS":  # CORS preflight — ไม่ใช่ action ของผู้ใช้
        return False
    if path == "/":
        return False
    return not path.startswith(_SKIP_PREFIXES)


def derive_action_resource(method: str, path: str) -> tuple[str, str | None, str | None]:
    """แปลง (method, path) → (action, resource_type, resource_id) ที่อ่านเข้าใจง่าย"""
    segments = [s for s in path.split("/") if s]
    resource_type = _RESOURCE_MAP.get(segments[0]) if segments else None
    resource_id = segments[1] if len(segments) >= 2 else None

    if path.endswith("/auth/login"):
        action = "login"
    elif "export" in segments:
        action = "export"
    elif method == "GET":
        # มี id ต่อท้าย = ดูรายละเอียด, ไม่มี = ดูรายการ
        action = "view_detail" if resource_id and not resource_id.isalpha() else "view_list"
    elif method in ("POST", "PUT", "PATCH", "DELETE"):
        action = "write"
    else:
        action = method.lower()

    return action, resource_type, resource_id


def record_access(
    *,
    username: str,
    method: str,
    path: str,
    status_code: int,
    ip: str | None,
    user_agent: str | None,
    connect,
) -> None:
    """
    เขียน 1 แถวลง access_log แบบ best-effort.
    `connect` = callable ที่คืน sqlite3.Connection (ส่ง database._connect เข้ามา
    เพื่อไม่ผูก dependency วนกับ database module)
    """
    action, resource_type, resource_id = derive_action_resource(method, path)
    try:
        conn: sqlite3.Connection = connect()
        try:
            role_row = conn.execute(
                "SELECT role FROM users WHERE username = ?", (username,)
            ).fetchone()
            role = role_row["role"] if role_row else None
            conn.execute(
                """INSERT INTO access_log
                   (username, role, action, method, path, resource_type, resource_id,
                    status_code, ip, user_agent)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (username, role, action, method, path, resource_type, resource_id,
                 status_code, ip, user_agent),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 — logging ต้องไม่ทำให้ request พัง
        # เช่น DB อ่านอย่างเดียวบน serverless / ตารางยังไม่มี — ข้ามแบบเงียบ (เตือนใน log ระดับ debug)
        log.debug("access_log write skipped: %s", exc)
