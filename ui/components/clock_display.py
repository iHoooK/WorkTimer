"""
ui/components/clock_display.py — Виджет: большие часы таймера + лейбл режима.

ClockDisplay не знает о TimerEngine — только получает TimerState и отображает.
"""

from __future__ import annotations

import customtkinter as ctk
from ui.theme import COLORS, FONTS


class ClockDisplay(ctk.CTkFrame):
    """
    Виджет отображения таймера: лейбл режима (РАБОТА / ОТДЫХ) + цифры MM:SS.

    Принимает TimerState через update() — не имеет зависимости на core-слой.

    Пример:
        clock = ClockDisplay(parent)
        clock.pack(pady=10)
        clock.update(state)   # вызывается AppController на каждый tick
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        # Лейбл режима: РАБОТА / ОТДЫХ
        self._lbl_mode = ctk.CTkLabel(
            self,
            text="РАБОТА",
            font=FONTS["mode"],
            text_color=COLORS["work"],
        )
        self._lbl_mode.pack(pady=(0, 0))

        # Большие цифры таймера
        self._lbl_clock = ctk.CTkLabel(
            self,
            text="00:00",
            font=FONTS["clock"],
            text_color=COLORS["text"],
        )
        self._lbl_clock.pack(pady=(4, 0))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, state) -> None:
        """
        Обновить отображение по TimerState.

        Args:
            state: core.timer.TimerState
        """
        from core.timer import TimerMode
        from ui.theme import accent_for_mode

        mode_text  = "РАБОТА" if state.mode == TimerMode.WORK else "ОТДЫХ"
        mode_color = accent_for_mode(state.mode.value)

        self._lbl_mode.configure(text=mode_text, text_color=mode_color)
        self._lbl_clock.configure(text=state.format_time())

    def set_time_text(self, text: str) -> None:
        """Установить произвольный текст времени (например, при idle)."""
        self._lbl_clock.configure(text=text)

    @property
    def clock_label(self) -> ctk.CTkLabel:
        """Прямой доступ к лейблу часов (для BigModeWindow)."""
        return self._lbl_clock
