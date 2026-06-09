"""
ui/main_window.py — Компактное главное окно (только таймер).

Показывает: лейбл режима + большой таймер + прогресс-бар + строка иконок.
Все настройки — в отдельном SettingsWindow.

Кнопки:
  ▶/⏸  — Старт / Пауза (primary action)
  ■    — Стоп
  ⚙    — Открыть настройки
  🔕   — DND toggle
  ⛶   — Big Mode (большое окно)
"""

from __future__ import annotations

import tkinter as tk
import customtkinter as ctk
from typing import TYPE_CHECKING

from ui.theme import COLORS, FONTS, accent_for_mode

if TYPE_CHECKING:
    from ui.app     import AppController
    from core.timer import TimerState

import logging
logger = logging.getLogger(__name__)


def _accent_for_phase_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role == "work":
        return COLORS["work"]
    if role == "rest":
        return COLORS["rest"]
    if role == "prep":
        return COLORS["glow_purple"]
    return COLORS["accent_text"]


class MainWindow(ctk.CTk):
    """
    Компактное окно таймера.

    Размер: ~300×220 px.
    Открывает SettingsWindow по кнопке ⚙.
    """

    def __init__(self, controller: "AppController") -> None:
        super().__init__()
        self._controller = controller

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._settings_win = None   # SettingsWindow (Toplevel)

        self._setup_window()
        self._build_header()
        self._build_timer_area()
        self._build_profile_selector()
        self._build_phase_selector()
        self._build_action_bar()

        self.protocol("WM_DELETE_WINDOW", self._controller.on_window_close)

    # ===========================================================================
    # Построение UI
    # ===========================================================================


    def _setup_window(self) -> None:
        self.title("Focus Timer")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])
        # Центрируем после отрисовки виджетов (вызываем в конце __init__)
        self.after(0, self._center_on_screen)

    def _center_on_screen(self) -> None:
        """Разместить окно по центру экрана."""
        self.update_idletasks()
        w, h = 300, 300   # + строка профиля и фаз
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")



    def _build_header(self) -> None:
        """Минималистичный хедер: символ + название."""
        hdr = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=36)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Мистический символ + название
        ctk.CTkLabel(
            hdr,
            text="✦  FOCUS TIMER",
            font=FONTS["title"],
            text_color=COLORS["accent_text"],
        ).pack(side="left", padx=14)

        # Индикатор DND (маленькая точка)
        self._lbl_dnd = ctk.CTkLabel(
            hdr,
            text="",
            font=("Segoe UI", 9),
            text_color=COLORS["dnd_on"],
        )
        self._lbl_dnd.pack(side="right", padx=10)

    def _build_timer_area(self) -> None:
        """Центральная зона: режим + часы + прогресс-бар."""
        area = ctk.CTkFrame(self, fg_color="transparent")
        area.pack(fill="both", expand=True, padx=0, pady=(6, 0))

        # Лейбл режима
        self._lbl_mode = ctk.CTkLabel(
            area,
            text="РАБОТА",
            font=FONTS["mode"],
            text_color=COLORS["work"],
        )
        self._lbl_mode.pack(pady=(4, 0))

        # Большие цифры таймера — с декоративными разделителями
        clock_row = ctk.CTkFrame(area, fg_color="transparent")
        clock_row.pack()

        self._lbl_clock = ctk.CTkLabel(
            clock_row,
            text="00:00",
            font=FONTS["clock"],
            text_color=COLORS["text"],
        )
        self._lbl_clock.pack()

        # Тонкая линия-разделитель с цветом режима (имитация свечения)
        self._separator = ctk.CTkFrame(area, height=2, corner_radius=1,
                                       fg_color=COLORS["work"])
        self._separator.pack(fill="x", padx=20, pady=(2, 0))

        # Прогресс-бар
        self._progress = ctk.CTkProgressBar(
            area,
            width=260, height=4,
            corner_radius=2,
            fg_color=COLORS["border"],
            progress_color=COLORS["work"],
        )
        self._progress.set(0)
        self._progress.pack(pady=(4, 2))

    def _build_profile_selector(self) -> None:
        """Компактная строка выбора профиля/сцены."""
        row = ctk.CTkFrame(self, fg_color=COLORS["panel_light"],
                           corner_radius=0, height=32)
        row.pack(fill="x")
        row.pack_propagate(False)

        ctk.CTkLabel(
            row, text="Сцена:",
            font=FONTS["label"], text_color=COLORS["subtext"],
        ).pack(side="left", padx=(10, 4))

        self._profile_var = ctk.StringVar(value="")
        self._profile_menu = ctk.CTkOptionMenu(
            row,
            variable=self._profile_var,
            values=[""],
            width=180, height=22,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            button_color=COLORS["border_glow"],
            button_hover_color=COLORS["border_glow"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["border"],
            dropdown_text_color=COLORS["text"],
            corner_radius=4,
            command=self._on_profile_selected,
        )
        self._profile_menu.pack(side="left", padx=4)

    def _build_phase_selector(self) -> None:
        """Компактная строка выбора и запуска конкретной фазы."""
        row = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=32)
        row.pack(fill="x")
        row.pack_propagate(False)

        ctk.CTkLabel(
            row,
            text="Фаза:",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        ).pack(side="left", padx=(10, 4))

        self._phase_names: list[str] = []
        self._phase_var = ctk.StringVar(value="")
        self._phase_menu = ctk.CTkOptionMenu(
            row,
            variable=self._phase_var,
            values=[""],
            width=148,
            height=22,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            button_color=COLORS["border_glow"],
            button_hover_color=COLORS["border_glow"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["border"],
            dropdown_text_color=COLORS["text"],
            corner_radius=4,
        )
        self._phase_menu.pack(side="left", padx=4)

        ctk.CTkButton(
            row,
            text="▶",
            width=32,
            height=22,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["border_glow"],
            corner_radius=4,
            command=self._start_selected_phase,
        ).pack(side="left", padx=(4, 0))

    def _build_action_bar(self) -> None:
        """Нижняя строка с иконками-кнопками."""
        bar = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=44)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        # Центрируем кнопки через внутренний фрейм
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")

        # Базовый конфиг (без fg_color/hover_color)
        btn_cfg = dict(width=40, height=32, corner_radius=6, font=FONTS["btn_icon"])
        neutral = dict(fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"])

        # ▶/⏸ Старт / Пауза
        self._btn_start = ctk.CTkButton(
            inner, text="▶",
            fg_color=COLORS["work"],
            hover_color=COLORS["btn_work_hover"],
            command=self._controller.toggle_timer,
            **btn_cfg,
        )
        self._btn_start.pack(side="left", padx=4)

        # Следующая фаза — пропустить текущую и перейти дальше
        ctk.CTkButton(
            inner, text="⏭",
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["border_glow"],
            command=self._controller.start_next_phase,
            **btn_cfg,
        ).pack(side="left", padx=4)

        # Тонкий разделитель
        ctk.CTkFrame(inner, width=1, height=20, fg_color=COLORS["border"]).pack(side="left", padx=6)

        # ⚙ Настройки
        ctk.CTkButton(
            inner, text="⚙",
            command=self._open_settings,
            **btn_cfg, **neutral,
        ).pack(side="left", padx=4)

        # 🔕 DND
        self._btn_dnd = ctk.CTkButton(
            inner, text="🔕",
            command=self._controller.toggle_dnd,
            **btn_cfg, **neutral,
        )
        self._btn_dnd.pack(side="left", padx=4)

    # ===========================================================================
    # Public API для AppController
    # ===========================================================================

    def update_timer(self, state: "TimerState") -> None:
        """Обновить всё по TimerState (вызывается из AppController через after(0,...))."""
        from core.timer import TimerPhase

        color = _accent_for_phase_role(state.phase_role)
        mode_txt = state.phase_name.upper()

        self._lbl_mode.configure(text=mode_txt, text_color=color)
        self._lbl_clock.configure(text=state.format_time(), text_color=COLORS["text"])
        self._separator.configure(fg_color=color)
        self._progress.configure(progress_color=color)
        self._progress.set(state.progress)

        if hasattr(self, "_phase_var") and state.phase_name in self._phase_names:
            self._phase_var.set(state.phase_name)

        # Кнопка Старт меняет иконку и цвет
        if state.phase == TimerPhase.RUNNING:
            self._btn_start.configure(text="⏸", fg_color=color,
                                      hover_color=COLORS["btn_rest_hover"] if state.phase_role == "rest" else COLORS["btn_work_hover"])
        elif state.phase == TimerPhase.PAUSED:
            self._btn_start.configure(text="▶", fg_color=COLORS["glow_purple"],
                                      hover_color="#7c3aed")
        else:
            self._btn_start.configure(text="▶", fg_color=color,
                                      hover_color=COLORS["btn_rest_hover"] if state.phase_role == "rest" else COLORS["btn_work_hover"])

        # Обновить SettingsWindow если открыт
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.sync_profile_bar(state)

    def apply_always_on_top(self, value: bool) -> None:
        self.attributes("-topmost", value)

    def update_dnd_button(self, dnd_active: bool) -> None:
        if dnd_active:
            self._btn_dnd.configure(fg_color=COLORS["dnd_on"])
            self._lbl_dnd.configure(text="● DND")
        else:
            self._btn_dnd.configure(fg_color=COLORS["btn_neutral"])
            self._lbl_dnd.configure(text="")

    def get_settings_window(self):
        return self._settings_win

    # ===========================================================================
    # Приватные методы
    # ===========================================================================

    def _open_settings(self) -> None:
        """Открыть / вывести на передний план окно настроек."""
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.lift()
            self._settings_win.focus_force()
            return

        from ui.settings_window import SettingsWindow
        self._settings_win = SettingsWindow(
            parent=self,
            controller=self._controller,
        )

    def _on_profile_selected(self, name: str) -> None:
        """Пользователь выбрал сцену в главном окне."""
        self._controller.select_profile(name)

    def _start_selected_phase(self) -> None:
        name = self._phase_var.get()
        if name in self._phase_names:
            self._controller.start_phase(self._phase_names.index(name))

    # ===========================================================================
    # Public API — обновление селектора сцен
    # ===========================================================================

    def refresh_profile_selector(self, profiles: list[str], active: str) -> None:
        """Обновить список сцен в dropdown главного окна."""
        if profiles:
            self._profile_menu.configure(values=profiles)
        self._profile_var.set(active)
        # Синхронизировать с окном настроек если открыто
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.refresh_profiles(profiles, active)

    def refresh_phase_selector(self, phases: list[str], active_index: int = 0) -> None:
        """Обновить список фаз активного сценария."""
        self._phase_names = list(phases)
        values = self._phase_names or [""]
        self._phase_menu.configure(values=values)
        if self._phase_names:
            index = max(0, min(active_index, len(self._phase_names) - 1))
            self._phase_var.set(self._phase_names[index])
        else:
            self._phase_var.set("")

    # ===========================================================================
    # Заглушки для обратной совместимости с AppController
    # ===========================================================================

    @property
    def profile_bar(self):
        """Возвращает ProfileBar из settings_window если открыто."""
        if self._settings_win and self._settings_win.winfo_exists():
            return self._settings_win.profile_bar
        return _DummyProfileBar()

    @property
    def settings_panel(self):
        if self._settings_win and self._settings_win.winfo_exists():
            return self._settings_win.settings_panel
        return _DummySettingsPanel()


class _DummyProfileBar:
    """Заглушка ProfileBar когда окно настроек закрыто."""
    def refresh(self, **kw): pass
    def highlight_active(self, *a, **kw): pass


class _DummySettingsPanel:
    """Заглушка SettingsPanel когда окно настроек закрыто."""
    def set_status(self, *a, **kw): pass
    def flash_status(self, *a, **kw): pass
    def load_profile(self, **kw): pass
    def load_settings(self, **kw): pass
