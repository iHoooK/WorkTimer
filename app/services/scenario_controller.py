"""Serialized scenario/session commands and durable timer checkpoints."""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, replace
from functools import wraps
from typing import Any

from app.domain.models import FocusMode, Phase, PhaseRepeatPolicy, Scenario
from app.storage.sqlite_database import SQLiteDatabase
from core.events import Event, EventBus
from core.timer import EVENT_FINISHED, EVENT_PAUSED, EVENT_RESUMED, EVENT_TICK, TimerEngine, TimerMode, TimerPhase

logger = logging.getLogger(__name__)


def serialized(method):
    @wraps(method)
    def command(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return command


class ScenarioController:
    def __init__(self, database: SQLiteDatabase, timer: TimerEngine, bus: EventBus | None = None) -> None:
        self._lock = threading.RLock()
        self._database = database
        self._timer = timer
        self._scenario_id = self._load_active_scenario_id()
        self._scenario = database.get_scenario(self._scenario_id) if self._scenario_id else None
        self._current_position: int | None = None
        self._running_phase: Phase | None = None
        self._is_first_cycle = True
        self._progress_count = 0
        self._scenario_completed = False
        self._mode = FocusMode.SCENARIO
        self._active_task_id = self._load_active_task_id()
        self._active_entry_id: int | None = None
        self._session_id: int | None = None
        self._run_id = 0
        self._recovered = False
        self._auto_timer: threading.Timer | None = None
        if bus is not None:
            bus.subscribe(EVENT_FINISHED, self._on_timer_ended)
            bus.subscribe(EVENT_TICK, self._on_tick)
            bus.subscribe(EVENT_PAUSED, self._on_checkpoint_event)
            bus.subscribe(EVENT_RESUMED, self._on_checkpoint_event)
        self._restore()
        database.close_orphan_entries(self._active_entry_id, self._session_id)

    def _load_active_scenario_id(self) -> int | None:
        value = self._database.get_setting("active_scenario_id")
        if isinstance(value, int):
            try:
                if not self._database.get_scenario(value).is_archived:
                    return value
            except KeyError:
                pass
        name = self._database.get_setting("active_scenario_name")
        scenarios = [s for s in self._database.list_scenarios() if not s.is_archived]
        match = next((s for s in scenarios if s.name == name), None)
        return match.id if match else scenarios[0].id if scenarios else None

    def _load_active_task_id(self) -> int | None:
        value = self._database.get_setting("active_task_id")
        if isinstance(value, int):
            try:
                task = self._database.get_task(value)
                return task.id if task.status.value != "archived" else None
            except KeyError:
                pass
        return None

    @property
    def scenario(self) -> Scenario | None:
        return self._scenario

    @serialized
    def select_scenario(self, scenario_id: int) -> Scenario:
        scenario = self._database.get_scenario(scenario_id)
        if scenario.is_archived:
            raise ValueError("Нельзя выбрать архивный сценарий")
        if scenario_id == self._scenario_id and self._mode == FocusMode.SCENARIO:
            return scenario
        self.stop()
        self._scenario_id, self._scenario = scenario_id, scenario
        self._mode = FocusMode.SCENARIO
        self._database.set_setting("active_scenario_id", scenario_id)
        return scenario

    @serialized
    def save_scenario(self, scenario: Scenario) -> Scenario:
        active = scenario.id is not None and scenario.id == self._scenario_id
        if active and (self._session_id or self._scenario_completed):
            if scenario.progress_total and scenario.progress_total < self._progress_count:
                raise ValueError("Количество циклов не может быть меньше уже начатых рабочих циклов")
            if (
                self._running_phase
                and self._running_phase.id
                and not any(p.id == self._running_phase.id for p in scenario.phases)
            ):
                raise ValueError("Завершите сессию перед удалением текущей фазы")
        saved = self._database.save_scenario(scenario)
        if active:
            self._scenario = saved
            if self._running_phase and self._running_phase.id:
                updated = next((p for p in saved.phases if p.id == self._running_phase.id), None)
                if updated:
                    self._current_position = updated.position
            if not saved.progress_total or saved.progress_total > self._progress_count:
                self._scenario_completed = False
            self._checkpoint()
        return saved

    @serialized
    def add_cycle(self) -> None:
        scenario = self._require_scenario()
        if not scenario.progress_total:
            raise ValueError("В бесконечном сценарии количество циклов не ограничено")
        if scenario.progress_total >= 100:
            raise ValueError("Максимум 100 рабочих циклов")
        self.save_scenario(replace(scenario, progress_total=scenario.progress_total + 1))

    @serialized
    def select_task(self, task_id: int | None) -> None:
        if task_id is not None and self._database.get_task(task_id).status.value == "archived":
            raise ValueError("Нельзя выбрать архивную задачу")
        self._active_task_id = task_id
        self._database.set_setting("active_task_id", task_id)
        # A selection applies to the next interval. The current interval keeps its attribution.
        self._checkpoint()

    def _cancel_auto(self) -> None:
        if self._auto_timer is not None:
            self._auto_timer.cancel()
            self._auto_timer = None

    @serialized
    def start(self) -> None:
        self._cancel_auto()
        state = self._timer.state
        if state.is_running:
            self._timer.pause()
        elif state.is_paused:
            self._recovered = False
            self._timer.resume()
        elif self._mode == FocusMode.FREE:
            self.start_free()
        elif state.is_finished and not self._scenario_completed:
            self.next_phase()
        else:
            self.start_from_beginning()
        self._checkpoint()

    def _new_session(self) -> None:
        if self._session_id is None:
            self._session_id = self._database.create_session(
                task_id=self._active_task_id,
                scenario_id=None if self._mode == FocusMode.FREE else self._scenario_id,
                mode=self._mode.value,
            )

    @serialized
    def start_from_beginning(self) -> None:
        scenario = self._require_scenario()
        self.stop()
        self._is_first_cycle = True
        self._progress_count = 0
        self._scenario_completed = False
        phase = self._first_allowed_phase(scenario, first_cycle=True)
        if phase is None:
            raise ValueError("В сценарии нет активных фаз")
        self._start_phase(phase)

    @serialized
    def start_free(self) -> None:
        self.stop()
        self._mode = FocusMode.FREE
        self._new_session()
        self._timer.start_free()
        self._run_id = self._timer.state.run_id
        self._active_entry_id = self._database.create_time_entry(
            task_id=self._active_task_id,
            scenario_id=None,
            phase_id=None,
            session_id=self._session_id,
            phase_name="Свободная работа",
        )
        self._checkpoint()

    @serialized
    def start_pomodoro(
        self,
        work_seconds: int = 1500,
        break_seconds: int = 300,
        long_break_seconds: int = 900,
        cycles_before_long_break: int = 4,
    ) -> None:
        if not (
            60 <= work_seconds <= 14400
            and 60 <= break_seconds <= 7200
            and 60 <= long_break_seconds <= 10800
            and 2 <= cycles_before_long_break <= 12
        ):
            raise ValueError("Некорректные интервалы Pomodoro")
        self.stop()
        system_id = self._database.get_setting("system_pomodoro_id")
        existing = None
        if isinstance(system_id, int):
            try:
                existing = self._database.get_scenario(system_id)
            except KeyError:
                pass
        name = existing.name if existing else "Pomodoro"
        names = {s.name.casefold() for s in self._database.list_scenarios() if not existing or s.id != existing.id}
        suffix = 2
        while name.casefold() in names:
            name = f"Pomodoro {suffix}"
            suffix += 1
        scenario = self._database.save_scenario(
            Scenario(
                name,
                tuple(
                    phase
                    for cycle in range(cycles_before_long_break)
                    for phase in (
                        Phase("Фокус" if cycle == 0 else f"Фокус {cycle + 1}", work_seconds, color_role="work"),
                        Phase(
                            "Длинный отдых" if cycle == cycles_before_long_break - 1 else "Отдых",
                            long_break_seconds if cycle == cycles_before_long_break - 1 else break_seconds,
                            color_role="rest",
                        ),
                    )
                ),
                id=existing.id if existing else None,
            )
        )
        self._database.set_setting("system_pomodoro_id", scenario.id)
        self._scenario_id, self._scenario = scenario.id, scenario
        self._mode = FocusMode.POMODORO
        self.start_from_beginning()

    @serialized
    def next_phase(self) -> None:
        self._cancel_auto()
        if self._mode == FocusMode.FREE:
            raise ValueError("В свободном режиме нет фаз: завершите сессию или поставьте её на паузу")
        scenario = self._require_scenario()
        if self._current_position is None:
            self.start_from_beginning()
            return
        phase, crossed_cycle = self._next_allowed_phase(scenario, self._current_position)
        if phase is None:
            self._finish_active_entry(self._timer.state.elapsed_seconds)
            self._timer.stop()
            self._scenario_completed = True
            self._finish_session(completed=True)
            self._checkpoint()
            return
        if crossed_cycle:
            self._is_first_cycle = False
        self._start_phase(phase)

    @serialized
    def repeat_phase(self) -> None:
        self._cancel_auto()
        if self._mode == FocusMode.FREE:
            raise ValueError("В свободном режиме нет повторяемой фазы")
        phase = self._phase_by_position(self._current_position)
        if phase is None:
            self.start_from_beginning()
        else:
            self._scenario_completed = False
            self._start_phase(phase, count_progress=False)

    @serialized
    def start_phase(self, position: int) -> None:
        phase = self._phase_by_position(position)
        if phase is None or phase.repeat_policy == PhaseRepeatPolicy.DISABLED:
            raise ValueError("Эта фаза недоступна для запуска")
        if self._mode == FocusMode.FREE:
            self.stop()
            self._mode = FocusMode.SCENARIO
        self._scenario_completed = False
        self._start_phase(phase)

    def _finish_session(self, *, completed: bool = False) -> None:
        if self._session_id is not None:
            self._database.finish_session(self._session_id, completed=completed)
            self._session_id = None

    @serialized
    def stop(self) -> None:
        self._cancel_auto()
        self._finish_active_entry(self._timer.state.elapsed_seconds)
        self._timer.stop()
        self._run_id = 0
        self._finish_session()
        self._current_position = None
        self._running_phase = None
        self._is_first_cycle = True
        self._progress_count = 0
        self._scenario_completed = False
        self._recovered = False
        self._database.checkpoint_runtime(None)

    @serialized
    def suspend_for_exit(self) -> None:
        # Graceful application exit preserves the session, paused on next launch.
        self._cancel_auto()
        if self._timer.state.is_running:
            self._timer.pause()
        self._checkpoint()
        self._timer.stop()
        self._run_id = 0

    @serialized
    def archive_scenario(self, scenario_id: int) -> None:
        if scenario_id == self._scenario_id and (self._active_entry_id or self._session_id):
            raise ValueError("Сначала завершите активную сессию")
        self._database.archive_scenario(scenario_id)
        if scenario_id == self._scenario_id:
            self._scenario_id = self._load_active_scenario_id()
            self._scenario = self._database.get_scenario(self._scenario_id) if self._scenario_id else None
            self._database.set_setting("active_scenario_id", self._scenario_id)

    @serialized
    def import_backup(self, payload: bytes) -> None:
        if self._session_id or self._active_entry_id:
            raise ValueError("Завершите сессию перед восстановлением данных")
        self._cancel_auto()
        self._database.restore_backup(payload)
        self._scenario_id = self._load_active_scenario_id()
        self._scenario = self._database.get_scenario(self._scenario_id) if self._scenario_id else None
        self._active_task_id = self._load_active_task_id()
        self._current_position = None
        self._running_phase = None
        self._progress_count = 0
        self._mode = FocusMode.SCENARIO
        self._scenario_completed = False
        self._restore()
        self._database.close_orphan_entries(self._active_entry_id, self._session_id)

    @serialized
    def to_dict(self) -> dict[str, Any]:
        state = self._timer.state
        scenario = None if self._mode == FocusMode.FREE else self._scenario
        next_phase = None
        if scenario and not self._scenario_completed:
            next_phase = (
                self._first_allowed_phase(scenario, first_cycle=True)
                if self._current_position is None
                else self._next_allowed_phase(scenario, self._current_position)[0]
            )
        current = self._running_phase
        return {
            "phase": state.phase.value,
            "mode": self._mode.value,
            "time": "00:00" if state.is_idle else state.format_time(),
            "progress": state.progress,
            "elapsed_seconds": state.elapsed_seconds,
            "remaining_seconds": state.remaining_seconds,
            "total_seconds": state.total_seconds,
            "phase_name": state.phase_name
            if not state.is_idle
            else "Сессия завершена"
            if self._scenario_completed
            else "Готов к началу",
            "phase_role": state.phase_role,
            "phase_note": current.note if current else "",
            "scenario_id": scenario.id if scenario else None,
            "scenario_name": scenario.name if scenario else None,
            "current_phase_id": current.id if current else None,
            "current_phase_position": self._current_position,
            "current_phase_name": current.name if current else None,
            "next_phase_name": next_phase.name if next_phase else None,
            "is_first_cycle": self._is_first_cycle,
            "progress_current": self._progress_count,
            "progress_total": scenario.progress_total if scenario else 0,
            "scenario_completed": self._scenario_completed,
            "active_task_id": self._active_task_id,
            "session_id": self._session_id,
            "recovered": self._recovered,
            "run_id": self._run_id,
        }

    def _require_scenario(self) -> Scenario:
        if self._scenario is None or self._scenario.is_archived:
            raise ValueError("Сначала создайте или выберите сценарий")
        return self._scenario

    def _phase_by_position(self, position: int | None) -> Phase | None:
        if position is None or self._scenario is None:
            return None
        return next((p for p in self._scenario.phases if p.position == position), None)

    @staticmethod
    def _first_allowed_phase(scenario: Scenario, *, first_cycle: bool) -> Phase | None:
        return next(
            (
                p
                for p in sorted(scenario.phases, key=lambda p: p.position)
                if p.repeat_policy != PhaseRepeatPolicy.DISABLED
                and (first_cycle or p.repeat_policy != PhaseRepeatPolicy.ONCE_AT_START)
            ),
            None,
        )

    def _next_allowed_phase(self, scenario: Scenario, current_position: int) -> tuple[Phase | None, bool]:
        phases = sorted(scenario.phases, key=lambda p: p.position)
        index = next((i for i, p in enumerate(phases) if p.position == current_position), -1)
        if index < 0:
            return self._first_allowed_phase(scenario, first_cycle=self._is_first_cycle), False
        for offset in range(1, len(phases) + 1):
            target = (index + offset) % len(phases)
            crossed = target <= index
            phase = phases[target]
            if phase.repeat_policy == PhaseRepeatPolicy.DISABLED:
                continue
            if phase.repeat_policy == PhaseRepeatPolicy.ONCE_AT_START and (crossed or not self._is_first_cycle):
                continue
            if phase.progress_marker and scenario.progress_total and self._progress_count >= scenario.progress_total:
                return None, crossed
            return phase, crossed
        return None, False

    def _start_phase(self, phase: Phase, *, count_progress: bool = True) -> None:
        self._cancel_auto()
        self._finish_active_entry(self._timer.state.elapsed_seconds)
        self._timer.stop()
        scenario = self._require_scenario()
        self._new_session()
        if phase.progress_marker and count_progress and scenario.progress_total:
            self._progress_count = min(self._progress_count + 1, scenario.progress_total)
        self._current_position, self._running_phase = phase.position, phase
        role = phase.color_role.casefold()
        mode = TimerMode.WORK if role == "work" else TimerMode.BREAK if role == "rest" else TimerMode.CUSTOM
        self._timer.start(
            phase.duration_seconds,
            mode,
            phase_name=phase.name,
            phase_role=role,
            sound_enabled=phase.sound_enabled,
            notification_enabled=phase.notification_enabled,
        )
        self._run_id = self._timer.state.run_id
        self._active_entry_id = self._database.create_time_entry(
            task_id=self._active_task_id,
            scenario_id=self._scenario_id,
            phase_id=phase.id,
            session_id=self._session_id,
            phase_name=phase.name,
            phase_role=role,
        )
        self._checkpoint()

    @serialized
    def _on_tick(self, event: Event) -> None:
        if event.data.run_id == self._run_id:
            self._checkpoint()

    @serialized
    def _on_checkpoint_event(self, event: Event) -> None:
        if event.data.run_id == self._run_id:
            self._checkpoint()

    @serialized
    def _on_timer_ended(self, event: Event) -> None:
        if event.data.run_id != self._run_id:
            return
        self._finish_active_entry(event.data.elapsed_seconds)
        self._checkpoint()
        preferences = self._database.get_setting("app_preferences", {})
        if isinstance(preferences, dict) and preferences.get("auto_start_next_phase"):
            run_id = self._run_id
            self._auto_timer = threading.Timer(0.25, self._auto_next, args=(run_id,))
            self._auto_timer.daemon = True
            self._auto_timer.start()

    @serialized
    def _auto_next(self, run_id: int) -> None:
        if run_id == self._run_id and self._timer.state.is_finished:
            self.next_phase()

    def _finish_active_entry(self, elapsed_seconds: int) -> None:
        if self._active_entry_id is not None:
            self._database.finish_time_entry(self._active_entry_id, elapsed_seconds)
            self._active_entry_id = None

    def _checkpoint(self) -> None:
        state = self._timer.state
        if state.phase not in (TimerPhase.RUNNING, TimerPhase.PAUSED, TimerPhase.FINISHED):
            self._database.checkpoint_runtime(None)
            return
        phase = asdict(self._running_phase) if self._running_phase else None
        self._database.checkpoint_runtime(
            {
                "entry_id": self._active_entry_id,
                "session_id": self._session_id,
                "scenario_id": self._scenario_id,
                "position": self._current_position,
                "first_cycle": self._is_first_cycle,
                "progress_count": self._progress_count,
                "mode": self._mode.value,
                "task_id": self._active_task_id,
                "phase": phase,
                "elapsed": state.elapsed_precise,
                "total": state.total_seconds,
                "timer_phase": state.phase.value,
            }
        )

    def _restore(self) -> None:
        raw = self._database.get_setting("active_runtime")
        if not isinstance(raw, dict) or raw.get("timer_phase") not in ("running", "paused", "finished"):
            return
        try:
            scenario_id = raw.get("scenario_id")
            self._mode = FocusMode(raw["mode"])
            if scenario_id is not None:
                self._scenario = self._database.get_scenario(int(scenario_id))
                self._scenario_id = int(scenario_id)
            self._active_entry_id = raw.get("entry_id")
            if self._active_entry_id and not self._database.open_entry_exists(self._active_entry_id):
                self._active_entry_id = None
            self._session_id = raw.get("session_id")
            self._current_position = raw.get("position")
            self._is_first_cycle = bool(raw.get("first_cycle", True))
            self._progress_count = int(raw.get("progress_count", 0))
            phase = raw.get("phase")
            if isinstance(phase, dict):
                phase["repeat_policy"] = PhaseRepeatPolicy(phase["repeat_policy"])
                self._running_phase = Phase(**phase)
            elapsed = max(0, float(raw.get("elapsed", 0)))
            if self._mode == FocusMode.FREE:
                self._timer.start_free(elapsed_seconds=elapsed, paused=True)
            elif self._running_phase:
                p = self._running_phase
                self._timer.start(
                    int(raw["total"]),
                    TimerMode.CUSTOM,
                    phase_name=p.name,
                    phase_role=p.color_role,
                    sound_enabled=p.sound_enabled,
                    notification_enabled=p.notification_enabled,
                    elapsed_seconds=elapsed,
                    paused=True,
                )
            else:
                return
            self._run_id = self._timer.state.run_id
            self._recovered = True
            if raw.get("timer_phase") == "finished":
                self._timer.restore_finished()
        except KeyError, ValueError, TypeError:
            logger.exception("Невозможно восстановить контрольную точку")
            self._database.checkpoint_runtime(None)
            self._active_entry_id = None
            self._session_id = None
            self._current_position = None
            self._running_phase = None
            self._progress_count = 0
            self._mode = FocusMode.SCENARIO
            self._timer.stop()
            self._run_id = 0
