# -*- coding: utf-8 -*-
"""PDPA masking tests for vendor/project fields."""

import pytest
from fastapi.testclient import TestClient

from src.database import db_session
from src.main import app
from src.privacy import mask_person_name, mask_project_for_public, mask_sensitive_note, mask_tin

client = TestClient(app)


def test_privacy_helpers_mask_vendor_identifiers():
    assert mask_tin("1234567890123") == "*********0123"
    assert mask_tin("xxxxxx1234") == "xxxxxx1234"
    assert mask_person_name("นาย ตัวอย่าง") == "นาย ต*******"
    assert mask_person_name("บริษัท ตัวอย่าง จำกัด") == "บริษัท ตัวอย่าง จำกัด"
    assert mask_sensitive_note("ref 12345678 ok") == "ref [NUMBER] ok"


def test_public_project_payload_masks_vendor_and_contract_fields():
    project = {
        "project_id": "TEST-PDPA",
        "vendor_id": 9,
        "vendor_name": "นาย ตัวอย่าง",
        "vendor_tin": "1234567890123",
        "contract_no": "CN-123",
        "contract_status": "ลงนามแล้ว",
        "data_quality_note": "source tin 1234567890123",
    }

    masked = mask_project_for_public(project)

    assert masked["vendor_id"] is None
    assert masked["contract_no"] is None
    assert masked["contract_status"] is None
    assert masked["vendor_tin"] == "*********0123"
    assert masked["vendor_name"] == "นาย ต*******"
    assert "1234567890123" not in masked["data_quality_note"]


def test_public_project_detail_does_not_expose_raw_vendor_pii():
    with db_session() as con:
        row = con.execute(
            """SELECT p.project_id, p.contract_no, p.vendor_id, v.tin
               FROM projects p
               JOIN vendors v ON v.vendor_id = p.vendor_id
               WHERE v.tin IS NOT NULL AND v.tin <> ?
               LIMIT 1""",
            ("",),
        ).fetchone()

    if row is None:
        pytest.skip("seed database has no project joined to a vendor with TIN")

    raw = dict(row)
    public_response = client.get(
        f"/projects/{raw['project_id']}",
        headers={"X-Username": "public1"},
    )
    assert public_response.status_code == 200, public_response.text
    public_project = public_response.json()["project"]

    assert public_project["vendor_id"] is None
    assert public_project["contract_no"] is None
    assert public_project["vendor_tin"] != raw["tin"]
    assert raw["tin"] not in str(public_project)

    admin_response = client.get(
        f"/projects/{raw['project_id']}",
        headers={"X-Username": "admin"},
    )
    assert admin_response.status_code == 200, admin_response.text
    admin_project = admin_response.json()["project"]
    assert admin_project["vendor_id"] == raw["vendor_id"]
    assert admin_project["contract_no"] == raw["contract_no"]
    assert admin_project["vendor_tin"] == raw["tin"]
