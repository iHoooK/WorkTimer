"""
ui/big_mode.py — Окно «большой режим»: полноэкранный таймер.

BigModeWindow — CTkToplevel с огромными цифрами.
Клик по окну переключает полноэкранный режим.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk
from ui.theme import COLORS, FONTS, accent_for_mode


class BigModeWindow:
    """
    Дополнительное окно с большим таймером (для второго монитора и т.п.).

    Клик по окну — toggle fullscreen.
    Крестик — скрыть окно (не уничтожать), вызывает on_close коллбэк.

    Пример:
        big = BigModeWindow(parent, on_close=controller.hide_big_mode)
        big.show()
        big.update(state)
        big.hide()
    """

    def __init__(self, parent, on_close: Optional[Callable] = None) -> None:
        self._parent   = parent
        self._on_close = on_close
        self._win: Optional[ctk.CTkToplevel] = None
        self._lbl: Optional[ctk.CTkLabel]    = None
        self._fullscreen = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Показать окно большого режима (создаёт если ещё нет)."""
        if self._win and self._win.winfo_exists():
            self._win.lift()
            self._win.focus_force()
            return

        self._win = ctk.CTkToplevel(self._parent)
        self._win.title("Focus Timer")
        self._win.geometry("600x300")
        self._win.configure(fg_color=COLORS["bg"])
        self._win.protocol("WM_DELETE_WINDOW", self._close)

        # Большой лейбл таймера по центру
        self._lbl = ctk.CTkLabel(
            self._win,
            text="00:00",
            font=FONTS["clock_big"],
            text_color=COLORS["text"],
        )
        self._lbl.pack(expand=True)

        # Подсказка
        ctk.CTkLabel(
            self._win,
            text="Клик — fullscreen  ·  ✕ — закрыть",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        ).pack(pady=(0, 16))

        # Клик по окну — переключить fullscreen
        self._win.bind("<Button-1>", self._toggle_fullscreen)
        self._lbl.bind("<Button-1>", self._toggle_fullscreen)

        self._win.lift()
        self._win.focus_force()

    def hide(self) -> None:
        """Скрыть окно без уничтожения."""
        if self._win and self._win.winfo_exists():
            self._win.withdraw()

    def destroy(self) -> None:
        """Уничтожить окно."""
        if self._win and self._win.winfo_exists():
            self._win.destroy()
        self._win = None
        self._lbl = None

    def update(self, state) -> None:
        """Обновить цифры и цвет по TimerState."""
        if self._lbl is None or not self._win.winfo_exists():
            return
        color = accent_for_mode(state.mode.value)
        self._lbl.configure(text=state.format_time(), text_color=color)

    @property
    def is_visible(self) -> bool:
        return (
            self._win is not None
            and self._win.winfo_exists()
            and self._win.state() != "withdrawn"
        )

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def _toggle_fullscreen(self, event=None) -> None:
        if self._win is None or not self._win.winfo_exists():
            return
        self._fullscreen = not self._fullscreen
        self._win.attributes("-fullscreen", self._fullscreen)

    def _close(self) -> None:
        """Вызывается при нажатии крестика."""
        self._fullscreen = False
        if self._win and self._win.winfo_exists():
            self._win.attributes("-fullscreen", False)
            self._win.withdraw()
        if self._on_close:
            self._on_close()
