"""
ui/components/progress_bar.py — Виджет: прогресс-бар с цветом по режиму.
"""

from __future__ import annotations

import customtkinter as ctk
from ui.theme import COLORS, accent_for_mode


class TimerProgressBar(ctk.CTkFrame):
    """
    Прогресс-бар таймера.

    Цвет меняется автоматически по режиму (work → оранжевый, break → голубой).

    Пример:
        bar = TimerProgressBar(parent)
        bar.pack(pady=20)
        bar.update(state)
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._bar = ctk.CTkProgressBar(
            self,
            width=320,
            height=6,
            corner_radius=3,
            fg_color=COLORS["border"],
            progress_color=COLORS["work"],
        )
        self._bar.set(0)
        self._bar.pack()

    def update(self, state) -> None:
        """Обновить прогресс и цвет по TimerState."""
        from core.timer import TimerMode
        color = accent_for_mode(state.mode.value)
        self._bar.configure(progress_color=color)
        self._bar.set(state.progress)

    def reset(self) -> None:
        """Сбросить прогресс-бар в 0."""
        self._bar.set(0)

    def set_color(self, color: str) -> None:
        """Установить цвет вручную."""
        self._bar.configure(progress_color=color)
