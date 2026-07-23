# -*- coding: utf-8 -*-
from ocr_pipeline.extractors.base import Extractor, PageMarkdown


def get_extractor(name: str) -> Extractor:
    if name == "typhoon":
        from ocr_pipeline.extractors.typhoon import TyphoonExtractor
        return TyphoonExtractor()
    raise ValueError(f"ไม่รู้จัก extractor: {name}")
