"""
ui/components/settings_panel.py — Панель настроек профиля (v3).

Поля: Название сцены + мин/сек для работы и отдыха.
on_save(name: str, work_total_seconds: int, break_total_seconds: int)
"""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk
from ui.theme import COLORS, FONTS


class SettingsPanel(ctk.CTkFrame):
    """
    Панель настроек: название сцены + поля мин+сек.
    """

    def __init__(
        self,
        parent,
        on_save: Callable[[str, int, int], None],
        on_toggle_top: Callable[[bool], None],
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._on_save       = on_save
        self._on_toggle_top = on_toggle_top
        self._build()

    def _build(self) -> None:
        grid = ctk.CTkFrame(self, fg_color=COLORS["panel_light"], corner_radius=10)
        grid.pack(padx=12, pady=4)

        # ── Название сцены ─────────────────────────────────────────
        ctk.CTkLabel(
            grid, text="Название сцены",
            font=FONTS["label_bold"], text_color=COLORS["accent_text"],
        ).grid(row=0, column=0, padx=(14, 6), pady=(10, 4), sticky="w")

        self._entry_name = ctk.CTkEntry(
            grid, width=174, height=28,
            font=FONTS["entry"],
            fg_color=COLORS["bg"],
            border_color=COLORS["border_glow"],
            text_color=COLORS["text"],
        )
        self._entry_name.grid(row=0, column=1, columnspan=2, padx=(0, 14), pady=(10, 4))

        # ── Заголовки колонок ──────────────────────────────────────
        for col, text in enumerate(["", "мин", "сек"], start=1):
            ctk.CTkLabel(
                grid, text=text,
                font=FONTS["label"], text_color=COLORS["subtext"],
            ).grid(row=1, column=col, padx=8, pady=(2, 0))

        # ── Строка «Работа» ────────────────────────────────────────
        ctk.CTkLabel(
            grid, text="Работа",
            font=FONTS["label_bold"], text_color=COLORS["work"],
        ).grid(row=2, column=0, padx=(14, 4), pady=6, sticky="w")

        self._entry_work_min = self._make_entry(grid)
        self._entry_work_min.grid(row=2, column=1, padx=8, pady=6)

        self._entry_work_sec = self._make_entry(grid)
        self._entry_work_sec.grid(row=2, column=2, padx=(4, 14), pady=6)

        # ── Строка «Отдых» ─────────────────────────────────────────
        ctk.CTkLabel(
            grid, text="Отдых",
            font=FONTS["label_bold"], text_color=COLORS["rest"],
        ).grid(row=3, column=0, padx=(14, 4), pady=(0, 10), sticky="w")

        self._entry_rest_min = self._make_entry(grid)
        self._entry_rest_min.grid(row=3, column=1, padx=8, pady=(0, 10))

        self._entry_rest_sec = self._make_entry(grid)
        self._entry_rest_sec.grid(row=3, column=2, padx=(4, 14), pady=(0, 10))

        # ── Кнопка сохранить ───────────────────────────────────────
        ctk.CTkButton(
            self,
            text="💾  Сохранить сцену",
            width=220, height=34,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["border_glow"],
            corner_radius=8,
            command=self._on_save_clicked,
        ).pack(pady=(8, 4))

        # ── Чекбокс «Поверх окон» ──────────────────────────────────
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

        # ── Статусная строка ───────────────────────────────────────
        self._lbl_status = ctk.CTkLabel(
            self, text="",
            font=FONTS["label"], text_color=COLORS["subtext"],
        )
        self._lbl_status.pack(pady=(2, 0))

    @staticmethod
    def _make_entry(parent) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent, width=58, height=28,
            font=FONTS["entry"],
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            justify="center",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_profile(
        self,
        name: str = "",
        work_minutes: int = 0,
        work_seconds: int = 0,
        break_minutes: int = 0,
        break_seconds: int = 0,
    ) -> None:
        self._set_entry(self._entry_name, name)
        self._set_entry(self._entry_work_min, str(work_minutes))
        self._set_entry(self._entry_work_sec, str(work_seconds))
        self._set_entry(self._entry_rest_min, str(break_minutes))
        self._set_entry(self._entry_rest_sec, str(break_seconds))

    def load_settings(self, always_on_top: bool) -> None:
        self._var_top.set(always_on_top)

    def set_status(self, text: str, color: str | None = None) -> None:
        cfg = {"text": text}
        if color:
            cfg["text_color"] = color
        self._lbl_status.configure(**cfg)

    def flash_status(self, text: str, color: str, master, delay_ms: int = 2500) -> None:
        self.set_status(text, color)
        master.after(delay_ms, lambda: self.set_status("", None))

    # ------------------------------------------------------------------
    # Приватные обработчики
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        name = self._entry_name.get().strip()
        if not name:
            self.set_status("⚠ Введите название сцены", COLORS["warning"])
            return
        try:
            work_min = int(self._entry_work_min.get() or "0")
            work_sec = int(self._entry_work_sec.get() or "0")
            rest_min = int(self._entry_rest_min.get() or "0")
            rest_sec = int(self._entry_rest_sec.get() or "0")
        except ValueError:
            self.set_status("⚠ Введите целые числа", COLORS["warning"])
            return

        if work_sec > 59 or rest_sec > 59:
            self.set_status("⚠ Секунды: от 0 до 59", COLORS["warning"])
            return

        self._on_save(name, work_min * 60 + work_sec, rest_min * 60 + rest_sec)

    def _on_top_changed(self) -> None:
        self._on_toggle_top(self._var_top.get())

    @staticmethod
    def _set_entry(entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)
