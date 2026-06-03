"""
ui/dialogs/confirm_dialog.py — Модальный диалог подтверждения.

Рефактор _show_confirm() из main.py в отдельный класс.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from ui.theme import COLORS, FONTS


class ConfirmDialog:
    """
    Модальный диалог с кнопками «Подтвердить» и «Отмена».

    Пример:
        ConfirmDialog.show(
            parent=window,
            title="Время работы вышло!",
            message="Начать таймер отдыха?",
            yes_label="Начать отдых",
            color=COLORS["rest"],
            on_yes=controller.switch_to_break,
            on_no=lambda: None,
        )
    """

    @staticmethod
    def show(
        parent,
        title:     str,
        message:   str,
        on_yes:    Callable,
        yes_label: str              = "OK",
        color:     str              = COLORS["work"],
        on_no:     Optional[Callable] = None,
    ) -> ctk.CTkToplevel:
        """
        Создать и показать диалог.

        Returns:
            Ссылку на окно (можно хранить чтобы destroy() при повторном вызове).
        """
        win = ctk.CTkToplevel(parent)
        win.title("")
        win.geometry("320x180")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["panel"])
        win.grab_set()
        win.lift()
        win.focus_force()

        # Заголовок
        ctk.CTkLabel(
            win,
            text=title,
            font=FONTS["dialog"],
            text_color=color,
        ).pack(pady=(24, 4))

        # Сообщение
        ctk.CTkLabel(
            win,
            text=message,
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        ).pack(pady=4)

        # Строка кнопок
        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(pady=16)

        def _yes():
            win.destroy()
            on_yes()

        def _no():
            win.destroy()
            if on_no:
                on_no()

        ctk.CTkButton(
            row,
            text=yes_label,
            width=130,
            height=36,
            font=FONTS["label_bold"],
            fg_color=color,
            hover_color=COLORS["btn_hover"],
            corner_radius=5,
            command=_yes,
        ).pack(side="left", padx=8)

        ctk.CTkButton(
            row,
            text="Отмена",
            width=100,
            height=36,
            font=FONTS["label"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=5,
            command=_no,
        ).pack(side="left", padx=8)

        return win
