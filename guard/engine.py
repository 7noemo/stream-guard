"""检测引擎：在后台线程运行截屏-判定-遮挡循环，向 UI 推送事件。"""
from __future__ import annotations

import logging
import queue
import threading
import time

from .capture import build_capture, list_windows
from .detector import build_detector
from .output import build_output
from .state import GuardState
from .stats import Stats

log = logging.getLogger("stream-guard.engine")


class GuardEngine:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.events: queue.Queue = queue.Queue()
        self.actions: queue.Queue = queue.Queue()
        self.stats = Stats()
        self.running = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._capture = None
        self._output = None

    # ---------- 外部控制 ----------
    def start(self):
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._emit_log("INFO", "引擎已启动")

    def stop(self):
        if not self.running:
            return
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=4)
        self.running = False
        self._emit_log("INFO", "引擎已停止")

    def toggle(self):
        self.actions.put("toggle")

    def panic(self):
        self.actions.put("panic")

    @staticmethod
    def list_windows() -> list[dict]:
        return list_windows()

    def resume_auto(self):
        self.actions.put("resume")

    # ---------- 内部循环 ----------
    def _emit_log(self, level: str, message: str):
        self.events.put(("log", level, message))

    def _emit_status(self, **kwargs):
        self.events.put(("status", kwargs))

    def _run(self):
        state = None
        try:
            capture_cfg = self.cfg["capture"]
            self._capture = build_capture(capture_cfg, self.cfg["output"]["obs"])
            detector = build_detector(self.cfg["detector"])
            dc = self.cfg["detector"]
            state = GuardState(
                threshold=dc["threshold"],
                clear_threshold=dc["clear_threshold"],
                consecutive_hits=dc["consecutive_hits"],
                consecutive_clear=dc["consecutive_clear"],
                min_hold_seconds=dc["min_hold_seconds"],
            )
            self._output = build_output(self.cfg["output"])
            self._emit_log("INFO", f"检测后端: {dc['backend']} · 画面来源: {self._capture.describe()}")

            # 全局热键由上层（GUI/CLI）在主线程注册，避免 macOS 后台线程调用 pynput 崩溃
            fps = max(1, self.cfg["capture"].get("fps", 8))
            interval = 1.0 / fps
            frames = 0
            last_blocked = False

            while not self._stop.is_set():
                started = time.monotonic()

                while not self.actions.empty():
                    action = self.actions.get()
                    if action == "toggle" and state:
                        blocked = state.toggle()
                        self._apply(blocked, 1.0 if blocked else 0.0, "manual", state)
                    elif action == "panic" and state:
                        state.panic()
                        self._apply(True, 1.0, "panic", state)
                    elif action == "resume" and state:
                        state.resume_auto()
                        self._emit_log("INFO", "已恢复自动判定")

                image = self._capture.grab()
                score = detector.predict(image)
                decision = state.feed(score)
                frames += 1

                if decision.blocked != last_blocked:
                    self._apply(decision.blocked, score, decision.reason, state)
                    last_blocked = decision.blocked

                if frames % (fps * 2) == 0:
                    summary = self.stats.summary()
                    self._emit_status(
                        score=score,
                        blocked=decision.blocked,
                        mode="手动" if state.manual_override is not None else "自动",
                        frames=frames,
                        fps=fps,
                        **summary,
                    )

                self._stop.wait(max(0, interval - (time.monotonic() - started)))

        except KeyboardInterrupt:
            pass
        except Exception as exc:
            log.exception("引擎异常")
            self._emit_log("ERROR", f"引擎异常: {exc}")
        finally:
            self._cleanup()

    def _apply(self, blocked: bool, score: float, reason: str, state: GuardState):
        self._output.set_blocked(blocked)
        if blocked:
            self.stats.on_block(score, reason)
        else:
            self.stats.on_unblock()
        action = "开启遮挡" if blocked else "移除遮挡"
        self._emit_log("WARN" if blocked else "INFO", f"{action} (score={score:.3f}, {reason})")
        self._emit_status(
            score=score,
            blocked=blocked,
            mode="手动" if state.manual_override is not None else "自动",
            frames=0,
            fps=self.cfg["capture"].get("fps", 8),
            **self.stats.summary(),
        )

    def _cleanup(self):
        try:
            if self._output:
                self._output.set_blocked(False)
                self._output.close()
        except Exception:
            pass
        try:
            if self._capture:
                self._capture.close()
        except Exception:
            pass
        self._output = None
        self._capture = None
        self.running = False
        self._emit_status(blocked=False, mode="停止", score=0.0, frames=0,
                          fps=0, count=self.stats.summary()["count"],
                          total_seconds=self.stats.summary()["total_seconds"],
                          last_at="-", last_score=0.0)
