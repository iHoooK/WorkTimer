"""
ui/components/settings_panel.py — Панель настроек профиля и фаз.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

import customtkinter as ctk

from core.profiles import Phase
from ui.theme import COLORS, FONTS


ROLE_OPTIONS: list[tuple[str, str]] = [
    ("work", "Работа"),
    ("rest", "Отдых"),
    ("prep", "Подготовка"),
    ("custom", "Своя"),
]

ROLE_LABEL_TO_VALUE = {label: value for value, label in ROLE_OPTIONS}
ROLE_VALUE_TO_LABEL = {value: label for value, label in ROLE_OPTIONS}


class SettingsPanel(ctk.CTkFrame):
    """
    Панель настроек: имя сценария, список фаз, общий переключатель always-on-top.
    """

    def __init__(
        self,
        parent,
        on_save: Callable[[str, list[Phase]], None],
        on_toggle_top: Callable[[bool], None],
        **kwargs,
    ):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self._on_save = on_save
        self._on_toggle_top = on_toggle_top
        self._phase_rows: list[_PhaseRow] = []
        self._build()

    def _build(self) -> None:
        self._wrap = ctk.CTkFrame(self, fg_color=COLORS["panel_light"], corner_radius=10)
        self._wrap.pack(padx=12, pady=4, fill="x")

        self._build_profile_name()
        self._build_phase_header()
        self._build_phase_list()
        self._build_actions()
        self._build_toggle_top()
        self._build_status()

    def _build_profile_name(self) -> None:
        ctk.CTkLabel(
            self._wrap,
            text="Название сценария",
            font=FONTS["label_bold"],
            text_color=COLORS["accent_text"],
        ).pack(anchor="w", padx=14, pady=(12, 4))

        self._entry_name = ctk.CTkEntry(
            self._wrap,
            width=240,
            height=30,
            font=FONTS["entry"],
            fg_color=COLORS["bg"],
            border_color=COLORS["border_glow"],
            text_color=COLORS["text"],
        )
        self._entry_name.pack(fill="x", padx=14, pady=(0, 10))

    def _build_phase_header(self) -> None:
        row = ctk.CTkFrame(self._wrap, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 4))

        ctk.CTkLabel(
            row,
            text="Фазы сценария",
            font=FONTS["label_bold"],
            text_color=COLORS["subtext"],
        ).pack(side="left")

        ctk.CTkButton(
            row,
            text="+ Фаза",
            width=72,
            height=24,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["border_glow"],
            corner_radius=4,
            command=self._add_phase,
        ).pack(side="right")

    def _build_phase_list(self) -> None:
        self._phases_box = ctk.CTkFrame(self._wrap, fg_color="transparent")
        self._phases_box.pack(fill="x", padx=12, pady=(0, 8))

    def _build_actions(self) -> None:
        ctk.CTkButton(
            self._wrap,
            text="💾  Сохранить сценарий",
            width=220,
            height=34,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["border_glow"],
            corner_radius=8,
            command=self._on_save_clicked,
        ).pack(pady=(2, 4))

    def _build_toggle_top(self) -> None:
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

    def _build_status(self) -> None:
        self._lbl_status = ctk.CTkLabel(
            self,
            text="",
            font=FONTS["label"],
            text_color=COLORS["subtext"],
        )
        self._lbl_status.pack(pady=(2, 0))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_profile(
        self,
        name: str = "",
        phases: list[Phase] | list[dict] | None = None,
        work_minutes: int = 0,
        work_seconds: int = 0,
        break_minutes: int = 0,
        break_seconds: int = 0,
    ) -> None:
        self._set_entry(self._entry_name, name)

        if phases is None:
            phases = [
                Phase(
                    name="Работа",
                    duration_seconds=work_minutes * 60 + work_seconds,
                    color_role="work",
                ),
                Phase(
                    name="Отдых",
                    duration_seconds=break_minutes * 60 + break_seconds,
                    color_role="rest",
                ),
            ]
        self._set_phase_rows(phases)

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
    # Internal helpers
    # ------------------------------------------------------------------

    def _set_phase_rows(self, phases: list[Phase] | list[dict]) -> None:
        for row in self._phase_rows:
            row.destroy()
        self._phase_rows.clear()

        for idx, phase in enumerate(phases, start=1):
            if isinstance(phase, dict):
                phase_obj = Phase.from_dict(phase, fallback_name=f"Фаза {idx}")
            else:
                phase_obj = phase
            self._add_phase(phase_obj)

        if not self._phase_rows:
            self._add_phase()

        self._reindex_phase_rows()

    def _add_phase(self, phase: Phase | None = None) -> None:
        if phase is None:
            phase = Phase(
                name="Новая фаза",
                duration_seconds=25 * 60,
                color_role="custom",
                sound_enabled=True,
                notification_enabled=True,
                auto_start_next=False,
                note="",
            )

        row = _PhaseRow(
            parent=self._phases_box,
            phase=phase,
            on_move_up=self._move_phase_up,
            on_move_down=self._move_phase_down,
            on_delete=self._delete_phase,
        )
        row.pack(fill="x", pady=5)
        self._phase_rows.append(row)
        self._reindex_phase_rows()

    def _delete_phase(self, row: "_PhaseRow") -> None:
        if len(self._phase_rows) <= 1:
            self.set_status("⚠ Нужна хотя бы одна фаза", COLORS["warning"])
            return
        row.destroy()
        self._phase_rows = [item for item in self._phase_rows if item is not row]
        self._reindex_phase_rows()

    def _move_phase_up(self, row: "_PhaseRow") -> None:
        idx = self._phase_rows.index(row)
        if idx <= 0:
            return
        self._phase_rows[idx - 1], self._phase_rows[idx] = self._phase_rows[idx], self._phase_rows[idx - 1]
        self._repack_phase_rows()

    def _move_phase_down(self, row: "_PhaseRow") -> None:
        idx = self._phase_rows.index(row)
        if idx >= len(self._phase_rows) - 1:
            return
        self._phase_rows[idx + 1], self._phase_rows[idx] = self._phase_rows[idx], self._phase_rows[idx + 1]
        self._repack_phase_rows()

    def _repack_phase_rows(self) -> None:
        for row in self._phase_rows:
            row.pack_forget()
        for row in self._phase_rows:
            row.pack(fill="x", pady=5)
        self._reindex_phase_rows()

    def _reindex_phase_rows(self) -> None:
        for idx, row in enumerate(self._phase_rows, start=1):
            row.set_index(idx)

    def _collect_phases(self) -> list[Phase]:
        phases: list[Phase] = []
        for row in self._phase_rows:
            phases.append(row.to_phase())
        return phases

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_save_clicked(self) -> None:
        name = self._entry_name.get().strip()
        if not name:
            self.set_status("⚠ Введите название сценария", COLORS["warning"])
            return

        try:
            phases = self._collect_phases()
        except ValueError as e:
            self.set_status(f"⚠ {e}", COLORS["warning"])
            return

        self._on_save(name, phases)

    def _on_top_changed(self) -> None:
        self._on_toggle_top(self._var_top.get())

    @staticmethod
    def _set_entry(entry: ctk.CTkEntry, value: str) -> None:
        entry.delete(0, "end")
        entry.insert(0, value)


class _PhaseRow(ctk.CTkFrame):
    def __init__(
        self,
        parent,
        phase: Phase,
        on_move_up: Callable[["_PhaseRow"], None],
        on_move_down: Callable[["_PhaseRow"], None],
        on_delete: Callable[["_PhaseRow"], None],
    ) -> None:
        super().__init__(parent, fg_color=COLORS["panel"], corner_radius=8)
        self._on_move_up = on_move_up
        self._on_move_down = on_move_down
        self._on_delete = on_delete
        self._index = 0

        self._build(phase)

    def _build(self, phase: Phase) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 4))

        self._lbl_title = ctk.CTkLabel(
            header,
            text="Фаза",
            font=FONTS["label_bold"],
            text_color=COLORS["text"],
        )
        self._lbl_title.pack(side="left")

        btns = ctk.CTkFrame(header, fg_color="transparent")
        btns.pack(side="right")

        ctk.CTkButton(
            btns,
            text="↑",
            width=26,
            height=24,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=4,
            command=lambda: self._on_move_up(self),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btns,
            text="↓",
            width=26,
            height=24,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=4,
            command=lambda: self._on_move_down(self),
        ).pack(side="left", padx=2)

        ctk.CTkButton(
            btns,
            text="×",
            width=26,
            height=24,
            font=FONTS["btn_xs"],
            fg_color=COLORS["btn_neutral"],
            hover_color=COLORS["dnd_on"],
            corner_radius=4,
            command=lambda: self._on_delete(self),
        ).pack(side="left", padx=2)

        row_name = ctk.CTkFrame(self, fg_color="transparent")
        row_name.pack(fill="x", padx=10, pady=(0, 6))

        self._entry_name = ctk.CTkEntry(
            row_name,
            width=180,
            height=28,
            font=FONTS["entry"],
            fg_color=COLORS["bg"],
            border_color=COLORS["border_glow"],
            text_color=COLORS["text"],
        )
        self._entry_name.pack(fill="x")
        self._entry_name.insert(0, phase.name)

        row_time = ctk.CTkFrame(self, fg_color="transparent")
        row_time.pack(fill="x", padx=10, pady=(0, 6))

        self._entry_min = self._make_small_entry(row_time)
        self._entry_min.pack(side="left", padx=(0, 4))
        self._entry_sec = self._make_small_entry(row_time)
        self._entry_sec.pack(side="left", padx=(0, 8))

        total_min, total_sec = divmod(max(int(phase.duration_seconds), 0), 60)
        self._entry_min.insert(0, str(total_min))
        self._entry_sec.insert(0, str(total_sec))

        self._role_var = ctk.StringVar(value=ROLE_VALUE_TO_LABEL.get(phase.color_role, "Своя"))
        self._role_menu = ctk.CTkOptionMenu(
            row_time,
            variable=self._role_var,
            values=[label for _, label in ROLE_OPTIONS],
            width=110,
            height=28,
            font=FONTS["btn_sm"],
            fg_color=COLORS["btn_neutral"],
            button_color=COLORS["border_glow"],
            button_hover_color=COLORS["border_glow"],
            dropdown_fg_color=COLORS["panel"],
            dropdown_hover_color=COLORS["border"],
            dropdown_text_color=COLORS["text"],
            corner_radius=6,
        )
        self._role_menu.pack(side="left")

        row_flags = ctk.CTkFrame(self, fg_color="transparent")
        row_flags.pack(fill="x", padx=10, pady=(0, 6))

        self._var_sound = ctk.BooleanVar(value=phase.sound_enabled)
        self._var_notify = ctk.BooleanVar(value=phase.notification_enabled)
        self._var_auto = ctk.BooleanVar(value=phase.auto_start_next)

        self._make_switch(row_flags, "Звук", self._var_sound).pack(side="left", padx=(0, 10))
        self._make_switch(row_flags, "Увед.", self._var_notify).pack(side="left", padx=(0, 10))
        self._make_switch(row_flags, "Авто", self._var_auto).pack(side="left")

        row_note = ctk.CTkFrame(self, fg_color="transparent")
        row_note.pack(fill="x", padx=10, pady=(0, 10))

        self._entry_note = ctk.CTkEntry(
            row_note,
            width=240,
            height=28,
            font=FONTS["entry"],
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            placeholder_text="Заметка",
        )
        self._entry_note.pack(fill="x")
        if phase.note:
            self._entry_note.insert(0, phase.note)

    def set_index(self, index: int) -> None:
        self._index = index
        self._lbl_title.configure(text=f"Фаза {index}")

    def to_phase(self) -> Phase:
        name = self._entry_name.get().strip()
        try:
            minutes = int(self._entry_min.get() or "0")
            seconds = int(self._entry_sec.get() or "0")
        except ValueError as e:
            raise ValueError("Введите целые числа для минут и секунд") from e

        if seconds > 59 or seconds < 0:
            raise ValueError("Секунды должны быть от 0 до 59")

        duration = minutes * 60 + seconds
        role_label = self._role_var.get()
        role_value = ROLE_LABEL_TO_VALUE.get(role_label, "custom")
        phase = Phase(
            name=name,
            duration_seconds=duration,
            color_role=role_value,
            sound_enabled=self._var_sound.get(),
            notification_enabled=self._var_notify.get(),
            auto_start_next=self._var_auto.get(),
            note=self._entry_note.get().strip(),
        )
        phase.validate()
        return phase

    def _make_small_entry(self, parent) -> ctk.CTkEntry:
        return ctk.CTkEntry(
            parent,
            width=54,
            height=28,
            font=FONTS["entry"],
            fg_color=COLORS["bg"],
            border_color=COLORS["border"],
            text_color=COLORS["text"],
            justify="center",
        )

    @staticmethod
    def _make_switch(parent, text: str, variable: ctk.BooleanVar) -> ctk.CTkSwitch:
        return ctk.CTkSwitch(
            parent,
            text=text,
            variable=variable,
            font=FONTS["label"],
            text_color=COLORS["subtext"],
            fg_color=COLORS["border"],
            progress_color=COLORS["work"],
            button_color=COLORS["text"],
            button_hover_color=COLORS["btn_hover"],
        )

