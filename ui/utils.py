"""
ui/utils.py — Общие вспомогательные функции для UI.
"""

from __future__ import annotations
import customtkinter as ctk


def center_window(win, width: int, height: int) -> None:
    """Разместить окно по центру экрана."""
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = (sw - width) // 2
    y = (sh - height) // 2
    win.geometry(f"{width}x{height}+{x}+{y}")
