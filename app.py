"""Stream Guard 图形界面入口。"""
from __future__ import annotations

import sys
import tkinter as tk

from guard.gui import App


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
