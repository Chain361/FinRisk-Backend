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
