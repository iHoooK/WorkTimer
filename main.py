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
# Путь к файлу данных (рядом с main.py)
# ---------------------------------------------------------------------------
BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
DATA_FILE    = os.path.join(BASE_DIR, "data", "settings.json")

# Backward-compat: если есть старый конфиг — мигрируем данные
_OLD_CONFIG  = os.path.join(os.path.expanduser("~"), ".focus_timer_config.json")


def _migrate_old_config(storage) -> None:
    """Если новый файл данных пустой, но есть старый — импортируем данные."""
    import json
    if os.path.exists(DATA_FILE) or not os.path.exists(_OLD_CONFIG):
        return
    try:
        with open(_OLD_CONFIG, encoding="utf-8") as f:
            old = json.load(f)
        storage.save(old)
        logger.info("main: мигрированы данные из старого конфига → %s", DATA_FILE)
    except Exception as e:
        logger.warning("main: не удалось мигрировать старый конфиг: %s", e)


# ---------------------------------------------------------------------------
# Composition Root
# ---------------------------------------------------------------------------

def main() -> None:
    logger.info("Focus Timer — запуск")

    # 1. Хранилище (один файл, разделяется между репозиториями)
    from infrastructure.storage import JsonFileStorage
    storage = JsonFileStorage(DATA_FILE)
    _migrate_old_config(storage)

    # 2. Репозитории core-слоя
    from core.profiles import ProfileRepository
    from core.settings import SettingsRepository
    profiles_repo = ProfileRepository(storage)
    settings_repo = SettingsRepository(storage)
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
    notifications = NotificationService(app_name="Focus Timer")
    tray          = TrayManager()
    hotkeys       = HotkeyManager()

    # Синхронизировать sound.enabled с настройками
    settings = settings_repo.get()
    sound.enabled = settings.sound_enabled

    # 5. AppController (Facade + DI)
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
    )

    # 6. Главное окно
    from ui.main_window import MainWindow
    window = MainWindow(controller=controller)

    # 7. Замыкаем DI-граф (window → controller)
    controller.set_window(window)
    controller.on_startup()

    # 8. Запуск event loop
    logger.info("main: запуск mainloop")
    window.mainloop()
    logger.info("main: завершение")


if __name__ == "__main__":
    main()
