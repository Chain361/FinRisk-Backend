# -*- coding: utf-8 -*-
"""
services/ — ชั้น service function (contract หลักของ legal linkage + document layer)

ทำไมต้องมีชั้นนี้ (ตาม docs/legal_linkage_plan.md §5.1 note):
ตรรกะ query + scope guard + payload (รวมฟิลด์ `computable`) เขียนไว้ที่เดียว
แล้ว expose 2 ทาง — (1) FastAPI router สำหรับ frontend (2) agent tool สำหรับ chatbot
เพื่อให้ access control เป็น deterministic ไม่พึ่ง guardrail ของ LLM
(agent ไม่เขียน SQL เอง)
"""
