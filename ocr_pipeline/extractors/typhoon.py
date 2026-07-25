# -*- coding: utf-8 -*-
"""Typhoon OCR extractor (default) — เขียนตามแนว pipeline v1 (extract_typhoon.py)

ต้องมี env TYPHOON_OCR_API_KEY + ติดตั้ง `pip install typhoon-ocr pypdf` และ poppler-utils
⚠️ ในสภาพแวดล้อมทดสอบไม่มี network/API key — โหมดทดสอบใช้ `--from-ocr` เท่านั้น (D7)
"""
import os
import subprocess
import sys

from ocr_pipeline.extractors.base import Extractor, PageMarkdown

# Fix Windows cp874 encoding: subprocess.run(text=True) ใช้ default encoding ของ OS
# ซึ่งบน Windows ไทยคือ cp874 — pdfinfo ของ typhoon_ocr ส่ง UTF-8 กลับมา decode ไม่ได้
# patch ให้ text-mode subprocess ใช้ UTF-8 เสมอ → ใช้ได้ทุกเครื่องไม่ต้องตั้ง env
if sys.platform == "win32":
    _orig_subprocess_run = subprocess.run

    def _utf8_subprocess_run(*args, **kwargs):
        if kwargs.get("text") and "encoding" not in kwargs:
            kwargs["encoding"] = "utf-8"
        return _orig_subprocess_run(*args, **kwargs)

    subprocess.run = _utf8_subprocess_run


class TyphoonExtractor(Extractor):
    name = "typhoon"

    def __init__(self, task_type: str = "v1.5", model: str = "typhoon-ocr"):
        self.task_type = task_type
        self.model = model
        try:
            from importlib.metadata import version
            self.version = version("typhoon-ocr")
        except Exception:
            self.version = None

    def extract(self, pdf_path: str) -> list[PageMarkdown]:
        if not os.getenv("TYPHOON_OCR_API_KEY"):
            raise RuntimeError("ต้องตั้ง env TYPHOON_OCR_API_KEY ก่อน (สมัครฟรีที่ opentyphoon.ai)")
        from pypdf import PdfReader
        from typhoon_ocr import ocr_document

        n_pages = len(PdfReader(pdf_path).pages)
        pages = []
        for i in range(1, n_pages + 1):
            md = ocr_document(pdf_or_image_path=pdf_path, task_type=self.task_type,
                              page_num=i, model=self.model)
            pages.append(PageMarkdown(page=i, markdown=md))
        return pages
