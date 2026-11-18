"""全局热键：手动开关遮挡、紧急遮挡、恢复自动判定。"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(self, bindings: dict, on_toggle, on_panic, on_resume):
        self.bindings = bindings
        self.on_toggle = on_toggle
        self.on_panic = on_panic
        self.on_resume = on_resume
        self.listener = None

    def start(self):
        from pynput import keyboard

        mapping = {}
        if self.bindings.get("toggle"):
            mapping[f"<{self.bindings['toggle']}>"] = self._toggle
        if self.bindings.get("panic"):
            mapping[f"<{self.bindings['panic']}>"] = self._panic
        if self.bindings.get("resume_auto"):
            mapping[f"<{self.bindings['resume_auto']}>"] = self._resume

        if not mapping:
            log.warning("未配置任何热键")
            return

        self.listener = keyboard.GlobalHotKeys(mapping)
        self.listener.start()
        log.info("热键已注册: %s", {k: v for k, v in mapping.items()})

    def _toggle(self):
        log.info("热键: 手动切换遮挡")
        self.on_toggle()

    def _panic(self):
        log.warning("热键: 紧急强制遮挡")
        self.on_panic()

    def _resume(self):
        log.info("热键: 恢复自动判定")
        self.on_resume()

    def stop(self):
        if self.listener:
            self.listener.stop()
