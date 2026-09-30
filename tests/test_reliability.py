from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from app.desktop.bridge import DesktopBridge
from app.domain import Phase, Scenario
from app.services import ScenarioController
from app.storage import SQLiteDatabase
from core.events import Event, EventBus
from core.timer import EVENT_FINISHED, TimerEngine, TimerPhase


class ReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = SQLiteDatabase(Path(self.temp.name) / "worktimer.db")
        self.db.migrate()
        self.clock_value = 100.0
        self.bus = EventBus()
        self.timer = TimerEngine(self.bus, clock=lambda: self.clock_value)
        self.timer._TICK_INTERVAL = 0.01
        self.scenario = self.db.save_scenario(
            Scenario(
                "Work",
                (
                    Phase(
                        "Focus",
                        90,
                        color_role="work",
                        progress_marker=True,
                        sound_enabled=False,
                        notification_enabled=False,
                    ),
                    Phase("Rest", 30, color_role="rest"),
                ),
                progress_total=3,
            )
        )
        self.controller = ScenarioController(self.db, self.timer, self.bus)

    def tearDown(self):
        self.controller.stop()
        self.timer.close()
        self.temp.cleanup()

    def test_add_cycle_keeps_live_phase_and_time(self):
        self.controller.start()
        self.clock_value += 22.5
        before = self.controller.to_dict()
        self.controller.add_cycle()
        after = self.controller.to_dict()
        self.assertEqual(after["progress_total"], 4)
        for key in ("run_id", "time", "phase", "current_phase_id", "progress_current", "session_id"):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(self.db.get_scenario(self.scenario.id).progress_total, 4)

    def test_save_paused_scenario_preserves_phase_time_and_flags(self):
        self.controller.start()
        self.clock_value += 15
        self.controller.start()
        before = self.timer.state
        self.controller.save_scenario(replace(self.scenario, progress_total=4, name="Renamed"))
        after = self.timer.state
        self.assertEqual(before, after)
        self.assertFalse(self.controller.scenario.phases[0].sound_enabled)
        self.assertEqual(self.controller.scenario.phases[0].duration_seconds, 90)

    def test_reorder_keeps_ids_and_updates_current_position(self):
        self.controller.start()
        saved = self.controller.save_scenario(replace(self.scenario, phases=tuple(reversed(self.scenario.phases))))
        self.assertEqual(saved.phases[1].id, self.scenario.phases[0].id)
        self.assertEqual(self.controller.to_dict()["current_phase_position"], 1)
        self.assertEqual(self.controller.to_dict()["phase"], "running")

    def test_history_keeps_original_phase_and_scenario_names(self):
        self.controller.start()
        self.clock_value += 12
        self.controller.stop()
        self.controller.save_scenario(
            replace(
                self.scenario,
                name="New",
                phases=(replace(self.scenario.phases[0], name="New Focus"), self.scenario.phases[1]),
            )
        )
        history = self.db.list_time_entries()
        self.assertEqual(history[0]["phase_name"], "Focus")
        self.assertEqual(history[0]["scenario_name"], "Work")
        self.assertEqual(history[0]["elapsed_seconds"], 12)

    def test_finite_duplicate_preserves_total(self):
        duplicate = self.db.duplicate_scenario(self.scenario.id)
        self.assertEqual(duplicate.progress_total, 3)
        self.assertTrue(duplicate.phases[0].progress_marker)
        self.assertNotEqual(duplicate.phases[0].id, self.scenario.phases[0].id)

    def test_restart_restores_checkpoint_paused_without_counting_downtime(self):
        self.controller.start()
        self.clock_value += 19.25
        self.controller._checkpoint()
        self.timer.close()  # Simulate process gone; controller did not close interval.
        bus = EventBus()
        timer = TimerEngine(bus, clock=lambda: self.clock_value)
        restored = ScenarioController(self.db, timer, bus)
        try:
            self.assertEqual(timer.state.phase, TimerPhase.PAUSED)
            self.assertEqual(timer.state.elapsed_seconds, 19)
            self.assertTrue(restored.to_dict()["recovered"])
            self.assertEqual(restored.to_dict()["progress_current"], 1)
            self.clock_value += 1000
            self.assertEqual(timer.state.elapsed_seconds, 19)
            restored.start()
            self.clock_value += 5
            restored.stop()
            self.assertEqual(self.db.list_time_entries()[0]["elapsed_seconds"], 24)
        finally:
            restored.stop()
            timer.close()

    def test_pause_excludes_time_and_delayed_tick_does_not_slow_clock(self):
        self.controller.start()
        self.clock_value += 21.7
        self.assertEqual(self.timer.state.elapsed_seconds, 21)
        self.assertEqual(self.timer.state.remaining_seconds, 69)
        self.controller.start()
        self.clock_value += 500
        self.assertEqual(self.timer.state.elapsed_seconds, 21)
        self.controller.start()
        self.clock_value += 10
        self.assertEqual(self.timer.state.elapsed_seconds, 31)

    def test_stop_after_finished_is_idle(self):
        ended = threading.Event()
        self.bus.subscribe(EVENT_FINISHED, lambda event: ended.set())
        self.controller.start()
        self.clock_value += 100
        self.assertTrue(ended.wait(2))
        self.controller.stop()
        self.assertEqual(self.timer.state.phase, TimerPhase.IDLE)

    def test_stop_cancels_pending_auto_start(self):
        self.db.set_setting("app_preferences", {"auto_start_next_phase": True})
        ended = threading.Event()
        self.bus.subscribe(EVENT_FINISHED, lambda event: ended.set())
        self.controller.start()
        self.clock_value += 100
        self.assertTrue(ended.wait(2))
        self.controller.stop()
        time.sleep(0.35)
        self.assertEqual(self.timer.state.phase, TimerPhase.IDLE)
        self.assertEqual(len(self.db.list_time_entries()), 1)

    def test_phase_notification_and_sound_flags(self):
        calls = []
        bridge = DesktopBridge(
            bus=self.bus,
            controller=self.controller,
            tray=SimpleNamespace(update_tooltip=lambda text: None),
            hotkeys=None,
            sound=SimpleNamespace(
                play_work_end=lambda: calls.append("sound"), play_break_end=lambda: calls.append("sound")
            ),
            notifications=SimpleNamespace(dnd=False, notify=lambda *args: calls.append("notice")),
            database=self.db,
            dashboard_url="",
            on_quit=lambda: None,
        )
        self.controller.start()
        bridge._on_finished(Event(EVENT_FINISHED, self.timer.state))
        self.assertEqual(calls, [])

    def test_pomodoro_keeps_same_named_user_scenario(self):
        custom = self.db.save_scenario(Scenario("Pomodoro", (Phase("Custom", 123),)))
        self.controller.start_pomodoro()
        self.assertEqual(self.db.get_scenario(custom.id).phases[0].name, "Custom")
        self.assertNotEqual(self.controller.scenario.id, custom.id)

    def test_commands_are_serialized_with_one_open_entry(self):
        self.controller.start()
        threads = [threading.Thread(target=self.controller.next_phase) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive())
        with self.db._connection() as conn:
            open_count = conn.execute("SELECT COUNT(*) FROM time_entries WHERE ended_at IS NULL").fetchone()[0]
        self.assertLessEqual(open_count, 1)

    def test_migration_preserves_selected_scenario_and_preferences(self):
        path = Path(self.temp.name) / "settings.json"
        path.write_text(
            json.dumps(
                {
                    "active_profile": "Z",
                    "settings": {"dnd": True, "sound_enabled": False},
                    "profiles": {"Z": {"work_seconds": 120, "rest_seconds": 30}},
                }
            ),
            encoding="utf-8",
        )
        self.db.import_legacy_json(path)
        self.assertEqual(self.db.get_scenario(self.db.get_setting("active_scenario_id")).name, "Z")
        self.assertTrue(self.db.get_setting("app_preferences")["dnd"])
        self.assertFalse(self.db.get_setting("app_preferences")["sound_enabled"])

    def test_manual_correction_keeps_original_value(self):
        entry = self.db.create_time_entry(task_id=None, scenario_id=None, phase_id=None)
        self.db.finish_time_entry(entry, 12)
        self.db.correct_time_entry(entry, 20)
        with self.db._connection() as conn:
            correction = conn.execute("SELECT old_seconds, new_seconds FROM time_entry_corrections").fetchone()
        self.assertEqual(tuple(correction), (12, 20))


if __name__ == "__main__":
    unittest.main()
