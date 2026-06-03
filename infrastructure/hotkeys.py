"""
infrastructure/hotkeys.py — Глобальные горячие клавиши.

HotkeyManager принимает словарь {hotkey_str: Callable},
регистрирует их через keyboard-библиотеку, умеет очищать.
Вся keyboard-логика изолирована здесь.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

try:
    import keyboard as _keyboard
    _KEYBOARD_OK = True
except ImportError:
    _KEYBOARD_OK = False
    logger.info("HotkeyManager: keyboard недоступен, горячие клавиши отключены")


class HotkeyManager:
    """
    Регистрирует и очищает глобальные горячие клавиши.

    Принимает словарь {строка_хоткея: callable}.
    Безопасно работает если keyboard не установлен.

    Пример:
        hk = HotkeyManager()
        hk.register({
            "ctrl+alt+space": controller.toggle_timer,
            "ctrl+alt+s":     controller.stop_timer,
        })
        # При закрытии:
        hk.cleanup()
    """

    def __init__(self) -> None:
        self._registered: list[str] = []   # список зарегистрированных хоткеев

    @property
    def available(self) -> bool:
        return _KEYBOARD_OK

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, hotkeys: dict[str, Callable]) -> None:
        """
        Зарегистрировать горячие клавиши.

        Args:
            hotkeys: {строка_хоткея: callable}, например
                     {"ctrl+alt+space": lambda: engine.toggle()}

        Ключи с ошибками регистрации пропускаются (WARNING в лог).
        """
        if not _KEYBOARD_OK:
            return

        for key, callback in hotkeys.items():
            try:
                _keyboard.add_hotkey(key, callback)
                self._registered.append(key)
                logger.debug("HotkeyManager: зарегистрирован '%s'", key)
            except Exception as e:
                logger.warning("HotkeyManager: не удалось зарегистрировать '%s': %s", key, e)

        logger.info(
            "HotkeyManager: зарегистрировано %d / %d хоткеев",
            len(self._registered), len(hotkeys),
        )

    def cleanup(self) -> None:
        """
        Отменить все зарегистрированные горячие клавиши.

        Вызывать при завершении приложения.
        """
        if not _KEYBOARD_OK:
            return

        for key in self._registered:
            try:
                _keyboard.remove_hotkey(key)
                logger.debug("HotkeyManager: снят '%s'", key)
            except Exception as e:
                logger.debug("HotkeyManager: не удалось снять '%s': %s", key, e)

        self._registered.clear()
        logger.info("HotkeyManager: все хоткеи сняты")

    def __repr__(self) -> str:
        return f"HotkeyManager(registered={self._registered})"
