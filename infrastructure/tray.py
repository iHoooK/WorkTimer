"""
infrastructure/tray.py — Иконка в системном трее.

TrayManager принимает коллбэки, а не ссылку на окно.
Вся pystray-логика инкапсулирована здесь — AppController не знает о pystray.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

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
        self._icon = None
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
        on_show: Callable,
        on_start_pause: Callable,
        on_stop: Callable,
        on_quit: Callable,
        on_next: Callable | None = None,
        on_restart: Callable | None = None,
        on_about: Callable | None = None,
        on_help: Callable | None = None,
    ) -> None:
        """
        Создать иконку и запустить её в daemon-потоке.

        Безопасно вызывать даже если pystray недоступен.
        """
        if not _PYSTRAY_OK:
            return
        try:
            img = self._make_icon_image()
            menu_items = [
                pystray.MenuItem("Открыть панель", lambda i, it: on_show(), default=True),
                pystray.MenuItem("Старт / Пауза", lambda i, it: on_start_pause()),
            ]
            if on_next is not None:
                menu_items.append(pystray.MenuItem("Следующая фаза", lambda i, it: on_next()))
            if on_restart is not None:
                menu_items.append(pystray.MenuItem("Начать сначала", lambda i, it: on_restart()))
            if on_about is not None:
                menu_items.append(pystray.MenuItem("О программе", lambda i, it: on_about()))
            if on_help is not None:
                menu_items.append(pystray.MenuItem("Руководство", lambda i, it: on_help()))
            menu_items.extend(
                [
                    pystray.MenuItem("Стоп", lambda i, it: on_stop()),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Выход", lambda i, it: on_quit()),
                ]
            )
            menu = pystray.Menu(*menu_items)
            self._icon = pystray.Icon("worktimer", img, "WorkTimer", menu)
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
                logger.exception("TrayManager: ошибка завершения")
            self._icon = None
            logger.info("TrayManager: остановлен")

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    @staticmethod
    def _make_icon_image():
        """WorkTimer clock icon, shared with the packaged application."""
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill="#22c7ff")
        d.ellipse([10, 10, 54, 54], fill="#07111c")
        d.line([(32, 17), (32, 32), (43, 39)], fill="#eaf2f8", width=5)
        return img

    def __repr__(self) -> str:
        return f"TrayManager(available={self._available})"
