"""图形界面：tkinter 实现的配置、监控、统计与托盘。"""
from __future__ import annotations

import json
import logging
import queue
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from PIL import Image, ImageDraw

from .engine import GuardEngine
from .hotkeys import HotkeyManager


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    import platform

    if getattr(sys, "frozen", False) and platform.system() == "darwin":
        folder = Path.home() / "Library" / "Application Support" / "StreamGuard"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "config.json"
    return app_dir() / "config.json"


DEFAULT_CONFIG = {
    "capture": {
        "source": "obs_scene", "obs_source_name": "", "window_title": "",
        "screenshot_width": 640, "screenshot_height": 360,
        "backend": "auto", "monitor": 0, "fps": 8, "region": None,
    },
    "detector": {
        "backend": "heuristic",
        "threshold": 0.72,
        "clear_threshold": 0.45,
        "consecutive_hits": 3,
        "consecutive_clear": 5,
        "min_hold_seconds": 2.0,
        "threads": 2,
        "frame_skip": True,
        "frame_skip_threshold": 3.0,
        "frame_skip_max": 12,
        "mock_scores": [0.05, 0.08, 0.12, 0.85, 0.88, 0.91, 0.80, 0.30, 0.10, 0.05],
    },
    "output": {
        "mode": "obs_filter",
        "obs": {
            "host": "localhost", "port": 4455, "password": "",
            "source_name": "Game Capture", "filter_name": "StreamGuard_Blur",
            "normal_scene": "Live", "blocked_scene": "StreamGuard_Blocked",
        },
        "companion": {
            "key_mode": "dual",
            "show_hotkey": "ctrl+shift+9", "hide_hotkey": "ctrl+shift+0",
            "toggle_hotkey": "ctrl+shift+8", "press_interval": 0.03,
        },
    },
    "hotkeys": {"toggle": "f9", "panic": "f10", "resume_auto": "f11"},
    "log": {"level": "INFO", "save_samples": False, "sample_dir": "./samples"},
}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config_path = config_path()
        self.cfg = self._load_config()
        self.engine = GuardEngine(self.cfg)
        self._hotkeys = HotkeyManager(
            self.cfg["hotkeys"],
            on_toggle=self.engine.toggle,
            on_panic=self.engine.panic,
            on_resume=self.engine.resume_auto,
        )
        self.tray = None
        self._status = {"score": 0.0, "blocked": False, "mode": "停止",
                        "count": 0, "total_seconds": 0.0, "last_at": "-", "last_score": 0.0}

        root.title("Stream Guard · 直播画面守护")
        root.geometry("1180x720")
        root.minsize(1100, 660)
        self._build_ui()
        self._load_cfg_to_ui()
        self._poll()

        root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._hotkeys.start()
        self._setup_tray()

    # ---------- 配置 ----------
    def _load_config(self) -> dict:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            for key, value in DEFAULT_CONFIG.items():
                cfg.setdefault(key, value)
            return cfg
        except Exception:
            cfg = json.loads(json.dumps(DEFAULT_CONFIG))
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return cfg

    def _save_config(self, show_message: bool = True):
        self._read_ui_to_cfg()
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
            if show_message:
                messagebox.showinfo("已保存", f"配置已写入:\n{self.config_path}\n\n部分参数需重启引擎后生效。")
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc))

    # ---------- UI 构建 ----------
    def _build_ui(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        root = self.root
        top = ttk.Frame(root, padding=(14, 12))
        top.pack(fill=tk.X)

        ttk.Label(top, text="Stream Guard", font=("Microsoft YaHei", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(top, text="直播画面风险自动遮挡", foreground="#6b7280").pack(side=tk.LEFT, padx=(10, 0))

        self.status_canvas = tk.Canvas(top, width=18, height=18, highlightthickness=0)
        self.status_canvas.pack(side=tk.RIGHT, padx=(0, 6))
        self.status_dot = self.status_canvas.create_oval(2, 2, 16, 16, fill="#9ca3af")
        self.status_label = ttk.Label(top, text="已停止", font=("Microsoft YaHei", 11, "bold"))
        self.status_label.pack(side=tk.RIGHT)

        monitor = ttk.LabelFrame(root, text="实时监控", padding=(14, 10))
        monitor.pack(fill=tk.X, padx=14, pady=(0, 8))

        row = ttk.Frame(monitor)
        row.pack(fill=tk.X)
        ttk.Label(row, text="风险分").pack(side=tk.LEFT)
        self.score_bar = ttk.Progressbar(row, maximum=100, length=420)
        self.score_bar.pack(side=tk.LEFT, padx=10)
        self.score_label = ttk.Label(row, text="0.000", width=8)
        self.score_label.pack(side=tk.LEFT)
        self.mode_label = ttk.Label(row, text="模式: 停止")
        self.mode_label.pack(side=tk.LEFT, padx=(20, 0))

        stat_row = ttk.Frame(monitor)
        stat_row.pack(fill=tk.X, pady=(10, 0))
        self.stat_vars = {}
        for key, text in [("count", "遮挡次数"), ("total_seconds", "累计遮挡"), ("last_at", "最近触发")]:
            box = ttk.Frame(stat_row)
            box.pack(side=tk.LEFT, padx=(0, 40))
            ttk.Label(box, text=text, foreground="#6b7280").pack(anchor=tk.W)
            var = tk.StringVar(value="0" if key == "count" else "0 秒" if key == "total_seconds" else "-")
            self.stat_vars[key] = var
            ttk.Label(box, textvariable=var, font=("Microsoft YaHei", 11, "bold")).pack(anchor=tk.W)

        ctrl = ttk.LabelFrame(root, text="控制", padding=(14, 10))
        ctrl.pack(fill=tk.X, padx=14, pady=(0, 8))
        self.btn_start = ttk.Button(ctrl, text="开始监控", command=self._on_start)
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_stop = ttk.Button(ctrl, text="停止", command=self._on_stop, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 20))
        ttk.Button(ctrl, text="手动遮挡 F9", command=lambda: self.engine.toggle()).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(ctrl, text="紧急遮挡 F10", command=lambda: self.engine.panic()).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(ctrl, text="恢复自动 F11", command=lambda: self.engine.resume_auto()).pack(side=tk.LEFT)

        cols = ttk.Frame(root)
        cols.pack(fill=tk.X, padx=14, pady=(0, 8))

        left = ttk.LabelFrame(cols, text="画面来源", padding=(12, 10))
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        ttk.Label(left, text="来源方式").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.source_kind = ttk.Combobox(
            left,
            values=["obs_scene", "obs_source", "window", "screen"],
            width=18,
            state="readonly",
        )
        self.source_kind.grid(row=0, column=1, sticky=tk.W, pady=3)
        self.source_kind.bind("<<ComboboxSelected>>", lambda e: self._on_source_change())

        self.source_hint = ttk.Label(left, text="", foreground="#6b7280", wraplength=330)
        self.source_hint.grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(2, 6))

        self.source_panel = ttk.Frame(left)
        self.source_panel.grid(row=2, column=0, columnspan=3, sticky=tk.W)

        ttk.Label(self.source_panel, text="OBS 源").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.obs_source_name = ttk.Combobox(self.source_panel, values=[], width=24)
        self.obs_source_name.grid(row=0, column=1, sticky=tk.W, pady=3)

        ttk.Label(self.source_panel, text="窗口标题").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.window_title = ttk.Combobox(self.source_panel, values=[], width=24)
        self.window_title.grid(row=1, column=1, sticky=tk.W, pady=3)

        btn_row = ttk.Frame(self.source_panel)
        btn_row.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(4, 0))
        ttk.Button(btn_row, text="刷新 OBS 源", command=self._refresh_obs_sources).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="刷新窗口", command=self._refresh_windows).pack(side=tk.LEFT, padx=6)

        ttk.Label(self.source_panel, text="截图分辨率").grid(row=3, column=0, sticky=tk.W, pady=3)
        res_row = ttk.Frame(self.source_panel)
        res_row.grid(row=3, column=1, sticky=tk.W)
        self.shot_width = ttk.Spinbox(res_row, from_=160, to=1920, width=6)
        self.shot_width.pack(side=tk.LEFT)
        ttk.Label(res_row, text="x").pack(side=tk.LEFT, padx=3)
        self.shot_height = ttk.Spinbox(res_row, from_=90, to=1080, width=6)
        self.shot_height.pack(side=tk.LEFT)

        self.screen_panel = ttk.Frame(left)
        self.screen_panel.grid(row=2, column=0, columnspan=3, sticky=tk.W)

        ttk.Label(self.screen_panel, text="抓屏后端").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.capture_backend = ttk.Combobox(self.screen_panel, values=["auto", "mss", "dxcam"], width=18)
        self.capture_backend.grid(row=0, column=1, sticky=tk.W, pady=3)

        region_row = ttk.Frame(self.screen_panel)
        region_row.grid(row=1, column=0, columnspan=3, pady=(6, 0), sticky=tk.W)
        ttk.Button(region_row, text="框选画面区域", command=self._pick_region).pack(side=tk.LEFT)
        ttk.Button(region_row, text="清除", command=self._clear_region).pack(side=tk.LEFT, padx=6)
        self.region_label = ttk.Label(region_row, text="全屏", foreground="#6b7280")
        self.region_label.pack(side=tk.LEFT, padx=6)

        detect = ttk.LabelFrame(cols, text="检测参数", padding=(12, 10))
        detect.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        ttk.Label(detect, text="检测后端").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.backend = ttk.Combobox(detect, values=["heuristic", "mock", "opennsfw2", "clip"], width=18)
        self.backend.grid(row=0, column=1, sticky=tk.W, pady=3)

        ttk.Label(detect, text="检测帧率").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.fps = ttk.Spinbox(detect, from_=1, to=30, width=8)
        self.fps.grid(row=1, column=1, sticky=tk.W, pady=3)

        ttk.Label(detect, text="触发阈值").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.threshold = ttk.Scale(detect, from_=0.3, to=0.95, length=170)
        self.threshold.grid(row=2, column=1, sticky=tk.W, pady=3)
        self.threshold_text = ttk.Label(detect, text="0.72")
        self.threshold_text.grid(row=2, column=2, padx=6)

        ttk.Label(detect, text="解除阈值").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.clear_threshold = ttk.Scale(detect, from_=0.05, to=0.8, length=170)
        self.clear_threshold.grid(row=3, column=1, sticky=tk.W, pady=3)
        self.clear_text = ttk.Label(detect, text="0.45")
        self.clear_text.grid(row=3, column=2, padx=6)

        ttk.Label(detect, text="连续命中/解除").grid(row=4, column=0, sticky=tk.W, pady=3)
        frame_hits = ttk.Frame(detect)
        frame_hits.grid(row=4, column=1, columnspan=2, sticky=tk.W)
        self.hits = ttk.Spinbox(frame_hits, from_=1, to=20, width=6)
        self.hits.pack(side=tk.LEFT)
        ttk.Label(frame_hits, text="/").pack(side=tk.LEFT, padx=4)
        self.clears = ttk.Spinbox(frame_hits, from_=1, to=20, width=6)
        self.clears.pack(side=tk.LEFT)
        ttk.Label(frame_hits, text="帧").pack(side=tk.LEFT, padx=4)

        ttk.Label(detect, text="最短保持(秒)").grid(row=5, column=0, sticky=tk.W, pady=3)
        self.min_hold = ttk.Spinbox(detect, from_=0, to=15, width=8)
        self.min_hold.grid(row=5, column=1, sticky=tk.W, pady=3)

        right = ttk.LabelFrame(cols, text="输出与热键", padding=(12, 10))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        ttk.Label(right, text="输出方式").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.output_mode = ttk.Combobox(
            right, values=["obs_filter", "obs_scene", "companion", "dry_run"], width=18,
            state="readonly",
        )
        self.output_mode.grid(row=0, column=1, sticky=tk.W, pady=3)
        self.output_mode.bind("<<ComboboxSelected>>", lambda e: self._on_output_change())

        self.output_hint = ttk.Label(right, text="", foreground="#6b7280", wraplength=330)
        self.output_hint.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(2, 6))

        # ---- OBS 专属面板 ----
        self.obs_panel = ttk.Frame(right)
        self.obs_panel.grid(row=2, column=0, columnspan=2, sticky=tk.W)

        obs_fields = [
            ("OBS 地址", "obs_host"), ("端口", "obs_port"), ("密码", "obs_password"),
            ("捕获源名称", "source_name"), ("模糊滤镜名", "filter_name"),
            ("正常场景", "normal_scene"), ("遮挡场景", "blocked_scene"),
        ]
        for i, (label, attr) in enumerate(obs_fields):
            ttk.Label(self.obs_panel, text=label).grid(row=i, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(self.obs_panel, width=22, show="*" if attr == "obs_password" else None)
            entry.grid(row=i, column=1, sticky=tk.W, pady=2)
            setattr(self, attr, entry)

        obs_btns = ttk.Frame(self.obs_panel)
        obs_btns.grid(row=7, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        ttk.Button(obs_btns, text="测试连接", command=self._test_obs).pack(side=tk.LEFT)
        ttk.Button(obs_btns, text="一键创建模糊滤镜", command=self._create_filter).pack(side=tk.LEFT, padx=6)
        self.obs_status = ttk.Label(self.obs_panel, text="", foreground="#6b7280", wraplength=330)
        self.obs_status.grid(row=8, column=0, columnspan=2, sticky=tk.W)

        # ---- 直播伴侣专属面板 ----
        self.companion_panel = ttk.Frame(right)
        self.companion_panel.grid(row=3, column=0, columnspan=2, sticky=tk.W)

        ttk.Label(self.companion_panel, text="按键模式").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.comp_mode = ttk.Combobox(
            self.companion_panel, values=["dual", "toggle"], width=18, state="readonly"
        )
        self.comp_mode.grid(row=0, column=1, sticky=tk.W, pady=2)
        self.comp_mode.bind("<<ComboboxSelected>>", lambda e: self._on_comp_mode_change())

        ttk.Label(self.companion_panel, text="显示遮挡键").grid(row=1, column=0, sticky=tk.W, pady=2)
        self.comp_show_key = ttk.Entry(self.companion_panel, width=22)
        self.comp_show_key.grid(row=1, column=1, sticky=tk.W, pady=2)

        ttk.Label(self.companion_panel, text="隐藏遮挡键").grid(row=2, column=0, sticky=tk.W, pady=2)
        self.comp_hide_key = ttk.Entry(self.companion_panel, width=22)
        self.comp_hide_key.grid(row=2, column=1, sticky=tk.W, pady=2)

        ttk.Label(self.companion_panel, text="切换键(单键模式)").grid(row=3, column=0, sticky=tk.W, pady=2)
        self.comp_toggle_key = ttk.Entry(self.companion_panel, width=22)
        self.comp_toggle_key.grid(row=3, column=1, sticky=tk.W, pady=2)

        ttk.Label(self.companion_panel, text="按键间隔(秒)").grid(row=4, column=0, sticky=tk.W, pady=2)
        self.comp_interval = ttk.Entry(self.companion_panel, width=22)
        self.comp_interval.grid(row=4, column=1, sticky=tk.W, pady=2)

        comp_btns = ttk.Frame(self.companion_panel)
        comp_btns.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        ttk.Button(comp_btns, text="配置向导", command=self._open_companion_wizard).pack(side=tk.LEFT)
        ttk.Button(comp_btns, text="生成遮挡素材", command=self._generate_cover).pack(side=tk.LEFT, padx=6)

        self.comp_warning = ttk.Label(
            self.companion_panel, text="", foreground="#dc2626", wraplength=330
        )
        self.comp_warning.grid(row=6, column=0, columnspan=2, sticky=tk.W)

        hk = ttk.Frame(right)
        hk.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky=tk.W)
        ttk.Label(hk, text="热键 切换/紧急/自动").pack(side=tk.LEFT)
        self.hk_toggle = ttk.Entry(hk, width=8)
        self.hk_panic = ttk.Entry(hk, width=8)
        self.hk_resume = ttk.Entry(hk, width=8)
        for e in (self.hk_toggle, self.hk_panic, self.hk_resume):
            e.pack(side=tk.LEFT, padx=3)
            e.bind("<KeyRelease>", lambda ev: self._check_hotkey_conflict())
        for e in (self.comp_show_key, self.comp_hide_key, self.comp_toggle_key):
            e.bind("<KeyRelease>", lambda ev: self._check_hotkey_conflict())

        log_frame = ttk.LabelFrame(root, text="运行日志", padding=(10, 6))
        log_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 8))
        self.log_text = ScrolledText(log_frame, height=8, font=("Consolas", 9), state=tk.DISABLED)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        bottom = ttk.Frame(root, padding=(14, 0, 14, 12))
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="保存配置", command=self._save_config).pack(side=tk.LEFT)
        ttk.Button(bottom, text="导出配置", command=self._export_config).pack(side=tk.LEFT, padx=8)
        ttk.Button(bottom, text="导入配置", command=self._import_config).pack(side=tk.LEFT)
        ttk.Button(bottom, text="导出诊断报告", command=self._export_diagnostics).pack(side=tk.LEFT, padx=8)
        ttk.Button(bottom, text="最小化到托盘", command=self._on_close).pack(side=tk.RIGHT)

    # ---------- 配置 <-> UI ----------
    def _load_cfg_to_ui(self):
        cfg = self.cfg
        self.backend.set(cfg["detector"]["backend"])
        cap = cfg["capture"]
        self.source_kind.set(cap.get("source", "obs_scene"))
        self.obs_source_name.set(cap.get("obs_source_name", ""))
        self.window_title.set(cap.get("window_title", ""))
        self.shot_width.delete(0, tk.END); self.shot_width.insert(0, cap.get("screenshot_width", 640))
        self.shot_height.delete(0, tk.END); self.shot_height.insert(0, cap.get("screenshot_height", 360))
        self.capture_backend.set(cap.get("backend", "auto"))
        self.fps.delete(0, tk.END); self.fps.insert(0, cap["fps"])
        self.threshold.set(cfg["detector"]["threshold"])
        self.clear_threshold.set(cfg["detector"]["clear_threshold"])
        self.threshold_text.config(text=f"{cfg['detector']['threshold']:.2f}")
        self.clear_text.config(text=f"{cfg['detector']['clear_threshold']:.2f}")
        self.hits.delete(0, tk.END); self.hits.insert(0, cfg["detector"]["consecutive_hits"])
        self.clears.delete(0, tk.END); self.clears.insert(0, cfg["detector"]["consecutive_clear"])
        self.min_hold.delete(0, tk.END); self.min_hold.insert(0, cfg["detector"]["min_hold_seconds"])

        out = cfg["output"]
        self.output_mode.set(out["mode"])
        obs = out["obs"]
        for attr, key in [("obs_host", "host"), ("obs_port", "port"), ("obs_password", "password"),
                          ("source_name", "source_name"), ("filter_name", "filter_name"),
                          ("normal_scene", "normal_scene"), ("blocked_scene", "blocked_scene")]:
            e = getattr(self, attr)
            e.delete(0, tk.END); e.insert(0, str(obs.get(key, "")))

        comp = out.get("companion", {})
        self.comp_mode.set(comp.get("key_mode", "dual"))
        for entry, key, default in [
            (self.comp_show_key, "show_hotkey", comp.get("on_hotkey", "f9")),
            (self.comp_hide_key, "hide_hotkey", comp.get("off_hotkey", "f10")),
            (self.comp_toggle_key, "toggle_hotkey", "ctrl+shift+8"),
            (self.comp_interval, "press_interval", 0.03),
        ]:
            entry.delete(0, tk.END); entry.insert(0, str(comp.get(key, default)))

        hk = cfg["hotkeys"]
        for entry, key in [(self.hk_toggle, "toggle"), (self.hk_panic, "panic"),
                           (self.hk_resume, "resume_auto")]:
            entry.delete(0, tk.END); entry.insert(0, hk.get(key, ""))

        region = cfg["capture"].get("region")
        self.region_label.config(text="全屏" if not region else
                                 f"{region['width']}×{region['height']} @ {region['left']},{region['top']}")
        self._on_source_change()
        self._on_output_change()
        self._sync_scale_labels()

    def _on_output_change(self):
        """按输出方式显示对应面板，并给出画面来源提示与热键冲突检查。"""
        mode = self.output_mode.get()
        is_obs = mode in ("obs_filter", "obs_scene")
        is_comp = mode == "companion"

        if is_obs:
            self.obs_panel.grid()
            self.companion_panel.grid_remove()
        elif is_comp:
            self.obs_panel.grid_remove()
            self.companion_panel.grid()
        else:  # dry_run
            self.obs_panel.grid_remove()
            self.companion_panel.grid_remove()

        hints = {
            "obs_filter": "通过 OBS WebSocket 切换模糊滤镜。需先在 OBS 中启用 WebSocket 并添加滤镜。",
            "obs_scene": "通过 OBS WebSocket 切换正常/遮挡两个场景。",
            "companion": "无 API 方案：模拟直播伴侣的自定义快捷键，控制遮挡图片素材的显示/隐藏。画面来源建议用 screen 或 window。",
            "dry_run": "只在日志里显示遮挡状态，不控制任何软件。用于测试判定逻辑。",
        }
        self.output_hint.config(text=hints.get(mode, ""))
        self._on_comp_mode_change()
        self._check_hotkey_conflict()

    def _on_comp_mode_change(self):
        mode = self.comp_mode.get()
        dual = mode != "toggle"
        for entry in (self.comp_show_key, self.comp_hide_key):
            entry.config(state=tk.NORMAL if dual else tk.DISABLED)
        self.comp_toggle_key.config(state=tk.DISABLED if dual else tk.NORMAL)

    def _check_hotkey_conflict(self):
        """检查伴侣输出热键是否与本程序的手动热键冲突。"""
        from .keys import parse_hotkey

        self.comp_warning.config(text="")
        if self.output_mode.get() != "companion":
            return
        manual = {parse_hotkey(self.hk_toggle.get()), parse_hotkey(self.hk_panic.get()),
                  parse_hotkey(self.hk_resume.get())}
        manual.discard(None)
        mode = self.comp_mode.get()
        used = ([self.comp_toggle_key.get()] if mode == "toggle"
                else [self.comp_show_key.get(), self.comp_hide_key.get()])
        for text in used:
            hk = parse_hotkey(text)
            if hk is not None and hk in manual:
                self.comp_warning.config(
                    text=f"⚠ {hk.display} 与手动控制热键冲突，可能导致状态反复切换。请改成不同的键。"
                )
                return

    def _on_source_change(self):
        """按所选来源切换专属控件并更新说明。"""
        kind = self.source_kind.get()
        use_obs = kind in ("obs_scene", "obs_source")
        if use_obs:
            self.source_panel.tkraise()
            self.screen_panel.grid_remove()
            self.source_panel.grid()
        elif kind == "window":
            self.source_panel.tkraise()
            self.screen_panel.grid_remove()
            self.source_panel.grid()
        else:
            self.screen_panel.tkraise()
            self.source_panel.grid_remove()
            self.screen_panel.grid()

        hints = {
            "obs_scene": "推荐：检测 OBS 当前节目场景的最终合成画面，与观众所见一致，不受弹窗/最小化影响。",
            "obs_source": "检测 OBS 中某个指定源（如游戏捕获），点「刷新 OBS 源」选择。",
            "window": "跟踪指定窗口的屏幕区域，DX 全屏游戏推荐用无边框窗口；被遮挡时可能抓到遮挡物。",
            "screen": "抓取整屏或框选区域，直播伴侣等无 API 软件用此方式。",
        }
        self.source_hint.config(text=hints.get(kind, ""))

        # OBS 源输入框仅在 obs_source 时启用
        for widget in (self.obs_source_name,):
            state = "normal" if kind == "obs_source" else "disabled"
            try:
                widget.config(state=state)
            except tk.TclError:
                pass

    def _refresh_obs_sources(self):
        self._read_ui_to_cfg()
        obs = self.cfg["output"]["obs"]

        def worker():
            try:
                from obsws_python import ReqClient

                client = ReqClient(host=obs["host"], port=obs["port"], password=obs["password"])
                scenes = [s.get("sceneName") for s in client.get_scene_list().scenes]
                sources = [s.get("sourceName") for s in client.get_source_list().sources]
                client.disconnect()
                values = sorted(set([v for v in scenes + sources if v]))
                self.root.after(0, lambda: self._apply_obs_source_values(values))
            except Exception as exc:
                self.root.after(0, lambda: self._append_log("ERROR", f"刷新 OBS 源失败: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_obs_source_values(self, values: list[str]):
        self.obs_source_name["values"] = values
        self.window_title["values"] = values
        self._append_log("INFO", f"已加载 {len(values)} 个 OBS 场景/源")

    def _refresh_windows(self):
        def worker():
            titles = sorted({w["title"] for w in self.engine.list_windows()})
            self.root.after(0, lambda: self._apply_window_values(titles))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_window_values(self, titles: list[str]):
        self.window_title["values"] = titles
        self._append_log("INFO", f"已加载 {len(titles)} 个窗口")

    def _read_ui_to_cfg(self):
        try:
            self.cfg["detector"]["backend"] = self.backend.get()
            cap = self.cfg["capture"]
            cap["source"] = self.source_kind.get()
            cap["obs_source_name"] = self.obs_source_name.get()
            cap["window_title"] = self.window_title.get()
            cap["screenshot_width"] = int(self.shot_width.get())
            cap["screenshot_height"] = int(self.shot_height.get())
            cap["backend"] = self.capture_backend.get()
            cap["fps"] = int(self.fps.get())
            self.cfg["detector"]["threshold"] = round(float(self.threshold.get()), 3)
            self.cfg["detector"]["clear_threshold"] = round(float(self.clear_threshold.get()), 3)
            self.cfg["detector"]["consecutive_hits"] = int(self.hits.get())
            self.cfg["detector"]["consecutive_clear"] = int(self.clears.get())
            self.cfg["detector"]["min_hold_seconds"] = float(self.min_hold.get())
            self.cfg["output"]["mode"] = self.output_mode.get()
            obs = self.cfg["output"]["obs"]
            obs.update({
                "host": self.obs_host.get(), "port": int(self.obs_port.get()),
                "password": self.obs_password.get(), "source_name": self.source_name.get(),
                "filter_name": self.filter_name.get(), "normal_scene": self.normal_scene.get(),
                "blocked_scene": self.blocked_scene.get(),
            })
            comp = self.cfg["output"].setdefault("companion", {})
            comp.update({
                "key_mode": self.comp_mode.get(),
                "show_hotkey": self.comp_show_key.get(),
                "hide_hotkey": self.comp_hide_key.get(),
                "toggle_hotkey": self.comp_toggle_key.get(),
            })
            try:
                comp["press_interval"] = float(self.comp_interval.get())
            except ValueError:
                comp["press_interval"] = 0.03
            self.cfg["hotkeys"].update({
                "toggle": self.hk_toggle.get(), "panic": self.hk_panic.get(),
                "resume_auto": self.hk_resume.get(),
            })
        except ValueError as exc:
            messagebox.showwarning("输入有误", f"请检查数值输入: {exc}")

    def _sync_scale_labels(self):
        self.threshold_text.config(text=f"{float(self.threshold.get()):.2f}")
        self.clear_text.config(text=f"{float(self.clear_threshold.get()):.2f}")

    # ---------- 按钮动作 ----------
    def _on_start(self):
        self._read_ui_to_cfg()
        if self.cfg["detector"]["backend"] == "heuristic":
            self._append_log("WARN", "启发式检测误报率较高，正式直播前请用样本校准阈值")
        self.engine.start()
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)

    def _on_stop(self):
        self.engine.stop()
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)

    # ---------- 直播伴侣 ----------
    def _generate_cover(self):
        """生成可导入直播伴侣的遮挡图片素材。"""
        from tools.make_cover import STYLE_LABELS, make_cover

        folder = filedialog.askdirectory(title="选择遮挡素材保存目录")
        if not folder:
            return
        try:
            from tkinter import simpledialog

            text = simpledialog.askstring("遮挡素材", "遮挡画面上显示的文字:",
                                          initialvalue="画面已临时处理", parent=self.root)
            if text is None:
                return
            paths = []
            for style, label in STYLE_LABELS.items():
                p = make_cover(Path(folder) / f"遮挡素材_{style}.png", style=style, text=text,
                               width=1920, height=1080)
                paths.append(p)
            self._append_log("INFO", f"已生成 {len(paths)} 张遮挡素材到 {folder}")
            messagebox.showinfo(
                "遮挡素材已生成",
                f"已生成 {len(paths)} 张 PNG:\n" + "\n".join(p.name for p in paths)
                + "\n\n在直播伴侣中「添加素材 → 图片」选一张，"
                  "拉伸铺满画布并置于最上层。",
            )
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc))

    def _open_companion_wizard(self):
        """分步讲解如何把抖音直播伴侣接入 Stream Guard。"""
        win = tk.Toplevel(self.root)
        win.title("抖音直播伴侣 · 接入向导")
        win.geometry("620x560")
        win.transient(self.root)

        frame = ttk.Frame(win, padding=(16, 14))
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frame, text="抖音直播伴侣接入向导",
                  font=("Microsoft YaHei", 14, "bold")).pack(anchor=tk.W)
        ttk.Label(frame, text="直播伴侣没有开放接口，通过「自定义快捷键 + 遮挡图片素材」实现自动遮挡。",
                  foreground="#6b7280", wraplength=580).pack(anchor=tk.W, pady=(4, 10))

        steps = [
            ("1. 准备遮挡素材",
             "点「生成遮挡素材」按钮，选一个目录生成 PNG。回到直播伴侣，"
             "「添加素材 → 图片」选中它，拉伸铺满画布并拖到最上层。平时保持隐藏。"),
            ("2. 设置快捷键",
             "直播伴侣左下角「直播设置 → 快捷键」，找到刚添加的图片素材，"
             "给「显示」绑定一个冷门组合键（如 Ctrl+Shift+9），「隐藏」绑定另一个（如 Ctrl+Shift+0）。"
             "不要用 Ctrl+1~9（那被场景切换占用），也不要和游戏按键、本程序热键重复。"),
            ("3. 在本程序填入同样的键",
             "输出方式选 companion；按键模式选 dual（显示/隐藏分开，最稳）；"
             "填入与直播伴侣完全一致的显示键和隐藏键。填完界面会自动检查是否与手动热键冲突。"),
            ("4. 选择画面来源",
             "直播伴侣无 API，检测画面请选 screen（框选游戏区域，排除弹幕和伴侣界面）"
             "或 window（跟踪游戏窗口）。OBS 虚拟摄像机方案也可保留 obs_scene。"),
            ("5. 测试与开播",
             "先点「开始监控」，用测试素材或真实画面触发一次，确认伴侣画面会自动盖遮挡、"
             "恢复后自动撤掉。确认无误再正式开播。"),
        ]
        for title, body in steps:
            box = ttk.LabelFrame(frame, text=title, padding=(10, 6))
            box.pack(fill=tk.X, pady=(0, 8))
            ttk.Label(box, text=body, wraplength=560, justify=tk.LEFT).pack(anchor=tk.W)

        note = ("提醒：模拟按键作用于当前焦点窗口。若直播伴侣的快捷键是全局生效的（推荐），"
                "切到游戏也无妨；若只在伴侣窗口内生效，开播时请勿让游戏独占焦点，"
                "或把游戏设为无边框窗口模式。")
        ttk.Label(frame, text=note, wraplength=580, foreground="#b45309",
                  justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 8))

        btns = ttk.Frame(frame)
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="生成遮挡素材", command=self._generate_cover).pack(side=tk.LEFT)
        ttk.Button(btns, text="关闭", command=win.destroy).pack(side=tk.RIGHT)

    def _pick_region(self):
        try:
            from tools.region_picker import pick_region

            region = pick_region()
            if region:
                self.cfg["capture"]["region"] = region
                self.region_label.config(
                    text=f"{region['width']}×{region['height']} @ {region['left']},{region['top']}"
                )
                self._append_log("INFO", "已选择抓屏区域，保存配置后重启引擎生效")
        except Exception as exc:
            messagebox.showerror("框选失败", str(exc))

    def _clear_region(self):
        self.cfg["capture"]["region"] = None
        self.region_label.config(text="全屏")
        self._append_log("INFO", "已清除区域限制，保存后重启引擎生效")

    def _test_obs(self):
        self.obs_status.config(text="测试中...")
        self._read_ui_to_cfg()

        def worker():
            try:
                from obsws_python import ReqClient

                from guard.output import list_obs_sources

                obs = self.cfg["output"]["obs"]
                client = ReqClient(host=obs["host"], port=obs["port"], password=obs["password"])
                client.get_current_program_scene()
                sources = list_obs_sources(obs)
                filters = client.get_source_filter_list(obs["source_name"]).filters
                names = [f.get("filterName") for f in filters]
                client.disconnect()
                ok = obs["filter_name"] in names
                base = "连接成功 · 滤镜已就绪" if ok else f"连接成功 · 缺少滤镜 {obs['filter_name']}"
                if sources:
                    base += " | 可用源: " + ", ".join(sources[:6])
                text = base
                self.root.after(0, lambda: self.obs_status.config(
                    text=text, foreground="#059669" if ok else "#d97706"))
            except Exception as exc:
                self.root.after(0, lambda: self.obs_status.config(
                    text=f"失败: {str(exc)[:40]}", foreground="#dc2626"))

        threading.Thread(target=worker, daemon=True).start()

    def _create_filter(self):
        self._read_ui_to_cfg()

        def worker():
            try:
                from guard.output import ensure_obs_filter

                message = ensure_obs_filter(self.cfg["output"]["obs"])
                self.root.after(0, lambda: (
                    self.obs_status.config(text=message, foreground="#059669"),
                    self._append_log("INFO", message),
                ))
            except Exception as exc:
                message = f"创建失败: {exc}"
                self.root.after(0, lambda: (
                    self.obs_status.config(text=message[:60], foreground="#dc2626"),
                    self._append_log("ERROR", message),
                ))

        threading.Thread(target=worker, daemon=True).start()

    def _export_config(self):
        self._read_ui_to_cfg()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)

    def _import_config(self):
        path = filedialog.askopenfilename(filetypes=[("JSON", "*.json")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.cfg = json.load(f)
            self.engine.cfg = self.cfg
            self._load_cfg_to_ui()
            messagebox.showinfo("已导入", "配置已载入，点击「保存配置」可设为默认。")
        except Exception as exc:
            messagebox.showerror("导入失败", str(exc))

    def _export_diagnostics(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt", initialfile="stream-guard-diagnostics.txt",
            filetypes=[("Text", "*.txt")])
        if not path:
            return
        safe = json.loads(json.dumps(self.cfg))
        if "obs" in safe.get("output", {}):
            safe["output"]["obs"]["password"] = "***"
        lines = [
            f"Stream Guard 诊断报告",
            f"平台: {sys.platform} / Python {sys.version.split()[0]}",
            f"抓屏后端: {self.cfg['capture'].get('backend')}",
            "",
            "配置:", json.dumps(safe, ensure_ascii=False, indent=2),
            "",
            f"统计: {self.stats_snapshot()}",
            "",
            "最近日志:",
            self.log_text.get("1.0", tk.END)[-6000:],
        ]
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def stats_snapshot(self) -> str:
        s = self._status
        return (f"遮挡 {s['count']} 次 / 累计 {s['total_seconds']:.1f} 秒 / "
                f"最近 {s['last_at']}")

    # ---------- 事件轮询 ----------
    def _poll(self):
        try:
            while True:
                msg = self.engine.events.get_nowait()
                if msg[0] == "log":
                    self._append_log(msg[1], msg[2])
                elif msg[0] == "status":
                    self._update_status(msg[1])
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _append_log(self, level: str, message: str):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{level}] {message}\n")
        # 日志面板行数有界：超过上限删掉最旧的一半，避免长期运行占用内存
        try:
            line_count = int(self.log_text.index("end-1c").split(".")[0])
            if line_count > 600:
                self.log_text.delete("1.0", "300.0")
        except Exception:
            pass
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def _update_status(self, data: dict):
        self._status.update(data)
        score = float(data.get("score", 0.0))
        blocked = bool(data.get("blocked", False))
        mode = data.get("mode", "停止")
        self.score_bar["value"] = min(100, score * 100)
        self.score_label.config(text=f"{score:.3f}")
        self.mode_label.config(text=f"模式: {mode}")

        if mode == "停止":
            color, text = "#9ca3af", "已停止"
        elif blocked:
            color, text = "#dc2626", "遮挡中"
        elif mode == "手动":
            color, text = "#2563eb", "手动解除"
        else:
            color, text = "#059669", "自动监控中"
        self.status_canvas.itemconfig(self.status_dot, fill=color)
        self.status_label.config(text=text)

        s = self._status
        self.stat_vars["count"].set(str(s["count"]))
        self.stat_vars["total_seconds"].set(f"{float(s['total_seconds']):.1f} 秒")
        self.stat_vars["last_at"].set(str(s["last_at"]))

    # ---------- 托盘 ----------
    def _setup_tray(self):
        import platform

        if platform.system() != "Windows":
            self._append_log("INFO", "系统托盘仅在 Windows 版启用；macOS 版关闭窗口即退出")
            return
        try:
            import pystray

            image = Image.new("RGB", (64, 64), "#2563eb")
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle((10, 6, 54, 34), radius=5, fill="#ffffff")
            draw.polygon([(32, 58), (16, 36), (48, 36)], fill="#ffffff")
            menu = pystray.Menu(
                pystray.MenuItem("显示窗口", lambda *_: self.root.after(0, self._show_window)),
                pystray.MenuItem("紧急遮挡", lambda *_: self.engine.panic()),
                pystray.MenuItem("退出", lambda *_: self.root.after(0, self._quit)),
            )
            self.tray = pystray.Icon("StreamGuard", image, "Stream Guard", menu)
            threading.Thread(target=self.tray.run, daemon=True).start()
        except Exception as exc:
            self._append_log("WARN", f"系统托盘不可用: {exc}")

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()

    def _on_close(self):
        if self.tray:
            self.root.withdraw()
            self._append_log("INFO", "已最小化到托盘，右键托盘图标可退出")
        else:
            self._quit()

    def _quit(self):
        try:
            self._hotkeys.stop()
            self.engine.stop()
        finally:
            if self.tray:
                try:
                    self.tray.stop()
                except Exception:
                    pass
            self.root.destroy()
