# -*- coding: utf-8 -*-
"""/users — GET รายชื่อ + POST สร้าง + PUT แก้ไข + DELETE ลบ (admin เท่านั้น)"""
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


def _admin_user_id() -> int:
    with db_session() as con:
        return con.execute(
            "SELECT user_id FROM users WHERE username = ?", ("admin",)
        ).fetchone()["user_id"]


def _delete_test_user(username: str) -> None:
    with db_session() as con:
        con.execute("DELETE FROM users WHERE username = ?", (username,))
        con.commit()


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


def test_create_user_requires_admin():
    r = client.post(
        "/users",
        headers={"X-Username": "thachang_user"},
        json={"username": "temp_test_user", "password": "password123", "role": "public_user"},
    )
    assert r.status_code == 403


def test_create_user_success():
    try:
        r = client.post(
            "/users",
            headers=ADMIN,
            json={
                "username": "temp_test_user",
                "password": "password123",
                "display_name": "ผู้ใช้ทดสอบ",
                "role": "public_user",
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["username"] == "temp_test_user"
        assert body["display_name"] == "ผู้ใช้ทดสอบ"
        assert body["role"] == "public_user"
        assert body["status"] == "active"
        assert body["allowed_features"] == []

        listed = client.get("/users", headers=ADMIN).json()
        assert any(u["username"] == "temp_test_user" for u in listed)
    finally:
        _delete_test_user("temp_test_user")


def test_create_user_duplicate_username():
    r = client.post(
        "/users",
        headers=ADMIN,
        json={"username": "admin", "password": "password123", "role": "public_user"},
    )
    assert r.status_code == 422


def test_create_user_invalid_role():
    r = client.post(
        "/users",
        headers=ADMIN,
        json={"username": "temp_test_user", "password": "password123", "role": "not_a_real_role"},
    )
    assert r.status_code == 422


def test_delete_user_requires_admin():
    user_id = _yonok_user_id()
    r = client.delete(f"/users/{user_id}", headers={"X-Username": "thachang_user"})
    assert r.status_code == 403


def test_delete_user_not_found():
    r = client.delete("/users/999999", headers=ADMIN)
    assert r.status_code == 404


def test_delete_user_cannot_delete_self():
    admin_id = _admin_user_id()
    r = client.delete(f"/users/{admin_id}", headers=ADMIN)
    assert r.status_code == 422


def test_delete_user_success():
    created = client.post(
        "/users",
        headers=ADMIN,
        json={"username": "temp_test_user", "password": "password123", "role": "public_user"},
    ).json()

    r = client.delete(f"/users/{created['user_id']}", headers=ADMIN)
    assert r.status_code == 204

    listed = client.get("/users", headers=ADMIN).json()
    assert not any(u["username"] == "temp_test_user" for u in listed)
