"""遮挡事件统计。

内存有界：只保留累计值与最近 N 条事件，避免长时间直播时列表无限增长。
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass


@dataclass
class BlockEvent:
    started: float
    score: float
    reason: str
    ended: float | None = None


class Stats:
    MAX_EVENTS = 200  # 只保留最近 200 条，摘要用累计值计算

    def __init__(self):
        self.events: deque[BlockEvent] = deque(maxlen=self.MAX_EVENTS)
        self._current: BlockEvent | None = None
        self._count = 0          # 累计遮挡次数（不受 deque 裁剪影响）
        self._total_seconds = 0.0  # 累计时长
        self._last: BlockEvent | None = None

    def on_block(self, score: float, reason: str):
        if self._current is None:
            self._current = BlockEvent(time.time(), score, reason)
            self.events.append(self._current)
            self._count += 1
            self._last = self._current

    def on_unblock(self):
        if self._current is not None:
            self._current.ended = time.time()
            if self._current.ended:
                self._total_seconds += self._current.ended - self._current.started
            self._current = None

    def summary(self) -> dict:
        # 正在遮挡中的部分也要计入当前时长
        ongoing = (time.time() - self._current.started) if self._current else 0.0
        last = self._last
        return {
            "count": self._count,
            "total_seconds": self._total_seconds + ongoing,
            "last_at": time.strftime("%H:%M:%S", time.localtime(last.started)) if last else "-",
            "last_score": last.score if last else 0.0,
        }
