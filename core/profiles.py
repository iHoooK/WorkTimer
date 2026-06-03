"""
core/profiles.py — Профили таймера (Value Object + Repository).

Профиль — иммутабельный объект с валидацией.
ProfileRepository управляет коллекцией профилей и делегирует
хранение абстракции IStorage (внедряется через DI).

SOLID:
  S — Profile только хранит данные и валидирует себя.
      ProfileRepository только управляет коллекцией.
  O — Добавить поле в Profile не ломает Repository.
  D — Repository зависит от абстракции IStorage, не от файловой системы.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.storage import IStorage

logger = logging.getLogger(__name__)


# ===========================================================================
# Шаг 3.1 — Profile (Value Object)
# ===========================================================================

# Ограничения на длительности (минуты)
_WORK_MIN,  _WORK_MAX  = 1, 240
_BREAK_MIN, _BREAK_MAX = 1, 60
_NAME_MAX_LEN = 32


@dataclass(frozen=True)
class Profile:
    """
    Иммутабельный профиль таймера.

    frozen=True гарантирует, что профиль нельзя изменить после создания —
    любые изменения должны идти через ProfileRepository.save().

    Поля:
        name        — уникальное имя профиля (например, «Работа»)
        work_minutes — длительность рабочего интервала в минутах
        break_minutes — длительность перерыва в минутах

    Пример:
        p = Profile(name="Работа", work_minutes=60, break_minutes=10)
        p.validate()           # бросает ValueError если данные некорректны
        p.work_seconds         # → 3600
    """
    name: str
    work_minutes: int
    break_minutes: int

    # ------------------------------------------------------------------
    # Вычисляемые свойства (из frozen dataclass — только через property)
    # ------------------------------------------------------------------

    @property
    def work_seconds(self) -> int:
        """Длительность работы в секундах."""
        return self.work_minutes * 60

    @property
    def break_seconds(self) -> int:
        """Длительность перерыва в секундах."""
        return self.break_minutes * 60

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Проверить корректность данных профиля.

        Raises:
            ValueError: если любое из полей не прошло проверку.
        """
        name = self.name.strip()
        if not name:
            raise ValueError("Имя профиля не может быть пустым")
        if len(name) > _NAME_MAX_LEN:
            raise ValueError(
                f"Имя профиля слишком длинное (макс. {_NAME_MAX_LEN} символов)"
            )

        if not (_WORK_MIN <= self.work_minutes <= _WORK_MAX):
            raise ValueError(
                f"Рабочее время должно быть от {_WORK_MIN} до {_WORK_MAX} мин, "
                f"получено: {self.work_minutes}"
            )

        if not (_BREAK_MIN <= self.break_minutes <= _BREAK_MAX):
            raise ValueError(
                f"Перерыв должен быть от {_BREAK_MIN} до {_BREAK_MAX} мин, "
                f"получено: {self.break_minutes}"
            )

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Сериализовать в словарь для JSON-хранилища."""
        return {
            "work":  self.work_minutes,
            "rest":  self.break_minutes,
        }

    @staticmethod
    def from_dict(name: str, data: dict) -> "Profile":
        """
        Восстановить Profile из словаря (формат старого JSON-конфига).

        Args:
            name: имя профиля (ключ в словаре profiles).
            data: {"work": int, "rest": int}

        Raises:
            KeyError:   если в data нет обязательных ключей.
            ValueError: если данные не прошли validate().
        """
        profile = Profile(
            name=name,
            work_minutes=int(data["work"]),
            break_minutes=int(data["rest"]),
        )
        profile.validate()
        return profile

    def __repr__(self) -> str:
        return (
            f"Profile({self.name!r}, "
            f"work={self.work_minutes}m, "
            f"break={self.break_minutes}m)"
        )


# ===========================================================================
# Значения по умолчанию (совместимость со старым DEFAULT_CONFIG)
# ===========================================================================

DEFAULT_PROFILES: list[Profile] = [
    Profile(name="Работа", work_minutes=60, break_minutes=10),
    Profile(name="Учёба",  work_minutes=50, break_minutes=10),
    Profile(name="Спорт",  work_minutes=45, break_minutes=15),
]

DEFAULT_ACTIVE_PROFILE = "Работа"


# ===========================================================================
# Шаг 3.2 — ProfileRepository
# ===========================================================================

class ProfileRepository:
    """
    Управляет коллекцией профилей и сохраняет их через IStorage.

    Работает как in-memory кэш поверх персистентного хранилища:
    при старте загружает данные, все мутации сразу записывает в storage.

    Не знает ничего о файловой системе — только об IStorage.

    Пример:
        storage = JsonFileStorage(path)
        repo = ProfileRepository(storage)
        repo.load()

        profiles = repo.get_all()          # [Profile(...), ...]
        active   = repo.get_active()       # Profile(...)
        repo.set_active("Учёба")
        repo.save(Profile("Спринт", 25, 5))
        repo.delete("Спринт")
    """

    # Ключи в JSON-документе хранилища
    _KEY_PROFILES = "profiles"
    _KEY_ACTIVE   = "active_profile"

    def __init__(self, storage: "IStorage") -> None:
        self._storage = storage
        # Упорядоченный список профилей (порядок важен для UI)
        self._profiles: list[Profile] = []
        self._active_name: str = DEFAULT_ACTIVE_PROFILE

    # ------------------------------------------------------------------
    # Загрузка / инициализация
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Загрузить профили из хранилища.

        Если данных нет или они повреждены — применяются значения по умолчанию.
        Вызывать один раз при старте приложения.
        """
        try:
            data: dict = self._storage.load()
        except Exception:
            logger.warning(
                "ProfileRepository: не удалось загрузить данные, "
                "используются значения по умолчанию"
            )
            data = {}

        raw_profiles: dict = data.get(self._KEY_PROFILES, {})
        loaded: list[Profile] = []

        for name, pdata in raw_profiles.items():
            try:
                loaded.append(Profile.from_dict(name, pdata))
            except (KeyError, ValueError) as e:
                logger.warning(
                    "ProfileRepository: пропущен профиль %r — %s", name, e
                )

        if not loaded:
            logger.info("ProfileRepository: загружены профили по умолчанию")
            loaded = list(DEFAULT_PROFILES)

        self._profiles = loaded
        self._active_name = data.get(self._KEY_ACTIVE, DEFAULT_ACTIVE_PROFILE)

        # Защита: если active_name не существует — берём первый
        if not self._find(self._active_name):
            self._active_name = self._profiles[0].name
            logger.warning(
                "ProfileRepository: активный профиль не найден, "
                "выбран %r", self._active_name
            )

        logger.info(
            "ProfileRepository: загружено %d профилей, активный: %r",
            len(self._profiles), self._active_name
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_all(self) -> list[Profile]:
        """Вернуть список всех профилей (копию, чтобы нельзя было мутировать)."""
        return list(self._profiles)

    def get_active(self) -> Profile:
        """
        Вернуть активный профиль.

        Raises:
            RuntimeError: если профили не загружены (не вызван load()).
        """
        profile = self._find(self._active_name)
        if profile is None:
            raise RuntimeError(
                f"Активный профиль {self._active_name!r} не найден. "
                "Вызовите load() перед использованием репозитория."
            )
        return profile

    def set_active(self, name: str) -> None:
        """
        Установить активный профиль по имени.

        Args:
            name: имя существующего профиля.

        Raises:
            KeyError: если профиль с таким именем не существует.
        """
        if not self._find(name):
            raise KeyError(f"Профиль {name!r} не найден")
        self._active_name = name
        self._persist()
        logger.info("ProfileRepository: активный профиль → %r", name)

    def save(self, profile: Profile) -> None:
        """
        Создать или обновить профиль.

        Если профиль с таким именем уже есть — перезаписывает.
        Иначе добавляет в конец списка.

        Args:
            profile: валидированный Profile (вызовите profile.validate() перед сохранением).

        Raises:
            ValueError: если profile не прошёл валидацию.
        """
        profile.validate()

        idx = self._index(profile.name)
        if idx is not None:
            self._profiles[idx] = profile
            logger.info("ProfileRepository: обновлён профиль %r", profile.name)
        else:
            self._profiles.append(profile)
            logger.info("ProfileRepository: добавлен профиль %r", profile.name)

        self._persist()

    def delete(self, name: str) -> None:
        """
        Удалить профиль по имени.

        Если удаляется активный профиль — активным становится первый в списке.

        Args:
            name: имя профиля для удаления.

        Raises:
            KeyError:    если профиль не найден.
            RuntimeError: если это последний профиль (нельзя удалить).
        """
        if len(self._profiles) <= 1:
            raise RuntimeError("Нельзя удалить последний профиль")

        idx = self._index(name)
        if idx is None:
            raise KeyError(f"Профиль {name!r} не найден")

        self._profiles.pop(idx)
        logger.info("ProfileRepository: удалён профиль %r", name)

        if self._active_name == name:
            self._active_name = self._profiles[0].name
            logger.info(
                "ProfileRepository: активный профиль сброшен на %r",
                self._active_name
            )

        self._persist()

    # ------------------------------------------------------------------
    # Приватные методы
    # ------------------------------------------------------------------

    def _find(self, name: str) -> Profile | None:
        """Найти профиль по имени, вернуть None если не найден."""
        return next((p for p in self._profiles if p.name == name), None)

    def _index(self, name: str) -> int | None:
        """Найти индекс профиля в списке, вернуть None если не найден."""
        for i, p in enumerate(self._profiles):
            if p.name == name:
                return i
        return None

    def _persist(self) -> None:
        """Сохранить текущее состояние в хранилище."""
        data = {
            self._KEY_PROFILES: {
                p.name: p.to_dict() for p in self._profiles
            },
            self._KEY_ACTIVE: self._active_name,
        }
        try:
            self._storage.save(data)
        except Exception:
            logger.exception("ProfileRepository: ошибка при сохранении данных")

    def __repr__(self) -> str:
        return (
            f"ProfileRepository("
            f"profiles={[p.name for p in self._profiles]}, "
            f"active={self._active_name!r})"
        )
