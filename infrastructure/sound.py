"""
infrastructure/sound.py — Звуковые стратегии и сервис воспроизведения.

Паттерн Strategy: ISoundStrategy — абстракция, WinsoundStrategy — реализация.
SoundService играет звук в daemon-потоке, не блокируя UI.

SOLID:
  O — Добавить WavFileStrategy не меняя SoundService.
  L — Любая ISoundStrategy взаимозаменяема.
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ===========================================================================
# Шаг 6.1 — ISoundStrategy (ABC) + WinsoundStrategy + SilentStrategy
# ===========================================================================


class ISoundStrategy(ABC):
    """Абстракция звуковой стратегии (Liskov: все подклассы взаимозаменяемы)."""

    @abstractmethod
    def play_work_end(self) -> None:
        """Звуковой сигнал окончания рабочего времени."""
        ...

    @abstractmethod
    def play_break_end(self) -> None:
        """Звуковой сигнал окончания перерыва."""
        ...


class WinsoundStrategy(ISoundStrategy):
    """
    Стратегия через встроенный winsound (только Windows, нет доп. зависимостей).

    work_end: 3 высоких коротких сигнала (880 Гц)
    break_end: 2 низких длинных сигнала (523 Гц)
    """

    def play_work_end(self) -> None:
        try:
            import winsound

            for _ in range(3):
                winsound.Beep(880, 200)
                time.sleep(0.1)
        except Exception as e:
            logger.warning("WinsoundStrategy.play_work_end: %s", e)

    def play_break_end(self) -> None:
        try:
            import winsound

            for _ in range(2):
                winsound.Beep(523, 300)
                time.sleep(0.15)
        except Exception as e:
            logger.warning("WinsoundStrategy.play_break_end: %s", e)


class SilentStrategy(ISoundStrategy):
    """Заглушка — не воспроизводит ничего. Используется если звук отключён."""

    def play_work_end(self) -> None:
        pass

    def play_break_end(self) -> None:
        pass


# ===========================================================================
# Шаг 6.2 — SoundService
# ===========================================================================


class SoundService:
    """
    Сервис воспроизведения звука.

    Запускает воспроизведение в daemon-потоке, не блокируя UI.
    Поддерживает включение/выключение и смену стратегии в runtime.

    Пример:
        service = SoundService(WinsoundStrategy())
        service.play_work_end()          # воспроизводит асинхронно
        service.enabled = False          # отключить без смены стратегии
        service.set_strategy(SilentStrategy())  # или сменить стратегию
    """

    def __init__(self, strategy: ISoundStrategy, enabled: bool = True) -> None:
        self._strategy = strategy
        self.enabled = enabled

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def play_work_end(self) -> None:
        """Воспроизвести сигнал окончания работы (асинхронно)."""
        if self.enabled:
            self._play_async(self._strategy.play_work_end)

    def play_break_end(self) -> None:
        """Воспроизвести сигнал окончания перерыва (асинхронно)."""
        if self.enabled:
            self._play_async(self._strategy.play_break_end)

    def set_strategy(self, strategy: ISoundStrategy) -> None:
        """Заменить стратегию на лету (OCP: не меняем SoundService)."""
        self._strategy = strategy
        logger.info("SoundService: стратегия → %s", strategy.__class__.__name__)

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def _play_async(self, func) -> None:
        t = threading.Thread(target=self._safe_call, args=(func,), daemon=True, name="SoundThread")
        t.start()

    @staticmethod
    def _safe_call(func) -> None:
        try:
            func()
        except Exception:
            logger.exception("SoundService: ошибка воспроизведения")

    def __repr__(self) -> str:
        return f"SoundService(strategy={self._strategy.__class__.__name__}, enabled={self.enabled})"
