from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.domain.models import Phase, PhaseRepeatPolicy, Scenario
from app.storage.sqlite_database import SQLiteDatabase


class SQLiteDatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.path = Path(self._temp.name) / "worktimer.db"
        self.database = SQLiteDatabase(self.path)
        self.database.migrate()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_round_trip_scenario_preserves_repeat_policy(self) -> None:
        saved = self.database.save_scenario(
            Scenario(
                name="Стрим",
                phases=(
                    Phase("Подготовка", 600, repeat_policy=PhaseRepeatPolicy.ONCE_AT_START),
                    Phase("Работа", 1800, color_role="work"),
                    Phase("Отдых", 300, color_role="rest"),
                ),
            )
        )

        self.assertIsNotNone(saved.id)
        restored = self.database.get_scenario(saved.id or 0)
        self.assertEqual([phase.name for phase in restored.phases], ["Подготовка", "Работа", "Отдых"])
        self.assertEqual(restored.phases[0].repeat_policy, PhaseRepeatPolicy.ONCE_AT_START)
        self.assertEqual(restored.phase_for_next(2, is_first_run=False).name, "Работа")

    def test_import_legacy_json_is_one_time(self) -> None:
        legacy_path = Path(self._temp.name) / "settings.json"
        legacy_path.write_text(
            json.dumps(
                {
                    "active_profile": "Работа",
                    "profiles": {
                        "Работа": {
                            "phases": [{"name": "Работа", "duration_seconds": 1500, "color_role": "work"}]
                        }
                    },
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.assertEqual(self.database.import_legacy_json(legacy_path), 1)
        self.assertEqual(self.database.import_legacy_json(legacy_path), 0)
        self.assertEqual(self.database.get_setting("active_scenario_name"), "Работа")

    def test_import_legacy_journal_preserves_original_event(self) -> None:
        journal_path = Path(self._temp.name) / "journal.json"
        journal_path.write_text(
            json.dumps({"events": [{"event_type": "timer.finished", "note": "готово"}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        self.assertEqual(self.database.import_legacy_journal(journal_path), 1)
        self.assertEqual(self.database.import_legacy_journal(journal_path), 0)
        self.assertEqual(self.database.legacy_journal_event_count(), 1)

    def test_duplicate_and_archive_scenario(self) -> None:
        saved = self.database.save_scenario(Scenario("Работа", (Phase("Работа", 60),)))
        duplicate = self.database.duplicate_scenario(saved.id or 0)
        self.assertEqual(duplicate.name, "Работа — копия")
        self.database.archive_scenario(saved.id or 0)
        self.assertTrue(self.database.get_scenario(saved.id or 0).is_archived)


    def test_editing_scenario_keeps_existing_time_entry(self) -> None:
        saved = self.database.save_scenario(Scenario("Focus", (Phase("Work", 60),)))
        entry_id = self.database.create_time_entry(
            task_id=None,
            scenario_id=saved.id,
            phase_id=saved.phases[0].id,
        )
        self.database.finish_time_entry(entry_id, 42)

        self.database.save_scenario(Scenario("Focus", (Phase("Deep work", 90),), id=saved.id))

        history = self.database.list_time_entries()
        self.assertEqual(history[0]["elapsed_seconds"], 42)
        self.assertEqual(history[0]["scenario_name"], "Focus")
        self.assertIsNone(history[0]["phase_name"])


if __name__ == "__main__":
    unittest.main()
