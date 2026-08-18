"""Трей, hotkeys, звук и уведомления для нового контроллера сценариев."""

from __future__ import annotations

import webbrowser
import threading
from collections.abc import Callable

from app.services import ScenarioController
from app.storage import SQLiteDatabase
from core.events import Event, EventBus
from core.timer import EVENT_FINISHED, EVENT_TICK, TimerState
from infrastructure.hotkeys import HotkeyManager
from infrastructure.notifications import NotificationService
from infrastructure.sound import SoundService
from infrastructure.tray import TrayManager


class DesktopBridge:
    """Связывает Windows-интеграции с единственным источником состояния."""

    def __init__(
        self,
        *,
        bus: EventBus,
        controller: ScenarioController,
        tray: TrayManager,
        hotkeys: HotkeyManager,
        sound: SoundService,
        notifications: NotificationService,
        database: SQLiteDatabase,
        dashboard_url: str,
        on_quit: Callable[[], None],
    ) -> None:
        self._controller = controller
        self._tray = tray
        self._hotkeys = hotkeys
        self._sound = sound
        self._notifications = notifications
        self._database = database
        self._dashboard_url = dashboard_url
        self._on_quit = on_quit
        self._warning_marker: tuple[str, int] | None = None
        bus.subscribe(EVENT_TICK, self._on_tick)
        bus.subscribe(EVENT_FINISHED, self._on_finished)

    def start(self) -> None:
        self._hotkeys.register({
            "ctrl+alt+space": self._controller.start,
            "ctrl+alt+right": self._controller.next_phase,
            "ctrl+alt+r": self._controller.start_from_beginning,
        })
        self._tray.setup(
            on_show=self.open_dashboard,
            on_start_pause=self._controller.start,
            on_next=self._controller.next_phase,
            on_restart=self._controller.start_from_beginning,
            on_stop=self._controller.stop,
            on_quit=self._on_quit,
        )

    def stop(self) -> None:
        self._hotkeys.cleanup()
        self._tray.stop()

    def open_dashboard(self) -> None:
        webbrowser.open(self._dashboard_url, new=0)

    def _on_tick(self, event: Event[TimerState]) -> None:
        state = event.data
        self._tray.update_tooltip(f"WorkTimer — {state.phase_name} {state.format_time()}")
        preferences = self._database.get_setting("app_preferences", {})
        if not isinstance(preferences, dict):
            return
        warning_seconds = int(preferences.get("warning_seconds", 0) or 0)
        marker = (state.phase_name, state.total_seconds)
        if state.remaining_seconds > warning_seconds:
            self._warning_marker = None
        if warning_seconds and state.remaining_seconds == warning_seconds and self._warning_marker != marker:
            self._warning_marker = marker
            self._notifications.dnd = bool(preferences.get("dnd", False))
            self._notifications.notify("Скоро окончание", f"{state.phase_name}: осталось {warning_seconds} сек.")

    def _on_finished(self, event: Event[TimerState]) -> None:
        state = event.data
        preferences = self._database.get_setting("app_preferences", {})
        if not isinstance(preferences, dict):
            preferences = {}
        self._notifications.dnd = bool(preferences.get("dnd", False))
        if not bool(preferences.get("sound_enabled", True)):
            self._notifications.notify("Фаза завершена", f"{state.phase_name}: выберите следующее действие в WorkTimer.")
            if bool(preferences.get("auto_start_next_phase", False)):
                threading.Timer(0.25, self._controller.next_phase).start()
            return
        if state.phase_role.casefold() == "rest":
            self._sound.play_break_end()
        else:
            self._sound.play_work_end()
        self._notifications.notify(
            "Фаза завершена",
            f"{state.phase_name}: выберите следующее действие в WorkTimer.",
        )
        if bool(preferences.get("auto_start_next_phase", False)):
            threading.Timer(0.25, self._controller.next_phase).start()
