"""
core/profiles.py — Профили таймера (Value Object + Repository).

ИЗМЕНЕНИЕ v2: Profile теперь хранит длительности в СЕКУНДАХ (work_seconds, break_seconds).
Это позволяет задавать время с точностью до 1 секунды (например 0 мин 15 сек).

Backward compat: from_dict() распознаёт оба формата:
  - Новый: {"work_seconds": N, "rest_seconds": N}
  - Старый: {"work": N, "rest": N} → значения считаются минутами, умножаются на 60
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.storage import IStorage

logger = logging.getLogger(__name__)


# ===========================================================================
# Ограничения (секунды)
# ===========================================================================

_WORK_MIN_SEC  = 5         # минимум 5 секунд
_WORK_MAX_SEC  = 14_400    # максимум 4 часа
_BREAK_MIN_SEC = 5
_BREAK_MAX_SEC = 3_600     # максимум 1 час
_NAME_MAX_LEN  = 32


# ===========================================================================
# Profile (Value Object)
# ===========================================================================

@dataclass(frozen=True)
class Profile:
    """
    Иммутабельный профиль таймера.

    Поля:
        name          — уникальное имя профиля
        work_seconds  — длительность рабочего интервала в СЕКУНДАХ
        break_seconds — длительность перерыва в СЕКУНДАХ

    Пример:
        p = Profile("Спринт", work_seconds=1500, break_seconds=300)
        p.work_minutes   # → 25
        p.work_extra_sec # → 0
        p.format_work()  # → "25:00"

        # 0 мин 15 сек:
        p2 = Profile("Тест", work_seconds=15, break_seconds=10)
        p2.format_work() # → "00:15"
    """
    name:         str
    work_seconds:  int
    break_seconds: int

    # ------------------------------------------------------------------
    # Удобные свойства для UI
    # ------------------------------------------------------------------

    @property
    def work_minutes(self) -> int:
        """Целые минуты рабочего времени."""
        return self.work_seconds // 60

    @property
    def work_extra_sec(self) -> int:
        """Секунды сверх целых минут (0–59)."""
        return self.work_seconds % 60

    @property
    def break_minutes(self) -> int:
        """Целые минуты перерыва."""
        return self.break_seconds // 60

    @property
    def break_extra_sec(self) -> int:
        """Секунды сверх целых минут (0–59)."""
        return self.break_seconds % 60

    def format_work(self) -> str:
        """Длительность работы в виде MM:SS."""
        m, s = divmod(self.work_seconds, 60)
        return f"{m:02d}:{s:02d}"

    def format_break(self) -> str:
        """Длительность перерыва в виде MM:SS."""
        m, s = divmod(self.break_seconds, 60)
        return f"{m:02d}:{s:02d}"

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self) -> None:
        """
        Raises:
            ValueError: если данные некорректны.
        """
        name = self.name.strip()
        if not name:
            raise ValueError("Имя профиля не может быть пустым")
        if len(name) > _NAME_MAX_LEN:
            raise ValueError(f"Имя профиля слишком длинное (макс. {_NAME_MAX_LEN} символов)")

        if not (_WORK_MIN_SEC <= self.work_seconds <= _WORK_MAX_SEC):
            m_min, s_min = divmod(_WORK_MIN_SEC, 60)
            m_max, s_max = divmod(_WORK_MAX_SEC, 60)
            raise ValueError(
                f"Рабочее время: от {m_min}:{s_min:02d} до {m_max}:{s_max:02d}, "
                f"получено {self.format_work()}"
            )

        if not (_BREAK_MIN_SEC <= self.break_seconds <= _BREAK_MAX_SEC):
            raise ValueError(
                f"Перерыв: от 00:05 до 60:00, "
                f"получено {self.format_break()}"
            )

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Сериализовать в новый формат (секунды)."""
        return {
            "work_seconds": self.work_seconds,
            "rest_seconds": self.break_seconds,
        }

    @staticmethod
    def from_dict(name: str, data: dict) -> "Profile":
        """
        Восстановить из словаря.

        Поддерживает оба формата:
          - Новый: {"work_seconds": N, "rest_seconds": N}
          - Старый: {"work": N, "rest": N}  →  умножает на 60 (были минуты)
        """
        if "work_seconds" in data:
            # Новый формат
            work_sec  = int(data["work_seconds"])
            break_sec = int(data["rest_seconds"])
        elif "work" in data:
            # Старый формат (минуты) → конвертируем в секунды
            work_sec  = int(data["work"]) * 60
            break_sec = int(data["rest"]) * 60
            logger.info("Profile.from_dict: мигрирован профиль %r из формата минут", name)
        else:
            raise KeyError(f"Неизвестный формат данных профиля: {data!r}")

        profile = Profile(name=name, work_seconds=work_sec, break_seconds=break_sec)
        profile.validate()
        return profile

    def __repr__(self) -> str:
        return f"Profile({self.name!r}, work={self.format_work()}, break={self.format_break()})"


