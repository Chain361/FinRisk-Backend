# -*- coding: utf-8 -*-
"""/users — GET รายชื่อ + PUT แก้ไข status/allowed_features (admin เท่านั้น)"""
from fastapi.testclient import TestClient

from src.database import db_session
from src.main import app

client = TestClient(app)

ADMIN = {"X-Username": "admin"}


def _yonok_user_id() -> int:
    with db_session() as con:
        return con.execute(
            "SELECT user_id FROM users WHERE username = ?", ("yonok_user",)
        ).fetchone()["user_id"]


def test_list_users_requires_admin():
    r = client.get("/users", headers={"X-Username": "thachang_user"})
    assert r.status_code == 403


def test_list_users_admin():
    r = client.get("/users", headers=ADMIN)
    assert r.status_code == 200
    users = r.json()
    assert any(u["username"] == "admin" for u in users)
    admin_row = next(u for u in users if u["username"] == "admin")
    assert admin_row["status"] == "active"
    assert admin_row["allowed_features"] == []


def test_update_user_not_found():
    r = client.put("/users/999999", headers=ADMIN, json={"status": "disabled"})
    assert r.status_code == 404


def test_update_user_requires_admin():
    user_id = _yonok_user_id()
    r = client.put(
        f"/users/{user_id}", headers={"X-Username": "thachang_user"}, json={"status": "disabled"}
    )
    assert r.status_code == 403


def test_update_user_invalid_status():
    user_id = _yonok_user_id()
    r = client.put(f"/users/{user_id}", headers=ADMIN, json={"status": "banned"})
    assert r.status_code == 422


def test_update_user_invalid_feature():
    user_id = _yonok_user_id()
    r = client.put(f"/users/{user_id}", headers=ADMIN, json={"allowed_features": ["not_a_real_feature"]})
    assert r.status_code == 422


def test_update_user_status_and_features():
    user_id = _yonok_user_id()
    try:
        r = client.put(
            f"/users/{user_id}",
            headers=ADMIN,
            json={"status": "disabled", "allowed_features": ["risk_dashboard", "chatbot"]},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "disabled"
        assert sorted(body["allowed_features"]) == ["chatbot", "risk_dashboard"]

        # partial update — ไม่ส่ง allowed_features ต้องไม่ถูกล้าง
        r = client.put(f"/users/{user_id}", headers=ADMIN, json={"status": "active"})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "active"
        assert sorted(body["allowed_features"]) == ["chatbot", "risk_dashboard"]
    finally:
        with db_session() as con:
            con.execute(
                "UPDATE users SET status = 'active', allowed_features = '{}' WHERE user_id = ?",
                (user_id,),
            )
            con.commit()
