"""
ui/dialogs/profile_dialog.py — Диалоги профилей (центрируются на экране, мин+сек).
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk
from ui.theme import COLORS, FONTS
from ui.utils import center_window


class ProfileDialog:

    @staticmethod
    def show_create(
        parent,
        on_create: Callable[[str, int, int], None],
    ) -> ctk.CTkToplevel:
        """on_create(name, work_total_seconds, break_total_seconds)"""
        W, H = 360, 310
        win = ctk.CTkToplevel(parent)
        win.title("Новый профиль")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["panel"])
        win.grab_set()
        center_window(win, W, H)
        win.lift()
        win.focus_force()

        ctk.CTkLabel(win, text="Новый профиль",
                     font=FONTS["dialog_title"], text_color=COLORS["work"]).pack(pady=(16, 10))

        grid = ctk.CTkFrame(win, fg_color="transparent")
        grid.pack(pady=2)

        def lbl(row, text, color=COLORS["subtext"]):
            ctk.CTkLabel(grid, text=text, font=FONTS["label"],
                         text_color=color).grid(row=row, column=0, padx=10, pady=4, sticky="w")

        def ent(row, col, default="0"):
            e = ctk.CTkEntry(grid, width=56, height=28, font=FONTS["entry"],
                             fg_color=COLORS["bg"], border_color=COLORS["border"],
                             text_color=COLORS["text"], justify="center")
            e.insert(0, default)
            e.grid(row=row, column=col, padx=4, pady=4)
            return e

        # Заголовки колонок
        ctk.CTkLabel(grid, text="мин", font=FONTS["label"],
                     text_color=COLORS["subtext"]).grid(row=0, column=1, padx=4)
        ctk.CTkLabel(grid, text="сек", font=FONTS["label"],
                     text_color=COLORS["subtext"]).grid(row=0, column=2, padx=4)

        # Название
        ctk.CTkLabel(grid, text="Название", font=FONTS["label"],
                     text_color=COLORS["subtext"]).grid(row=1, column=0, padx=10, pady=4, sticky="w")
        entry_name = ctk.CTkEntry(grid, width=140, height=28, font=FONTS["entry"],
                                  fg_color=COLORS["bg"], border_color=COLORS["border"],
                                  text_color=COLORS["text"])
        entry_name.grid(row=1, column=1, columnspan=2, padx=4, pady=4)
        entry_name.focus_set()

        lbl(2, "Работа", COLORS["work"])
        e_wm = ent(2, 1, "25")
        e_ws = ent(2, 2, "0")

        lbl(3, "Отдых", COLORS["rest"])
        e_rm = ent(3, 1, "5")
        e_rs = ent(3, 2, "0")

        lbl_err = ctk.CTkLabel(win, text="", font=FONTS["label"],
                               text_color=COLORS["warning"])
        lbl_err.pack(pady=2)

        row_btns = ctk.CTkFrame(win, fg_color="transparent")
        row_btns.pack(pady=8)

        def _confirm():
            name = entry_name.get().strip()
            try:
                wm, ws = int(e_wm.get() or "0"), int(e_ws.get() or "0")
                rm, rs = int(e_rm.get() or "0"), int(e_rs.get() or "0")
            except ValueError:
                lbl_err.configure(text="⚠ Введите целые числа")
                return
            if not name:
                lbl_err.configure(text="⚠ Введите название")
                return
            if ws > 59 or rs > 59:
                lbl_err.configure(text="⚠ Секунды: 0–59")
                return
            win.destroy()
            on_create(name, wm * 60 + ws, rm * 60 + rs)

        ctk.CTkButton(row_btns, text="Создать", width=120, height=32,
                      font=FONTS["label_bold"], fg_color=COLORS["work"],
                      hover_color=COLORS["btn_work_hover"], corner_radius=5,
                      command=_confirm).pack(side="left", padx=6)

        ctk.CTkButton(row_btns, text="Отмена", width=90, height=32,
                      font=FONTS["label"], fg_color=COLORS["btn_neutral"],
                      hover_color=COLORS["btn_hover"], corner_radius=5,
                      command=win.destroy).pack(side="left", padx=6)

        win.bind("<Return>", lambda e: _confirm())
        return win

    @staticmethod
    def show_delete(
        parent,
        profiles: list[str],
        active:   str,
        on_delete: Callable[[str], None],
    ) -> ctk.CTkToplevel:
        W, H = 300, 200
        win = ctk.CTkToplevel(parent)
        win.title("Удалить профиль")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["panel"])
        win.grab_set()
        center_window(win, W, H)
        win.lift()
        win.focus_force()

        ctk.CTkLabel(win, text="Удалить профиль",
                     font=FONTS["dialog_title"], text_color=COLORS["danger"]).pack(pady=(20, 12))

        var = ctk.StringVar(value=active)
        ctk.CTkOptionMenu(win, variable=var, values=profiles,
                          font=FONTS["label"], fg_color=COLORS["bg"],
                          button_color=COLORS["btn_neutral"],
                          dropdown_fg_color=COLORS["panel"],
                          dropdown_text_color=COLORS["text"]).pack(pady=8)

        row_btns = ctk.CTkFrame(win, fg_color="transparent")
        row_btns.pack(pady=14)

        def _confirm():
            name = var.get()
            win.destroy()
            on_delete(name)

        ctk.CTkButton(row_btns, text="Удалить", width=110, height=34,
                      font=FONTS["label_bold"], fg_color=COLORS["danger"],
                      hover_color="#b91c1c", corner_radius=5,
                      command=_confirm).pack(side="left", padx=6)

        ctk.CTkButton(row_btns, text="Отмена", width=90, height=34,
                      font=FONTS["label"], fg_color=COLORS["btn_neutral"],
                      hover_color=COLORS["btn_hover"], corner_radius=5,
                      command=win.destroy).pack(side="left", padx=6)

        return win
