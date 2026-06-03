"""
ui/components/control_buttons.py — Виджет: кнопки управления таймером.

Кнопки Старт/Пауза и Стоп. Текст кнопки меняется автоматически по фазе.
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk
from ui.theme import COLORS, FONTS, accent_for_mode, hover_for_mode


class ControlButtons(ctk.CTkFrame):
    """
    Строка кнопок управления таймером: [Старт/Пауза] [Стоп].

    Автоматически меняет текст и цвет по TimerState.

    Коллбэки:
        on_start_pause() — нажата кнопка Старт/Пауза/Возобновить
        on_stop()        — нажата кнопка Стоп

    Пример:
        btns = ControlButtons(
            parent,
            on_start_pause=controller.toggle_timer,
            on_stop=controller.stop_timer,
        )
        btns.update(state)
    """

    def __init__(
        self,
        parent,
        on_start_pause: Callable,
        on_stop: Callable,
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self._on_start_pause = on_start_pause
        self._on_stop        = on_stop

        # Кнопка Старт/Пауза
        self._btn_start = ctk.CTkButton(
            self,
            text="▶  СТАРТ",
            width=140,
            height=48,
            font=FONTS["btn"],
            fg_color=COLORS["work"],
            hover_color=COLORS["btn_work_hover"],
            corner_radius=6,
            command=self._on_start_pause,
        )
        self._btn_start.pack(side="left", padx=6)

        # Кнопка Стоп
        self._btn_stop = ctk.CTkButton(
            self,
            text="■  СТОП",
            width=100,
            height=48,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=6,
            command=self._on_stop,
        )
        self._btn_stop.pack(side="left", padx=6)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(self, state) -> None:
        """Обновить текст/цвет кнопок по TimerState."""
        from core.timer import TimerPhase

        accent = accent_for_mode(state.mode.value)
        hover  = hover_for_mode(state.mode.value)
        self._btn_start.configure(fg_color=accent, hover_color=hover)

        if state.phase == TimerPhase.RUNNING:
            self._btn_start.configure(text="⏸  ПАУЗА")
        elif state.phase == TimerPhase.PAUSED:
            self._btn_start.configure(text="▶  ПРОДОЛЖИТЬ")
        else:
            # IDLE или FINISHED
            self._btn_start.configure(text="▶  СТАРТ")

    def reset(self) -> None:
        """Сбросить кнопки в начальное состояние."""
        self._btn_start.configure(
            text="▶  СТАРТ",
            fg_color=COLORS["work"],
            hover_color=COLORS["btn_work_hover"],
        )
