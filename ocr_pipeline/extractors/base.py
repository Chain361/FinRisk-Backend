# -*- coding: utf-8 -*-
"""Stage 1 — Extract (pluggable): interface เดียว extract(pdf_path) → markdown ต่อหน้า

extractor อ่าน "ตามที่พิมพ์" เท่านั้น — ไม่ตีความ (หลักการข้อ 1)
raw output ต่อหน้าถูก cache ลง work/<run_id>/ocr/ เสมอ (audit trail)
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PageMarkdown:
    page: int          # เลขหน้าเริ่มที่ 1
    markdown: str


class Extractor(ABC):
    name: str = "base"
    version: str | None = None

    @abstractmethod
    def extract(self, pdf_path: str) -> list[PageMarkdown]:
        """PDF ทั้งไฟล์ → markdown ต่อหน้า (ทุกหน้า — การเลือกหน้าเป็นเรื่องของ parse)"""
