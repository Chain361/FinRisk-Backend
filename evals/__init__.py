# -*- coding: utf-8 -*-
"""
evals — ชุดวัดคุณภาพชั้น AI ด้วย LangSmith (ดู docs/langsmith_eval_plan.md)

⚠️ แพ็กเกจนี้ **ไม่ถูก collect โดย `pytest -q`** (pytest.ini กำหนด testpaths = tests ocr_pipeline/tests)
   เพราะสคริปต์ในนี้ยิง Gemini/Pinecone จริง มีค่าใช้จ่าย — รันแยกด้วยมือหรือ nightly job
   unit test ที่ไม่ยิง API จริงยังอยู่ที่ tests/ ตามเดิม
"""
