# -*- coding: utf-8 -*-
"""Smoke test — ยืนยันว่า app boot ได้และ endpoint หลักทำงานกับ fraud_risk.db"""
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["db_exists"] is True


def test_login_and_scope():
    # login mock — รหัสผ่านทุก user = password123
    r = client.post("/auth/login", json={"username": "thachang_user", "password": "password123"})
    assert r.status_code == 200
    user = r.json()["user"]
    assert user["role"] == "municipality_user"

    headers = {"X-Username": "thachang_user"}
    # municipality_user เห็นเฉพาะตำบลตัวเอง (1 ตำบล)
    subs = client.get("/subdistricts", headers=headers).json()
    assert len(subs) == 1

    projects = client.get("/projects", headers=headers).json()
    assert all(p["subdistrict_id"] == user["subdistrict_id"] for p in projects)


def test_admin_sees_all():
    headers = {"X-Username": "admin"}
    subs = client.get("/subdistricts", headers=headers).json()
    assert len(subs) == 3
    summary = client.get("/risk/summary", headers=headers).json()
    assert summary["total"] > 0


def test_financial_statements_routes():
    headers = {"X-Username": "thachang_user"}

    r = client.get("/financial-statements", headers=headers)
    assert r.status_code == 200
    rows = r.json()
    assert rows
    assert all(row["subdistrict_id"] == 1 for row in rows)

    r2 = client.get("/financials", headers=headers)
    assert r2.status_code == 200
    assert len(r2.json()) == len(rows)


def test_wrong_password():
    r = client.post("/auth/login", json={"username": "admin", "password": "nope"})
    assert r.status_code == 401
