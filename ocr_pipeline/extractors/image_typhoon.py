# -*- coding: utf-8 -*-
"""Typhoon OCR extractor สำหรับ "ไฟล์ภาพ" (PNG/JPG) — ใช้กับเอกสาร ปร.4/5/6 ใน raw_documents/

ทำไมต้องมีคลาสนี้: `TyphoonExtractor` เดิมนับจำนวนหน้าด้วย `PdfReader(pdf_path).pages`
ซึ่งโยน exception ทันทีถ้าไฟล์เป็น PNG แต่ `typhoon_ocr.ocr_document` รับไฟล์ภาพอยู่แล้ว
(พารามิเตอร์ชื่อ `pdf_or_image_path`) จึงเหลือแค่ข้ามขั้นตอนนับหน้า → ภาพ 1 ไฟล์ = 1 หน้า

interface เหมือนเดิมทุกอย่าง (`extract() -> list[PageMarkdown]`) — เมื่อเอกสารจริงเป็น PDF
หลายหน้าให้กลับไปใช้ `TyphoonExtractor` ได้โดยไม่ต้องแก้ผู้เรียก
(ดู `scripts/ingest_documents.py` ที่เลือก extractor ตามนามสกุลไฟล์ และ docs/rag_pinecone_plan.md §6.4)
"""
import os

from ocr_pipeline.extractors.base import PageMarkdown
from ocr_pipeline.extractors.typhoon import TyphoonExtractor

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}


class ImageTyphoonExtractor(TyphoonExtractor):
    name = "typhoon-image"

    def extract(self, image_path: str) -> list[PageMarkdown]:
        if not os.getenv("TYPHOON_OCR_API_KEY"):
            raise RuntimeError("ต้องตั้ง env TYPHOON_OCR_API_KEY ก่อน (สมัครฟรีที่ opentyphoon.ai)")
        from typhoon_ocr import ocr_document

        md = ocr_document(
            pdf_or_image_path=image_path,
            task_type=self.task_type,
            page_num=1,          # ภาพ 1 ไฟล์ = 1 หน้าเสมอ
            model=self.model,
        )
        return [PageMarkdown(page=1, markdown=md)]
