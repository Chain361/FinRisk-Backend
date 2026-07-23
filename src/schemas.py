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
