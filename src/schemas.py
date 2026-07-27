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


AssignmentPriority = Literal["low", "normal", "high"]
AssignmentStatus = Literal[
    "waiting_acceptance",
    "accepted",
    "in_progress",
    "clarification_needed",
    "ready_for_review",
    "under_review",
    "revision_requested",
    "completed",
]


class AssignmentCreate(BaseModel):
    project_id: str
    assignee_id: int
    priority: AssignmentPriority = "normal"
    note: str = Field(min_length=1, max_length=5000)
    due_date: str | None = None


class AssignmentUpdate(BaseModel):
    assignee_id: int | None = None
    priority: AssignmentPriority | None = None
    note: str | None = Field(default=None, min_length=1, max_length=5000)
    due_date: str | None = None


class AssignmentStatusUpdate(BaseModel):
    status: AssignmentStatus
    note: str | None = Field(default=None, max_length=5000)


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


class ChatMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # ประวัติแชทฝั่ง client ถืออยู่ ส่งมาทุกครั้ง — backend ไม่เก็บ conversation state
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
