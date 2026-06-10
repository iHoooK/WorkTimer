"""
main.py — Точка входа приложения (Composition Root).

Здесь и только здесь собирается весь граф зависимостей (DI).
Никакой бизнес-логики — только создание объектов и запуск.

Старый монолитный main.py заменён. Вся логика перенесена в слои:
  core/         — бизнес-логика
  infrastructure/ — файлы, звук, трей, хоткеи
  ui/           — интерфейс
"""

import logging
import os
import sys

# ---------------------------------------------------------------------------
# Логирование — настраиваем первым делом
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Composition Root
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("WorkTimer — запуск")

    from infrastructure.app_paths import (
        get_legacy_project_settings_path,
        get_journal_path,
        get_settings_path,
    )
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_file = get_settings_path()
    legacy_project_file = get_legacy_project_settings_path(base_dir)
    legacy_home_file = os.path.join(os.path.expanduser("~"), ".focus_timer_config.json")

    # 1. Хранилище (один файл, разделяется между репозиториями)
    from infrastructure.storage import JsonFileStorage
    storage = JsonFileStorage(data_file)

    if not os.path.exists(data_file):
        import json

        source_path = None
        for candidate in (legacy_project_file, legacy_home_file):
            if os.path.exists(candidate):
                source_path = candidate
                break
        if source_path:
            try:
                with open(source_path, encoding="utf-8") as f:
                    storage.save(json.load(f))
                logger.info("main: мигрированы данные → %s", data_file)
            except Exception as e:
                logger.warning("main: не удалось мигрировать данные из %s: %s", source_path, e)

    # 2. Репозитории core-слоя
    from core.profiles import ProfileRepository
    from core.journal import JournalRepository
    from core.settings import SettingsRepository
    profiles_repo = ProfileRepository(storage)
    settings_repo = SettingsRepository(storage)
    journal_repo = JournalRepository(JsonFileStorage(get_journal_path()))
    profiles_repo.load()
    settings_repo.load()

    # 3. EventBus + TimerEngine
    from core.events import EventBus
    from core.timer  import TimerEngine
    bus   = EventBus()
    timer = TimerEngine(bus=bus)

    # 4. Инфраструктура
    from infrastructure.sound         import SoundService, WinsoundStrategy
    from infrastructure.notifications import NotificationService
    from infrastructure.tray          import TrayManager
    from infrastructure.hotkeys       import HotkeyManager

    sound         = SoundService(strategy=WinsoundStrategy(), enabled=True)
    notifications = NotificationService(app_name="WorkTimer")
    tray          = TrayManager()
    hotkeys       = HotkeyManager()

    # Синхронизировать sound.enabled с настройками
    settings = settings_repo.get()
    sound.enabled = settings.sound_enabled
    from ui.theme import set_theme_mode
    set_theme_mode(settings.theme_mode)

    # 5. OBS-сервер (запускаем до AppController, чтобы порт был занят)
    from infrastructure.obs_server import OBSServer
    obs = OBSServer(port=8765)
    obs_ok = obs.start()
    if obs_ok:
        logger.info("main: OBS Browser Source → %s", obs.url)
    else:
        logger.warning("main: OBS-сервер не запущен (порт 8765 занят?)")
        obs = None

    # 6. AppController (Facade + DI)
    from ui.app import AppController
    controller = AppController(
        bus=bus,
        timer=timer,
        profiles=profiles_repo,
        settings=settings_repo,
        sound=sound,
        notifications=notifications,
        tray=tray,
        hotkeys=hotkeys,
        obs=obs,
        journal=journal_repo,
    )

    # 7. Главное окно
    from ui.main_window import MainWindow
    window = MainWindow(controller=controller)

    # 8. Замыкаем DI-граф (window → controller)
    controller.set_window(window)
    controller.on_startup()

    # 9. Запуск event loop
    logger.info("main: запуск mainloop")
    window.mainloop()
    logger.info("main: завершение")



if __name__ == "__main__":
    main()
