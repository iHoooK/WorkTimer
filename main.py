"""Windows desktop entry point. Data, logs and process lifetime are explicit."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="WorkTimer — локальный таймер")
    parser.add_argument("--data-dir", help="Отдельный каталог данных")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--no-hotkeys", action="store_true")
    parser.add_argument("--exit-after", type=float, default=0, help="Завершить после N секунд (проверка запуска)")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Порт должен быть от 1 до 65535")
    if args.data_dir:
        os.environ["WORKTIMER_DATA_DIR"] = str(Path(args.data_dir).resolve())
    from infrastructure.app_paths import ensure_app_data_dir, get_database_path, get_journal_path, get_settings_path
    from infrastructure.instance import InstanceLock

    directory = Path(ensure_app_data_dir())
    lock = InstanceLock(str(directory), args.port)
    if not lock.acquire():
        port = lock.existing_port()
        lock.close()
        if not args.no_browser:
            webbrowser.open(f"http://127.0.0.1:{port}/", new=0)
        return 0
    logpath = directory / "worktimer.log"
    handlers = [RotatingFileHandler(logpath, maxBytes=2_000_000, backupCount=3, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO, handlers=handlers, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", force=True
    )
    logger = logging.getLogger(__name__)
    timer = controller = server = bridge = None
    exit_timer = None
    stopped = threading.Event()
    try:
        from app.desktop import DesktopBridge
        from app.services import ScenarioController
        from app.storage import SQLiteDatabase
        from app.web import LocalWebServer, create_web_app
        from core.events import EventBus
        from core.timer import TimerEngine
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
        controller = ScenarioController(database, timer, bus)
        server = LocalWebServer(create_web_app(database, controller.to_dict, controller, stopped.set), port=args.port)
        server.start()
        bridge = DesktopBridge(
            bus=bus,
            controller=controller,
            tray=TrayManager(),
            hotkeys=HotkeyManager(),
            sound=SoundService(strategy=WinsoundStrategy(), enabled=True),
            notifications=NotificationService(app_name="WorkTimer"),
            database=database,
            dashboard_url=server.url,
            on_quit=stopped.set,
        )
        bridge.start(enable_tray=not args.no_tray, enable_hotkeys=not args.no_hotkeys)
        logger.info("WorkTimer ready: %s; data: %s", server.url, directory)
        if not args.no_browser:
            webbrowser.open(server.url, new=0)
        if args.exit_after > 0:
            exit_timer = threading.Timer(args.exit_after, stopped.set)
            exit_timer.daemon = True
            exit_timer.start()
        stopped.wait()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as error:
        logger.exception("WorkTimer не запущен")
        if sys.stderr is None and os.name == "nt" and not args.no_browser:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, f"Не удалось запустить WorkTimer.\n{error}\n\nЖурнал: {logpath}", "WorkTimer", 0x10
            )
        return 1
    finally:
        if exit_timer:
            exit_timer.cancel()
        if bridge:
            bridge.stop()
        if server:
            server.stop()
        if controller:
            controller.suspend_for_exit()
        if timer:
            timer.close()
        lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
