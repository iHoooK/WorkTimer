"""Точка входа WorkTimer: локальный сервис, web-панель и Windows tray."""

from __future__ import annotations

import logging
import threading
import webbrowser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    from app.desktop import DesktopBridge
    from app.services import ScenarioController
    from app.storage import SQLiteDatabase
    from app.web import LocalWebServer, create_web_app
    from core.events import EventBus
    from core.timer import TimerEngine
    from infrastructure.app_paths import get_database_path, get_journal_path, get_settings_path
    from infrastructure.hotkeys import HotkeyManager
    from infrastructure.notifications import NotificationService
    from infrastructure.sound import SoundService, WinsoundStrategy
    from infrastructure.tray import TrayManager

    database = SQLiteDatabase(get_database_path())
    database.migrate()
    database.import_legacy_json(get_settings_path())
    database.import_legacy_journal(get_journal_path())

    bus = EventBus()
    timer = TimerEngine(bus)
    scenarios = ScenarioController(database, timer, bus)
    web_server = LocalWebServer(create_web_app(database, scenarios.to_dict, scenarios), port=8765)
    web_server.start()

    stopped = threading.Event()
    tray = TrayManager()
    bridge = DesktopBridge(
        bus=bus,
        controller=scenarios,
        tray=tray,
        hotkeys=HotkeyManager(),
        sound=SoundService(strategy=WinsoundStrategy(), enabled=True),
        notifications=NotificationService(app_name="WorkTimer"),
        database=database,
        dashboard_url=web_server.url,
        on_quit=stopped.set,
    )
    bridge.start()
    logger.info("WorkTimer ready: %s", web_server.url)
    webbrowser.open(web_server.url, new=0)
    try:
        stopped.wait()
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()
        timer.stop()
        web_server.stop()


if __name__ == "__main__":
    main()
