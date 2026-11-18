"""画面来源抽象：OBS 节目场景 / OBS 指定源 / 窗口跟踪 / 屏幕区域。

推荐 obs_scene —— 通过已有的 OBS WebSocket 拿到最终合成画面，
检测内容与观众所见完全一致，且不受弹窗、切窗口、最小化影响。
"""
from __future__ import annotations

import base64
import io
import logging
import platform
from typing import Optional

from PIL import Image

log = logging.getLogger(__name__)

IS_WINDOWS = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


class CaptureSource:
    """统一接口：grab() 返回 RGB 的 PIL Image，close() 释放资源。"""

    backend = "base"

    def grab(self) -> Image.Image:
        raise NotImplementedError

    def close(self):
        pass

    def describe(self) -> str:
        return self.backend


# ---------------------------------------------------------------- OBS 场景/源
class OBSCapture(CaptureSource):
    """通过 OBS WebSocket 的 GetSourceScreenshot 取画面。

    name 为空代表当前节目场景（含全部叠加滤镜），也可指定某个源名称。
    """

    def __init__(self, obs_cfg: dict, source_name: str = "", width: int = 640, height: int = 360):
        from obsws_python import ReqClient

        self.client = None
        try:
            # ReqClient 构造时即建立连接，需整体捕获
            self.client = ReqClient(
                host=obs_cfg.get("host", "localhost"),
                port=obs_cfg.get("port", 4455),
                password=obs_cfg.get("password", ""),
            )
            self.client.get_current_program_scene()
        except Exception as exc:
            if self.client is not None:
                try:
                    self.client.disconnect()
                except Exception:
                    pass
            raise RuntimeError(
                f"无法连接 OBS WebSocket（{obs_cfg.get('host')}:{obs_cfg.get('port')}）。"
                "请先在 OBS「工具 → WebSocket 服务器设置」中启用服务并填写密码，"
                "或把画面来源切换为 screen / window。"
            ) from exc
        self.fixed_name = source_name or None
        self.width = max(0, int(width))
        self.height = max(0, int(height))
        self.backend = "obs_source" if self.fixed_name else "obs_scene"

    def _resolve_name(self) -> str:
        if self.fixed_name:
            return self.fixed_name
        resp = self.client.get_current_program_scene()
        return resp.scene_name

    def grab(self) -> Image.Image:
        name = self._resolve_name()
        resp = self.client.get_source_screenshot(
            name=name,
            img_format="jpeg",
            width=self.width,
            height=self.height,
            quality=80,
        )
        raw = base64.b64decode(resp.image_data)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    def describe(self) -> str:
        return f"{self.backend}({self.fixed_name or '节目场景'})"

    def close(self):
        try:
            self.client.disconnect()
        except Exception:
            pass


# ---------------------------------------------------------------- 窗口跟踪
class WindowCapture(CaptureSource):
    """按窗口标题关键字找到窗口，跟踪其屏幕矩形抓屏。

    相比 PrintWindow，直接抓屏幕矩形对 DirectX 游戏更可靠（不会黑屏），
    缺点是窗口被其他窗口遮挡时会抓到遮挡物，且窗口最小化时无法抓取。
    """

    backend = "window"

    def __init__(self, title_contains: str = ""):
        import mss

        self.title = title_contains.strip()
        self.sct = mss.mss()
        if self.title:
            wins = list_windows()
            match = [w for w in wins if self.title.lower() in w["title"].lower()]
            if not match:
                raise RuntimeError(
                    f"找不到标题包含 [{self.title}] 的窗口。当前窗口: "
                    + ", ".join(w["title"] for w in wins[:10])
                )

    def _find_rect(self) -> dict:
        wins = list_windows()
        if self.title:
            match = [w for w in wins if self.title.lower() in w["title"].lower()]
            if not match:
                raise RuntimeError("目标窗口已关闭或标题变化")
            w = match[0]
        else:
            if not wins:
                raise RuntimeError("没有可采集的窗口")
            w = wins[0]
        return w["rect"]

    def grab(self) -> Image.Image:
        rect = self._find_rect()
        area = {
            "left": rect["left"],
            "top": rect["top"],
            "width": max(1, rect["width"]),
            "height": max(1, rect["height"]),
        }
        raw = self.sct.grab(area)
        return Image.frombytes("RGB", raw.size, raw.rgb)

    def describe(self) -> str:
        return f"window({self.title or '首个窗口'})"

    def close(self):
        self.sct.close()


