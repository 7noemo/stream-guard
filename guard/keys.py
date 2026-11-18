"""按键解析与模拟：支持单键与组合键（ctrl+1、ctrl+shift+f9 等）。

pynput 的 GlobalHotKeys 需要 `<ctrl>+<shift>+<f9>` 这种格式，而模拟按下需要
Controller.press(Key.ctrl) 这种对象。这个模块把两者统一成一种字符串写法，
供热键注册与直播伴侣输出共用。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

_MOD_ORDER = ("ctrl", "alt", "shift", "cmd")
_MOD_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "ctl": "ctrl",
    "alt": "alt", "option": "alt",
    "shift": "shift",
    "cmd": "cmd", "command": "cmd", "win": "cmd", "super": "cmd", "meta": "cmd",
}
_KEY_ALIASES = {
    "esc": "esc", "escape": "esc",
    "return": "enter", "enter": "enter",
    "del": "delete", "delete": "delete",
    "space": "space", " ": "space", "spacebar": "space",
    "pgup": "page_up", "pageup": "page_up",
    "pgdn": "page_down", "pagedown": "page_down",
    "printscreen": "print_screen", "prtsc": "print_screen", "print": "print_screen",
    "capslock": "caps_lock", "numlock": "num_lock", "scrolllock": "scroll_lock",
    "backspace": "backspace", "tab": "tab",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "home": "home", "end": "end", "insert": "insert", "pause": "pause",
}


@dataclass(frozen=True)
class Hotkey:
    """规范化后的热键：parts 为 pynput 键名，修饰键在前。"""

    parts: tuple[str, ...]

    @property
    def global_format(self) -> str:
        """GlobalHotKeys 注册格式，如 <ctrl>+<shift>+<f9> / <ctrl>+1。"""
        rendered = []
        for part in self.parts:
            if len(part) == 1 and part.isalnum():
                rendered.append(part)
            else:
                rendered.append(f"<{part}>")
        return "+".join(rendered)

    @property
    def display(self) -> str:
        names = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}
        out = []
        for part in self.parts:
            if part in names:
                out.append(names[part])
            elif len(part) == 1:
                out.append(part.upper() if part.isalpha() else part)
            elif part.startswith("f") and part[1:].isdigit():
                out.append(part.upper())
            else:
                out.append(part.replace("_", " ").title())
        return "+".join(out)

    def __str__(self) -> str:
        return self.display


def parse_hotkey(text: Optional[str]) -> Optional[Hotkey]:
    """把用户输入的热键字符串解析成 Hotkey。

    支持分隔符 `+`、`-`、空格；修饰键别名 control/ctl、win/super/meta 等。
    解析失败返回 None，不抛异常，方便界面直接喂用户输入。
    """
    if not text or not str(text).strip():
        return None
    tokens = [t.lower() for t in re.split(r"\s*\+\s*|\s*-\s*|\s+", str(text).strip()) if t]
    if not tokens:
        return None

    mods: list[str] = []
    mains: list[str] = []
    for token in tokens:
        if token in _MOD_ALIASES:
            mod = _MOD_ALIASES[token]
            if mod not in mods:
                mods.append(mod)
        else:
            mains.append(_KEY_ALIASES.get(token, token))

    if len(mains) > 1:
        log.warning("热键 [%s] 含多个主键，仅使用最后一个: %s", text, mains[-1])
    if not mains:
        return None

    # 修饰键按固定顺序排列，避免 ctrl+shift 与 shift+ctrl 被视为不同热键
    parts = tuple([m for m in _MOD_ORDER if m in mods] + [mains[-1]])
    return Hotkey(parts)


# ---- 模拟按键时对自身热键监听的抑制 --------------------------------------
# CompanionOutput 模拟按下 Ctrl+Shift+9 时，HotkeyManager 的全局监听也会收到
# 这个按键；若不抑制，会误触发"手动切换"，导致状态反复横跳。
_suppress_lock = threading.Lock()
_suppress_depth = 0
_controller = None
_controller_lock = threading.Lock()


class _Suppress:
    def __enter__(self):
        global _suppress_depth
        with _suppress_lock:
            _suppress_depth += 1
        return self

    def __exit__(self, *exc):
        global _suppress_depth
        with _suppress_lock:
            _suppress_depth = max(0, _suppress_depth - 1)
        return False


def suppress_hotkeys() -> _Suppress:
    """上下文管理器：期间注册的全局热键回调会被忽略。"""
    return _Suppress()


def hotkeys_suppressed() -> bool:
    with _suppress_lock:
        return _suppress_depth > 0


def press_hotkey(hotkey: Hotkey | str | None, interval: float = 0.03) -> bool:
    """模拟按下热键。interval 为组合键每个按键之间的间隔（秒）。"""
    from pynput.keyboard import Controller, Key

    global _controller
    hk = hotkey if isinstance(hotkey, Hotkey) else parse_hotkey(hotkey)
    if hk is None:
        return False

    objects = []
    for part in hk.parts:
        if len(part) == 1 and part.isalnum():
            objects.append(part)
            continue
        key = getattr(Key, part, None)
        if key is None:
            raise ValueError(f"无法识别的按键: {part}")
        objects.append(key)

    with _controller_lock:
        if _controller is None:
            _controller = Controller()

    interval = max(0.0, min(0.5, float(interval)))
    with suppress_hotkeys():
        for key in objects:
            _controller.press(key)
            if interval:
                time.sleep(interval)
        for key in reversed(objects):
            _controller.release(key)
            if interval:
                time.sleep(interval)
    log.info("已模拟按键: %s", hk.display)
    return True
