# -*- coding: utf-8 -*-
"""
schemas.py — Pydantic models (request/response)

เก็บ schema ที่ backend รับ-ส่งไว้ที่เดียว เพื่อให้ auto docs (/docs) อ่านง่าย
และ frontend generate type ได้จาก OpenAPI
"""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# feature flag ที่แจกจ่ายได้ผ่าน allowed_features — สอดคล้องกับ "Permissions" ต่อ role ใน roles.md
# (ใช้จำกัดสิทธิ์ย่อยรายคน นอกเหนือจาก role เดิม) แก้/เพิ่มได้ที่นี่ที่เดียว
ALLOWED_FEATURES = frozenset({
    "risk_dashboard",
    "fiscal_dashboard",
    "projects_view",
    "filter_by_subdistrict",
    "public_audit_info",
    "public_projects_export",
    "assign_audit_tasks",
    "team_reports",
    "chatbot",
    "audit_feedback",
    "auditor_feedback",
    "access_logs",
    "risk_engine",
    "user_management",
    "contact_report",
})


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    user_id: int
    username: str
    display_name: str | None = None
    role: str
    subdistrict_id: int | None = None
    status: Literal["active", "disabled"] = "active"
    allowed_features: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    """แก้ไขบางส่วน (partial) — ส่งเฉพาะ field ที่ต้องการเปลี่ยน ไม่แตะ username/password"""

    display_name: str | None = None
    role: str | None = None
    subdistrict_id: int | None = None
    status: Literal["active", "disabled"] | None = None
    allowed_features: list[str] | None = None

    @field_validator("allowed_features")
    @classmethod
    def _check_allowed_features(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        unknown = sorted(set(value) - ALLOWED_FEATURES)
        if unknown:
            raise ValueError(f"allowed_features ไม่รู้จัก: {', '.join(unknown)}")
        return value


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=6, max_length=200)
    display_name: str | None = None
    role: str
    subdistrict_id: int | None = None
    status: Literal["active", "disabled"] = "active"
    allowed_features: list[str] = Field(default_factory=list)

    @field_validator("allowed_features")
    @classmethod
    def _check_allowed_features(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - ALLOWED_FEATURES)
        if unknown:
            raise ValueError(f"allowed_features ไม่รู้จัก: {', '.join(unknown)}")
        return value


class LoginResponse(BaseModel):
    token: str  # JWT access token — แนบเป็น "Authorization: Bearer <token>"
    user: UserOut


class AuditorFeedbackIn(BaseModel):
    project_id: str
    feedback_text: str
    concern_level: Literal["low", "medium", "high"] | None = None
    likelihood_score: int | None = Field(default=None, ge=1, le=5)
    impact_score: int | None = Field(default=None, ge=1, le=5)
    suggestions: str | None = None
    status: Literal["draft", "submitted"] = "draft"


class AuditorFeedbackOut(BaseModel):
    feedback_id: int
    project_id: str
    auditor_username: str
    auditor_name: str | None = None
    feedback_text: str
    concern_level: str | None = None
    likelihood_score: int | None = None
    impact_score: int | None = None
    risk_score: int | None = None
    suggestions: str | None = None
    status: str
    created_at: str
    updated_at: str
    submitted_at: str | None = None
    resolved_at: str | None = None


class AuditReportOut(BaseModel):
    report_id: int | None = None
    feedback_id: int
    assignment_id: int
    project_id: str
    project_name: str
    dept_name: str | None = None
    work_process: str | None = None
    objective: str | None = None
    findings: str
    suggestions: str | None = None
    likelihood: int | None = None
    impact: int | None = None
    impact_score: int | None = None
    risk_level: int | None = None
    concern_level: str | None = None
    submitted_at: str | None = None


AssignmentPriority = Literal["low", "normal", "high"]
AssignmentStatus = Literal[
    "waiting_acceptance",
    "in_progress",
    "under_review",
    "completed",
]


class AssignmentCreate(BaseModel):
    project_id: str
    assignee_id: int
    priority: AssignmentPriority = "normal"
    note: str = Field(max_length=5000)
    due_date: str | None = None
    work_process: str = Field(default="", max_length=5000)
    work_objective: str = Field(default="", max_length=5000)
    # รองรับ client รุ่นก่อนที่ส่งฟิลด์รวมมาในช่วงเปลี่ยนผ่าน
    audit_steps: str | None = Field(default=None, max_length=10000)


class AssignmentUpdate(BaseModel):
    assignee_id: int | None = None
    priority: AssignmentPriority | None = None
    note: str | None = Field(default=None, min_length=1, max_length=5000)
    due_date: str | None = None
    work_process: str | None = Field(default=None, max_length=5000)
    work_objective: str | None = Field(default=None, max_length=5000)
    audit_steps: str | None = Field(default=None, max_length=10000)


class AssignmentStatusUpdate(BaseModel):
    status: AssignmentStatus
    note: str | None = Field(default=None, max_length=5000)


class AttachmentOut(BaseModel):
    attachment_id: int
    assignment_id: int
    file_name: str
    content_type: str
    file_size: int
    uploaded_by: int
    uploaded_by_display_name: str | None = None
    created_at: str


class ClarificationCreate(BaseModel):
    message_text: str = Field(min_length=1, max_length=5000)


class ClarificationOut(BaseModel):
    clarification_id: int
    assignment_id: int
    message_text: str
    created_by: int
    created_by_display_name: str | None = None
    created_at: str


class RiskEngineRunOut(BaseModel):
    run_id: int
    run_at: str
    triggered_by: str
    project_count: int
    annual_count: int


class DataUploadOut(BaseModel):
    subdistrict_id: int
    projects_inserted: int
    projects_skipped_duplicate: list[str]
    financial_rows_inserted: int


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(min_length=1, max_length=4000)


class LogRetentionRunOut(BaseModel):
    run_id: int
    run_at: str
    hot_days: int
    archive_days: int
    error_debug_days: int
    archive_cutoff: str
    delete_cutoff: str
    error_debug_cutoff: str
    archived_count: int
    deleted_count: int
    error_debug_deleted_count: int


class AccessLogHoldIn(BaseModel):
    log_id: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=1000)
    case_reference: str | None = Field(default=None, max_length=255)


class AccessLogHoldOut(BaseModel):
    hold_id: int
    log_id: int
    reason: str
    case_reference: str | None = None
    created_by: str | None = None
    created_at: str
