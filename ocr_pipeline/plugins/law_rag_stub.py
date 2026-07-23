# -*- coding: utf-8 -*-
"""Law Document RAG — stub plugin (ยังไม่ implement จริง)

จองตำแหน่ง integration ของฟีเจอร์ "Document Intelligence" (อ่านเอกสารกฎหมาย/ระเบียบ
จัดซื้อจัดจ้าง → index สำหรับ RAG) — เปิดใช้ผ่าน `python run_pipeline.py --enable-rag`

เมื่อ implement จริง: อ่านเอกสารจาก law_documents/, ทำ chunk + embed,
เขียนลงตารางแยก (เช่น law_chunks) — ห้ามแตะตาราง fraud_risk เดิม
"""
from ocr_pipeline.plugins import BasePipelinePlugin


class LawRagStubPlugin(BasePipelinePlugin):
    def name(self) -> str:
        return "law_rag_stub"

    def is_enabled(self, args) -> bool:
        return bool(getattr(args, "enable_rag", False))

    def run(self, db_conn) -> dict:
        print("[plugin:law_rag_stub] ยังเป็น stub — โครงสร้างพร้อมสำหรับ Law RAG ingestion ในอนาคต")
        return {"plugin": self.name(), "status": "stub", "documents_indexed": 0}


def run_plugin(db_conn=None) -> dict:
    """ทางลัดตาม implementation plan (`law_rag_stub.run_plugin()`)"""
    return LawRagStubPlugin().run(db_conn)
