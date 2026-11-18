"""用样本图片校准阈值：文件名以 pos_ 开头视为风险样本，neg_ 开头为安全样本。"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from PIL import Image

from guard.detector import build_detector


def main():
    parser = argparse.ArgumentParser(description="检测阈值校准工具")
    parser.add_argument("folder", help="样本图片目录")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    with open(args.config, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    detector = build_detector(cfg["detector"])

    positive, negative = [], []
    for path in sorted(Path(args.folder).glob("*")):
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        score = detector.predict(Image.open(path))
        print(f"{score:.3f}  {path.name}")
        (positive if path.name.startswith("pos_") else negative).append(score)

    print("\n" + "=" * 48)
    for label, scores in [("风险样本 pos_", positive), ("安全样本 neg_", negative)]:
        if scores:
            print(f"{label}: n={len(scores)} min={min(scores):.3f} "
                  f"mean={statistics.mean(scores):.3f} max={max(scores):.3f}")
        else:
            print(f"{label}: 无样本")
    if positive and negative:
        suggested = (min(positive) + max(negative)) / 2
        print(f"建议阈值（两者中点）: {suggested:.3f}")
        if suggested <= max(negative) or suggested >= min(positive):
            print("警告: 两类分数有重叠，单靠阈值无法完全分开，需换后端或调提示词")


if __name__ == "__main__":
    main()
