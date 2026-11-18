"""输出控制：把遮挡状态同步到 OBS 滤镜 / OBS 场景 / 直播伴侣热键。"""
from __future__ import annotations

import logging
from typing import Protocol

log = logging.getLogger(__name__)


class Output(Protocol):
    def set_blocked(self, blocked: bool) -> None: ...

    def close(self) -> None: ...


class DryRunOutput:
    def set_blocked(self, blocked: bool) -> None:
        log.info("[dry-run] 遮挡状态 -> %s", "开启" if blocked else "关闭")

    def close(self) -> None:
        pass


class OBSFilterOutput:
    """切换 OBS 中已存在滤镜的启用状态（推荐）。

    需要提前在 OBS 的「 Game Capture 」源上添加一个名为 StreamGuard_Blur
    的模糊滤镜，并设置为「已禁用」。滤镜名和源名可在 config.json 修改。
    """

    def __init__(self, cfg: dict):
        from obsws_python import ReqClient

        self.client = ReqClient(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 4455),
            password=cfg.get("password", ""),
        )
        self.source = cfg["source_name"]
        self.filter_name = cfg["filter_name"]

        try:
            filters = self.client.get_source_filter_list(self.source).filters
            names = [f.get("filterName") for f in filters]
            if self.filter_name not in names:
                raise RuntimeError(
                    f"OBS 源 [{self.source}] 下找不到滤镜 [{self.filter_name}]，"
                    f"现有滤镜: {names}。请先在 OBS 中手动添加并禁用该模糊滤镜。"
                )
        except Exception as exc:
            self.client.disconnect()
            raise RuntimeError(
                f"连接 OBS 失败或读取滤镜失败: {exc}。请确认 OBS 已开启 WebSocket 服务器。"
            ) from exc

        self.client.set_source_filter_enabled(self.source, self.filter_name, False)
        log.info("OBS 滤镜输出已就绪: %s / %s", self.source, self.filter_name)

    def set_blocked(self, blocked: bool) -> None:
        self.client.set_source_filter_enabled(self.source, self.filter_name, blocked)

    def close(self) -> None:
        self.client.set_source_filter_enabled(self.source, self.filter_name, False)
        self.client.disconnect()


class OBSSceneOutput:
    """切换到专门的遮挡场景（当滤镜方案不适用时）。"""

    def __init__(self, cfg: dict):
        from obsws_python import ReqClient

        self.client = ReqClient(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 4455),
            password=cfg.get("password", ""),
        )
        self.normal_scene = cfg["normal_scene"]
        self.blocked_scene = cfg["blocked_scene"]

    def set_blocked(self, blocked: bool) -> None:
        self.client.set_current_program_scene(
            self.blocked_scene if blocked else self.normal_scene
        )

    def close(self) -> None:
        self.client.set_current_program_scene(self.normal_scene)
        self.client.disconnect()


class CompanionOutput:
    """抖音直播伴侣等无 API 的软件：模拟其自定义快捷键显示/隐藏遮挡素材。

    在直播伴侣「直播设置 → 快捷键」里给一张遮挡图片素材绑定显示/隐藏按键，
    本模块在风险出现时发「显示」键把遮挡图层盖上去，画面恢复后发「隐藏」键。

    两种模式：
      - dual   : 显示键 / 隐藏键分开（推荐，状态确定，不受焦点影响）
      - toggle : 单个键切换（要求直播伴侣侧设置为切换语义）

    所有按键都支持组合键写法，如 ctrl+1、ctrl+shift+f9。
    """

    def __init__(self, cfg: dict):
        from .keys import parse_hotkey, press_hotkey

        self._press = press_hotkey
        self.mode = cfg.get("key_mode", "dual")

        # 兼容旧配置的 on_hotkey / off_hotkey 字段
        show_text = cfg.get("show_hotkey") or cfg.get("on_hotkey") or "f9"
        hide_text = cfg.get("hide_hotkey") or cfg.get("off_hotkey") or "f10"
        toggle_text = cfg.get("toggle_hotkey") or ""

        self.show = parse_hotkey(show_text)
        self.hide = parse_hotkey(hide_text)
        self.toggle = parse_hotkey(toggle_text)
        self.interval = float(cfg.get("press_interval", 0.03))

        if self.mode == "toggle":
            if self.toggle is None:
                raise RuntimeError("单键切换模式需要填写「切换热键」")
        else:
            if self.show is None or self.hide is None:
                raise RuntimeError("双键模式需要填写「显示热键」和「隐藏热键」")
            if self.show == self.hide:
                raise RuntimeError("显示热键与隐藏热键不能相同，否则无法区分遮挡状态")

        self._blocked = False
        log.info("直播伴侣输出已就绪: 模式=%s, 显示=%s, 隐藏=%s",
                 self.mode,
                 self.show.display if self.show else "-",
                 self.hide.display if self.hide else "-")

    def set_blocked(self, blocked: bool) -> None:
        if blocked == self._blocked:
            return
        if self.mode == "toggle":
            self._press(self.toggle, self.interval)
        else:
            self._press(self.show if blocked else self.hide, self.interval)
        self._blocked = blocked

    def close(self) -> None:
        # 退出时务必把遮挡图层撤掉，不能把马赛克留在观众的直播画面上
        if self._blocked:
            if self.mode == "toggle":
                self._press(self.toggle, self.interval)
            else:
                self._press(self.hide, self.interval)
            self._blocked = False
            log.info("直播伴侣遮挡已复位（画面恢复）")


def ensure_obs_filter(cfg: dict) -> str:
    """在 OBS 中自动创建模糊滤镜（若不存在），返回状态说明。"""
    from obsws_python import ReqClient

    client = ReqClient(
        host=cfg.get("host", "localhost"),
        port=cfg.get("port", 4455),
        password=cfg.get("password", ""),
    )
    try:
        filters = client.get_source_filter_list(cfg["source_name"]).filters
        names = [f.get("filterName") for f in filters]
        if cfg["filter_name"] in names:
            return "滤镜已存在，无需创建"
        client.create_source_filter(
            source_name=cfg["source_name"],
            filter_name=cfg["filter_name"],
            filter_kind="blur_filter",
            filter_settings={"blur_size": 24},
        )
        client.set_source_filter_enabled(cfg["source_name"], cfg["filter_name"], False)
        return "已创建模糊滤镜（默认禁用）"
    finally:
        client.disconnect()


def list_obs_sources(cfg: dict) -> list[str]:
    """列出 OBS 中的源名称，便于用户填写正确的捕获源。"""
    from obsws_python import ReqClient

    client = ReqClient(
        host=cfg.get("host", "localhost"),
        port=cfg.get("port", 4455),
        password=cfg.get("password", ""),
    )
    try:
        return [s.get("sourceName", "") for s in client.get_source_list().sources]
    finally:
        client.disconnect()


def build_output(cfg: dict, dry_run: bool = False) -> Output:
    if dry_run or cfg.get("mode") == "dry_run":
        return DryRunOutput()
    mode = cfg["mode"]
    if mode == "obs_filter":
        return OBSFilterOutput(cfg["obs"])
    if mode == "obs_scene":
        return OBSSceneOutput(cfg["obs"])
    if mode == "companion":
        return CompanionOutput(cfg["companion"])
    raise ValueError(f"未知输出模式: {mode}")
