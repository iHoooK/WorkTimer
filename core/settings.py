"""
core/settings.py — Настройки приложения (не профили таймера).

AppSettings    — dataclass с флагами уровня приложения.
SettingsRepository — загружает/сохраняет через IStorage.

SOLID:
  S — Settings хранит только app-level настройки; Profile хранит таймерные.
  D — Repository зависит от IStorage, а не от файловой системы.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.storage import IStorage

logger = logging.getLogger(__name__)


# ===========================================================================
# Шаг 4.1 — AppSettings
# ===========================================================================

@dataclass
class AppSettings:
    """
    Настройки приложения, не связанные с профилями таймера.

    Поля:
        dnd           — Do Not Disturb: подавлять уведомления
        always_on_top — окно всегда поверх остальных
        sound_enabled — воспроизводить звук при окончании таймера
        auto_switch   — автоматически переключать работа→отдых без диалога
    """
    dnd: bool           = False
    always_on_top: bool = False
    sound_enabled: bool = True
    auto_switch: bool   = False

    def to_dict(self) -> dict:
        """Сериализовать в словарь для JSON-хранилища."""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "AppSettings":
        """
        Восстановить из словаря. Неизвестные ключи игнорируются.
        Поддерживает backward compat: старый конфиг имеет "dnd" на верхнем уровне.
        """
        return AppSettings(
            dnd           = bool(data.get("dnd",           False)),
            always_on_top = bool(data.get("always_on_top", False)),
            sound_enabled = bool(data.get("sound_enabled", True)),
            auto_switch   = bool(data.get("auto_switch",   False)),
        )


# ===========================================================================
# Шаг 4.2 — SettingsRepository
# ===========================================================================

class SettingsRepository:
    """
    Загружает и сохраняет AppSettings через IStorage.

    Хранит настройки под ключом "settings" в JSON-документе.
    Может разделять один файл с ProfileRepository (разные ключи).

    Backward compat: если ключа "settings" нет, но есть "dnd" на верхнем
    уровне (старый формат main.py), читает его оттуда.

    Пример:
        repo = SettingsRepository(storage)
        repo.load()
        settings = repo.get()         # AppSettings(dnd=False, ...)
        settings.dnd = True
        repo.save(settings)
    """

    _KEY = "settings"

    def __init__(self, storage: "IStorage") -> None:
        self._storage  = storage
        self._settings = AppSettings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Загрузить настройки из хранилища.

        При ошибке или отсутствии данных — применяются defaults.
        """
        try:
            data: dict = self._storage.load()
        except Exception:
            logger.warning(
                "SettingsRepository: не удалось загрузить, используются defaults"
            )
            data = {}

        raw: dict = data.get(self._KEY, {})

        # Backward compat: старый .focus_timer_config.json хранил "dnd" в корне
        if not raw and "dnd" in data:
            raw = {"dnd": data["dnd"]}

        self._settings = AppSettings.from_dict(raw)
        logger.info("SettingsRepository: загружены настройки → %s", self._settings)

    def get(self) -> AppSettings:
        """Вернуть текущие настройки (in-memory копия)."""
        return self._settings

    def save(self, settings: AppSettings) -> None:
        """
        Сохранить настройки в хранилище.

        Читает текущий документ из storage, обновляет только ключ "settings",
        пишет обратно. Таким образом не затрагиваются данные ProfileRepository.
        """
        self._settings = settings
        try:
            data: dict = self._storage.load()
        except Exception:
            data = {}

        data[self._KEY] = settings.to_dict()

        try:
            self._storage.save(data)
            logger.info("SettingsRepository: настройки сохранены")
        except Exception:
            logger.exception("SettingsRepository: ошибка при сохранении")

    def __repr__(self) -> str:
        return f"SettingsRepository(settings={self._settings})"
