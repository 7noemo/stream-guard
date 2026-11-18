"""截屏模块：mss（GDI）与 dxcam（DXGI）双后端。

Windows 全屏独占 DirectX 游戏下 mss 可能抓到黑屏，此时 dxcam 更可靠；
建议同时把游戏设为「无边框窗口」模式作为兜底。
"""
from __future__ import annotations

import logging
import platform
from typing import Optional

import mss
from PIL import Image

log = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"


class ScreenCapture:
    """抓屏器。monitor=0 表示主显示器。region 为相对该显示器的 {left,top,width,height}。"""

    def __init__(self, backend: str = "auto", monitor: int = 0, region: Optional[dict] = None):
        self.sct = mss.mss()
        monitors = self.sct.monitors
        idx = (1 if len(monitors) > 1 else 0) if monitor == 0 else monitor
        if idx >= len(monitors):
            raise ValueError(f"显示器编号 {monitor} 不存在，共 {len(monitors) - 1} 个")
        self.base = monitors[idx]

        self.region = region
        if region:
            left = self.base["left"] + region["left"]
            top = self.base["top"] + region["top"]
            width, height = region["width"], region["height"]
        else:
            left, top = self.base["left"], self.base["top"]
            width, height = self.base["width"], self.base["height"]

        self.capture_area = {"left": left, "top": top, "width": width, "height": height}
        self.dxcam_region = (left, top, left + width, top + height)

        if backend == "auto":
            backend = "dxcam" if IS_WINDOWS and self._dxcam_available() else "mss"
        self.backend = backend

        self.camera = None
        if backend == "dxcam":
            try:
                import dxcam

                self.camera = dxcam.create(output_idx=max(0, idx - 1))
                if self.camera is None:
                    raise RuntimeError("dxcam.create() 返回 None")
            except Exception as exc:
                log.warning("dxcam 初始化失败，回退到 mss: %s", exc)
                self.backend = "mss"
                self.camera = None

        log.info("抓屏后端=%s 区域=%s", self.backend, self.capture_area)

    @staticmethod
    def _dxcam_available() -> bool:
        import importlib.util

        return importlib.util.find_spec("dxcam") is not None

    def grab(self) -> Image.Image:
        if self.backend == "dxcam" and self.camera is not None:
            frame = self.camera.grab(region=self.dxcam_region)
            if frame is None:
                raise RuntimeError("dxcam 未能抓到画面（可能游戏正在切换或全屏独占）")
            return Image.fromarray(frame)

        raw = self.sct.grab(self.capture_area)
        return Image.frombytes("RGB", raw.size, raw.rgb)

    def close(self):
        if self.camera is not None:
            self.camera.release()
        self.sct.close()
