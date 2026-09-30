from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from app.domain import Phase, Scenario
from app.services import ScenarioController
from app.storage import SQLiteDatabase
from core.events import Event, EventBus
from core.timer import EVENT_FINISHED, EVENT_TICK, TimerEngine


class MigrationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "worktimer.db"

    def tearDown(self):
        self.temp.cleanup()

    def create_v3(self):
        connection = sqlite3.connect(self.path)
        connection.executescript((Path(__file__).parent / "fixtures/schema_v3.sql").read_text(encoding="utf-8"))
        connection.execute("INSERT INTO scenarios(id,name) VALUES(1,'Legacy')")
        connection.execute(
            "INSERT INTO phases(id,scenario_id,position,name,duration_seconds,color_role) VALUES(1,1,0,'Work',90,'work')"
        )
        connection.execute(
            "INSERT INTO time_entries(scenario_id,phase_id,started_at,ended_at,elapsed_seconds,source) VALUES(1,1,'2026-09-01T12:00:00+03:00','2026-09-01T12:01:00+03:00',60,'timer')"
        )
        connection.commit()
        connection.close()

    def test_v3_migration_preserves_history_and_backs_up_original(self):
        self.create_v3()
        db = SQLiteDatabase(self.path)
        db.migrate()
        self.assertEqual(db.list_time_entries()[0]["phase_name"], "Work")
        backups = list((self.path.parent / "backups").glob("*.db"))
        self.assertEqual(len(backups), 1)
        with closing(sqlite3.connect(backups[0])) as connection:
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_versions").fetchone()[0], 3)
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_versions").fetchone()[0], 4)

    def test_failed_upgrade_rolls_back_schema_and_retries(self):
        self.create_v3()

        class FailedMigration(SQLiteDatabase):
            def _upgrade_v4(self, connection):
                super()._upgrade_v4(connection)
                raise RuntimeError("Injected disk failure")

        with self.assertRaises(RuntimeError):
            FailedMigration(self.path).migrate()
        with closing(sqlite3.connect(self.path)) as connection:
            columns = {x[1] for x in connection.execute("PRAGMA table_info(time_entries)")}
            self.assertNotIn("phase_name_snapshot", columns)
            self.assertEqual(connection.execute("SELECT MAX(version) FROM schema_versions").fetchone()[0], 3)
        SQLiteDatabase(self.path).migrate()

    def test_completed_phase_keeps_session_open_across_restart(self):
        db = SQLiteDatabase(self.path)
        db.migrate()
        db.save_scenario(Scenario("Work", (Phase("Work", 1), Phase("Rest", 1, color_role="rest"))))
        bus = EventBus()
        timer = TimerEngine(bus)
        controller = ScenarioController(db, timer, bus)
        controller.start()
        session = controller.to_dict()["session_id"]
        deadline = time.monotonic() + 3
        while not timer.state.is_finished and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(timer.state.is_finished)
        # Ensure the event handler has committed the finished checkpoint.
        controller._on_timer_ended(Event(EVENT_FINISHED, timer.state))
        controller.suspend_for_exit()
        timer.close()
        bus = EventBus()
        timer = TimerEngine(bus)
        restored = ScenarioController(db, timer, bus)
        try:
            self.assertEqual(restored.to_dict()["session_id"], session)
            self.assertEqual(db.list_sessions()[0]["status"], "running")
            restored.next_phase()
            self.assertEqual(restored.to_dict()["session_id"], session)
        finally:
            restored.stop()
            timer.close()

    def test_slow_subscriber_does_not_lengthen_countdown(self):
        bus = EventBus()
        timer = TimerEngine(bus)
        bus.subscribe(EVENT_TICK, lambda event: time.sleep(0.15))
        started = time.monotonic()
        timer.start(1)
        try:
            deadline = started + 3
            while not timer.state.is_finished and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(timer.state.is_finished)
            self.assertLess(time.monotonic() - started, 1.6)
            self.assertEqual(timer.state.elapsed_seconds, 1)
        finally:
            timer.close()

    def test_invalid_legacy_number_does_not_prevent_valid_import(self):
        db = SQLiteDatabase(self.path)
        db.migrate()
        legacy = self.path.with_suffix(".json")
        legacy.write_text(
            json.dumps({"profiles": {"Bad": {"work": "bad"}, "Good": {"work": 25, "rest": 5}}}), encoding="utf-8"
        )
        self.assertEqual(db.import_legacy_json(legacy), 1)
        self.assertEqual(db.list_scenarios()[0].name, "Good")


if __name__ == "__main__":
    unittest.main()
