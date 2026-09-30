"""
infrastructure/notifications.py — Системные уведомления ОС.

NotificationService: оборачивает plyer с graceful fallback на logging.
Если plyer не установлен — не падает, просто пишет в лог.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Импортируем plyer один раз при загрузке модуля
try:
    from plyer import notification as _plyer_notification

    _PLYER_OK = True
except ImportError:
    _PLYER_OK = False
    logger.info("NotificationService: plyer недоступен — уведомления через лог")


class NotificationService:
    """
    Отправляет системные уведомления.

    Если plyer не установлен — graceful fallback: пишет в logger.info.
    Если dnd=True — уведомления подавляются.

    Пример:
        svc = NotificationService(app_name="Focus Timer")
        svc.notify("⏰ Время работы истекло!", "Пора отдохнуть.")
        svc.dnd = True   # подавить уведомления
    """

    def __init__(self, app_name: str = "Focus Timer") -> None:
        self._app_name = app_name
        self.dnd = False

    def notify(self, title: str, message: str, timeout: int = 8) -> None:
        """
        Отправить системное уведомление.

        Args:
            title:   заголовок.
            message: текст.
            timeout: время отображения в секундах (поддерживается не всеми ОС).
        """
        if self.dnd:
            logger.debug("NotificationService: DND активен, уведомление подавлено")
            return

        if _PLYER_OK:
            try:
                _plyer_notification.notify(
                    title=title,
                    message=message,
                    app_name=self._app_name,
                    timeout=timeout,
                )
                logger.debug("NotificationService: отправлено → %s", title)
                return
            except Exception as e:
                logger.warning("NotificationService: plyer ошибка: %s", e)

        # Fallback: если plyer упал или недоступен
        logger.info("🔔 %s | %s — %s", self._app_name, title, message)

    def __repr__(self) -> str:
        return f"NotificationService(app={self._app_name!r}, dnd={self.dnd})"
