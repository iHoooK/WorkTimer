"""
core/journal.py - event journal and CSV export for WorkTimer.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from infrastructure.storage import IStorage

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "timestamp",
    "event_type",
    "profile_name",
    "phase_index",
    "phase_name",
    "phase_role",
    "timer_phase",
    "timer_mode",
    "planned_seconds",
    "remaining_seconds",
    "elapsed_seconds",
    "note",
]


@dataclass(frozen=True)
class JournalEntry:
    timestamp: str
    event_type: str
    profile_name: str
    phase_index: int
    phase_name: str
    phase_role: str
    timer_phase: str
    timer_mode: str
    planned_seconds: int
    remaining_seconds: int
    elapsed_seconds: int
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "JournalEntry":
        return JournalEntry(
            timestamp=str(data.get("timestamp", "")),
            event_type=str(data.get("event_type", "")),
            profile_name=str(data.get("profile_name", "")),
            phase_index=int(data.get("phase_index", 0)),
            phase_name=str(data.get("phase_name", "")),
            phase_role=str(data.get("phase_role", "")),
            timer_phase=str(data.get("timer_phase", "")),
            timer_mode=str(data.get("timer_mode", "")),
            planned_seconds=int(data.get("planned_seconds", 0)),
            remaining_seconds=int(data.get("remaining_seconds", 0)),
            elapsed_seconds=int(data.get("elapsed_seconds", 0)),
            note=str(data.get("note", "")),
        )


class JournalRepository:
    _KEY_VERSION = "version"
    _KEY_EVENTS = "events"
    _VERSION = 1

    def __init__(self, storage: "IStorage") -> None:
        self._storage = storage

    def append(self, entry: JournalEntry) -> None:
        data = self._load_raw()
        events = data.setdefault(self._KEY_EVENTS, [])
        events.append(entry.to_dict())
        data[self._KEY_VERSION] = self._VERSION
        self._storage.save(data)

    def record(
        self,
        *,
        event_type: str,
        profile_name: str,
        phase_index: int,
        phase_name: str,
        phase_role: str,
        timer_phase: str,
        timer_mode: str,
        planned_seconds: int,
        remaining_seconds: int,
        elapsed_seconds: int,
        note: str = "",
    ) -> None:
        entry = JournalEntry(
            timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
            event_type=event_type,
            profile_name=profile_name,
            phase_index=phase_index,
            phase_name=phase_name,
            phase_role=phase_role,
            timer_phase=timer_phase,
            timer_mode=timer_mode,
            planned_seconds=planned_seconds,
            remaining_seconds=remaining_seconds,
            elapsed_seconds=elapsed_seconds,
            note=note,
        )
        self.append(entry)

    def all(self) -> list[JournalEntry]:
        data = self._load_raw()
        events = data.get(self._KEY_EVENTS, [])
        if not isinstance(events, list):
            return []
        result: list[JournalEntry] = []
        for item in events:
            if not isinstance(item, dict):
                continue
            try:
                result.append(JournalEntry.from_dict(item))
            except (TypeError, ValueError):
                logger.warning("JournalRepository: skipped invalid event %r", item)
        return result

    def export_csv(self, path: str) -> int:
        entries = self.all()
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for entry in entries:
                writer.writerow(entry.to_dict())
        return len(entries)

    def _load_raw(self) -> dict:
        try:
            data = self._storage.load()
        except Exception:
            logger.warning("JournalRepository: failed to load journal, using empty store")
            return {self._KEY_VERSION: self._VERSION, self._KEY_EVENTS: []}
        if not isinstance(data, dict):
            return {self._KEY_VERSION: self._VERSION, self._KEY_EVENTS: []}
        if not isinstance(data.get(self._KEY_EVENTS, []), list):
            data[self._KEY_EVENTS] = []
        data.setdefault(self._KEY_VERSION, self._VERSION)
        return data
