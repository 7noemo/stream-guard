"""遮挡事件统计。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class BlockEvent:
    started: float
    score: float
    reason: str
    ended: float | None = None


@dataclass
class Stats:
    events: list[BlockEvent] = field(default_factory=list)
    _current: BlockEvent | None = None

    def on_block(self, score: float, reason: str):
        if self._current is None:
            self._current = BlockEvent(time.time(), score, reason)
            self.events.append(self._current)

    def on_unblock(self):
        if self._current is not None:
            self._current.ended = time.time()
            self._current = None

    def summary(self) -> dict:
        total = sum(
            (e.ended or time.time()) - e.started for e in self.events
        )
        last = self.events[-1] if self.events else None
        return {
            "count": len(self.events),
            "total_seconds": total,
            "last_at": time.strftime("%H:%M:%S", time.localtime(last.started)) if last else "-",
            "last_score": last.score if last else 0.0,
        }
