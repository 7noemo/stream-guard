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
    "capture": {"backend": "auto", "monitor": 0, "fps": 8, "region": None},
    "detector": {
        "backend": "heuristic",
        "threshold": 0.72,
        "clear_threshold": 0.45,
        "consecutive_hits": 3,
        "consecutive_clear": 5,
        "min_hold_seconds": 2.0,
        "mock_scores": [0.05, 0.08, 0.12, 0.85, 0.88, 0.91, 0.80, 0.30, 0.10, 0.05],
    },
    "output": {
        "mode": "obs_filter",
        "obs": {
            "host": "localhost", "port": 4455, "password": "",
            "source_name": "Game Capture", "filter_name": "StreamGuard_Blur",
            "normal_scene": "Live", "blocked_scene": "StreamGuard_Blocked",
        },
        "companion": {"on_hotkey": "f9", "off_hotkey": "f10"},
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
        root.geometry("960x700")
        root.minsize(880, 640)
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

        left = ttk.LabelFrame(cols, text="检测与抓屏", padding=(12, 10))
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        ttk.Label(left, text="检测后端").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.backend = ttk.Combobox(left, values=["heuristic", "mock", "opennsfw2", "clip"], width=18)
        self.backend.grid(row=0, column=1, sticky=tk.W, pady=3)

        ttk.Label(left, text="抓屏后端").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.capture_backend = ttk.Combobox(left, values=["auto", "mss", "dxcam"], width=18)
        self.capture_backend.grid(row=1, column=1, sticky=tk.W, pady=3)

        ttk.Label(left, text="检测帧率").grid(row=2, column=0, sticky=tk.W, pady=3)
        self.fps = ttk.Spinbox(left, from_=1, to=30, width=8)
        self.fps.grid(row=2, column=1, sticky=tk.W, pady=3)

        ttk.Label(left, text="触发阈值").grid(row=3, column=0, sticky=tk.W, pady=3)
        self.threshold = ttk.Scale(left, from_=0.3, to=0.95, length=170)
        self.threshold.grid(row=3, column=1, sticky=tk.W, pady=3)
        self.threshold_text = ttk.Label(left, text="0.72")
        self.threshold_text.grid(row=3, column=2, padx=6)

        ttk.Label(left, text="解除阈值").grid(row=4, column=0, sticky=tk.W, pady=3)
        self.clear_threshold = ttk.Scale(left, from_=0.05, to=0.8, length=170)
        self.clear_threshold.grid(row=4, column=1, sticky=tk.W, pady=3)
        self.clear_text = ttk.Label(left, text="0.45")
        self.clear_text.grid(row=4, column=2, padx=6)

        ttk.Label(left, text="连续命中/解除").grid(row=5, column=0, sticky=tk.W, pady=3)
        frame_hits = ttk.Frame(left)
        frame_hits.grid(row=5, column=1, columnspan=2, sticky=tk.W)
        self.hits = ttk.Spinbox(frame_hits, from_=1, to=20, width=6)
        self.hits.pack(side=tk.LEFT)
        ttk.Label(frame_hits, text="/").pack(side=tk.LEFT, padx=4)
        self.clears = ttk.Spinbox(frame_hits, from_=1, to=20, width=6)
        self.clears.pack(side=tk.LEFT)
        ttk.Label(frame_hits, text="帧").pack(side=tk.LEFT, padx=4)

        ttk.Label(left, text="最短保持(秒)").grid(row=6, column=0, sticky=tk.W, pady=3)
        self.min_hold = ttk.Spinbox(left, from_=0, to=15, width=8)
        self.min_hold.grid(row=6, column=1, sticky=tk.W, pady=3)

        region_row = ttk.Frame(left)
        region_row.grid(row=7, column=0, columnspan=3, pady=(10, 0), sticky=tk.W)
        ttk.Button(region_row, text="框选游戏画面区域", command=self._pick_region).pack(side=tk.LEFT)
        ttk.Button(region_row, text="清除", command=self._clear_region).pack(side=tk.LEFT, padx=6)
        self.region_label = ttk.Label(region_row, text="全屏", foreground="#6b7280")
        self.region_label.pack(side=tk.LEFT, padx=6)

        right = ttk.LabelFrame(cols, text="输出与热键", padding=(12, 10))
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        ttk.Label(right, text="输出方式").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.output_mode = ttk.Combobox(
            right, values=["obs_filter", "obs_scene", "companion", "dry_run"], width=18
        )
        self.output_mode.grid(row=0, column=1, sticky=tk.W, pady=3)

        obs_fields = [
            ("OBS 地址", "obs_host"), ("端口", "obs_port"), ("密码", "obs_password"),
            ("捕获源名称", "source_name"), ("模糊滤镜名", "filter_name"),
            ("正常场景", "normal_scene"), ("遮挡场景", "blocked_scene"),
        ]
        for i, (label, attr) in enumerate(obs_fields, start=1):
            ttk.Label(right, text=label).grid(row=i, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(right, width=22, show="*" if attr == "obs_password" else None)
            entry.grid(row=i, column=1, sticky=tk.W, pady=2)
            setattr(self, attr, entry)

        obs_btns = ttk.Frame(right)
        obs_btns.grid(row=8, column=0, columnspan=2, sticky=tk.W, pady=(6, 0))
        ttk.Button(obs_btns, text="测试连接", command=self._test_obs).pack(side=tk.LEFT)
        ttk.Button(obs_btns, text="一键创建模糊滤镜", command=self._create_filter).pack(side=tk.LEFT, padx=6)
        self.obs_status = ttk.Label(right, text="", foreground="#6b7280", wraplength=330)
        self.obs_status.grid(row=9, column=0, columnspan=2, sticky=tk.W)

        hk = ttk.Frame(right)
        hk.grid(row=10, column=0, columnspan=2, pady=(10, 0), sticky=tk.W)
        ttk.Label(hk, text="热键 切换/紧急/自动").pack(side=tk.LEFT)
        self.hk_toggle = ttk.Entry(hk, width=6)
        self.hk_panic = ttk.Entry(hk, width=6)
        self.hk_resume = ttk.Entry(hk, width=6)
        for e in (self.hk_toggle, self.hk_panic, self.hk_resume):
            e.pack(side=tk.LEFT, padx=3)

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
        self.capture_backend.set(cfg["capture"].get("backend", "auto"))
        self.fps.delete(0, tk.END); self.fps.insert(0, cfg["capture"]["fps"])
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

        hk = cfg["hotkeys"]
        for entry, key in [(self.hk_toggle, "toggle"), (self.hk_panic, "panic"),
                           (self.hk_resume, "resume_auto")]:
            entry.delete(0, tk.END); entry.insert(0, hk.get(key, ""))

        region = cfg["capture"].get("region")
        self.region_label.config(text="全屏" if not region else
                                 f"{region['width']}×{region['height']} @ {region['left']},{region['top']}")
        self._sync_scale_labels()

    def _read_ui_to_cfg(self):
        try:
            self.cfg["detector"]["backend"] = self.backend.get()
            self.cfg["capture"]["backend"] = self.capture_backend.get()
            self.cfg["capture"]["fps"] = int(self.fps.get())
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
