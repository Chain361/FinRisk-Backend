# -*- coding: utf-8 -*-
"""PDPA-oriented masking helpers for procurement project/vendor data."""

from __future__ import annotations

import re

PERSON_VENDOR_PREFIXES = ("นาย", "นาง", "นางสาว", "ร้าน")
PUBLIC_PROJECT_REDACTED_FIELDS = {
    "contract_no",
    "contract_date",
    "contract_finish_date",
    "contract_duration_days",
    "contract_status",
    "vendor_id",
}
_LONG_DIGIT_RE = re.compile(r"\d{4,}")


def is_person_vendor_name(name: str | None) -> bool:
    text = (name or "").strip()
    return text.startswith(PERSON_VENDOR_PREFIXES)


def mask_tin(tin: str | None) -> str | None:
    if not tin:
        return None
    text = str(tin).strip()
    if not text:
        return None
    if "x" in text.lower():
        return text
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 4:
        return "[MASKED]"
    return "*" * max(len(digits) - 4, 0) + digits[-4:]


def mask_person_name(name: str | None) -> str | None:
    text = (name or "").strip()
    if not text:
        return None
    if not is_person_vendor_name(text):
        return text
    parts = text.split()
    if not parts:
        return "[MASKED]"
    masked_parts = []
    for part in parts:
        if part in PERSON_VENDOR_PREFIXES:
            masked_parts.append(part)
        elif len(part) <= 1:
            masked_parts.append("*")
        else:
            masked_parts.append(part[0] + "*" * (len(part) - 1))
    return " ".join(masked_parts)


def coarse_coordinate(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def mask_sensitive_note(value: str | None) -> str | None:
    if value is None:
        return None
    return _LONG_DIGIT_RE.sub("[NUMBER]", value)


def mask_project_for_public(project: dict) -> dict:
    """Return a public-safe project detail payload."""
    masked = dict(project)
    for field in PUBLIC_PROJECT_REDACTED_FIELDS:
        if field in masked:
            masked[field] = None
    if "tin" in masked:
        masked["tin"] = mask_tin(masked["tin"])
    if "vendor_tin" in masked:
        masked["vendor_tin"] = mask_tin(masked["vendor_tin"])
    if "winner_tin" in masked:
        masked["winner_tin"] = mask_tin(masked["winner_tin"])
    if "vendor_name" in masked:
        masked["vendor_name"] = mask_person_name(masked["vendor_name"])
    if "winner_name" in masked:
        masked["winner_name"] = mask_person_name(masked["winner_name"])
    if "latitude" in masked:
        masked["latitude"] = coarse_coordinate(masked["latitude"])
    if "longitude" in masked:
        masked["longitude"] = coarse_coordinate(masked["longitude"])
    if "data_quality_note" in masked:
        masked["data_quality_note"] = mask_sensitive_note(masked["data_quality_note"])
    return masked
