"""stream-guard 主程序。

用法:
    python3 main.py --dry-run                 # 不连接 OBS，只打印判定结果
    python3 main.py --config config.json      # 正式运行
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from guard.capture import ScreenCapture
from guard.detector import build_detector
from guard.hotkeys import HotkeyManager
from guard.output import build_output
from guard.state import GuardState

log = logging.getLogger("stream-guard")


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main():
    parser = argparse.ArgumentParser(description="直播画面风险自动遮挡工具")
    parser.add_argument("--config", default="config.json", help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="不连接 OBS，仅打印判定")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg["log"].get("level", "INFO"))

    capture = ScreenCapture(
        monitor=cfg["capture"].get("monitor", 0),
        region=cfg["capture"].get("region"),
    )
    detector = build_detector(cfg["detector"])
    state = GuardState(
        threshold=cfg["detector"]["threshold"],
        clear_threshold=cfg["detector"]["clear_threshold"],
        consecutive_hits=cfg["detector"]["consecutive_hits"],
        consecutive_clear=cfg["detector"]["consecutive_clear"],
        min_hold_seconds=cfg["detector"]["min_hold_seconds"],
    )
    output = build_output(cfg["output"], dry_run=args.dry_run)

    fps = max(1, cfg["capture"].get("fps", 8))
    interval = 1.0 / fps
    sample_dir = Path(cfg["log"].get("sample_dir", "./samples"))
    save_samples = cfg["log"].get("save_samples", False)
    if save_samples:
        sample_dir.mkdir(parents=True, exist_ok=True)

    last_blocked = False

    def apply(blocked: bool, score: float, reason: str):
        nonlocal last_blocked
        output.set_blocked(blocked)
        last_blocked = blocked
        action = "开启遮挡" if blocked else "移除遮挡"
        log.warning("%s (score=%.3f, source=%s)", action, score, reason)
        if save_samples:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            try:
                capture.grab().save(sample_dir / f"{stamp}-{action}-{score:.2f}.png")
            except Exception as exc:
                log.debug("保存样本失败: %s", exc)

    hotkeys = HotkeyManager(
        cfg["hotkeys"],
        on_toggle=lambda: apply(state.toggle(), state.blocked, "manual"),
        on_panic=lambda: (state.panic(), apply(True, 1.0, "panic")),
        on_resume=lambda: log.info("已恢复自动判定，等待下一帧"),
    )
    hotkeys.start()

    log.info("启动完成: backend=%s, fps=%d, dry_run=%s",
             cfg["detector"]["backend"], fps, args.dry_run)
    log.info("提示: 手动切换 %s / 紧急遮挡 %s / 恢复自动 %s",
             cfg["hotkeys"].get("toggle"), cfg["hotkeys"].get("panic"),
             cfg["hotkeys"].get("resume_auto"))

    frames = 0
    try:
        while True:
            started = time.monotonic()
            image = capture.grab()
            score = detector.predict(image)
            decision = state.feed(score)
            frames += 1

            if decision.blocked != last_blocked:
                apply(decision.blocked, decision.score, decision.reason)
                last_blocked = decision.blocked

            if frames % (fps * 5) == 0:
                log.info("运行中: score=%.3f, 遮挡=%s, 帧数=%d",
                         score, "是" if decision.blocked else "否", frames)

            time.sleep(max(0, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log.info("收到中断，清理中...")
    finally:
        hotkeys.stop()
        output.set_blocked(False)
        output.close()
        capture.close()
        log.info("已退出")


if __name__ == "__main__":
    main()
