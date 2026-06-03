"""
ui/dialogs/profile_dialog.py — Диалог создания и удаления профилей.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from ui.theme import COLORS, FONTS


class ProfileDialog:
    """
    Диалог управления профилями: создание нового и удаление существующего.

    Пример создания нового профиля:
        ProfileDialog.show_create(
            parent=window,
            on_create=controller.create_profile,
        )

    Пример удаления:
        ProfileDialog.show_delete(
            parent=window,
            profiles=["Работа", "Учёба", "Спорт"],
            active="Учёба",
            on_delete=controller.delete_profile,
        )
    """

    @staticmethod
    def show_create(
        parent,
        on_create: Callable[[str, int, int], None],
    ) -> ctk.CTkToplevel:
        """
        Диалог создания профиля.

        on_create(name, work_minutes, break_minutes) — вызывается при подтверждении.
        """
        win = ctk.CTkToplevel(parent)
        win.title("Новый профиль")
        win.geometry("320x260")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["panel"])
        win.grab_set()
        win.lift()
        win.focus_force()

        ctk.CTkLabel(
            win, text="Новый профиль",
            font=FONTS["dialog"],
            text_color=COLORS["work"],
        ).pack(pady=(20, 12))

        # Поля ввода
        grid = ctk.CTkFrame(win, fg_color="transparent")
        grid.pack(pady=4)

        ctk.CTkLabel(grid, text="Название", font=FONTS["label"],
                     text_color=COLORS["subtext"]).grid(row=0, column=0, padx=10, pady=4, sticky="w")
        entry_name = ctk.CTkEntry(grid, width=140, font=FONTS["entry"],
                                  fg_color=COLORS["bg"], border_color=COLORS["border"])
        entry_name.grid(row=0, column=1, padx=10)
        entry_name.focus_set()

        ctk.CTkLabel(grid, text="Работа (мин)", font=FONTS["label"],
                     text_color=COLORS["subtext"]).grid(row=1, column=0, padx=10, pady=4, sticky="w")
        entry_work = ctk.CTkEntry(grid, width=70, font=FONTS["entry"],
                                  fg_color=COLORS["bg"], border_color=COLORS["border"], justify="center")
        entry_work.insert(0, "25")
        entry_work.grid(row=1, column=1, padx=10)

        ctk.CTkLabel(grid, text="Отдых (мин)", font=FONTS["label"],
                     text_color=COLORS["subtext"]).grid(row=2, column=0, padx=10, pady=4, sticky="w")
        entry_rest = ctk.CTkEntry(grid, width=70, font=FONTS["entry"],
                                  fg_color=COLORS["bg"], border_color=COLORS["border"], justify="center")
        entry_rest.insert(0, "5")
        entry_rest.grid(row=2, column=1, padx=10)

        # Строка статуса ошибок
        lbl_err = ctk.CTkLabel(win, text="", font=FONTS["label"],
                                text_color=COLORS["warning"])
        lbl_err.pack(pady=2)

        # Кнопки
        row_btns = ctk.CTkFrame(win, fg_color="transparent")
        row_btns.pack(pady=10)

        def _confirm():
            name = entry_name.get().strip()
            try:
                work = int(entry_work.get())
                rest = int(entry_rest.get())
            except ValueError:
                lbl_err.configure(text="⚠ Введите целые числа")
                return
            if not name:
                lbl_err.configure(text="⚠ Введите название")
                return
            win.destroy()
            on_create(name, work, rest)

        ctk.CTkButton(
            row_btns, text="Создать", width=120, height=34,
            font=FONTS["label_bold"],
            fg_color=COLORS["work"], hover_color=COLORS["btn_work_hover"],
            corner_radius=5, command=_confirm,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            row_btns, text="Отмена", width=90, height=34,
            font=FONTS["label"],
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"],
            corner_radius=5, command=win.destroy,
        ).pack(side="left", padx=6)

        win.bind("<Return>", lambda e: _confirm())
        return win

    @staticmethod
    def show_delete(
        parent,
        profiles: list[str],
        active: str,
        on_delete: Callable[[str], None],
    ) -> ctk.CTkToplevel:
        """
        Диалог удаления профиля.

        Показывает выпадающий список профилей. Нельзя удалить единственный.
        on_delete(name) — вызывается при подтверждении.
        """
        win = ctk.CTkToplevel(parent)
        win.title("Удалить профиль")
        win.geometry("300x200")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["panel"])
        win.grab_set()
        win.lift()
        win.focus_force()

        ctk.CTkLabel(
            win, text="Удалить профиль",
            font=FONTS["dialog"],
            text_color=COLORS["work"],
        ).pack(pady=(20, 12))

        var = ctk.StringVar(value=active)
        combo = ctk.CTkOptionMenu(
            win, variable=var,
            values=profiles,
            font=FONTS["label"],
            fg_color=COLORS["bg"],
            button_color=COLORS["btn_neutral"],
        )
        combo.pack(pady=8)

        row_btns = ctk.CTkFrame(win, fg_color="transparent")
        row_btns.pack(pady=14)

        def _confirm():
            name = var.get()
            win.destroy()
            on_delete(name)

        ctk.CTkButton(
            row_btns, text="Удалить", width=110, height=34,
            font=FONTS["label_bold"],
            fg_color="#c0392b", hover_color="#a93226",
            corner_radius=5, command=_confirm,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            row_btns, text="Отмена", width=90, height=34,
            font=FONTS["label"],
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"],
            corner_radius=5, command=win.destroy,
        ).pack(side="left", padx=6)

        return win
