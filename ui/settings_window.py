"""
ui/settings_window.py — Окно настроек (Toplevel).

v4:
 - Адаптивная высота: контент в CTkScrollableFrame, окно resizable по высоте
 - Профиль — CTkOptionMenu (dropdown)
 - Самостоятельно заполняет данные при открытии
 - Центрируется на экране
 - Кнопка Стоп только здесь
"""

from __future__ import annotations

import customtkinter as ctk
from tkinter import filedialog
from typing import TYPE_CHECKING

from ui.theme import COLORS, FONTS, THEME_DARK, THEME_LIGHT, THEME_SYSTEM, accent_for_mode
from ui.components.settings_panel import SettingsPanel

if TYPE_CHECKING:
    from ui.app     import AppController
    from core.timer import TimerState

import logging
logger = logging.getLogger(__name__)

_WIN_W   = 430
_WIN_MIN_H = 400
_WIN_MAX_H = 700

THEME_OPTIONS = [
    (THEME_SYSTEM, "Системная"),
    (THEME_LIGHT, "Светлая"),
    (THEME_DARK, "Тёмная"),
]
THEME_LABEL_TO_VALUE = {label: value for value, label in THEME_OPTIONS}
THEME_VALUE_TO_LABEL = {value: label for value, label in THEME_OPTIONS}


def _accent_for_phase_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role == "work":
        return COLORS["work"]
    if role == "rest":
        return COLORS["rest"]
    if role == "prep":
        return COLORS["glow_purple"]
    return COLORS["accent_text"]


