from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.domain import Task, TaskGroup, TaskStatus
from app.storage import SQLiteDatabase


class TaskStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.database = SQLiteDatabase(Path(self._temp.name) / "worktimer.db")
        self.database.migrate()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_group_and_task_round_trip(self) -> None:
        parent = self.database.save_task_group(TaskGroup("WorkTimer"))
        group = self.database.save_task_group(TaskGroup("Web", parent_id=parent.id))
        task = self.database.save_task(Task("Редактор сценариев", group_id=group.id, estimate_seconds=3_600))
        done = self.database.save_task(Task(id=task.id, title=task.title, group_id=group.id, status=TaskStatus.DONE))
        self.assertEqual(self.database.list_task_groups()[1].parent_id, parent.id)
        self.assertEqual(done.status, TaskStatus.DONE)
        self.assertEqual(self.database.list_tasks()[0].title, "Редактор сценариев")

    def test_analytics_reads_finished_time_entry(self) -> None:
        task = self.database.save_task(Task("Аналитика"))
        entry_id = self.database.create_time_entry(task_id=task.id, scenario_id=None, phase_id=None)
        self.database.finish_time_entry(entry_id, 600)
        self.assertEqual(self.database.time_summary_by_task()[0]["elapsed_seconds"], 600)
        self.assertEqual(self.database.time_summary_by_day()[0]["elapsed_seconds"], 600)
        self.assertEqual(self.database.list_time_entries()[0]["task_title"], "Аналитика")

    def test_task_tags_round_trip(self) -> None:
        task = self.database.save_task(Task("OBS", tags=("stream", "urgent")))
        self.assertEqual(task.tags, ("stream", "urgent"))

    def test_filters_and_corrects_finished_time_entry(self) -> None:
        task = self.database.save_task(Task("Фильтр"))
        entry_id = self.database.create_time_entry(task_id=task.id, scenario_id=None, phase_id=None)
        self.database.finish_time_entry(entry_id, 10)
        self.database.correct_time_entry(entry_id, 90)
        history = self.database.list_time_entries(task_id=task.id)
        self.assertEqual(history[0]["elapsed_seconds"], 90)
        self.assertEqual(history[0]["source"], "manual")


if __name__ == "__main__":
    unittest.main()