# ===========================================================================
# Значения по умолчанию
# ===========================================================================

DEFAULT_PROFILES: list[Profile] = [
    Profile(name="Работа", work_seconds=3600,  break_seconds=600),   # 60:00 / 10:00
    Profile(name="Учёба",  work_seconds=3000,  break_seconds=600),   # 50:00 / 10:00
    Profile(name="Спорт",  work_seconds=2700,  break_seconds=900),   # 45:00 / 15:00
]

DEFAULT_ACTIVE_PROFILE = "Работа"


# ===========================================================================
# ProfileRepository (без изменений логики, только _persist использует новый to_dict)
# ===========================================================================

class ProfileRepository:
    """Управляет коллекцией профилей и сохраняет через IStorage."""

    _KEY_PROFILES = "profiles"
    _KEY_ACTIVE   = "active_profile"

    def __init__(self, storage: "IStorage") -> None:
        self._storage     = storage
        self._profiles:   list[Profile] = []
        self._active_name: str          = DEFAULT_ACTIVE_PROFILE

    def load(self) -> None:
        try:
            data: dict = self._storage.load()
        except Exception:
            logger.warning("ProfileRepository: ошибка загрузки, используются defaults")
            data = {}

        raw_profiles: dict = data.get(self._KEY_PROFILES, {})
        loaded: list[Profile] = []

        for name, pdata in raw_profiles.items():
            try:
                loaded.append(Profile.from_dict(name, pdata))
            except (KeyError, ValueError) as e:
                logger.warning("ProfileRepository: пропущен профиль %r — %s", name, e)

        if not loaded:
            loaded = list(DEFAULT_PROFILES)
            logger.info("ProfileRepository: используются профили по умолчанию")

        self._profiles    = loaded
        self._active_name = data.get(self._KEY_ACTIVE, DEFAULT_ACTIVE_PROFILE)

        if not self._find(self._active_name):
            self._active_name = self._profiles[0].name

        logger.info("ProfileRepository: загружено %d профилей, активный: %r",
                    len(self._profiles), self._active_name)

    def get_all(self) -> list[Profile]:
        return list(self._profiles)

    def get_active(self) -> Profile:
        p = self._find(self._active_name)
        if p is None:
            raise RuntimeError("ProfileRepository: load() не был вызван")
        return p

    def set_active(self, name: str) -> None:
        if not self._find(name):
            raise KeyError(f"Профиль {name!r} не найден")
        self._active_name = name
        self._persist()

    def save(self, profile: Profile) -> None:
        profile.validate()
        idx = self._index(profile.name)
        if idx is not None:
            self._profiles[idx] = profile
        else:
            self._profiles.append(profile)
        self._persist()

    def delete(self, name: str) -> None:
        if len(self._profiles) <= 1:
            raise RuntimeError("Нельзя удалить последний профиль")
        idx = self._index(name)
        if idx is None:
            raise KeyError(f"Профиль {name!r} не найден")
        self._profiles.pop(idx)
        if self._active_name == name:
            self._active_name = self._profiles[0].name
        self._persist()

    def _find(self, name: str) -> Profile | None:
        return next((p for p in self._profiles if p.name == name), None)

    def _index(self, name: str) -> int | None:
        for i, p in enumerate(self._profiles):
            if p.name == name:
                return i
        return None

    def _persist(self) -> None:
        data = {
            self._KEY_PROFILES: {p.name: p.to_dict() for p in self._profiles},
            self._KEY_ACTIVE:    self._active_name,
        }
        try:
            self._storage.save(data)
        except Exception:
            logger.exception("ProfileRepository: ошибка сохранения")

    def __repr__(self) -> str:
        return f"ProfileRepository(profiles={[p.name for p in self._profiles]}, active={self._active_name!r})"
