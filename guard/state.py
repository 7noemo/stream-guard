"""状态机：滞回判定 + 最短保持时间 + 手动覆盖，避免遮挡来回闪烁。"""
from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class Decision:
    blocked: bool
    score: float
    reason: str


class GuardState:
    def __init__(
        self,
        threshold: float,
        clear_threshold: float,
        consecutive_hits: int,
        consecutive_clear: int,
        min_hold_seconds: float,
    ):
        self.threshold = threshold
        self.clear_threshold = clear_threshold
        self.hits_required = consecutive_hits
        self.clears_required = consecutive_clear
        self.min_hold = min_hold_seconds

        self.blocked = False
        self._hits = 0
        self._clears = 0
        self._changed_at = 0.0
        self.manual_override: bool | None = None  # None=自动, True=强制遮挡, False=强制取消

    def feed(self, score: float) -> Decision:
        now = time.monotonic()

        if self.manual_override is not None:
            self.blocked = self.manual_override
            return Decision(self.blocked, score, "manual")

        if score >= self.threshold:
            self._hits += 1
            self._clears = 0
        elif score <= self.clear_threshold:
            self._clears += 1
            self._hits = 0
        else:
            # 处于中间模糊带：两边计数都衰减，避免抖动累积
            self._hits = max(0, self._hits - 1)
            self._clears = max(0, self._clears - 1)

        changed = False
        if not self.blocked and self._hits >= self.hits_required:
            self.blocked = True
            changed = True
        elif (
            self.blocked
            and self._clears >= self.clears_required
            and now - self._changed_at >= self.min_hold
        ):
            self.blocked = False
            changed = True

        if changed:
            self._changed_at = now
            self._hits = 0
            self._clears = 0

        return Decision(self.blocked, score, "auto")

    def toggle(self) -> bool:
        """手动翻转遮挡状态并进入手动模式。"""
        self.manual_override = not self.blocked
        self.blocked = self.manual_override
        return self.blocked

    def panic(self):
        """紧急强制遮挡。"""
        self.manual_override = True
        self.blocked = True

    def resume_auto(self):
        self.manual_override = None
        self._hits = 0
        self._clears = 0
