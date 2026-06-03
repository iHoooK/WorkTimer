"""
ui/components/settings_panel.py — Виджет: панель настроек профиля.

Поля «Работа (мин)» и «Отдых (мин)», кнопка «Сохранить»,
чекбокс «Поверх окон», строка статуса.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk
from ui.theme import COLORS, FONTS


class SettingsPanel(ctk.CTkFrame):
    """
    Панель настроек профиля + общих настроек приложения.

    Коллбэки:
        on_save(work_min: int, break_min: int) — пользователь сохранил профиль
        on_toggle_top(value: bool)             — изменён чекбокс «Поверх окон»

    Пример:
        panel = SettingsPanel(
            parent,
            on_save=controller.save_profile_settings,
            on_toggle_top=controller.set_always_on_top,
        )
        panel.load_profile(work_minutes=60, break_minutes=10)
        panel.load_settings(always_on_top=False)
    """

    def __init__(
        self,
        parent,
        on_save: Callable[[int, int], None],
        on_toggle_top: Callable[[bool], None],
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._on_save       = on_save
        self._on_toggle_top = on_toggle_top

        # Заголовок секции
        ctk.CTkLabel(
            self,
            text="НАСТРОЙКИ ПРОФИЛЯ",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        ).pack()

        # Сетка полей ввода
        grid = ctk.CTkFrame(self, fg_color="transparent")
        grid.pack(pady=8)

        # Работа (мин)
        ctk.CTkLabel(
            grid, text="Работа (мин)",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        ).grid(row=0, column=0, padx=12, pady=4, sticky="w")
        self._entry_work = ctk.CTkEntry(
            grid, width=70, font=FONTS["entry"],
            fg_color=COLORS["panel"], border_color=COLORS["border"],
            justify="center",
        )
        self._entry_work.grid(row=0, column=1, padx=12)

        # Отдых (мин)
        ctk.CTkLabel(
            grid, text="Отдых (мин)",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        ).grid(row=1, column=0, padx=12, pady=4, sticky="w")
        self._entry_rest = ctk.CTkEntry(
            grid, width=70, font=FONTS["entry"],
            fg_color=COLORS["panel"], border_color=COLORS["border"],
            justify="center",
        )
        self._entry_rest.grid(row=1, column=1, padx=12)

        # Кнопка сохранить
        ctk.CTkButton(
            self,
            text="💾  Сохранить профиль",
            width=200,
            height=34,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=6,
            command=self._on_save_clicked,
        ).pack(pady=(8, 4))

        # Чекбокс «Поверх окон»
        self._var_top = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self,
            text="Поверх всех окон",
            variable=self._var_top,
            font=FONTS["label"],
            text_color=COLORS["subtext"],
            fg_color=COLORS["work"],
            hover_color=COLORS["btn_work_hover"],
            command=self._on_top_changed,
        ).pack(pady=4)

        # Строка статуса
        self._lbl_status = ctk.CTkLabel(
            self,
            text="Нажмите СТАРТ",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        )
        self._lbl_status.pack(pady=(8, 0))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_profile(self, work_minutes: int, break_minutes: int) -> None:
        """Заполнить поля ввода значениями из профиля."""
        self._entry_work.delete(0, "end")
        self._entry_work.insert(0, str(work_minutes))
        self._entry_rest.delete(0, "end")
        self._entry_rest.insert(0, str(break_minutes))

    def load_settings(self, always_on_top: bool) -> None:
        """Синхронизировать чекбокс с AppSettings."""
        self._var_top.set(always_on_top)

    def set_status(self, text: str, color: str | None = None) -> None:
        """Обновить строку статуса."""
        cfg = {"text": text}
        if color:
            cfg["text_color"] = color
        self._lbl_status.configure(**cfg)

    def flash_status(self, text: str, color: str, master, delay_ms: int = 2000) -> None:
        """Показать временное сообщение, затем вернуть 'Нажмите СТАРТ'."""
        self.set_status(text, color)
        master.after(
            delay_ms,
            lambda: self.set_status("Нажмите СТАРТ", COLORS["subtext"]),
        )

    # ------------------------------------------------------------------
    # Приватные обработчики
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        try:
            work  = int(self._entry_work.get())
            rest  = int(self._entry_rest.get())
        except ValueError:
            self.set_status("⚠ Введите целые числа", COLORS["warning"])
            return
        self._on_save(work, rest)

    def _on_top_changed(self) -> None:
        self._on_toggle_top(self._var_top.get())
