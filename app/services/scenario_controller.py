"""Управление сценариями поверх чистого TimerEngine."""

from __future__ import annotations

from typing import Any

from app.domain.models import Phase, PhaseRepeatPolicy, Scenario
from app.storage.sqlite_database import SQLiteDatabase
from core.timer import TimerEngine, TimerMode, TimerPhase
from core.events import Event, EventBus
from core.timer import EVENT_FINISHED, EVENT_STOPPED


class ScenarioController:
    """Оркестрирует сценарий, но не зависит от legacy UI.

    Переходы остаются ручными. Окончание фазы только переводит TimerEngine в
    `finished`; пользователь решает, запустить ли следующую, повторить фазу
    или начать сценарий заново.
    """

    def __init__(self, database: SQLiteDatabase, timer: TimerEngine, bus: EventBus | None = None) -> None:
        self._database = database
        self._timer = timer
        self._scenario_id: int | None = self._load_active_scenario_id()
        self._current_position: int | None = None
        self._is_first_cycle = True
        self._active_task_id = self._load_active_task_id()
        self._active_entry_id: int | None = None
        if bus is not None:
            bus.subscribe(EVENT_FINISHED, self._on_timer_ended)
            bus.subscribe(EVENT_STOPPED, self._on_timer_ended)

    def _load_active_scenario_id(self) -> int | None:
        value = self._database.get_setting("active_scenario_id")
        if isinstance(value, int):
            try:
                self._database.get_scenario(value)
                return value
            except KeyError:
                pass
        scenarios = [scenario for scenario in self._database.list_scenarios() if not scenario.is_archived]
        return scenarios[0].id if scenarios else None

    def _load_active_task_id(self) -> int | None:
        value = self._database.get_setting("active_task_id")
        if isinstance(value, int):
            try:
                return self._database.get_task(value).id
            except KeyError:
                pass
        return None

    @property
    def scenario(self) -> Scenario | None:
        if self._scenario_id is None:
            return None
        try:
            return self._database.get_scenario(self._scenario_id)
        except KeyError:
            return None

    def select_scenario(self, scenario_id: int) -> Scenario:
        scenario = self._database.get_scenario(scenario_id)
        if scenario.is_archived:
            raise ValueError("Нельзя выбрать архивный сценарий")
        self.stop()
        self._scenario_id = scenario_id
        self._database.set_setting("active_scenario_id", scenario_id)
        return scenario

    def select_task(self, task_id: int | None) -> None:
        if task_id is not None:
            task = self._database.get_task(task_id)
            if task.status.value == "archived":
                raise ValueError("Нельзя выбрать архивную задачу")
        self._active_task_id = task_id
        self._database.set_setting("active_task_id", task_id)

    def start(self) -> None:
        state = self._timer.state
        if state.phase == TimerPhase.PAUSED:
            self._timer.resume()
            return
        if state.phase == TimerPhase.RUNNING:
            self._timer.pause()
            return
        if self._current_position is None:
            self.start_from_beginning()
            return
        phase = self._phase_by_position(self._current_position)
        if phase is None:
            self.start_from_beginning()
        else:
            self._start_phase(phase)

    def start_from_beginning(self) -> None:
        scenario = self._require_scenario()
        self._is_first_cycle = True
        phase = self._first_allowed_phase(scenario, first_cycle=True)
        if phase is None:
            raise ValueError("В сценарии нет активных фаз")
        self._start_phase(phase)

    def start_free(self) -> None:
        self._finish_active_entry(self._timer.state.elapsed_seconds)
        self._current_position = None
        self._timer.start_free()
        self._active_entry_id = self._database.create_time_entry(
            task_id=self._active_task_id,
            scenario_id=None,
            phase_id=None,
        )

    def start_pomodoro(self, work_seconds: int = 1_500, break_seconds: int = 300, long_break_seconds: int = 900, cycles_before_long_break: int = 4) -> None:
        if not 60 <= work_seconds <= 14_400 or not 60 <= break_seconds <= 7_200 or not 60 <= long_break_seconds <= 10_800 or not 2 <= cycles_before_long_break <= 12:
            raise ValueError("Интервалы Pomodoro должны быть разумной длительности")
        existing = next((scenario for scenario in self._database.list_scenarios() if scenario.name == "Pomodoro"), None)
        scenario = self._database.save_scenario(
            Scenario(
                id=existing.id if existing else None,
                name="Pomodoro",
                phases=tuple(
                    phase for cycle in range(cycles_before_long_break)
                    for phase in (
                        Phase("Фокус" if cycle == 0 else f"Фокус {cycle + 1}", work_seconds, color_role="work"),
                        Phase("Длинный отдых" if cycle == cycles_before_long_break - 1 else "Отдых", long_break_seconds if cycle == cycles_before_long_break - 1 else break_seconds, color_role="rest"),
                    )
                ),
            )
        )
        self.select_scenario(scenario.id or 0)
        self.start_from_beginning()

    def next_phase(self) -> None:
        scenario = self._require_scenario()
        if self._current_position is None:
            self.start_from_beginning()
            return
        phase, crossed_cycle = self._next_allowed_phase(scenario, self._current_position)
        if phase is None:
            raise ValueError("В сценарии нет активных фаз")
        if crossed_cycle:
            self._is_first_cycle = False
        self._start_phase(phase)

    def repeat_phase(self) -> None:
        if self._current_position is None:
            self.start_from_beginning()
            return
        phase = self._phase_by_position(self._current_position)
        if phase is None:
            self.start_from_beginning()
            return
        self._start_phase(phase)

    def start_phase(self, position: int) -> None:
        """Запустить конкретную фазу по явному действию пользователя."""
        phase = self._phase_by_position(position)
        if phase is None or phase.repeat_policy is PhaseRepeatPolicy.DISABLED:
            raise ValueError("Эта фаза недоступна для запуска")
        self._start_phase(phase)

    def stop(self) -> None:
        elapsed_seconds = self._timer.state.elapsed_seconds
        self._timer.stop()
        self._finish_active_entry(elapsed_seconds)
        self._current_position = None
        self._is_first_cycle = True

    def to_dict(self) -> dict[str, Any]:
        state = self._timer.state
        scenario = self.scenario
        current_phase = self._phase_by_position(self._current_position)
        next_phase: Phase | None = None
        if scenario is not None:
            if self._current_position is None:
                next_phase = self._first_allowed_phase(scenario, first_cycle=True)
            else:
                next_phase, _ = self._next_allowed_phase(scenario, self._current_position)
        return {
            "phase": state.phase.value,
            "time": state.format_time(),
            "progress": state.progress,
            "phase_name": state.phase_name,
            "phase_role": state.phase_role,
            "scenario_id": scenario.id if scenario else None,
            "scenario_name": scenario.name if scenario else None,
            "current_phase_position": self._current_position,
            "current_phase_name": current_phase.name if current_phase else None,
            "next_phase_name": next_phase.name if next_phase else None,
            "is_first_cycle": self._is_first_cycle,
            "active_task_id": self._active_task_id,
        }

    def _require_scenario(self) -> Scenario:
        scenario = self.scenario
        if scenario is None:
            raise ValueError("Сначала создайте или выберите сценарий")
        return scenario

    def _phase_by_position(self, position: int | None) -> Phase | None:
        if position is None or self.scenario is None:
            return None
        return next((phase for phase in self.scenario.phases if phase.position == position), None)

    @staticmethod
    def _first_allowed_phase(scenario: Scenario, *, first_cycle: bool) -> Phase | None:
        for phase in sorted(scenario.phases, key=lambda item: item.position):
            if phase.repeat_policy is PhaseRepeatPolicy.DISABLED:
                continue
            if not first_cycle and phase.repeat_policy is PhaseRepeatPolicy.ONCE_AT_START:
                continue
            return phase
        return None

    def _next_allowed_phase(self, scenario: Scenario, current_position: int) -> tuple[Phase | None, bool]:
        phases = sorted(scenario.phases, key=lambda item: item.position)
        current_index = next((i for i, phase in enumerate(phases) if phase.position == current_position), -1)
        if current_index < 0:
            return self._first_allowed_phase(scenario, first_cycle=self._is_first_cycle), False
        for offset in range(1, len(phases) + 1):
            index = (current_index + offset) % len(phases)
            crossed_cycle = index <= current_index
            phase = phases[index]
            if phase.repeat_policy is PhaseRepeatPolicy.DISABLED:
                continue
            if phase.repeat_policy is PhaseRepeatPolicy.ONCE_AT_START and (crossed_cycle or not self._is_first_cycle):
                continue
            return phase, crossed_cycle
        return None, False

    def _start_phase(self, phase: Phase) -> None:
        self._finish_active_entry(self._timer.state.elapsed_seconds)
        self._current_position = phase.position
        role = phase.color_role.casefold()
        mode = TimerMode.WORK if role == "work" else TimerMode.BREAK if role == "rest" else TimerMode.CUSTOM
        self._timer.start(
            duration_seconds=phase.duration_seconds,
            mode=mode,
            phase_name=phase.name,
            phase_role=phase.color_role,
        )
        self._active_entry_id = self._database.create_time_entry(
            task_id=self._active_task_id,
            scenario_id=self._scenario_id,
            phase_id=phase.id,
        )

    def _on_timer_ended(self, event: Event) -> None:
        self._finish_active_entry(event.data.elapsed_seconds)

    def _finish_active_entry(self, elapsed_seconds: int) -> None:
        if self._active_entry_id is not None:
            self._database.finish_time_entry(self._active_entry_id, elapsed_seconds)
            self._active_entry_id = None
