# -*- coding: utf-8 -*-
"""Plugin seam ของ ocr_pipeline — จุดต่อขยาย optional feature (เช่น Law Document RAG)

Plugin ทุกตัว subclass `BasePipelinePlugin` และถูกเรียกโดย run_pipeline.py
หลังขั้น seed DB สำเร็จ (plugin ห้ามแก้ schema/ข้อมูลตารางหลักของ fraud_risk.db)
"""


class BasePipelinePlugin:
    """Interface กลางของ pipeline plugin (ตาม implementation plan §2)"""

    def name(self) -> str:
        raise NotImplementedError

    def is_enabled(self, args) -> bool:
        """ตัดสินจาก CLI args ว่า plugin นี้ควรรันหรือไม่ (เช่น args.enable_rag)"""
        raise NotImplementedError

    def run(self, db_conn) -> dict:
        """รัน plugin — คืน dict summary สำหรับ log (ห้าม raise ทะลุ: ผู้เรียก isolate ให้)"""
        raise NotImplementedError


def get_plugins() -> list:
    """รายการ plugin ที่ลงทะเบียนไว้ (ลำดับ = ลำดับรัน)"""
    from ocr_pipeline.plugins.law_rag_stub import LawRagStubPlugin
    return [LawRagStubPlugin()]