# ---------------------------------------------------------------- 屏幕区域
class ScreenCapture(CaptureSource):
    """抓整屏或指定区域。mss（GDI）与 dxcam（DXGI）双后端。"""

    backend = "screen"

    def __init__(self, backend: str = "auto", monitor: int = 0, region: Optional[dict] = None):
        import mss

        self.sct = mss.mss()
        monitors = self.sct.monitors
        idx = (1 if len(monitors) > 1 else 0) if monitor == 0 else monitor
        if idx >= len(monitors):
            raise ValueError(f"显示器编号 {monitor} 不存在，共 {len(monitors) - 1} 个")
        self.base = monitors[idx]

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
            backend = "dxcam" if IS_WINDOWS and _dxcam_available() else "mss"
        self.screen_backend = backend
        self.camera = None
        if backend == "dxcam":
            try:
                import dxcam

                self.camera = dxcam.create(output_idx=max(0, idx - 1))
                if self.camera is None:
                    raise RuntimeError("dxcam.create() 返回 None")
            except Exception as exc:
                log.warning("dxcam 初始化失败，回退到 mss: %s", exc)
                self.screen_backend = "mss"
                self.camera = None

    def grab(self) -> Image.Image:
        if self.screen_backend == "dxcam" and self.camera is not None:
            frame = self.camera.grab(region=self.dxcam_region)
            if frame is None:
                raise RuntimeError("dxcam 未能抓到画面")
            return Image.fromarray(frame)
        raw = self.sct.grab(self.capture_area)
        return Image.frombytes("RGB", raw.size, raw.rgb)

    def describe(self) -> str:
        return f"screen({self.screen_backend})"

    def close(self):
        if self.camera is not None:
            self.camera.release()
        self.sct.close()


def _dxcam_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("dxcam") is not None


def list_windows() -> list[dict]:
    """列出可见窗口，返回 [{title, rect:{left,top,width,height}}]。"""
    result: list[dict] = []
    if IS_WINDOWS:
        try:
            import win32gui

            def cb(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if not title:
                    return
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                result.append({"title": title, "rect": {"left": l, "top": t, "width": r - l, "height": b - t}})

            win32gui.EnumWindows(cb, None)
        except Exception as exc:
            log.warning("枚举窗口失败: %s", exc)
    elif IS_MAC:
        try:
            from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID

            for w in CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID):
                name = w.get("kCGWindowName", "")
                if not name:
                    continue
                bounds = w.get("kCGWindowBounds", {})
                result.append({
                    "title": str(name),
                    "rect": {
                        "left": int(bounds.get("X", 0)),
                        "top": int(bounds.get("Y", 0)),
                        "width": int(bounds.get("Width", 0)),
                        "height": int(bounds.get("Height", 0)),
                    },
                })
        except Exception as exc:
            log.warning("枚举窗口失败(需安装 pyobjc-framework-Quartz): %s", exc)
    return result


def build_capture(cfg: dict, obs_cfg: dict) -> CaptureSource:
    """按配置构建画面来源。

    cfg 支持字段：
      source: obs_scene | obs_source | window | screen
      obs_source_name / window_title: 对应来源的标识
      screenshot_width / screenshot_height: OBS 截图分辨率
      backend / monitor / region: 屏幕区域模式沿用旧参数
    """
    source = cfg.get("source", "obs_scene")
    if source in ("obs_scene", "obs_source"):
        return OBSCapture(
            obs_cfg,
            source_name=cfg.get("obs_source_name", "") if source == "obs_source" else "",
            width=cfg.get("screenshot_width", 640),
            height=cfg.get("screenshot_height", 360),
        )
    if source == "window":
        return WindowCapture(cfg.get("window_title", ""))
    if source == "screen":
        return ScreenCapture(
            backend=cfg.get("backend", "auto"),
            monitor=cfg.get("monitor", 0),
            region=cfg.get("region"),
        )
    raise ValueError(f"未知画面来源: {source}")
