"""
infrastructure/tray.py — Иконка в системном трее.

TrayManager принимает коллбэки, а не ссылку на окно.
Вся pystray-логика инкапсулирована здесь — AppController не знает о pystray.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image, ImageDraw
    _PYSTRAY_OK = True
except ImportError:
    _PYSTRAY_OK = False
    logger.info("TrayManager: pystray/PIL недоступны, трей отключён")


class TrayManager:
    """
    Управляет иконкой в системном трее.

    Принимает коллбэки — не ссылку на окно (DIP).
    Работает даже если pystray не установлен (graceful degradation).

    Пример:
        tray = TrayManager()
        tray.setup(
            on_show=lambda: window.deiconify(),
            on_start_pause=controller.toggle_timer,
            on_stop=controller.stop_timer,
            on_quit=app.quit,
        )
        tray.update_tooltip("Focus Timer — Работа 24:59")
        # При закрытии:
        tray.stop()
    """

    def __init__(self) -> None:
        self._icon     = None
        self._available = _PYSTRAY_OK

    @property
    def available(self) -> bool:
        """True если pystray доступен и иконка создана."""
        return self._available and self._icon is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def setup(
        self,
        on_show:        Callable,
        on_start_pause: Callable,
        on_stop:        Callable,
        on_quit:        Callable,
    ) -> None:
        """
        Создать иконку и запустить её в daemon-потоке.

        Безопасно вызывать даже если pystray недоступен.
        """
        if not _PYSTRAY_OK:
            return
        try:
            img  = self._make_icon_image()
            menu = pystray.Menu(
                pystray.MenuItem("Показать",       lambda i, it: on_show(),        default=True),
                pystray.MenuItem("Старт / Пауза",  lambda i, it: on_start_pause()),
                pystray.MenuItem("Стоп",           lambda i, it: on_stop()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход",          lambda i, it: on_quit()),
            )
            self._icon = pystray.Icon("focus_timer", img, "Focus Timer", menu)
            threading.Thread(
                target=self._icon.run,
                daemon=True,
                name="TrayIcon",
            ).start()
            logger.info("TrayManager: иконка создана")
        except Exception:
            logger.exception("TrayManager: не удалось создать иконку")
            self._available = False

    def update_tooltip(self, text: str) -> None:
        """Обновить всплывающую подсказку иконки трея."""
        if self._icon is None:
            return
        try:
            self._icon.title = text
        except Exception as e:
            logger.debug("TrayManager.update_tooltip: %s", e)

    def stop(self) -> None:
        """Остановить иконку трея (вызывать при закрытии приложения)."""
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
            logger.info("TrayManager: остановлен")

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _make_icon_image():
        """Создать PIL-изображение: оранжевый круг с белым треугольником (play)."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d   = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill="#e05c3a")
        d.polygon([(24, 18), (24, 46), (48, 32)], fill="white")
        return img

    def __repr__(self) -> str:
        return f"TrayManager(available={self._available})"
