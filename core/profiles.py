"""
core/profiles.py — Профили таймера.

Новая модель:
  - Profile хранит список фаз.
  - Phase описывает одну настраиваемую фазу.
  - Старый формат work/rest поддерживается для миграции.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.storage import IStorage

logger = logging.getLogger(__name__)


# ===========================================================================
# Ограничения
# ===========================================================================

_PHASE_MIN_SEC = 5
_PHASE_MAX_SEC = 14_400
_NAME_MAX_LEN = 32
_NOTE_MAX_LEN = 120


# ===========================================================================
# Phase (Value Object)
# ===========================================================================

@dataclass(frozen=True)
class Phase:
    """
    Одна фаза пользовательского сценария.

    Поля:
        name               — название фазы
        duration_seconds    — длительность в секундах
        color_role          — цветовая роль UI: work, rest, custom, prep и т.п.
        sound_enabled       — проигрывать звук при завершении фазы
        notification_enabled— показывать уведомление при завершении фазы
        auto_start_next     — автоматически запускать следующую фазу
        note                — короткая заметка для UI/OBS
    """

    name: str
    duration_seconds: int
    color_role: str = "custom"
    sound_enabled: bool = True
    notification_enabled: bool = True
    auto_start_next: bool = False
    note: str = ""

    def validate(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("Имя фазы не может быть пустым")
        if len(name) > _NAME_MAX_LEN:
            raise ValueError(f"Имя фазы слишком длинное (макс. {_NAME_MAX_LEN} символов)")
        if not (_PHASE_MIN_SEC <= int(self.duration_seconds) <= _PHASE_MAX_SEC):
            raise ValueError(
                f"Длительность фазы должна быть от 00:05 до 04:00:00, получено {self.format_duration()}"
            )
        if len(self.note.strip()) > _NOTE_MAX_LEN:
            raise ValueError(f"Заметка слишком длинная (макс. {_NOTE_MAX_LEN} символов)")

    def format_duration(self) -> str:
        m, s = divmod(max(int(self.duration_seconds), 0), 60)
        return f"{m:02d}:{s:02d}"

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "duration_seconds": int(self.duration_seconds),
            "color_role": self.color_role,
            "sound_enabled": bool(self.sound_enabled),
            "notification_enabled": bool(self.notification_enabled),
            "auto_start_next": bool(self.auto_start_next),
            "note": self.note,
        }
        return data

    @staticmethod
    def from_dict(data: dict, fallback_name: str | None = None) -> "Phase":
        """
        Поддерживает:
          - новый формат: full phase dict
          - старые алиасы: duration, seconds, minutes, color, role, text
        """
        raw_name = str(data.get("name", fallback_name or "")).strip()
        raw_duration = data.get("duration_seconds", data.get("seconds", data.get("duration")))
        if raw_duration is None and "minutes" in data:
            raw_duration = int(data["minutes"]) * 60
        phase = Phase(
            name=raw_name,
            duration_seconds=int(raw_duration or 0),
            color_role=str(data.get("color_role", data.get("color", data.get("role", "custom")))),
            sound_enabled=bool(data.get("sound_enabled", True)),
            notification_enabled=bool(data.get("notification_enabled", True)),
            auto_start_next=bool(data.get("auto_start_next", False)),
            note=str(data.get("note", data.get("text", ""))),
        )
        phase.validate()
        return phase


# ===========================================================================
# Profile (Value Object)
# ===========================================================================

@dataclass
class Profile:
    """
    Иммутабельный по соглашению профиль таймера.

    Профиль хранит сценарий из фаз.
    Для совместимости доступны свойства work_seconds / break_seconds,
    которые читают первые две фазы.
    """

    name: str
    phases: list[Phase] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.phases = list(self.phases)

    # ------------------------------------------------------------------
    # Удобные свойства
    # ------------------------------------------------------------------

    @property
    def phase_count(self) -> int:
        return len(self.phases)

    @property
    def total_seconds(self) -> int:
        return sum(p.duration_seconds for p in self.phases)

    @property
    def first_phase(self) -> Phase | None:
        return self.phases[0] if self.phases else None

    @property
    def second_phase(self) -> Phase | None:
        return self.phases[1] if len(self.phases) > 1 else None

    @property
    def work_seconds(self) -> int:
        phase = self.first_phase
        return phase.duration_seconds if phase else 0

    @property
    def break_seconds(self) -> int:
        phase = self.second_phase
        return phase.duration_seconds if phase else 0

    @property
    def work_minutes(self) -> int:
        return self.work_seconds // 60

    @property
    def work_extra_sec(self) -> int:
        return self.work_seconds % 60

    @property
    def break_minutes(self) -> int:
        return self.break_seconds // 60

    @property
    def break_extra_sec(self) -> int:
        return self.break_seconds % 60

    def format_work(self) -> str:
        return self.first_phase.format_duration() if self.first_phase else "00:00"

    def format_break(self) -> str:
        return self.second_phase.format_duration() if self.second_phase else "00:00"

    def phase_summary(self) -> str:
        if not self.phases:
            return ""
        return " · ".join(f"{phase.name} {phase.format_duration()}" for phase in self.phases[:3])

    # ------------------------------------------------------------------
    # Валидация
    # ------------------------------------------------------------------

    def validate(self) -> None:
        name = self.name.strip()
        if not name:
            raise ValueError("Имя профиля не может быть пустым")
        if len(name) > _NAME_MAX_LEN:
            raise ValueError(f"Имя профиля слишком длинное (макс. {_NAME_MAX_LEN} символов)")
        if not self.phases:
            raise ValueError("Профиль должен содержать хотя бы одну фазу")

        seen: set[str] = set()
        for phase in self.phases:
            phase.validate()
            normalized = phase.name.strip().casefold()
            if normalized in seen:
                raise ValueError(f"В профиле есть повторяющаяся фаза: {phase.name!r}")
            seen.add(normalized)

    # ------------------------------------------------------------------
    # Сериализация
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "phases": [phase.to_dict() for phase in self.phases],
        }

    @staticmethod
    def from_dict(name: str, data: dict) -> "Profile":
        """
        Поддерживает:
          - новый формат: {"phases": [...]}
          - старый формат: {"work_seconds": N, "rest_seconds": N}
          - старый старый: {"work": N, "rest": N} в минутах
        """
        phases_data = data.get("phases")
        if isinstance(phases_data, list) and phases_data:
            phases = []
            for idx, item in enumerate(phases_data, start=1):
                if not isinstance(item, dict):
                    raise KeyError(f"Фаза #{idx} имеет неверный формат: {item!r}")
                phases.append(Phase.from_dict(item, fallback_name=f"Фаза {idx}"))
        elif "work_seconds" in data or "rest_seconds" in data:
            phases = [
                Phase(
                    name=str(data.get("work_name", "Работа")),
                    duration_seconds=int(data.get("work_seconds", 0)),
                    color_role=str(data.get("work_color_role", "work")),
                    sound_enabled=bool(data.get("work_sound_enabled", True)),
                    notification_enabled=bool(data.get("work_notification_enabled", True)),
                    auto_start_next=bool(data.get("work_auto_start_next", False)),
                    note=str(data.get("work_note", "")),
                ),
                Phase(
                    name=str(data.get("rest_name", "Отдых")),
                    duration_seconds=int(data.get("rest_seconds", 0)),
                    color_role=str(data.get("rest_color_role", "rest")),
                    sound_enabled=bool(data.get("rest_sound_enabled", True)),
                    notification_enabled=bool(data.get("rest_notification_enabled", True)),
                    auto_start_next=bool(data.get("rest_auto_start_next", False)),
                    note=str(data.get("rest_note", "")),
                ),
            ]
        elif "work" in data or "rest" in data:
            phases = [
                Phase(
                    name="Работа",
                    duration_seconds=int(data.get("work", 0)) * 60,
                    color_role="work",
                ),
                Phase(
                    name="Отдых",
                    duration_seconds=int(data.get("rest", 0)) * 60,
                    color_role="rest",
                ),
            ]
            logger.info("Profile.from_dict: мигрирован профиль %r из старого минутного формата", name)
        else:
            raise KeyError(f"Неизвестный формат данных профиля: {data!r}")

        profile = Profile(name=name, phases=phases)
        profile.validate()
        return profile

    def __repr__(self) -> str:
        return f"Profile({self.name!r}, phases={[p.name for p in self.phases]!r})"


# ===========================================================================
# Значения по умолчанию
# ===========================================================================

DEFAULT_PROFILES: list[Profile] = [
    Profile(
        name="Работа",
        phases=[
            Phase(name="Работа", duration_seconds=3600, color_role="work", auto_start_next=False),
            Phase(name="Отдых", duration_seconds=600, color_role="rest", auto_start_next=False),
        ],
    ),
    Profile(
        name="Учёба",
        phases=[
            Phase(name="Учёба", duration_seconds=3000, color_role="work", auto_start_next=False),
            Phase(name="Перерыв", duration_seconds=600, color_role="rest", auto_start_next=False),
        ],
    ),
    Profile(
        name="Спорт",
        phases=[
            Phase(name="Тренировка", duration_seconds=2700, color_role="work", auto_start_next=False),
            Phase(name="Восстановление", duration_seconds=900, color_role="rest", auto_start_next=False),
        ],
    ),
]

DEFAULT_ACTIVE_PROFILE = "Работа"


# ===========================================================================
# ProfileRepository
# ===========================================================================

class ProfileRepository:
    """Управляет коллекцией профилей и сохраняет через IStorage."""

    _KEY_PROFILES = "profiles"
    _KEY_ACTIVE = "active_profile"

    def __init__(self, storage: "IStorage") -> None:
        self._storage = storage
        self._profiles: list[Profile] = []
        self._active_name: str = DEFAULT_ACTIVE_PROFILE

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

        self._profiles = loaded
        self._active_name = data.get(self._KEY_ACTIVE, DEFAULT_ACTIVE_PROFILE)

        if not self._find(self._active_name):
            self._active_name = self._profiles[0].name

        logger.info(
            "ProfileRepository: загружено %d профилей, активный: %r",
            len(self._profiles),
            self._active_name,
        )

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
        try:
            data: dict = self._storage.load()
        except Exception:
            data = {}

        data[self._KEY_PROFILES] = {p.name: p.to_dict() for p in self._profiles}
        data[self._KEY_ACTIVE] = self._active_name

        try:
            self._storage.save(data)
        except Exception:
            logger.exception("ProfileRepository: ошибка сохранения")

    def __repr__(self) -> str:
        return f"ProfileRepository(profiles={[p.name for p in self._profiles]}, active={self._active_name!r})"
