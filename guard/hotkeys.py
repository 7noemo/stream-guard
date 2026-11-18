"""全局热键：手动开关遮挡、紧急遮挡、恢复自动判定。

支持组合键（如 ctrl+shift+f9）。注册格式由 guard.keys 统一处理；
当程序自己模拟按键（直播伴侣输出）时，回调会被抑制，避免自触发。
"""
from __future__ import annotations

import logging

from .keys import hotkeys_suppressed, parse_hotkey

log = logging.getLogger(__name__)


class HotkeyManager:
    def __init__(self, bindings: dict, on_toggle, on_panic, on_resume):
        self.bindings = bindings
        self.on_toggle = on_toggle
        self.on_panic = on_panic
        self.on_resume = on_resume
        self.listener = None
        self.registered: dict[str, str] = {}  # global_format -> 显示名

    def start(self):
        from pynput import keyboard

        mapping = {}
        specs = [
            ("toggle", self.bindings.get("toggle"), self._toggle),
            ("panic", self.bindings.get("panic"), self._panic),
            ("resume_auto", self.bindings.get("resume_auto"), self._resume),
        ]

        for name, text, callback in specs:
            hk = parse_hotkey(text)
            if hk is None:
                continue
            fmt = hk.global_format
            if fmt in mapping:
                log.warning("热键冲突：%s 与已有热键重复，跳过 %s", hk.display, name)
                continue
            mapping[fmt] = self._wrapped(name, callback)
            self.registered[fmt] = name

        if not mapping:
            log.warning("未配置任何有效热键")
            return

        self.listener = keyboard.GlobalHotKeys(mapping)
        self.listener.start()
        log.info("热键已注册: %s", ", ".join(mapping.keys()))

    def _wrapped(self, name: str, callback):
        def handler():
            if hotkeys_suppressed():
                return
            log.info("热键触发: %s", name)
            callback()
        return handler

    def _toggle(self):
        self.on_toggle()

    def _panic(self):
        self.on_panic()

    def _resume(self):
        self.on_resume()

    def stop(self):
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass
            self.listener = None