class SettingsWindow(ctk.CTkToplevel):
    """
    Окно настроек с адаптивной высотой и скроллируемым контентом.
    """

    def __init__(self, parent, controller: "AppController") -> None:
        super().__init__(parent)
        self._controller = controller

        self.title("WorkTimer — Настройки")
        self.resizable(False, True)          # можно тянуть по высоте
        self.configure(fg_color=COLORS["bg"])
        self.minsize(_WIN_W, _WIN_MIN_H)
        self.maxsize(_WIN_W, _WIN_MAX_H)
        self.transient(parent)

        # --- Шапка (фиксированная, не скроллится) ---
        self._build_header()

        # --- Скроллируемая область ---
        self._scroll = ctk.CTkScrollableFrame(
            self,
            fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["border_glow"],
        )
        self._scroll.pack(fill="both", expand=True)

        self._build_profile_selector()
        self._build_timer_display()
        self._build_app_preferences()
        self._build_obs_preferences()
        self._build_separator()
        self._build_settings_section()
        self._build_profile_management()

        # Подобрать высоту под контент и центрировать
        self.after(10, self._fit_and_center)

        # Заполнить данными
        self._populate()

        self.lift()
        self.focus_force()

    # ===========================================================================
    # Построение UI
    # ===========================================================================

    def _build_header(self) -> None:
        """Фиксированная шапка вне скроллируемой зоны."""
        hdr = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=44)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(
            hdr, text="✦  НАСТРОЙКИ",
            font=FONTS["title"], text_color=COLORS["accent_text"],
        ).pack(side="left", padx=16)

        self._btn_dnd = ctk.CTkButton(
            hdr, text="🔕  DND",
            width=90, height=28,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"],
            corner_radius=5, command=self._controller.toggle_dnd,
        )
        self._btn_dnd.pack(side="right", padx=12)

    def _build_profile_selector(self) -> None:
        """Dropdown для выбора профиля."""
        row = ctk.CTkFrame(self._scroll, fg_color=COLORS["panel_light"], corner_radius=8)
        row.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            row, text="Профиль:",
            font=FONTS["label_bold"], text_color=COLORS["subtext"],
        ).pack(side="left", padx=(14, 6), pady=8)

        self._profile_var = ctk.StringVar(value="")
        self._profile_menu = ctk.CTkOptionMenu(
            row,
            variable=self._profile_var,
            values=[""],
            width=190, height=28,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            button_color=COLORS["border_glow"],
            button_hover_color=COLORS["border_glow"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["border"],
            dropdown_text_color=COLORS["text"],
            corner_radius=6,
            command=self._on_profile_selected,
        )
        self._profile_menu.pack(side="left", padx=6, pady=8)

    def _build_timer_display(self) -> None:
        """Мини-предпросмотр таймера + кнопки Старт/Стоп."""
        preview = ctk.CTkFrame(self._scroll, fg_color=COLORS["panel_light"], corner_radius=12)
        preview.pack(fill="x", padx=12, pady=4)

        self._lbl_preview_mode = ctk.CTkLabel(
            preview, text="РАБОТА",
            font=FONTS["mode"], text_color=COLORS["work"],
        )
        self._lbl_preview_mode.pack(pady=(10, 2))

        self._lbl_preview_clock = ctk.CTkLabel(
            preview, text="00:00",
            font=("Courier New", 34, "bold"), text_color=COLORS["text"],
        )
        self._lbl_preview_clock.pack(pady=(0, 4))

        self._lbl_preview_phase = ctk.CTkLabel(
            preview,
            text="Работа",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        )
        self._lbl_preview_phase.pack(pady=(0, 6))

        self._preview_progress = ctk.CTkProgressBar(
            preview, height=4, corner_radius=2,
            fg_color=COLORS["border"], progress_color=COLORS["work"],
        )
        self._preview_progress.set(0)
        self._preview_progress.pack(fill="x", padx=20, pady=(0, 8))

        # Кнопки
        ctrl_row = ctk.CTkFrame(preview, fg_color="transparent")
        ctrl_row.pack(pady=(0, 12))

        btn_cfg = dict(width=110, height=34, corner_radius=6, font=FONTS["btn_text"])

        self._btn_start = ctk.CTkButton(
            ctrl_row, text="▶  СТАРТ",
            fg_color=COLORS["work"], hover_color=COLORS["btn_work_hover"],
            command=self._controller.toggle_timer, **btn_cfg,
        )
        self._btn_start.pack(side="left", padx=6)

        ctk.CTkButton(
            ctrl_row, text="■  СТОП",
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"],
            command=self._controller.stop_timer, **btn_cfg,
        ).pack(side="left", padx=6)

    def _build_app_preferences(self) -> None:
        self._app_prefs = ctk.CTkFrame(self._scroll, fg_color=COLORS["panel_light"], corner_radius=8)
        self._app_prefs.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(
            self._app_prefs,
            text="Тема:",
            font=FONTS["label_bold"],
            text_color=COLORS["subtext"],
        ).pack(side="left", padx=(14, 6), pady=8)

        self._theme_var = ctk.StringVar(value=THEME_VALUE_TO_LABEL[THEME_SYSTEM])
        self._theme_menu = ctk.CTkOptionMenu(
            self._app_prefs,
            variable=self._theme_var,
            values=[label for _, label in THEME_OPTIONS],
            width=145,
            height=28,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            button_color=COLORS["border_glow"],
            button_hover_color=COLORS["border_glow"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["border"],
            dropdown_text_color=COLORS["text"],
            corner_radius=6,
            command=self._on_theme_selected,
        )
        self._theme_menu.pack(side="left", padx=6, pady=8)

        ctk.CTkButton(
            self._app_prefs,
            text="CSV",
            width=58,
            height=28,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=6,
            command=self._export_journal_csv,
        ).pack(side="right", padx=10, pady=8)

    def _build_obs_preferences(self) -> None:
        self._obs_prefs = ctk.CTkFrame(self._scroll, fg_color=COLORS["panel_light"], corner_radius=8)
        self._obs_prefs.pack(fill="x", padx=12, pady=4)

        ctk.CTkLabel(
            self._obs_prefs,
            text="OBS:",
            font=FONTS["label_bold"],
            text_color=COLORS["subtext"],
        ).pack(side="left", padx=(14, 6), pady=8)

        self._entry_obs_url = ctk.CTkEntry(
            self._obs_prefs,
            width=235,
            height=28,
            font=FONTS["entry"],
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
        )
        self._entry_obs_url.pack(side="left", padx=6, pady=8)
        self._entry_obs_url.insert(0, self._controller.get_obs_url())

        ctk.CTkButton(
            self._obs_prefs,
            text="Copy",
            width=58,
            height=28,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=6,
            command=self._copy_obs_url,
        ).pack(side="right", padx=10, pady=8)

    def _build_separator(self) -> None:
        ctk.CTkFrame(self._scroll, fg_color=COLORS["border"], height=1).pack(
            fill="x", padx=16, pady=10)
        ctk.CTkLabel(
            self._scroll, text="⟡  НАСТРОЙКИ ПРОФИЛЯ",
            font=FONTS["section"], text_color=COLORS["subtext"],
        ).pack()

    def _build_settings_section(self) -> None:
        self.settings_panel = SettingsPanel(
            self._scroll,
            on_save=self._controller.save_profile_settings,
            on_toggle_top=self._controller.set_always_on_top,
        )
        self.settings_panel.pack(pady=4)

    def _build_profile_management(self) -> None:
        mgmt = ctk.CTkFrame(self._scroll, fg_color="transparent")
        mgmt.pack(pady=(6, 16))

        ctk.CTkButton(
            mgmt, text="＋  Новый профиль",
            width=160, height=30, font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["border_glow"],
            corner_radius=6, command=self._controller.show_add_profile_dialog,
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            mgmt, text="✕  Удалить профиль",
            width=160, height=30, font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["dnd_on"],
            corner_radius=6, command=self._controller.show_delete_profile_dialog,
        ).pack(side="left", padx=6)

    # ===========================================================================
    # Вспомогательные
    # ===========================================================================

    def _fit_and_center(self) -> None:
        """Подобрать высоту под контент и расположить по центру экрана."""
        self.update_idletasks()
        # Реальная высота контента
        content_h = self._scroll.winfo_reqheight() + 44  # 44 — высота header
        h = max(_WIN_MIN_H, min(content_h + 30, _WIN_MAX_H))
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x  = (sw - _WIN_W) // 2
        y  = (sh - h) // 2
        self.geometry(f"{_WIN_W}x{h}+{x}+{y}")

    def _populate(self) -> None:
        """Заполнить UI данными из controller."""
        try:
            profiles = [p.name for p in self._controller._profiles.get_all()]
            active   = self._controller._profiles.get_active().name
            if profiles:
                self._profile_menu.configure(values=profiles)
                self._profile_var.set(active)
        except Exception as e:
            logger.warning("SettingsWindow._populate profiles: %s", e)

        try:
            profile  = self._controller._profiles.get_active()
            settings = self._controller._settings.get()
            self.settings_panel.load_profile(
                name=profile.name,
                phases=profile.phases,
            )
            self.settings_panel.load_settings(always_on_top=settings.always_on_top)
            self.update_theme_selector(settings.theme_mode)
            self.update_dnd_button(settings.dnd)
        except Exception as e:
            logger.warning("SettingsWindow._populate settings: %s", e)

        # Синхронизировать предпросмотр с текущим состоянием таймера
        try:
            state = self._controller._timer.state
            self.sync_profile_bar(state)
        except Exception:
            pass

    def _on_profile_selected(self, name: str) -> None:
        self._controller.select_profile(name)
        try:
            profile = self._controller._profiles.get_active()
            self.settings_panel.load_profile(
                name=profile.name,
                phases=profile.phases,
            )
        except Exception as e:
            logger.warning("SettingsWindow._on_profile_selected: %s", e)

    def _on_theme_selected(self, label: str) -> None:
        self._controller.set_theme_mode(THEME_LABEL_TO_VALUE.get(label, THEME_SYSTEM))

    def _copy_obs_url(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._controller.get_obs_url())
        self.settings_panel.set_status("OBS URL скопирован", COLORS["success"])

    def _export_journal_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Экспорт журнала WorkTimer",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")],
            initialfile="worktimer-journal.csv",
        )
        if not path:
            return
        try:
            count = self._controller.export_journal_csv(path)
            self.settings_panel.set_status(f"Экспортировано событий: {count}", COLORS["success"])
        except Exception as e:
            logger.exception("SettingsWindow: journal export failed")
            self.settings_panel.set_status(f"Ошибка экспорта: {e}", COLORS["danger"])

    # ===========================================================================
    # Public API
    # ===========================================================================

    @property
    def profile_bar(self) -> "_ProfileMenuAdapter":
        return _ProfileMenuAdapter(self)

    def refresh_profiles(self, profiles: list[str], active: str) -> None:
        if profiles:
            self._profile_menu.configure(values=profiles)
        self._profile_var.set(active)

    def sync_profile_bar(self, state: "TimerState") -> None:
        from core.timer import TimerPhase

        color = _accent_for_phase_role(state.phase_role)

        self._lbl_preview_mode.configure(text=state.phase_name.upper(), text_color=color)
        self._lbl_preview_clock.configure(text=state.format_time())
        self._lbl_preview_phase.configure(text=state.phase_name, text_color=COLORS["subtext"])
        self._preview_progress.configure(progress_color=color)
        self._preview_progress.set(state.progress)

        if state.phase == TimerPhase.RUNNING:
            self._btn_start.configure(text="⏸  ПАУЗА", fg_color=color)
        elif state.phase == TimerPhase.PAUSED:
            self._btn_start.configure(text="▶  ПРОДОЛЖИТЬ", fg_color=COLORS["glow_purple"])
        else:
            self._btn_start.configure(text="▶  СТАРТ", fg_color=COLORS["work"])

    def update_dnd_button(self, dnd_active: bool) -> None:
        color = COLORS["dnd_on"] if dnd_active else COLORS["btn_neutral"]
        self._btn_dnd.configure(fg_color=color)

    def update_theme_selector(self, theme_mode: str) -> None:
        self._theme_var.set(THEME_VALUE_TO_LABEL.get(theme_mode, THEME_VALUE_TO_LABEL[THEME_SYSTEM]))

    def apply_theme(self) -> None:
        self.configure(fg_color=COLORS["bg"])
        self._scroll.configure(
            fg_color=COLORS["bg"],
            scrollbar_button_color=COLORS["border"],
            scrollbar_button_hover_color=COLORS["border_glow"],
        )
        for frame in (getattr(self, "_app_prefs", None), getattr(self, "_obs_prefs", None)):
            if frame is not None:
                frame.configure(fg_color=COLORS["panel_light"])
        if hasattr(self, "_entry_obs_url"):
            self._entry_obs_url.configure(
                fg_color=COLORS["bg"],
                border_color=COLORS["border"],
                text_color=COLORS["text"],
            )
        self._theme_menu.configure(
            fg_color=COLORS["btn_neutral"],
            button_color=COLORS["border_glow"],
            button_hover_color=COLORS["border_glow"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["border"],
            dropdown_text_color=COLORS["text"],
        )
        self.sync_profile_bar(self._controller._timer.state)
        self.update_dnd_button(self._controller._settings.get().dnd)


class _ProfileMenuAdapter:
    """Адаптер: AppController.profile_bar.refresh(...) → SettingsWindow.refresh_profiles(...)"""
    def __init__(self, win: SettingsWindow) -> None:
        self._win = win

    def refresh(self, profiles: list[str], active: str, mode: str = "work") -> None:
        if self._win.winfo_exists():
            self._win.refresh_profiles(profiles, active)

    def highlight_active(self, active: str, mode: str) -> None:
        if self._win.winfo_exists():
            self._win._profile_var.set(active)
