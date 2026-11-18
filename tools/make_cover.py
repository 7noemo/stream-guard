"""生成可直接导入抖音直播伴侣的遮挡图片素材。

直播伴侣没有 OBS 那样的滤镜 API，但支持图片素材 + 快捷键显示/隐藏。
本工具生成一张铺满画布的遮挡图，主播把它加到直播伴侣最上层，
再用 Stream Guard 模拟热键控制它的显示/隐藏。

用法：
    python3 tools/make_cover.py ./covers
或在界面点「生成遮挡素材」按钮。
"""
from __future__ import annotations

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

STYLES = ("frost", "dark", "mosaic", "solid")

STYLE_LABELS = {
    "frost": "磨砂玻璃（浅色）",
    "dark": "哑光深色",
    "mosaic": "马赛克块",
    "solid": "纯色遮罩",
}


def _load_font(size: int):
    """跨平台尽力加载中文字体，失败时用默认字体。"""
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        try:
            if Path(path).exists():
                return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def make_cover(
    path: str | Path,
    style: str = "frost",
    text: str = "画面已临时处理",
    subtitle: str = "Stream Guard · 内容合规守护",
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """生成一张不透明遮挡图并保存，返回文件路径。"""
    if style not in STYLES:
        raise ValueError(f"未知风格: {style}，可选 {STYLES}")
    width, height = max(320, int(width)), max(180, int(height))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if style == "frost":
        img = Image.new("RGB", (width, height), (226, 232, 240))
        # 柔和的斜向色块，避免纯色过于刺眼
        d = ImageDraw.Draw(img)
        for i in range(0, width + height, 90):
            d.line([(i, 0), (i - height, height)], fill=(214, 222, 233), width=46)
        img = img.filter(ImageFilter.GaussianBlur(radius=18))
        fg = (71, 85, 105)
    elif style == "dark":
        img = Image.new("RGB", (width, height), (24, 28, 36))
        d = ImageDraw.Draw(img)
        for i in range(0, width, 160):
            d.rectangle([i, 0, i + 80, height], fill=(30, 35, 44))
        fg = (226, 232, 240)
    elif style == "mosaic":
        img = Image.new("RGB", (width, height), (40, 44, 52))
        d = ImageDraw.Draw(img)
        rnd = random.Random(20261118)
        block = max(24, width // 48)
        palette = [(58, 64, 78), (76, 84, 102), (46, 52, 66), (92, 100, 118)]
        for y in range(0, height, block):
            for x in range(0, width, block):
                d.rectangle(
                    [x, y, min(x + block, width), min(y + block, height)],
                    fill=rnd.choice(palette),
                )
        fg = (255, 255, 255)
    else:  # solid
        img = Image.new("RGB", (width, height), (17, 24, 39))
        fg = (233, 238, 245)

    d = ImageDraw.Draw(img)
    font_size = max(20, width // 22)
    font = _load_font(font_size)
    sub_font = _load_font(max(14, font_size // 2))

    if text:
        box = d.textbbox((0, 0), text, font=font) if font else (0, 0, len(text) * font_size, font_size)
        tw = box[2] - box[0]
        d.text(((width - tw) / 2, height / 2 - font_size), text, fill=fg, font=font)
    if subtitle and sub_font:
        box = d.textbbox((0, 0), subtitle, font=sub_font)
        tw = box[2] - box[0]
        d.text(((width - tw) / 2, height / 2 + font_size * 0.7), subtitle,
               fill=tuple(min(255, c + 20) for c in fg), font=sub_font)

    img.save(path, "PNG")
    return path


def generate_all(folder: str | Path, width: int = 1920, height: int = 1080) -> list[Path]:
    """一次性生成四种风格的遮挡图。"""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return [
        make_cover(folder / f"遮挡素材_{style}_{width}x{height}.png", style=style,
                   width=width, height=height)
        for style in STYLES
    ]


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "./covers"
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 1920
    h = int(sys.argv[3]) if len(sys.argv) > 3 else 1080
    for p in generate_all(target, w, h):
        print(p)
