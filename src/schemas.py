# -*- coding: utf-8 -*-
"""
schemas.py — Pydantic models (request/response)

เก็บ schema ที่ backend รับ-ส่งไว้ที่เดียว เพื่อให้ auto docs (/docs) อ่านง่าย
และ frontend generate type ได้จาก OpenAPI
"""
from typing import Literal

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    user_id: int
    username: str
    display_name: str | None = None
    role: str
    subdistrict_id: int | None = None


class LoginResponse(BaseModel):
    # mock token = username; production ให้เปลี่ยนเป็น JWT
    token: str
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


class AssignmentCreate(BaseModel):
    project_id: str
    assignee_id: int
    priority: Literal["low", "normal", "high"] = "normal"
    note: str
    due_date: str | None = None
    budget_hours: float | None = None
    audit_steps: str = ""


class AssignmentStatusUpdate(BaseModel):
    status: Literal[
        "waiting_acceptance",
        "accepted",
        "in_progress",
        "clarification_needed",
        "ready_for_review",
        "under_review",
        "revision_requested",
        "completed",
    ]


class AssignmentOut(BaseModel):
    assignment_id: int
    project_id: str
    assigned_to: int
    assigned_by: int
    priority: str
    note: str
    due_date: str | None = None
    budget_hours: float | None = None
    audit_steps: str
    status: str
    created_at: str
    updated_at: str
    project_name: str | None = None
    subdistrict_id: int | None = None
    assignee_username: str | None = None
    assignee_display_name: str | None = None
    assigned_by_username: str | None = None
    assigned_by_display_name: str | None = None


class AssignmentAssigneeOut(BaseModel):
    user_id: int
    username: str
    display_name: str | None = None
    subdistrict_id: int
    active_cases: int


class AuditReportCreate(BaseModel):
    work_process: str | None = None
    objective: str | None = None
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    # schema เดิมของ audit_reports แยก impact_score/risk_level ออกจาก impact โดยไม่มีเอกสารสูตรคำนวณ
    # รับตรงจาก client ไว้ก่อน (1-5 ตาม CHECK constraint) ไม่เดาสูตร derive เอง
    impact_score: int | None = Field(default=None, ge=1, le=5)
    risk_level: int | None = Field(default=None, ge=1, le=5)
    findings: str | None = None


class AuditReportOut(BaseModel):
    report_id: int
    assignment_id: int
    work_process: str | None = None
    objective: str | None = None
    likelihood: int | None = None
    impact: int | None = None
    impact_score: int | None = None
    risk_level: int | None = None
    findings: str | None = None
    submitted_at: str
