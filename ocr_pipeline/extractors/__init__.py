# -*- coding: utf-8 -*-
from ocr_pipeline.extractors.base import Extractor, PageMarkdown


def get_extractor(name: str) -> Extractor:
    if name == "typhoon":
        from ocr_pipeline.extractors.typhoon import TyphoonExtractor
        return TyphoonExtractor()
    if name == "typhoon-image":
        from ocr_pipeline.extractors.image_typhoon import ImageTyphoonExtractor
        return ImageTyphoonExtractor()
    raise ValueError(f"ไม่รู้จัก extractor: {name}")


def extractor_for_path(path: str) -> Extractor:
    """เลือก extractor ตามนามสกุลไฟล์ — ภาพใช้ typhoon-image, ที่เหลือ (PDF) ใช้ typhoon"""
    from ocr_pipeline.extractors.image_typhoon import IMAGE_EXTS
    import os

    ext = os.path.splitext(path)[1].lower()
    return get_extractor("typhoon-image" if ext in IMAGE_EXTS else "typhoon")
