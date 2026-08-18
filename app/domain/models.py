"""Независимые от UI модели сценариев и фаз."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PhaseRepeatPolicy(str, Enum):
    """Правило включения фазы при переходе к следующему циклу сценария."""

    ONCE_AT_START = "once_at_start"
    EVERY_CYCLE = "every_cycle"
    DISABLED = "disabled"


class FocusMode(str, Enum):
    """Верхнеуровневые режимы работы таймера."""

    SCENARIO = "scenario"
    FREE = "free"
    POMODORO = "pomodoro"


class TaskStatus(str, Enum):
    OPEN = "open"
    DONE = "done"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class TaskGroup:
    name: str
    parent_id: int | None = None
    id: int | None = None
    position: int = 0
    is_archived: bool = False

    def validate(self) -> None:
        if not self.name.strip() or len(self.name.strip()) > 80:
            raise ValueError("Название группы должно содержать от 1 до 80 символов")


@dataclass(frozen=True, slots=True)
class Task:
    title: str
    group_id: int | None = None
    description: str = ""
    status: TaskStatus = TaskStatus.OPEN
    estimate_seconds: int | None = None
    tags: tuple[str, ...] = ()
    id: int | None = None
    position: int = 0

    def validate(self) -> None:
        if not self.title.strip() or len(self.title.strip()) > 160:
            raise ValueError("Название задачи должно содержать от 1 до 160 символов")
        if len(self.description) > 5_000:
            raise ValueError("Описание задачи длиннее 5000 символов")
        if self.estimate_seconds is not None and not 0 < self.estimate_seconds <= 31_536_000:
            raise ValueError("Некорректная оценка задачи")
        if len(self.tags) > 20 or any(not tag.strip() or len(tag.strip()) > 40 for tag in self.tags):
            raise ValueError("Некорректные теги задачи")


@dataclass(frozen=True, slots=True)
class Phase:
    """Одна фаза сценария, не привязанная к конкретному интерфейсу."""

    name: str
    duration_seconds: int
    color_role: str = "custom"
    repeat_policy: PhaseRepeatPolicy = PhaseRepeatPolicy.EVERY_CYCLE
    sound_enabled: bool = True
    notification_enabled: bool = True
    note: str = ""
    id: int | None = None
    position: int = 0

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Название фазы не может быть пустым")
        if len(self.name.strip()) > 80:
            raise ValueError("Название фазы длиннее 80 символов")
        if not 1 <= self.duration_seconds <= 86_400:
            raise ValueError("Длительность фазы должна быть от 1 секунды до 24 часов")
        if len(self.note) > 1_000:
            raise ValueError("Заметка к фазе длиннее 1000 символов")


@dataclass(frozen=True, slots=True)
class Scenario:
    """Упорядоченная последовательность фаз, которую можно повторять."""

    name: str
    phases: tuple[Phase, ...] = field(default_factory=tuple)
    id: int | None = None
    is_archived: bool = False

    def validate(self) -> None:
        if not self.name.strip():
            raise ValueError("Название сценария не может быть пустым")
        if len(self.name.strip()) > 80:
            raise ValueError("Название сценария длиннее 80 символов")
        if not self.phases:
            raise ValueError("Сценарий должен содержать хотя бы одну фазу")
        if not any(p.repeat_policy is not PhaseRepeatPolicy.DISABLED for p in self.phases):
            raise ValueError("В сценарии должна быть хотя бы одна активная фаза")
        for phase in self.phases:
            phase.validate()

    def phase_for_next(self, current_position: int | None, *, is_first_run: bool) -> Phase | None:
        """Вернуть следующую разрешённую фазу.

        На первом запуске учитываются все активные фазы. На последующих
        циклах `once_at_start` пропускаются, что покрывает сценарий
        «подготовка → работа → отдых → работа → отдых».
        """
        phases = sorted(self.phases, key=lambda phase: phase.position)
        if not phases:
            return None
        start = 0
        if current_position is not None:
            for index, phase in enumerate(phases):
                if phase.position == current_position:
                    start = (index + 1) % len(phases)
                    break
        for offset in range(len(phases)):
            phase = phases[(start + offset) % len(phases)]
            if phase.repeat_policy is PhaseRepeatPolicy.DISABLED:
                continue
            if not is_first_run and phase.repeat_policy is PhaseRepeatPolicy.ONCE_AT_START:
                continue
            return phase
        return None
