"""Локальное SQLite-хранилище WorkTimer.

База никогда не слушает сеть: она создаётся в `%LOCALAPPDATA%\\WorkTimer`
и доступна только процессу приложения. Все значения передаются в SQLite
параметрами, а не собираются через SQL-строки.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from app.domain.models import Phase, PhaseRepeatPolicy, Scenario, Task, TaskGroup, TaskStatus

logger = logging.getLogger(__name__)


class SQLiteDatabase:
    """Хранилище сценариев, настроек и будущих задач WorkTimer."""

    LATEST_SCHEMA_VERSION = 4

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._storage_lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._storage_lock, self._unlocked_connection() as connection:
            yield connection

    @contextmanager
    def _unlocked_connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
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
            connection.execute("CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER NOT NULL)")
            version = connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_versions").fetchone()[0]
            if version > self.LATEST_SCHEMA_VERSION:
                raise ValueError("База создана более новой версией WorkTimer")
            if version >= self.LATEST_SCHEMA_VERSION:
                return
            if version:
                self.backup(label=f"before-v{self.LATEST_SCHEMA_VERSION}")
                connection.execute("BEGIN IMMEDIATE")
            if version == 1:
                connection.execute("ALTER TABLE tasks ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
                connection.execute("INSERT INTO schema_versions(version) VALUES (2)")
                version = 2
            if version == 2:
                connection.execute(
                    "ALTER TABLE scenarios ADD COLUMN progress_total INTEGER NOT NULL DEFAULT 0 CHECK (progress_total BETWEEN 0 AND 100)"
                )
                connection.execute(
                    "ALTER TABLE phases ADD COLUMN progress_marker INTEGER NOT NULL DEFAULT 0 CHECK (progress_marker IN (0, 1))"
                )
                connection.execute("INSERT INTO schema_versions(version) VALUES (3)")
                version = 3
            if version == 3:
                self._upgrade_v4(connection)
                return
            connection.executescript(
                """
                BEGIN IMMEDIATE;
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
            connection.execute("INSERT INTO schema_versions(version) VALUES (3)")
            self._upgrade_v4(connection)

    @staticmethod
    def _upgrade_v4(connection: sqlite3.Connection) -> None:
        for column in ("task_title_snapshot", "scenario_name_snapshot", "phase_name_snapshot", "phase_role"):
            connection.execute(f"ALTER TABLE time_entries ADD COLUMN {column} TEXT")
        connection.execute("""UPDATE time_entries SET
            task_title_snapshot = (SELECT title FROM tasks WHERE id = task_id),
            scenario_name_snapshot = (SELECT name FROM scenarios WHERE id = scenario_id),
            phase_name_snapshot = (SELECT name FROM phases WHERE id = phase_id),
            phase_role = COALESCE((SELECT color_role FROM phases WHERE id = phase_id), 'work')""")
        connection.execute("ALTER TABLE timer_sessions ADD COLUMN scenario_name_snapshot TEXT")
        connection.execute("ALTER TABLE timer_sessions ADD COLUMN task_title_snapshot TEXT")
        connection.execute("""CREATE TABLE time_entry_corrections (
            id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES time_entries(id),
            old_seconds INTEGER NOT NULL, new_seconds INTEGER NOT NULL,
            corrected_at TEXT NOT NULL)""")
        connection.execute("CREATE INDEX idx_entries_started ON time_entries(started_at)")
        connection.execute("INSERT INTO schema_versions(version) VALUES (4)")

    def backup(self, *, label: str = "manual") -> Path:
        with self._storage_lock:
            return self._backup_locked(label=label)

    def _backup_locked(self, *, label: str) -> Path:
        folder = self.path.parent / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        destination = folder / f"worktimer-{label}-{timestamp}.db"
        source = sqlite3.connect(self.path)
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return destination

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
                result = connection.execute(
                    "UPDATE scenarios SET name = ?, is_archived = ?, progress_total = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (scenario.name.strip(), int(scenario.is_archived), scenario.progress_total, scenario.id),
                )
                if result.rowcount == 0:
                    raise KeyError(f"Сценарий {scenario.id} не найден")
                scenario_id = scenario.id
            old_rows = connection.execute(
                "SELECT id, position FROM phases WHERE scenario_id = ? ORDER BY position", (scenario_id,)
            ).fetchall()
            old_ids = {int(row["id"]) for row in old_rows}
            # Moving all existing positions first avoids UNIQUE collisions on reorder.
            connection.execute("UPDATE phases SET position = position + 1000 WHERE scenario_id = ?", (scenario_id,))
            kept_ids: set[int] = set()
            positional_legacy = all(phase.id is None for phase in scenario.phases)
            for position, phase in enumerate(scenario.phases):
                phase_id = phase.id
                if phase_id is None and positional_legacy and position < len(old_rows):
                    phase_id = int(old_rows[position]["id"])
                values = (
                    position,
                    phase.name.strip(),
                    phase.duration_seconds,
                    phase.color_role,
                    phase.repeat_policy.value,
                    int(phase.sound_enabled),
                    int(phase.notification_enabled),
                    phase.note,
                    int(phase.progress_marker),
                )
                if phase_id is not None:
                    if phase_id not in old_ids or phase_id in kept_ids:
                        raise ValueError("Некорректный ID фазы")
                    connection.execute(
                        """UPDATE phases SET position = ?, name = ?, duration_seconds = ?,
                        color_role = ?, repeat_policy = ?, sound_enabled = ?, notification_enabled = ?,
                        note = ?, progress_marker = ? WHERE id = ? AND scenario_id = ?""",
                        (*values, phase_id, scenario_id),
                    )
                    kept_ids.add(phase_id)
                    continue
                cursor = connection.execute(
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
                kept_ids.add(int(cursor.lastrowid))
            for phase_id in old_ids - kept_ids:
                connection.execute("DELETE FROM phases WHERE id = ?", (phase_id,))
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
        return self.save_scenario(
            Scenario(
                name=name,
                phases=tuple(replace(phase, id=None) for phase in source.phases),
                progress_total=source.progress_total,
            )
        )

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
            if group.parent_id is not None:
                parent = connection.execute(
                    "SELECT parent_id, is_archived FROM task_groups WHERE id = ?", (group.parent_id,)
                ).fetchone()
                if parent is None or parent[1]:
                    raise ValueError("Родительская группа не найдена или в архиве")
                if parent[0] is not None or group.parent_id == group.id:
                    raise ValueError("Поддерживается один уровень подгрупп")
                if (
                    group.id is not None
                    and connection.execute("SELECT 1 FROM task_groups WHERE parent_id = ?", (group.id,)).fetchone()
                ):
                    raise ValueError("Группу с подгруппами нельзя сделать подгруппой")
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
        return TaskGroup(
            id=group_id,
            name=group.name.strip(),
            parent_id=group.parent_id,
            position=group.position,
            is_archived=group.is_archived,
        )

    def list_task_groups(self) -> list[TaskGroup]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM task_groups ORDER BY parent_id IS NOT NULL, position, name COLLATE NOCASE"
            ).fetchall()
        return [
            TaskGroup(
                id=int(row["id"]),
                parent_id=row["parent_id"],
                name=str(row["name"]),
                position=int(row["position"]),
                is_archived=bool(row["is_archived"]),
            )
            for row in rows
        ]

    def save_task(self, task: Task) -> Task:
        task.validate()
        with self._connection() as connection:
            if (
                task.group_id is not None
                and connection.execute("SELECT 1 FROM task_groups WHERE id = ?", (task.group_id,)).fetchone() is None
            ):
                raise ValueError("Указанная группа не существует")
            if task.id is None:
                cursor = connection.execute(
                    "INSERT INTO tasks(group_id, title, description, status, estimate_seconds, tags_json, position, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, CASE WHEN ? = 'done' THEN CURRENT_TIMESTAMP ELSE NULL END)",
                    (
                        task.group_id,
                        task.title.strip(),
                        task.description,
                        task.status.value,
                        task.estimate_seconds,
                        json.dumps(list(task.tags), ensure_ascii=False),
                        task.position,
                        task.status.value,
                    ),
                )
                task_id = int(cursor.lastrowid)
            else:
                result = connection.execute(
                    "UPDATE tasks SET group_id = ?, title = ?, description = ?, status = ?, estimate_seconds = ?, tags_json = ?, position = ?, completed_at = CASE WHEN ? = 'done' THEN COALESCE(completed_at, CURRENT_TIMESTAMP) ELSE NULL END WHERE id = ?",
                    (
                        task.group_id,
                        task.title.strip(),
                        task.description,
                        task.status.value,
                        task.estimate_seconds,
                        json.dumps(list(task.tags), ensure_ascii=False),
                        task.position,
                        task.status.value,
                        task.id,
                    ),
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

    def create_session(self, *, task_id: int | None, scenario_id: int | None, mode: str) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO timer_sessions(task_id, scenario_id, mode, started_at,
                scenario_name_snapshot, task_title_snapshot) VALUES (?, ?, ?, ?,
                (SELECT name FROM scenarios WHERE id = ?), (SELECT title FROM tasks WHERE id = ?))""",
                (
                    task_id,
                    scenario_id,
                    mode,
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    scenario_id,
                    task_id,
                ),
            )
            return int(cursor.lastrowid)

    def finish_session(self, session_id: int, *, completed: bool = False) -> None:
        with self._connection() as connection:
            connection.execute(
                "UPDATE timer_sessions SET ended_at = ?, status = ? WHERE id = ?",
                (
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                    "completed" if completed else "stopped",
                    session_id,
                ),
            )

    def create_time_entry(
        self,
        *,
        task_id: int | None,
        scenario_id: int | None,
        phase_id: int | None,
        session_id: int | None = None,
        phase_name: str | None = None,
        phase_role: str = "work",
    ) -> int:
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO time_entries(task_id, scenario_id, phase_id, started_at, source, session_id,
                    task_title_snapshot, scenario_name_snapshot, phase_name_snapshot, phase_role)
                    VALUES (?, ?, ?, ?, 'timer', ?, (SELECT title FROM tasks WHERE id = ?),
                    (SELECT name FROM scenarios WHERE id = ?),
                    COALESCE(?, (SELECT name FROM phases WHERE id = ?)),
                    COALESCE((SELECT color_role FROM phases WHERE id = ?), ?))""",
                (
                    task_id,
                    scenario_id,
                    phase_id,
                    started_at,
                    session_id,
                    task_id,
                    scenario_id,
                    phase_name,
                    phase_id,
                    phase_id,
                    phase_role,
                ),
            )
            return int(cursor.lastrowid)

    def finish_time_entry(self, entry_id: int, elapsed_seconds: int) -> None:
        ended_at = datetime.now().astimezone().isoformat(timespec="seconds")
        with self._connection() as connection:
            connection.execute(
                "UPDATE time_entries SET ended_at = ?, elapsed_seconds = ? WHERE id = ? AND ended_at IS NULL",
                (ended_at, max(0, elapsed_seconds), entry_id),
            )

    def checkpoint_runtime(self, runtime: dict[str, object] | None) -> None:
        with self._connection() as connection:
            if runtime and runtime.get("entry_id"):
                connection.execute(
                    "UPDATE time_entries SET elapsed_seconds = ? WHERE id = ? AND ended_at IS NULL",
                    (int(float(runtime.get("elapsed", 0))), runtime["entry_id"]),
                )
            connection.execute(
                "INSERT INTO app_settings(key, value_json) VALUES ('active_runtime', ?) "
                "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json",
                (json.dumps(runtime, ensure_ascii=False),),
            )

    def open_entry_exists(self, entry_id: int) -> bool:
        with self._connection() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM time_entries WHERE id = ? AND ended_at IS NULL", (entry_id,)
                ).fetchone()
                is not None
            )

    def close_orphan_entries(self, keep_id: int | None = None, keep_session_id: int | None = None) -> int:
        # For legacy/no-checkpoint entries, never invent elapsed time after a crash.
        with self._connection() as connection:
            result = connection.execute(
                "UPDATE time_entries SET ended_at = started_at, source = 'interrupted' "
                "WHERE ended_at IS NULL AND id != ?",
                (keep_id or -1,),
            )
            connection.execute(
                "UPDATE timer_sessions SET status = 'stopped', ended_at = started_at "
                "WHERE ended_at IS NULL AND id != ? AND id NOT IN (SELECT session_id FROM time_entries WHERE ended_at IS NULL AND session_id IS NOT NULL)",
                (keep_session_id or -1,),
            )
            return result.rowcount

    def time_summary_by_task(self) -> list[dict[str, object]]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT t.id, t.title, COALESCE(SUM(e.elapsed_seconds), 0) AS elapsed_seconds
                   FROM tasks AS t LEFT JOIN time_entries AS e ON e.task_id = t.id AND e.ended_at IS NOT NULL AND e.phase_role NOT IN ('rest', 'prep')
                   WHERE t.status != 'archived' GROUP BY t.id, t.title ORDER BY elapsed_seconds DESC, t.id DESC"""
            ).fetchall()
        return [
            {"task_id": int(row["id"]), "title": str(row["title"]), "elapsed_seconds": int(row["elapsed_seconds"])}
            for row in rows
        ]

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
        return [
            {"scenario_id": int(row["id"]), "name": str(row["name"]), "elapsed_seconds": int(row["elapsed_seconds"])}
            for row in rows
        ]

    def list_time_entries(
        self,
        limit: int = 100,
        *,
        task_id: int | None = None,
        group_id: int | None = None,
        scenario_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        offset: int = 0,
        phase_role: str | None = None,
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
        if phase_role:
            filters.append("e.phase_role = ?")
            values.append(phase_role)
        values.extend((max(1, min(limit, 1_000)), max(0, offset)))
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT e.id, e.started_at, e.ended_at, e.elapsed_seconds, e.source,
                   COALESCE(e.task_title_snapshot, t.title) AS task_title,
                   COALESCE(e.scenario_name_snapshot, s.name) AS scenario_name,
                   COALESCE(e.phase_name_snapshot, p.name) AS phase_name,
                   e.task_id, e.scenario_id, e.session_id, e.phase_role, t.group_id
                   FROM time_entries AS e
                   LEFT JOIN tasks AS t ON t.id = e.task_id
                   LEFT JOIN scenarios AS s ON s.id = e.scenario_id
                   LEFT JOIN phases AS p ON p.id = e.phase_id
                   WHERE """
                + " AND ".join(filters)
                + " ORDER BY e.id DESC LIMIT ? OFFSET ?",
                values,
            ).fetchall()
        return [dict(row) for row in rows]

    def iter_time_entries(self, **filters):
        offset = 0
        while True:
            items = self.list_time_entries(limit=1000, offset=offset, **filters)
            yield from items
            if len(items) < 1000:
                return
            offset += len(items)

    def analytics(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        task_id: int | None = None,
        group_id: int | None = None,
        scenario_id: int | None = None,
        phase_role: str | None = None,
    ) -> dict[str, object]:
        end = date.fromisoformat(date_to) if date_to else date.today()
        start = date.fromisoformat(date_from) if date_from else end - timedelta(days=13)
        if end < start or (end - start).days > 3660:
            raise ValueError("Выберите период не длиннее 10 лет, начало не позже окончания")
        entries = list(
            self.iter_time_entries(
                date_from=start.isoformat(),
                date_to=end.isoformat(),
                task_id=task_id,
                group_id=group_id,
                scenario_id=scenario_id,
                phase_role=phase_role,
            )
        )
        days = {
            str(start + timedelta(days=i)): {
                "day": str(start + timedelta(days=i)),
                "elapsed_seconds": 0,
                "work_seconds": 0,
            }
            for i in range((end - start).days + 1)
        }
        roles = {role: 0 for role in ("work", "rest", "prep", "custom")}
        tasks: dict[int, dict] = {}
        groups: dict[int, dict] = {}
        scenarios: dict[int, dict] = {}
        group_names = {g.id: g.name for g in self.list_task_groups()}
        session_ids = set()
        for entry in entries:
            seconds = int(entry["elapsed_seconds"])
            role = entry["phase_role"] if entry["phase_role"] in roles else "custom"
            roles[role] += seconds
            work = seconds if role in ("work", "custom") else 0
            day = str(entry["started_at"])[:10]
            if day in days:
                days[day]["elapsed_seconds"] += seconds
                days[day]["work_seconds"] += work
            if entry["session_id"]:
                session_ids.add(entry["session_id"])
            for target, identifier, title in (
                (tasks, entry["task_id"], entry["task_title"]),
                (groups, entry["group_id"], group_names.get(entry["group_id"])),
                (scenarios, entry["scenario_id"], entry["scenario_name"]),
            ):
                if identifier is not None:
                    item = target.setdefault(
                        identifier,
                        {"id": identifier, "name": title or "Без названия", "elapsed_seconds": 0, "work_seconds": 0},
                    )
                    item["elapsed_seconds"] += seconds
                    item["work_seconds"] += work
        return {
            "date_from": start.isoformat(),
            "date_to": end.isoformat(),
            "entries_count": len(entries),
            "total_seconds": sum(roles.values()),
            "work_seconds": roles["work"] + roles["custom"],
            "rest_seconds": roles["rest"],
            "prep_seconds": roles["prep"],
            "roles": roles,
            "days": list(days.values()),
            "tasks": sorted(tasks.values(), key=lambda x: x["work_seconds"], reverse=True),
            "groups": sorted(groups.values(), key=lambda x: x["work_seconds"], reverse=True),
            "scenarios": sorted(scenarios.values(), key=lambda x: x["elapsed_seconds"], reverse=True),
            "sessions_count": len(session_ids),
        }

    def list_sessions(self, limit: int = 50) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                """SELECT s.id, s.mode, s.status, s.started_at, s.ended_at,
                s.scenario_name_snapshot AS scenario_name, s.task_title_snapshot AS task_title,
                COALESCE(SUM(e.elapsed_seconds), 0) AS elapsed_seconds,
                COALESCE(SUM(CASE WHEN e.phase_role NOT IN ('rest', 'prep') THEN e.elapsed_seconds ELSE 0 END), 0) AS work_seconds
                FROM timer_sessions s LEFT JOIN time_entries e ON e.session_id = s.id AND e.ended_at IS NOT NULL
                GROUP BY s.id ORDER BY s.id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_scenario(self, scenario_id: int) -> None:
        with self._connection() as connection:
            result = connection.execute("UPDATE scenarios SET is_archived = 0 WHERE id = ?", (scenario_id,))
            if not result.rowcount:
                raise KeyError("Сценарий не найден")

    def correction_history(self, entry_id: int) -> list[dict]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM time_entry_corrections WHERE entry_id = ? ORDER BY id DESC", (entry_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def restore_backup(self, payload: bytes) -> None:
        if not payload.startswith(b"SQLite format 3\x00") or len(payload) > 50 * 1024 * 1024:
            raise ValueError("Выберите SQLite-копию WorkTimer размером до 50 МБ")
        descriptor, temporary = tempfile.mkstemp(prefix="worktimer-import-", suffix=".db", dir=self.path.parent)
        candidate = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(payload)
            connection = sqlite3.connect(f"file:{candidate.as_posix()}?mode=ro", uri=True)
            try:
                if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValueError("Копия базы повреждена")
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                if not {
                    "schema_versions",
                    "app_settings",
                    "scenarios",
                    "phases",
                    "tasks",
                    "time_entries",
                    "timer_sessions",
                    "task_groups",
                }.issubset(tables):
                    raise ValueError("Это не база WorkTimer")
                version = connection.execute("SELECT MAX(version) FROM schema_versions").fetchone()[0]
                if not isinstance(version, int) or version < 1:
                    raise ValueError("В копии отсутствует версия схемы")
                if version > self.LATEST_SCHEMA_VERSION:
                    raise ValueError("Копия создана более новой версией приложения")
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ValueError("В копии нарушены связи данных")
                for row in connection.execute("SELECT value_json FROM app_settings"):
                    json.loads(row[0])
            finally:
                connection.close()
            imported = SQLiteDatabase(candidate)
            imported.migrate()
            for scenario in imported.list_scenarios():
                scenario.validate()
            for task in imported.list_tasks(include_archived=True):
                task.validate()
            with self._storage_lock:
                self.backup(label="before-import")
                os.replace(candidate, self.path)
        except sqlite3.DatabaseError as error:
            raise ValueError("Не удалось прочитать копию базы") from error
        finally:
            candidate.unlink(missing_ok=True)

    def correct_time_entry(self, entry_id: int, elapsed_seconds: int) -> None:
        with self._connection() as connection:
            previous = connection.execute(
                "SELECT elapsed_seconds FROM time_entries WHERE id = ? AND ended_at IS NOT NULL", (entry_id,)
            ).fetchone()
            if previous is None:
                raise KeyError(f"Запись времени {entry_id} не найдена или ещё активна")
            connection.execute(
                "INSERT INTO time_entry_corrections(entry_id, old_seconds, new_seconds, corrected_at) VALUES (?, ?, ?, ?)",
                (
                    entry_id,
                    previous[0],
                    max(0, min(elapsed_seconds, 31_536_000)),
                    datetime.now().astimezone().isoformat(timespec="seconds"),
                ),
            )
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
        if row is None:
            return default
        try:
            return json.loads(str(row["value_json"]))
        except ValueError:
            logger.warning("Повреждена настройка %s; используется значение по умолчанию", key)
            return default

    def import_legacy_json(self, settings_path: str | Path) -> int:
        """Однократно импортировать legacy-профили, не перезаписывая SQLite."""
        if self.get_setting("legacy_import_completed", False):
            return 0
        path = Path(settings_path)
        if not path.exists():
            return 0
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except OSError, ValueError:
            logger.exception("Legacy JSON не прочитан; оригинал сохранён")
            self.set_setting(
                "migration_warning",
                "Старые настройки не прочитаны. Оригинальный файл сохранён; проверьте журнал приложения.",
            )
            return 0
        profiles = raw.get("profiles", {}) if isinstance(raw, dict) else {}
        if not isinstance(profiles, dict):
            self.set_setting("migration_warning", "Некорректный формат старых сценариев; исходный JSON сохранён.")
            return 0
        existing = {item.name.casefold(): item for item in self.list_scenarios()}
        imported = 0
        for name, profile in profiles.items():
            if not isinstance(name, str) or not isinstance(profile, dict):
                continue
            if name.casefold() in existing:
                continue
            raw_phases = profile.get("phases", [])
            if not raw_phases and ("work_seconds" in profile or "work" in profile):
                try:
                    work = (
                        int(profile["work_seconds"]) if "work_seconds" in profile else int(profile.get("work", 0)) * 60
                    )
                    rest = (
                        int(profile["rest_seconds"]) if "rest_seconds" in profile else int(profile.get("rest", 0)) * 60
                    )
                except ValueError, TypeError:
                    logger.warning("Пропущена некорректная длительность legacy-сценария")
                    continue
                raw_phases = [
                    {"name": "Работа", "duration_seconds": work, "color_role": "work"},
                    {"name": "Отдых", "duration_seconds": rest, "color_role": "rest"},
                ]
            if not isinstance(raw_phases, list):
                continue
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
                            repeat_policy=PhaseRepeatPolicy(raw_phase.get("repeat_policy", "every_cycle")),
                            sound_enabled=bool(raw_phase.get("sound_enabled", True)),
                            notification_enabled=bool(raw_phase.get("notification_enabled", True)),
                            note=str(raw_phase.get("note", "")),
                            position=position,
                        )
                    )
                    phases[-1].validate()
                except TypeError, ValueError:
                    continue
            if phases:
                try:
                    saved = self.save_scenario(Scenario(name=name, phases=tuple(phases)))
                    existing[name.casefold()] = saved
                    imported += 1
                except ValueError:
                    logger.warning("Пропущен некорректный legacy-сценарий")
        self.set_setting("legacy_import_completed", True)
        active_name = raw.get("active_profile")
        if isinstance(active_name, str):
            self.set_setting("active_scenario_name", active_name)
            active = existing.get(active_name.casefold())
            if active and self.get_setting("active_scenario_id") is None:
                self.set_setting("active_scenario_id", active.id)
        if self.get_setting("app_preferences") is None:
            settings = raw.get("settings", {})
            if not isinstance(settings, dict):
                settings = {}
            self.set_setting(
                "app_preferences",
                {
                    "sound_enabled": bool(settings.get("sound_enabled", True)),
                    "dnd": bool(settings.get("dnd", raw.get("dnd", False))),
                    "auto_start_next_phase": bool(settings.get("auto_switch", False)),
                },
            )
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
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except OSError, ValueError:
            logger.exception("Legacy-журнал не прочитан; оригинал сохранён")
            return 0
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
            id=int(row["id"]),
            group_id=row["group_id"],
            title=str(row["title"]),
            description=str(row["description"]),
            status=TaskStatus(str(row["status"])),
            estimate_seconds=row["estimate_seconds"],
            tags=tuple(json.loads(str(row["tags_json"]))),
            position=int(row["position"]),
        )
