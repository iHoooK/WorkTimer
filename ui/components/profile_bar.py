"""
ui/components/profile_bar.py — Виджет: панель профилей + кнопка «+».

ProfileBar отображает кнопки профилей, подсвечивает активный,
и эмитит события вверх через коллбэки.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from ui.theme import COLORS, FONTS, accent_for_mode


class ProfileBar(ctk.CTkFrame):
    """
    Горизонтальная панель с кнопками профилей и кнопкой «+».

    Коллбэки (не знает о AppController напрямую):
        on_select(name: str)  — пользователь выбрал профиль
        on_add()              — пользователь нажал «+»

    Пример:
        bar = ProfileBar(
            parent,
            on_select=controller.select_profile,
            on_add=controller.show_add_profile_dialog,
        )
        bar.refresh(profiles=["Работа","Учёба"], active="Работа", mode="work")
    """

    def __init__(
        self,
        parent,
        on_select: Callable[[str], None],
        on_add: Callable,
        **kwargs,
    ):
        super().__init__(
            parent,
            fg_color=COLORS["panel"],
            corner_radius=0,
            height=40,
            **kwargs,
        )
        self.pack_propagate(False)

        self._on_select = on_select
        self._on_add    = on_add
        self._btns: dict[str, ctk.CTkButton] = {}

        # Кнопка «+» — добавить профиль (всегда справа)
        self._btn_add = ctk.CTkButton(
            self,
            text="+",
            width=32,
            height=28,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=4,
            command=self._on_add,
        )
        self._btn_add.pack(side="right", padx=(0, 12))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refresh(
        self,
        profiles: list[str],
        active: str,
        mode: str = "work",
    ) -> None:
        """
        Перерисовать кнопки профилей.

        Args:
            profiles: список имён профилей в порядке отображения.
            active:   имя активного профиля (будет подсвечено).
            mode:     текущий режим ('work' или 'break') — определяет цвет подсветки.
        """
        # Удаляем старые кнопки
        for btn in self._btns.values():
            btn.destroy()
        self._btns.clear()

        accent = accent_for_mode(mode)
        first  = True

        for name in profiles:
            is_active = (name == active)
            btn = ctk.CTkButton(
                self,
                text=name,
                width=90,
                height=28,
                font=FONTS["btn_xs"],
                fg_color=accent if is_active else COLORS["btn_neutral"],
                hover_color=COLORS["btn_hover"],
                corner_radius=4,
                command=lambda n=name: self._on_select(n),
            )
            btn.pack(side="left", padx=(12 if first else 4, 0))
            self._btns[name] = btn
            first = False

    def highlight_active(self, active: str, mode: str) -> None:
        """Обновить только подсветку без полного перестроения кнопок."""
        accent = accent_for_mode(mode)
        for name, btn in self._btns.items():
            btn.configure(fg_color=accent if name == active else COLORS["btn_neutral"])
