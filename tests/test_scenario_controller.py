from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.domain import Task
from app.domain.models import Phase, PhaseRepeatPolicy, Scenario
from app.services import ScenarioController
from app.storage import SQLiteDatabase
from core.events import EventBus
from core.timer import TimerEngine


class ScenarioControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        database = SQLiteDatabase(Path(self._temp.name) / "worktimer.db")
        database.migrate()
        saved = database.save_scenario(
            Scenario(
                name="Стрим",
                phases=(
                    Phase("Подготовка", 600, repeat_policy=PhaseRepeatPolicy.ONCE_AT_START),
                    Phase("Работа", 1800, color_role="work"),
                    Phase("Отдых", 300, color_role="rest"),
                ),
            )
        )
        self.database = database
        self.bus = EventBus()
        self.timer = TimerEngine(self.bus)
        self.controller = ScenarioController(database, self.timer, self.bus)
        self.controller.select_scenario(saved.id or 0)

    def tearDown(self) -> None:
        self.controller.stop()
        self.timer.close()
        self._temp.cleanup()

    def test_once_at_start_is_skipped_after_first_cycle(self) -> None:
        self.controller.start_from_beginning()
        self.assertEqual(self.controller.to_dict()["current_phase_name"], "Подготовка")
        self.controller.next_phase()
        self.assertEqual(self.controller.to_dict()["current_phase_name"], "Работа")
        self.controller.next_phase()
        self.assertEqual(self.controller.to_dict()["current_phase_name"], "Отдых")
        self.controller.next_phase()
        self.assertEqual(self.controller.to_dict()["current_phase_name"], "Работа")
        self.assertFalse(self.controller.to_dict()["is_first_cycle"])

    def test_start_from_beginning_restores_preparation(self) -> None:
        self.controller.start_from_beginning()
        self.controller.next_phase()
        self.controller.next_phase()
        self.controller.next_phase()
        self.controller.start_from_beginning()
        self.assertEqual(self.controller.to_dict()["current_phase_name"], "Подготовка")

    def test_selected_task_receives_time_entry(self) -> None:
        task = self.database.save_task(Task("Панель"))
        self.controller.select_task(task.id)
        self.controller.start_from_beginning()
        self.controller.stop()
        summary = self.database.time_summary_by_task()
        self.assertEqual(summary[0]["task_id"], task.id)
        self.assertGreaterEqual(summary[0]["elapsed_seconds"], 0)

    def test_free_mode_counts_up_and_can_stop(self) -> None:
        self.controller.start_free()
        self.assertEqual(self.timer.state.mode.value, "free")
        self.assertEqual(self.timer.state.phase.value, "running")
        self.controller.stop()
        self.assertEqual(self.timer.state.phase.value, "idle")

    def test_pomodoro_creates_reusable_scenario(self) -> None:
        self.controller.start_pomodoro(60, 60)
        self.assertEqual(self.controller.to_dict()["scenario_name"], "Pomodoro")
        self.assertEqual(self.controller.to_dict()["current_phase_name"], "Фокус")

    def test_pomodoro_adds_long_break_after_configured_cycles(self) -> None:
        self.controller.start_pomodoro(60, 60, 120, 2)
        scenario = self.controller.scenario
        self.assertIsNotNone(scenario)
        self.assertEqual([phase.name for phase in scenario.phases], ["Фокус", "Отдых", "Фокус 2", "Длинный отдых"])

    def test_can_start_a_specific_phase_manually(self) -> None:
        self.controller.start_phase(1)
        self.assertEqual(self.controller.to_dict()["current_phase_name"], "Работа")

    def test_state_exposes_next_phase_for_obs_scene(self) -> None:
        self.controller.start_from_beginning()
        self.assertEqual(self.controller.to_dict()["next_phase_name"], "Работа")

    def test_progress_counts_when_work_phase_starts_and_stops_after_limit(self) -> None:
        scenario = self.database.save_scenario(
            Scenario(
                name="Конечный стрим",
                progress_total=4,
                phases=(
                    Phase("Подготовка", 60, repeat_policy=PhaseRepeatPolicy.ONCE_AT_START),
                    Phase("Работа", 60, color_role="work", progress_marker=True),
                    Phase("Отдых", 60, color_role="rest"),
                ),
            )
        )
        self.controller.select_scenario(scenario.id or 0)
        self.controller.start_from_beginning()
        self.assertEqual(self.controller.to_dict()["progress_current"], 0)
        self.controller.next_phase()
        self.assertEqual(self.controller.to_dict()["progress_current"], 1)
        for expected in (2, 3, 4):
            self.controller.next_phase()  # отдых
            self.assertEqual(self.controller.to_dict()["progress_current"], expected - 1)
            self.controller.next_phase()  # следующая работа
            self.assertEqual(self.controller.to_dict()["progress_current"], expected)
        self.controller.next_phase()  # последний отдых
        self.controller.next_phase()  # сценарий завершён, новая работа не начинается
        state = self.controller.to_dict()
        self.assertEqual(state["progress_current"], 4)
        self.assertTrue(state["scenario_completed"])
        self.assertIsNone(state["next_phase_name"])


if __name__ == "__main__":
    unittest.main()
