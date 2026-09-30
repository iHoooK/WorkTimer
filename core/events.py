"""
core/events.py — Типизированная шина событий.

Никаких внешних зависимостей. Любой слой может подписаться на событие
и получать типизированные данные без прямых ссылок на источник.

Паттерн: Observer / Event-Driven (часть архитектуры SOLID — DIP).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass(frozen=True)
class Event(Generic[T]):
    """
    Иммутабельный контейнер события.

    Пример использования:
        tick_event = Event(name="timer.tick", data=TimerState(...))
    """

    name: str  # Уникальное имя события, например "timer.tick"
    data: T  # Полезная нагрузка — типизированные данные


# Тип подписчика: принимает Event[T], ничего не возвращает
Handler = Callable[[Event], None]


class EventBus:
    """
    Шина событий приложения.

    Позволяет компонентам общаться не зная друг о друге.
    Один экземпляр создаётся в main.py и передаётся через DI.

    Пример:
        bus = EventBus()

        # Подписка
        bus.subscribe("timer.tick", lambda e: print(e.data))

        # Публикация
        bus.publish(Event(name="timer.tick", data=state))
    """

    def __init__(self) -> None:
        # defaultdict: при первом обращении к ключу создаётся пустой список
        self._handlers: defaultdict[str, list[Handler]] = defaultdict(list)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def subscribe(self, event_name: str, handler: Handler) -> None:
        """Подписать обработчик на событие по имени."""
        self._handlers[event_name].append(handler)
        logger.debug("EventBus: подписка на '%s' → %s", event_name, handler)

    def unsubscribe(self, event_name: str, handler: Handler) -> None:
        """Отписать обработчик. Безопасно если его нет в списке."""
        handlers = self._handlers.get(event_name, [])
        try:
            handlers.remove(handler)
            logger.debug("EventBus: отписка от '%s' → %s", event_name, handler)
        except ValueError:
            logger.warning(
                "EventBus: попытка отписать незарегистрированный обработчик '%s'",
                event_name,
            )

    def publish(self, event: Event) -> None:
        """
        Опубликовать событие — вызвать всех подписчиков синхронно.

        Ошибка в одном обработчике не ломает остальных (изолируется через try/except).
        """
        handlers = list(self._handlers.get(event.name, []))
        logger.debug("EventBus: публикация '%s' → %d обработчиков", event.name, len(handlers))
        for handler in handlers:
            try:
                handler(event)
            except Exception:  # noqa: BLE001
                logger.exception("EventBus: ошибка в обработчике '%s' (%s)", event.name, handler)

    def clear(self) -> None:
        """Удалить все подписки. Используется при завершении приложения."""
        self._handlers.clear()
        logger.debug("EventBus: все подписки очищены")

    # ------------------------------------------------------------------
    # Introspection (для отладки)
    # ------------------------------------------------------------------

    def subscriber_count(self, event_name: str) -> int:
        """Вернуть количество подписчиков на событие."""
        return len(self._handlers.get(event_name, []))

    def __repr__(self) -> str:
        total = sum(len(h) for h in self._handlers.values())
        return f"EventBus(events={len(self._handlers)}, total_handlers={total})"
