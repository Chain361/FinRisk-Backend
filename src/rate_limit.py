# -*- coding: utf-8 -*-
"""
rate_limit.py — in-memory sliding-window rate limiter

per-process counter เท่านั้น (พอสำหรับ deploy แบบ 1 instance ตอนนี้) — ถ้าต้อง scale
หลาย instance ในอนาคตค่อยเปลี่ยนไปใช้ Redis/DB-backed counter แทน
"""
import threading
import time
from collections import defaultdict, deque
from typing import Hashable


class SlidingWindowRateLimiter:
    def __init__(self, max_requests: int, window_seconds: float):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[Hashable, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: Hashable) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return False
            hits.append(now)
            return True
