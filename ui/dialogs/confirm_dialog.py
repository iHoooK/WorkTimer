"""
ui/dialogs/confirm_dialog.py — Модальный диалог подтверждения (центрируется на экране).
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from ui.theme import COLORS, FONTS
from ui.utils import center_window

_W, _H = 320, 180


class ConfirmDialog:
    @staticmethod
    def show(
        parent,
        title:     str,
        message:   str,
        on_yes:    Callable,
        yes_label: str               = "OK",
        color:     str               = COLORS["work"],
        on_no:     Optional[Callable] = None,
    ) -> ctk.CTkToplevel:
        win = ctk.CTkToplevel(parent)
        win.title("")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["panel"])
        win.grab_set()
        center_window(win, _W, _H)
        win.lift()
        win.focus_force()

        ctk.CTkLabel(win, text=title,
                     font=FONTS["dialog_title"], text_color=color).pack(pady=(22, 4))

        ctk.CTkLabel(win, text=message,
                     font=FONTS["label"], text_color=COLORS["subtext"]).pack(pady=4)

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(pady=14)

        def _yes():
            win.destroy()
            on_yes()

        def _no():
            win.destroy()
            if on_no:
                on_no()

        ctk.CTkButton(row, text=yes_label, width=130, height=34,
                      font=FONTS["label_bold"], fg_color=color,
                      hover_color=COLORS["btn_hover"], corner_radius=5,
                      command=_yes).pack(side="left", padx=8)

        ctk.CTkButton(row, text="Отмена", width=100, height=34,
                      font=FONTS["label"], fg_color=COLORS["btn_neutral"],
                      hover_color=COLORS["btn_hover"], corner_radius=5,
                      command=_no).pack(side="left", padx=8)

        return win
