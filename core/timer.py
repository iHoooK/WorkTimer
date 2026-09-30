"""Clock-based timer. Delayed subscribers never slow the countdown."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from core.events import Event, EventBus


class TimerMode(str, Enum):
    WORK = "work"
    BREAK = "break"
    CUSTOM = "custom"
    FREE = "free"


class TimerPhase(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class TimerState:
    mode: TimerMode
    phase: TimerPhase
    phase_name: str
    phase_role: str
    remaining_seconds: int
    total_seconds: int
    elapsed_seconds: int
    run_id: int = 0
    elapsed_precise: float = 0
    sound_enabled: bool = True
    notification_enabled: bool = True

    @property
    def progress(self) -> float:
        return min(self.elapsed_precise / self.total_seconds, 1.0) if self.total_seconds else 0.0

    @property
    def is_running(self) -> bool:
        return self.phase == TimerPhase.RUNNING

    @property
    def is_paused(self) -> bool:
        return self.phase == TimerPhase.PAUSED

    @property
    def is_idle(self) -> bool:
        return self.phase == TimerPhase.IDLE

    @property
    def is_finished(self) -> bool:
        return self.phase == TimerPhase.FINISHED

    def format_time(self) -> str:
        value = self.elapsed_seconds if self.mode == TimerMode.FREE else self.remaining_seconds
        minutes, seconds = divmod(max(value, 0), 60)
        return f"{minutes:02d}:{seconds:02d}"


EVENT_TICK = "timer.tick"
EVENT_FINISHED = "timer.finished"
EVENT_STARTED = "timer.started"
EVENT_PAUSED = "timer.paused"
EVENT_RESUMED = "timer.resumed"
EVENT_STOPPED = "timer.stopped"


class TimerEngine:
    # Countdown includes system sleep; a paused timer excludes all paused time.
    _TICK_INTERVAL = 0.2

    def __init__(self, bus: EventBus, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._bus = bus
        self._clock = clock
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._run_id = 0
        self._mode = TimerMode.WORK
        self._phase = TimerPhase.IDLE
        self._phase_name = "Готов к началу"
        self._phase_role = "work"
        self._total_seconds = 0
        self._elapsed = 0.0
        self._anchor: float | None = None
        self._sound_enabled = True
        self._notification_enabled = True

    def _elapsed_now(self) -> float:
        elapsed = self._elapsed
        if self._phase == TimerPhase.RUNNING and self._anchor is not None:
            elapsed += max(0, self._clock() - self._anchor)
        return elapsed if self._mode == TimerMode.FREE else min(elapsed, self._total_seconds)

    @property
    def state(self) -> TimerState:
        with self._lock:
            elapsed = self._elapsed_now()
            remaining = 0 if self._mode == TimerMode.FREE else math.ceil(max(0, self._total_seconds - elapsed))
            return TimerState(
                self._mode,
                self._phase,
                self._phase_name,
                self._phase_role,
                remaining,
                self._total_seconds,
                int(elapsed),
                self._run_id,
                elapsed,
                self._sound_enabled,
                self._notification_enabled,
            )

    def start(
        self,
        duration_seconds: int,
        mode: TimerMode = TimerMode.WORK,
        *,
        phase_name: str = "",
        phase_role: str | None = None,
        count_up: bool = False,
        sound_enabled: bool = True,
        notification_enabled: bool = True,
        elapsed_seconds: float = 0,
        paused: bool = False,
    ) -> None:
        if duration_seconds <= 0 and not count_up:
            raise ValueError("Длительность должна быть больше нуля")
        self.stop()
        with self._lock:
            self._run_id += 1
            self._mode = TimerMode.FREE if count_up else mode
            self._phase = TimerPhase.PAUSED if paused else TimerPhase.RUNNING
            self._phase_name = (
                phase_name.strip()
                or {
                    TimerMode.WORK: "Работа",
                    TimerMode.BREAK: "Отдых",
                    TimerMode.CUSTOM: "Фаза",
                    TimerMode.FREE: "Свободная работа",
                }[self._mode]
            )
            self._phase_role = phase_role or mode.value
            self._total_seconds = duration_seconds
            self._elapsed = max(0, float(elapsed_seconds))
            self._anchor = None if paused else self._clock()
            self._sound_enabled = sound_enabled
            self._notification_enabled = notification_enabled
            self._stop_event = threading.Event()
            event = self._stop_event
            run_id = self._run_id
            self._thread = threading.Thread(target=self._run, args=(event, run_id), name="WorkTimer-clock", daemon=True)
            self._thread.start()
        self._publish(EVENT_STARTED)

    def start_free(
        self,
        *,
        phase_name: str = "Свободная работа",
        phase_role: str = "work",
        elapsed_seconds: float = 0,
        paused: bool = False,
    ) -> None:
        self.start(
            0,
            TimerMode.FREE,
            phase_name=phase_name,
            phase_role=phase_role,
            count_up=True,
            elapsed_seconds=elapsed_seconds,
            paused=paused,
        )

    def pause(self) -> None:
        with self._lock:
            if self._phase != TimerPhase.RUNNING:
                return
            self._elapsed = self._elapsed_now()
            self._anchor = None
            self._phase = TimerPhase.PAUSED
        self._publish(EVENT_PAUSED)

    def resume(self) -> None:
        with self._lock:
            if self._phase != TimerPhase.PAUSED:
                return
            self._anchor = self._clock()
            self._phase = TimerPhase.RUNNING
        self._publish(EVENT_RESUMED)

    def stop(self) -> None:
        # Do not join: a worker may be delivering a callback waiting for the
        # controller's command lock. Each worker has its own cancellation event.
        with self._lock:
            previous = self._phase
            self._elapsed = self._elapsed_now()
            self._anchor = None
            self._phase = TimerPhase.IDLE
            self._stop_event.set()
            snapshot = self.state
        if previous in (TimerPhase.RUNNING, TimerPhase.PAUSED):
            self._bus.publish(Event(EVENT_STOPPED, snapshot))

    def close(self) -> None:
        self.stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)

    def restore_finished(self) -> None:
        with self._lock:
            self._elapsed = float(self._total_seconds)
            self._anchor = None
            self._phase = TimerPhase.FINISHED
            self._stop_event.set()

    def _run(self, cancelled: threading.Event, run_id: int) -> None:
        last_second = -1
        while not cancelled.wait(self._TICK_INTERVAL):
            with self._lock:
                if run_id != self._run_id or self._phase == TimerPhase.IDLE:
                    return
                if self._phase != TimerPhase.RUNNING:
                    continue
                elapsed = self._elapsed_now()
                finished = self._mode != TimerMode.FREE and elapsed >= self._total_seconds
                if finished:
                    self._elapsed = float(self._total_seconds)
                    self._anchor = None
                    self._phase = TimerPhase.FINISHED
                snapshot = self.state
            if cancelled.is_set():
                return
            if snapshot.elapsed_seconds != last_second or finished:
                last_second = snapshot.elapsed_seconds
                self._bus.publish(Event(EVENT_TICK, snapshot))
            if finished:
                if not cancelled.is_set():
                    self._bus.publish(Event(EVENT_FINISHED, snapshot))
                return

    def _publish(self, name: str) -> None:
        self._bus.publish(Event(name, self.state))
