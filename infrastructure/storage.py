"""
infrastructure/storage.py — Абстракция хранилища данных.

IStorage        — абстрактный интерфейс (ABC).
JsonFileStorage — реализация через JSON-файл с атомарной записью (os.replace).

SOLID:
  O — Добавить SQLiteStorage не меняя репозитории.
  I — IStorage содержит только load/save, ничего лишнего.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


# ===========================================================================
# Шаг 5.1 — IStorage (ABC)
# ===========================================================================

class IStorage(ABC):
    """
    Абстракция хранилища: загрузить / сохранить dict.

    Репозитории (ProfileRepository, SettingsRepository) зависят только
    от этого интерфейса — не от файловой системы (DIP).
    """

    @abstractmethod
    def load(self) -> dict:
        """Загрузить данные. Возвращает dict (пустой если данных нет)."""
        ...

    @abstractmethod
    def save(self, data: dict) -> None:
        """Сохранить данные. Raises OSError при ошибке записи."""
        ...


# ===========================================================================
# Шаг 5.2 — JsonFileStorage
# ===========================================================================

class JsonFileStorage(IStorage):
    """
    Хранилище в JSON-файле с атомарной записью через os.replace.

    Атомарность: данные пишутся во временный файл в той же директории,
    затем os.replace() атомарно переименовывает его в целевой.
    Это гарантирует, что файл никогда не окажется в частично
    записанном состоянии (нет риска потерять данные при сбое питания).

    Автоматически создаёт родительские директории при инициализации.

    Пример:
        storage = JsonFileStorage("data/settings.json")
        data = storage.load()           # {} если файла нет
        storage.save({"key": "value"})  # атомарная запись
    """

    def __init__(self, path: str) -> None:
        self._path = path
        # Создаём директорию заранее — save() не должен об этом беспокоиться
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        logger.debug("JsonFileStorage: инициализирован → %s", path)

    # ------------------------------------------------------------------
    # IStorage implementation
    # ------------------------------------------------------------------

    def load(self) -> dict:
        """
        Прочитать JSON-файл и вернуть dict.

        Возвращает {} если файл не существует или повреждён
        (логирует предупреждение во втором случае).
        """
        if not os.path.exists(self._path):
            logger.debug("JsonFileStorage: файл не существует → %s", self._path)
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(
                    "JsonFileStorage: файл %s содержит не dict, возвращаем {}",
                    self._path,
                )
                return {}
            logger.debug("JsonFileStorage: загружено из %s", self._path)
            return data
        except json.JSONDecodeError as e:
            logger.error("JsonFileStorage: JSON повреждён в %s: %s", self._path, e)
            return {}
        except OSError as e:
            logger.error("JsonFileStorage: ошибка чтения %s: %s", self._path, e)
            return {}

    def save(self, data: dict) -> None:
        """
        Атомарно записать dict в JSON-файл.

        Raises:
            OSError: если запись не удалась (директория недоступна и т.п.)
        """
        dir_name = os.path.dirname(os.path.abspath(self._path))
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            # Атомарная замена: на уровне ФС это одна операция
            os.replace(tmp_path, self._path)
            logger.debug("JsonFileStorage: сохранено → %s", self._path)
        except Exception:
            # Убираем временный файл если что-то пошло не так
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            logger.exception("JsonFileStorage: ошибка записи → %s", self._path)
            raise

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def path(self) -> str:
        return self._path

    def __repr__(self) -> str:
        return f"JsonFileStorage(path={self._path!r})"
