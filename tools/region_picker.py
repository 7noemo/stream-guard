"""可视化区域选择：全屏半透明蒙层上拖拽框选游戏画面区域。"""
from __future__ import annotations

import tkinter as tk


def pick_region() -> dict | None:
    """返回 {left, top, width, height}（相对主显示器），取消返回 None。"""
    result: dict | None = None
    start = {"x": 0, "y": 0}
    rect = {"id": None}

    root = tk.Tk()
    root.title("框选游戏画面区域 · 拖拽选择，Esc 取消")
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", 0.35)
    except tk.TclError:
        pass

    canvas = tk.Canvas(root, highlightthickness=0, bg="#2b2b2b")
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_text(
        root.winfo_screenwidth() // 2,
        40,
        text="拖拽鼠标框选游戏画面区域，松开确认；按 Esc 取消",
        fill="#ffffff",
        font=("Microsoft YaHei", 16),
    )

    def on_press(event):
        start["x"], start["y"] = event.x, event.y
        if rect["id"]:
            canvas.delete(rect["id"])
        rect["id"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#ff4d4f", width=2
        )

    def on_drag(event):
        if rect["id"]:
            canvas.coords(rect["id"], start["x"], start["y"], event.x, event.y)

    def on_release(event):
        nonlocal result
        x1, y1 = min(start["x"], event.x), min(start["y"], event.y)
        x2, y2 = max(start["x"], event.x), max(start["y"], event.y)
        if x2 - x1 > 40 and y2 - y1 > 40:
            result = {"left": x1, "top": y1, "width": x2 - x1, "height": y2 - y1}
        root.destroy()

    def on_escape(_event=None):
        root.destroy()

    root.bind("<ButtonPress-1>", on_press)
    root.bind("<B1-Motion>", on_drag)
    root.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)
    root.mainloop()
    return result


if __name__ == "__main__":
    print(pick_region())
