"""Локальное SQLite-хранилище WorkTimer.

База никогда не слушает сеть: она создаётся в `%LOCALAPPDATA%\\WorkTimer`
и доступна только процессу приложения. Все значения передаются в SQLite
параметрами, а не собираются через SQL-строки.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from app.domain.models import Phase, PhaseRepeatPolicy, Scenario, Task, TaskGroup, TaskStatus


class SQLiteDatabase:
    """Хранилище сценариев, настроек и будущих задач WorkTimer."""

    LATEST_SCHEMA_VERSION = 3

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        """Создать последнюю схему; миграции выполняются транзакционно."""
        with self._connection() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER NOT NULL)"
            )
            version = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_versions"
            ).fetchone()[0]
            if version >= self.LATEST_SCHEMA_VERSION:
                return
            if version == 1:
                connection.execute("ALTER TABLE tasks ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
                connection.execute("INSERT INTO schema_versions(version) VALUES (2)")
                version = 2
            if version == 2:
                connection.execute("ALTER TABLE scenarios ADD COLUMN progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total BETWEEN 0 AND 100)")
                connection.execute("ALTER TABLE phases ADD COLUMN progress_marker INTEGER NOT NULL DEFAULT 0 CHECK (progress_marker IN (0, 1))")
                connection.execute("INSERT INTO schema_versions(version) VALUES (3)")
                return
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scenarios (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
                    progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total BETWEEN 0 AND 100),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS phases (
                    id INTEGER PRIMARY KEY,
                    scenario_id INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL CHECK (position >= 0),
                    name TEXT NOT NULL,
                    duration_seconds INTEGER NOT NULL CHECK (duration_seconds BETWEEN 1 AND 86400),
                    color_role TEXT NOT NULL DEFAULT 'custom',
                    repeat_policy TEXT NOT NULL DEFAULT 'every_cycle'
                        CHECK (repeat_policy IN ('once_at_start', 'every_cycle', 'disabled')),
                    sound_enabled INTEGER NOT NULL DEFAULT 1 CHECK (sound_enabled IN (0, 1)),
                    notification_enabled INTEGER NOT NULL DEFAULT 1 CHECK (notification_enabled IN (0, 1)),
                    note TEXT NOT NULL DEFAULT '',
                    progress_marker INTEGER NOT NULL DEFAULT 0 CHECK (progress_marker IN (0, 1)),
                    UNIQUE (scenario_id, position)
                );

                CREATE TABLE IF NOT EXISTS task_groups (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER REFERENCES task_groups(id) ON DELETE RESTRICT,
                    name TEXT NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1))
                );

                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY,
                    group_id INTEGER REFERENCES task_groups(id) ON DELETE SET NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'archived')),
                    estimate_seconds INTEGER,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS timer_sessions (
                    id INTEGER PRIMARY KEY,
                    scenario_id INTEGER REFERENCES scenarios(id) ON DELETE SET NULL,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    mode TEXT NOT NULL CHECK (mode IN ('scenario', 'free', 'pomodoro')),
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'stopped'))
                );

                CREATE TABLE IF NOT EXISTS time_entries (
                    id INTEGER PRIMARY KEY,
                    session_id INTEGER REFERENCES timer_sessions(id) ON DELETE SET NULL,
                    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
                    scenario_id INTEGER REFERENCES scenarios(id) ON DELETE SET NULL,
                    phase_id INTEGER REFERENCES phases(id) ON DELETE SET NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    elapsed_seconds INTEGER NOT NULL DEFAULT 0 CHECK (elapsed_seconds >= 0),
                    source TEXT NOT NULL DEFAULT 'timer'
                );

                CREATE TABLE IF NOT EXISTS legacy_journal_events (
                    id INTEGER PRIMARY KEY,
                    source_index INTEGER NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_phases_scenario_position
                    ON phases(scenario_id, position);
                CREATE INDEX IF NOT EXISTS idx_time_entries_task_started
                    ON time_entries(task_id, started_at);
                """
            )
            connection.execute("INSERT INTO schema_versions(version) VALUES (?)", (self.LATEST_SCHEMA_VERSION,))

    def save_scenario(self, scenario: Scenario) -> Scenario:
        scenario.validate()
        with self._connection() as connection:
            if scenario.id is None:
                cursor = connection.execute(
                    "INSERT INTO scenarios(name, is_archived, progress_total) VALUES (?, ?, ?)",
                    (scenario.name.strip(), int(scenario.is_archived), scenario.progress_total),
                )
                scenario_id = int(cursor.lastrowid)
            else:
                connection.execute(
                    "UPDATE scenarios SET name = ?, is_archived = ?, progress_total = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (scenario.name.strip(), int(scenario.is_archived), scenario.progress_total, scenario.id),
                )
                scenario_id = scenario.id
                # Старые фазы заменяются новыми при сохранении сценария.
                # История остаётся целой: отвязываем запись только от фазы.
                connection.execute(
                    "UPDATE time_entries SET phase_id = NULL WHERE phase_id IN (SELECT id FROM phases WHERE scenario_id = ?)",
                    (scenario_id,),
                )
                connection.execute("DELETE FROM phases WHERE scenario_id = ?", (scenario_id,))
            for position, phase in enumerate(scenario.phases):
                connection.execute(
                    """INSERT INTO phases(
                        scenario_id, position, name, duration_seconds, color_role,
                        repeat_policy, sound_enabled, notification_enabled, note, progress_marker
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        scenario_id,
                        position,
                        phase.name.strip(),
                        phase.duration_seconds,
                        phase.color_role,
                        phase.repeat_policy.value,
                        int(phase.sound_enabled),
                        int(phase.notification_enabled),
                        phase.note,
                        int(phase.progress_marker),
                    ),
                )
        return self.get_scenario(scenario_id)

    def get_scenario(self, scenario_id: int) -> Scenario:
        with self._connection() as connection:
            scenario_row = connection.execute(
                "SELECT id, name, is_archived, progress_total FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
            if scenario_row is None:
                raise KeyError(f"Сценарий {scenario_id} не найден")
            phase_rows = connection.execute(
                "SELECT * FROM phases WHERE scenario_id = ? ORDER BY position", (scenario_id,)
            ).fetchall()
        return self._scenario_from_rows(scenario_row, phase_rows)

    def archive_scenario(self, scenario_id: int) -> None:
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE scenarios SET is_archived = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (scenario_id,),
            )
        if result.rowcount == 0:
            raise KeyError(f"Сценарий {scenario_id} не найден")

    def duplicate_scenario(self, scenario_id: int) -> Scenario:
        source = self.get_scenario(scenario_id)
        existing_names = {scenario.name.casefold() for scenario in self.list_scenarios()}
        base_name = f"{source.name} — копия"
        name = base_name
        suffix = 2
        while name.casefold() in existing_names:
            name = f"{base_name} {suffix}"
            suffix += 1
        return self.save_scenario(Scenario(name=name, phases=source.phases))

    def list_scenarios(self) -> list[Scenario]:
        with self._connection() as connection:
            scenarios = connection.execute(
                "SELECT id, name, is_archived, progress_total FROM scenarios ORDER BY is_archived, name COLLATE NOCASE"
            ).fetchall()
            phase_rows = connection.execute("SELECT * FROM phases ORDER BY scenario_id, position").fetchall()
        phases_by_scenario: dict[int, list[sqlite3.Row]] = {}
        for phase in phase_rows:
            phases_by_scenario.setdefault(int(phase["scenario_id"]), []).append(phase)
        return [self._scenario_from_rows(row, phases_by_scenario.get(int(row["id"]), [])) for row in scenarios]

    def save_task_group(self, group: TaskGroup) -> TaskGroup:
        group.validate()
        with self._connection() as connection:
            if group.id is None:
                cursor = connection.execute(
                    "INSERT INTO task_groups(parent_id, name, position, is_archived) VALUES (?, ?, ?, ?)",
                    (group.parent_id, group.name.strip(), group.position, int(group.is_archived)),
                )
                group_id = int(cursor.lastrowid)
            else:
                result = connection.execute(
                    "UPDATE task_groups SET parent_id = ?, name = ?, position = ?, is_archived = ? WHERE id = ?",
                    (group.parent_id, group.name.strip(), group.position, int(group.is_archived), group.id),
                )
                if result.rowcount == 0:
                    raise KeyError(f"Группа {group.id} не найдена")
                group_id = group.id
        return TaskGroup(id=group_id, name=group.name.strip(), parent_id=group.parent_id, position=group.position, is_archived=group.is_archived)

    def list_task_groups(self) -> list[TaskGroup]:
        with self._connection() as connection:
            rows = connection.execute("SELECT * FROM task_groups ORDER BY parent_id IS NOT NULL, position, name COLLATE NOCASE").fetchall()
        return [TaskGroup(id=int(row["id"]), parent_id=row["parent_id"], name=str(row["name"]), position=int(row["position"]), is_archived=bool(row["is_archived"])) for row in rows]

    def save_task(self, task: Task) -> Task:
        task.validate()
        with self._connection() as connection:
            if task.group_id is not None and connection.execute("SELECT 1 FROM task_groups WHERE id = ?", (task.group_id,)).fetchone() is None:
                raise ValueError("Указанная группа не существует")
            if task.id is None:
                cursor = connection.execute(
                    "INSERT INTO tasks(group_id, title, description, status, estimate_seconds, tags_json, position, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'done' THEN CURRENT_TIMESTAMP ELSE NULL END)",
                    (task.group_id, task.title.strip(), task.description, task.status.value, task.estimate_seconds, json.dumps(list(task.tags), ensure_ascii=False), task.position, task.status.value),
                )
                task_id = int(cursor.lastrowid)
            else:
                result = connection.execute(
                    "UPDATE tasks SET group_id = ?, title = ?, description = ?, status = ?, estimate_seconds = ?, tags_json = ?, position = ?, completed_at = CASE WHEN ? = 'done' THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE NULL END WHERE id = ?",
                    (task.group_id, task.title.strip(), task.description, task.status.value, task.estimate_seconds, json.dumps(list(task.tags), ensure_ascii=False), task.position, task.status.value, task.id),
                )
                if result.rowcount == 0:
                    raise KeyError(f"Задача {task.id} не найдена")
                task_id = task.id
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> Task:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(f"Задача {task_id} не найдена")
        return self._task_from_row(row)

    def list_tasks(self, *, include_archived: bool = False) -> list[Task]:
        query = "SELECT * FROM tasks" if include_archived else "SELECT * FROM tasks WHERE status != 'archived'"
        with self._connection() as connection:
            rows = connection.execute(f"{query} ORDER BY status = 'done', position, id DESC").fetchall()
        return [self._task_from_row(row) for row in rows]

    def create_time_entry(self, *, task_id: int | None, scenario_id: int | None, phase_id: int | None) -> int:
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection() as connection:
            cursor = connection.execute(
                "INSERT INTO time_entries(task_id, scenario_id, phase_id, started_at, source) VALUES (?, ?, ?, ?, 'timer')",
                (task_id, scenario_id, phase_id, started_at),
            )
            return int(cursor.lastrowid)

    def finish_time_entry(self, entry_id: int, elapsed_seconds: int) -> None:
        ended_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection() as connection:
            connection.execute(
                "UPDATE time_entries SET ended_at = ?, elapsed_seconds = ? WHERE id = ?",
                (ended_at, max(0, elapsed_seconds), entry_id),
            )

    def time_summary_by_task(self) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT t.id, t.title, COALESCE(SUM(e.elapsed_seconds), 0) AS elapsed_seconds
                   FROM tasks AS t LEFT JOIN time_entries AS e ON e.task_id = t.id
                   WHERE t.status != 'archived' GROUP BY t.id, t.title ORDER BY elapsed_seconds DESC, t.id DESC"""
            ).fetchall()
        return [{"task_id": int(row["id"]), "title": str(row["title"]), "elapsed_seconds": int(row["elapsed_seconds"])} for row in rows]

    def time_summary_by_day(self, limit: int = 14) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT substr(started_at, 1, 10) AS day, SUM(elapsed_seconds) AS elapsed_seconds
                   FROM time_entries WHERE ended_at IS NOT NULL
                   GROUP BY substr(started_at, 1, 10) ORDER BY day DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [{"day": str(row["day"]), "elapsed_seconds": int(row["elapsed_seconds"])} for row in rows]

    def time_summary_by_scenario(self) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT s.id, s.name, SUM(e.elapsed_seconds) AS elapsed_seconds
                   FROM time_entries AS e JOIN scenarios AS s ON s.id = e.scenario_id
                   WHERE e.ended_at IS NOT NULL GROUP BY s.id, s.name
                   ORDER BY elapsed_seconds DESC, s.id DESC"""
            ).fetchall()
        return [{"scenario_id": int(row["id"]), "name": str(row["name"]), "elapsed_seconds": int(row["elapsed_seconds"])} for row in rows]

    def list_time_entries(
        self,
        limit: int = 100,
        *,
        task_id: int | None = None,
        group_id: int | None = None,
        scenario_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[dict[str, object]]:
        filters = ["e.ended_at IS NOT NULL"]
        values: list[object] = []
        if task_id is not None:
            filters.append("e.task_id = ?")
            values.append(task_id)
        if group_id is not None:
            filters.append("t.group_id = ?")
            values.append(group_id)
        if scenario_id is not None:
            filters.append("e.scenario_id = ?")
            values.append(scenario_id)
        if date_from:
            filters.append("substr(e.started_at, 1, 10) >= ?")
            values.append(date_from)
        if date_to:
            filters.append("substr(e.started_at, 1, 10) <= ?")
            values.append(date_to)
        values.append(max(1, min(limit, 1_000)))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT e.id, e.started_at, e.ended_at, e.elapsed_seconds, e.source,
                   t.title AS task_title, s.name AS scenario_name, p.name AS phase_name
                   FROM time_entries AS e
                   LEFT JOIN tasks AS t ON t.id = e.task_id
                   LEFT JOIN scenarios AS s ON s.id = e.scenario_id
                   LEFT JOIN phases AS p ON p.id = e.phase_id
                   WHERE """ + " AND ".join(filters) + " ORDER BY e.id DESC LIMIT ?",
                values,
            ).fetchall()
        return [{"id": int(row["id"]), "started_at": str(row["started_at"]), "ended_at": str(row["ended_at"]), "elapsed_seconds": int(row["elapsed_seconds"]), "source": str(row["source"]), "task_title": row["task_title"], "scenario_name": row["scenario_name"], "phase_name": row["phase_name"]} for row in rows]

    def correct_time_entry(self, entry_id: int, elapsed_seconds: int) -> None:
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE time_entries SET elapsed_seconds = ?, source = 'manual' WHERE id = ? AND ended_at IS NOT NULL",
                (max(0, min(elapsed_seconds, 31_536_000)), entry_id),
            )
        if result.rowcount == 0:
            raise KeyError(f"Запись времени {entry_id} не найдена или ещё активна")

    def set_setting(self, key: str, value: object) -> None:
        if not key or len(key) > 120:
            raise ValueError("Некорректный ключ настройки")
        serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO app_settings(key, value_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (key, serialized),
            )

    def get_setting(self, key: str, default: object = None) -> object:
        with self._connection() as connection:
            row = connection.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        return default if row is None else json.loads(str(row["value_json"]))

    def import_legacy_json(self, settings_path: str | Path) -> int:
        """Однократно импортировать legacy-профили, не перезаписывая SQLite."""
        if self.list_scenarios():
            return 0
        path = Path(settings_path)
        if not path.exists():
            return 0
        raw = json.loads(path.read_text(encoding="utf-8"))
        profiles = raw.get("profiles", {}) if isinstance(raw, dict) else {}
        imported = 0
        for name, profile in profiles.items():
            if not isinstance(name, str) or not isinstance(profile, dict):
                continue
            raw_phases = profile.get("phases", [])
            phases: list[Phase] = []
            for position, raw_phase in enumerate(raw_phases):
                if not isinstance(raw_phase, dict):
                    continue
                try:
                    phases.append(
                        Phase(
                            name=str(raw_phase.get("name", f"Фаза {position + 1}")),
                            duration_seconds=int(raw_phase.get("duration_seconds", 0)),
                            color_role=str(raw_phase.get("color_role", "custom")),
                            sound_enabled=bool(raw_phase.get("sound_enabled", True)),
                            notification_enabled=bool(raw_phase.get("notification_enabled", True)),
                            note=str(raw_phase.get("note", "")),
                            position=position,
                        )
                    )
                    phases[-1].validate()
                except (TypeError, ValueError):
                    continue
            if phases:
                self.save_scenario(Scenario(name=name, phases=tuple(phases)))
                imported += 1
        if imported:
            self.set_setting("legacy_import_completed", True)
            active_name = raw.get("active_profile")
            if isinstance(active_name, str):
                self.set_setting("active_scenario_name", active_name)
        return imported

    def import_legacy_journal(self, journal_path: str | Path) -> int:
        """Сохранить legacy-журнал без потери полей для будущей конвертации.

        Старые записи — события жизненного цикла, а не непрерывные отрезки
        времени. Поэтому на этом этапе их нельзя честно превратить в
        `time_entries`; исходные payload сохраняются неизменёнными.
        """
        path = Path(journal_path)
        if not path.exists():
            return 0
        raw = json.loads(path.read_text(encoding="utf-8"))
        events = raw.get("events", []) if isinstance(raw, dict) else []
        if not isinstance(events, list):
            return 0
        imported = 0
        with self._connection() as connection:
            for index, event in enumerate(events):
                if not isinstance(event, dict):
                    continue
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO legacy_journal_events(source_index, payload_json) VALUES (?, ?)",
                    (index, json.dumps(event, ensure_ascii=False, separators=(",", ":"))),
                )
                imported += int(cursor.rowcount > 0)
        return imported

    def legacy_journal_event_count(self) -> int:
        with self._connection() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM legacy_journal_events").fetchone()[0])

    @staticmethod
    def _scenario_from_rows(scenario_row: sqlite3.Row, phase_rows: list[sqlite3.Row]) -> Scenario:
        phases = tuple(
            Phase(
                id=int(row["id"]),
                position=int(row["position"]),
                name=str(row["name"]),
                duration_seconds=int(row["duration_seconds"]),
                color_role=str(row["color_role"]),
                repeat_policy=PhaseRepeatPolicy(str(row["repeat_policy"])),
                sound_enabled=bool(row["sound_enabled"]),
                notification_enabled=bool(row["notification_enabled"]),
                note=str(row["note"]),
                progress_marker=bool(row["progress_marker"]),
            )
            for row in phase_rows
        )
        return Scenario(
            id=int(scenario_row["id"]),
            name=str(scenario_row["name"]),
            is_archived=bool(scenario_row["is_archived"]),
            progress_total=int(scenario_row["progress_total"]),
            phases=phases,
        )

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        return Task(
            id=int(row["id"]), group_id=row["group_id"], title=str(row["title"]), description=str(row["description"]),
            status=TaskStatus(str(row["status"])), estimate_seconds=row["estimate_seconds"], tags=tuple(json.loads(str(row["tags_json"]))), position=int(row["position"]),
        )
