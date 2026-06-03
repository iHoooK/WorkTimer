"""
core/timer.py — Чистая логика таймера обратного отсчёта.

Никакого tkinter, никакого UI. Только счёт времени и публикация событий.
TimerEngine работает в daemon-потоке и общается с внешним миром
исключительно через EventBus.

SOLID:
  S — Engine только считает время, не знает ни о звуке, ни об UI.
  D — Зависит от абстракции EventBus, не от конкретного UI-класса.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.events import EventBus

logger = logging.getLogger(__name__)


# ===========================================================================
# Шаг 2.1 — TimerState
# ===========================================================================

class TimerMode(str, Enum):
    """Режим таймера: работа или перерыв."""
    WORK  = "work"
    BREAK = "break"


class TimerPhase(str, Enum):
    """Фаза жизненного цикла таймера."""
    IDLE     = "idle"      # Не запущен / сброшен
    RUNNING  = "running"   # Тикает
    PAUSED   = "paused"    # Приостановлен
    FINISHED = "finished"  # Обратный отсчёт достиг нуля


@dataclass
class TimerState:
    """
    Иммутабельный (по соглашению) снимок состояния таймера.

    Публикуется с каждым событием timer.tick и timer.finished.
    Не frozen — чтобы не создавать лишние объекты; не изменяй снаружи.

    Поля:
        mode             — режим (work / break)
        phase            — текущая фаза (idle / running / paused / finished)
        remaining_seconds — сколько секунд осталось
        total_seconds    — изначальная длительность
        elapsed_seconds  — сколько секунд прошло
    """
    mode: TimerMode
    phase: TimerPhase
    remaining_seconds: int
    total_seconds: int
    elapsed_seconds: int

    # ------------------------------------------------------------------
    # Вычисляемые свойства — удобны для UI
    # ------------------------------------------------------------------

    @property
    def progress(self) -> float:
        """Прогресс от 0.0 (начало) до 1.0 (завершение)."""
        if self.total_seconds == 0:
            return 0.0
        return min(self.elapsed_seconds / self.total_seconds, 1.0)

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
        """Форматировать remaining_seconds как MM:SS. Например: '24:59'."""
        m, s = divmod(max(self.remaining_seconds, 0), 60)
        return f"{m:02d}:{s:02d}"

    def __repr__(self) -> str:
        return (
            f"TimerState({self.phase.value}, {self.format_time()}, "
            f"mode={self.mode.value}, progress={self.progress:.0%})"
        )


# ===========================================================================
# Константы имён событий (избегаем опечаток через строки в коде)
# ===========================================================================

EVENT_TICK     = "timer.tick"      # Каждую секунду; data: TimerState
EVENT_FINISHED = "timer.finished"  # Обратный отсчёт достиг нуля; data: TimerState
EVENT_STARTED  = "timer.started"   # Таймер запущен; data: TimerState
EVENT_PAUSED   = "timer.paused"    # Поставлен на паузу; data: TimerState
EVENT_RESUMED  = "timer.resumed"   # Возобновлён; data: TimerState
EVENT_STOPPED  = "timer.stopped"   # Принудительно остановлен; data: TimerState


# ===========================================================================
# Шаг 2.2 — TimerEngine
# ===========================================================================

class TimerEngine:
    """
    Движок таймера обратного отсчёта.

    Работает в отдельном daemon-потоке — не блокирует UI.
    Общается с внешним миром исключительно через EventBus (DIP).

    Жизненный цикл:
        IDLE → start() → RUNNING → pause() → PAUSED → resume() → RUNNING
                                           → stop()  → IDLE
                                           → (0 сек) → FINISHED

    Пример:
        engine = TimerEngine(bus=event_bus)
        engine.start(duration_seconds=25 * 60, mode=TimerMode.WORK)
        # ...
        engine.pause()
        engine.resume()
        engine.stop()
    """

    _TICK_INTERVAL = 1.0  # интервал между тиками, секунды

    def __init__(self, bus: "EventBus") -> None:
        self._bus = bus

        # Поток
        self._thread: threading.Thread | None = None
        self._stop_event  = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # изначально — не на паузе

        # Состояние
        self._mode              = TimerMode.WORK
        self._total_seconds     = 0
        self._remaining_seconds = 0
        self._elapsed_seconds   = 0
        self._phase             = TimerPhase.IDLE

        # Мьютекс для безопасного чтения состояния из UI-потока
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, duration_seconds: int, mode: TimerMode = TimerMode.WORK) -> None:
        """
        Запустить таймер заново.

        Если таймер уже работает — сначала корректно останавливает его.

        Args:
            duration_seconds: длительность в секундах, должна быть > 0.
            mode: TimerMode.WORK или TimerMode.BREAK.

        Raises:
            ValueError: если duration_seconds <= 0.
        """
        if duration_seconds <= 0:
            raise ValueError(
                f"duration_seconds должен быть > 0, получено: {duration_seconds}"
            )

        self.stop()  # безопасно — ничего не делает если уже остановлен

        with self._lock:
            self._mode              = mode
            self._total_seconds     = duration_seconds
            self._remaining_seconds = duration_seconds
            self._elapsed_seconds   = 0
            self._phase             = TimerPhase.RUNNING

        self._stop_event.clear()
        self._pause_event.set()

        self._thread = threading.Thread(
            target=self._run,
            name="TimerEngine",
            daemon=True,  # поток умирает вместе с приложением
        )
        self._thread.start()

        self._publish(EVENT_STARTED)
        logger.info("TimerEngine: старт [%s] %ds", mode.value, duration_seconds)

    def pause(self) -> None:
        """
        Поставить таймер на паузу.

        Игнорирует вызов если таймер не запущен.
        """
        with self._lock:
            if self._phase != TimerPhase.RUNNING:
                return
            self._phase = TimerPhase.PAUSED

        self._pause_event.clear()  # поток встанет на wait()
        self._publish(EVENT_PAUSED)
        logger.info("TimerEngine: пауза (%ds осталось)", self._remaining_seconds)

    def resume(self) -> None:
        """
        Возобновить таймер с паузы.

        Игнорирует вызов если таймер не на паузе.
        """
        with self._lock:
            if self._phase != TimerPhase.PAUSED:
                return
            self._phase = TimerPhase.RUNNING

        self._pause_event.set()  # поток продолжит цикл
        self._publish(EVENT_RESUMED)
        logger.info("TimerEngine: возобновление")

    def stop(self) -> None:
        """
        Принудительно остановить таймер и дождаться завершения потока.

        Безопасно вызывать в любой момент, в том числе если таймер уже остановлен.
        """
        if self._thread is None or not self._thread.is_alive():
            return

        with self._lock:
            prev_phase  = self._phase
            self._phase = TimerPhase.IDLE

        self._pause_event.set()   # разбудить поток если он ждёт на паузе
        self._stop_event.set()    # сигнал: выйти из цикла
        self._thread.join(timeout=2.0)
        self._thread = None

        if prev_phase not in (TimerPhase.IDLE, TimerPhase.FINISHED):
            self._publish(EVENT_STOPPED)

        logger.info("TimerEngine: остановлен")

    @property
    def state(self) -> TimerState:
        """Текущий снимок состояния (thread-safe)."""
        with self._lock:
            return TimerState(
                mode=self._mode,
                phase=self._phase,
                remaining_seconds=self._remaining_seconds,
                total_seconds=self._total_seconds,
                elapsed_seconds=self._elapsed_seconds,
            )

    # ------------------------------------------------------------------
    # Приватный цикл потока
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Основной цикл таймера. Запускается в daemon-потоке."""
        while not self._stop_event.is_set():

            # Ожидание если на паузе (без CPU spin — блокирующий wait)
            self._pause_event.wait()

            if self._stop_event.is_set():
                break

            # Ждём ровно 1 секунду (или до stop_event)
            was_stopped = self._stop_event.wait(timeout=self._TICK_INTERVAL)
            if was_stopped:
                break

            # Перепроверяем: за время ожидания мог прийти pause()
            if not self._pause_event.is_set():
                continue

            # Обновляем счётчики
            with self._lock:
                self._remaining_seconds -= 1
                self._elapsed_seconds   += 1
                finished = self._remaining_seconds <= 0
                if finished:
                    self._remaining_seconds = 0
                    self._phase = TimerPhase.FINISHED

            # Публикуем tick в любом случае
            self._publish(EVENT_TICK)

            if finished:
                self._publish(EVENT_FINISHED)
                logger.info("TimerEngine: завершён [%s]", self._mode.value)
                break

    def _publish(self, event_name: str) -> None:
        """Опубликовать текущее состояние как событие на шине."""
        # Локальный импорт — разрываем возможный циклический импорт
        from core.events import Event
        self._bus.publish(Event(name=event_name, data=self.state))

    def __repr__(self) -> str:
        s = self.state
        return (
            f"TimerEngine(phase={s.phase.value}, "
            f"remaining={s.format_time()}, "
            f"mode={s.mode.value})"
        )
