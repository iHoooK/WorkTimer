"""
ui/main_window.py — Главное окно приложения.

MainWindow собирает все компоненты и прокидывает события в AppController.
Не содержит бизнес-логики — только компоновка и привязка коллбэков.
"""

from __future__ import annotations

import customtkinter as ctk
from typing import TYPE_CHECKING

from ui.theme import COLORS, FONTS
from ui.components.clock_display   import ClockDisplay
from ui.components.progress_bar    import TimerProgressBar
from ui.components.profile_bar     import ProfileBar
from ui.components.control_buttons import ControlButtons
from ui.components.settings_panel  import SettingsPanel
from ui.big_mode                   import BigModeWindow

if TYPE_CHECKING:
    from ui.app      import AppController
    from core.timer  import TimerState

import logging
logger = logging.getLogger(__name__)


class MainWindow(ctk.CTk):
    """
    Главное окно: компоновка всех UI-компонентов.

    Публичные атрибуты (для AppController):
        profile_bar    — ProfileBar
        settings_panel — SettingsPanel
        clock          — ClockDisplay
        progress       — TimerProgressBar
        controls       — ControlButtons

    Пример:
        window = MainWindow(controller=app_controller)
        controller.set_window(window)
        controller.on_startup()
        window.mainloop()
    """

    def __init__(self, controller: "AppController") -> None:
        super().__init__()
        self._controller = controller

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._setup_window()
        self._build_header()
        self._build_profile_bar()
        self._build_clock_area()
        self._build_controls()
        self._build_settings()

        self._big_mode = BigModeWindow(
            parent=self,
            on_close=lambda: None,
        )

        self.protocol("WM_DELETE_WINDOW", self._controller.on_window_close)

    # ===========================================================================
    # Шаг 15.1 — Построение UI
    # ===========================================================================

    def _setup_window(self) -> None:
        self.title("Focus Timer")
        self.geometry("400x590")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])

    def _build_header(self) -> None:
        """Шапка: заголовок FOCUS TIMER + кнопка DND."""
        hdr = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr,
            text="FOCUS TIMER",
            font=FONTS["title"],
            text_color=COLORS["subtext"],
        ).pack(side="left", padx=20)

        # Кнопка Big Mode
        self._btn_big = ctk.CTkButton(
            hdr,
            text="⛶",
            width=36,
            height=28,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=4,
            command=self._toggle_big_mode,
        )
        self._btn_big.pack(side="right", padx=(0, 6))

        # Кнопка DND
        self._btn_dnd = ctk.CTkButton(
            hdr,
            text="🔕 DND",
            width=80,
            height=28,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=4,
            command=self._controller.toggle_dnd,
        )
        self._btn_dnd.pack(side="right", padx=(0, 4))

    def _build_profile_bar(self) -> None:
        """Панель профилей."""
        self.profile_bar = ProfileBar(
            self,
            on_select=self._controller.select_profile,
            on_add=self._controller.show_add_profile_dialog,
        )
        self.profile_bar.pack(fill="x")

    def _build_clock_area(self) -> None:
        """Зона с часами и прогресс-баром."""
        self.clock = ClockDisplay(self)
        self.clock.pack(pady=(28, 0))

        self.progress = TimerProgressBar(self)
        self.progress.pack(pady=16)

    def _build_controls(self) -> None:
        """Кнопки управления таймером."""
        self.controls = ControlButtons(
            self,
            on_start_pause=self._controller.toggle_timer,
            on_stop=self._controller.stop_timer,
        )
        self.controls.pack(pady=4)

    def _build_settings(self) -> None:
        """Разделитель + панель настроек."""
        sep = ctk.CTkFrame(self, fg_color=COLORS["border"], height=1)
        sep.pack(fill="x", padx=24, pady=24)

        self.settings_panel = SettingsPanel(
            self,
            on_save=self._controller.save_profile_settings,
            on_toggle_top=self._controller.set_always_on_top,
        )
        self.settings_panel.pack()

    # ===========================================================================
    # Шаг 15.2 — Публичный API для AppController
    # ===========================================================================

    def update_timer(self, state: "TimerState") -> None:
        """
        Обновить все UI-компоненты по TimerState.

        Вызывается AppController из обработчиков EventBus (через after(0,...)).
        """
        self.clock.update(state)
        self.progress.update(state)
        self.controls.update(state)

        # Обновить подсветку профилей при смене режима
        from core.timer import TimerPhase
        if state.phase in (TimerPhase.IDLE, TimerPhase.FINISHED):
            self.settings_panel.set_status("Нажмите СТАРТ", COLORS["subtext"])

        # Синхронизировать ProfileBar с текущим режимом
        try:
            active = self._controller._profiles.get_active().name
            profiles = [p.name for p in self._controller._profiles.get_all()]
            self.profile_bar.highlight_active(active, state.mode.value)
        except Exception:
            pass

        # Обновить BigModeWindow если открыт
        if self._big_mode.is_visible:
            self._big_mode.update(state)

    def apply_always_on_top(self, value: bool) -> None:
        """Применить настройку «Поверх окон»."""
        self.attributes("-topmost", value)

    def update_dnd_button(self, dnd_active: bool) -> None:
        """Обновить цвет кнопки DND."""
        color = COLORS["dnd_on"] if dnd_active else COLORS["btn_neutral"]
        self._btn_dnd.configure(fg_color=color)

    def _toggle_big_mode(self) -> None:
        """Показать/скрыть окно большого режима."""
        if self._big_mode.is_visible:
            self._big_mode.hide()
        else:
            self._big_mode.show()
            # Обновить с текущим состоянием
            state = self._controller._timer.state
            self._big_mode.update(state)
