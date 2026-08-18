from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

from app.storage.sqlite_database import SQLiteDatabase
from app.web.server import ScenarioPayload, TaskGroupPayload, TaskPayload, create_web_app
from app.services import ScenarioController
from core.events import EventBus
from core.timer import TimerEngine


class WebServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        database = SQLiteDatabase(Path(self._temp.name) / "worktimer.db")
        database.migrate()
        self.timer = TimerEngine(EventBus())
        self.app = create_web_app(database, controller=ScenarioController(database, self.timer))

    def tearDown(self) -> None:
        self.timer.stop()
        self._temp.cleanup()

    def _endpoint(self, path: str, method: str = "GET"):
        return next(
            route.endpoint
            for route in self.app.routes
            if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
        )

    def test_health_and_scenario_api(self) -> None:
        self.assertEqual(self._endpoint("/api/health")(), {"status": "ok"})
        self.assertEqual(self._endpoint("/api/state")()["phase"], "idle")
        created = self._endpoint("/api/scenarios", "POST")(
            ScenarioPayload.model_validate(
                {
                    "name": "Стрим",
                    "phases": [
                        {"name": "Подготовка", "duration_seconds": 600, "repeat_policy": "once_at_start"},
                        {"name": "Работа", "duration_seconds": 1800},
                    ],
                }
            )
        )
        self.assertEqual(created["phases"][0]["repeat_policy"], "once_at_start")
        self.assertEqual(self._endpoint("/api/scenarios")()["items"][0]["name"], "Стрим")
        selected = self._endpoint("/api/scenarios/{scenario_id}/select", "POST")(created["id"])
        self.assertEqual(selected["scenario_name"], "Стрим")
        started = self._endpoint("/api/timer/toggle", "POST")()
        self.assertEqual(started["phase"], "running")
        self.assertEqual(self._endpoint("/api/timer/repeat", "POST")()["phase"], "running")

    def test_rejects_invalid_scenario(self) -> None:
        with self.assertRaises(ValidationError):
            ScenarioPayload.model_validate({"name": "", "phases": []})

    def test_overlay_routes_are_limited_to_known_templates(self) -> None:
        overlay = self._endpoint("/overlay/{overlay_name}")
        self.assertTrue(str(overlay("minimal").path).endswith("web\\overlays\\minimal.html"))
        self.assertTrue(str(overlay("progress").path).endswith("web\\overlays\\progress.html"))
        with self.assertRaises(Exception):
            overlay("unknown")

    def test_scenario_api_persists_progress_configuration(self) -> None:
        created = self._endpoint("/api/scenarios", "POST")(
            ScenarioPayload.model_validate(
                {
                    "name": "Stream loop",
                    "progress_total": 4,
                    "phases": [
                        {"name": "Starting", "duration_seconds": 300, "repeat_policy": "once_at_start"},
                        {"name": "Work", "duration_seconds": 2100, "color_role": "work", "progress_marker": True},
                        {"name": "Break", "duration_seconds": 300, "color_role": "rest"},
                    ],
                }
            )
        )
        self.assertEqual(created["progress_total"], 4)
        self.assertTrue(created["phases"][1]["progress_marker"])
        listed = self._endpoint("/api/scenarios")()["items"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "Stream loop")

    def test_dashboard_and_assets_disable_cache(self) -> None:
        dashboard = self._endpoint("/")()
        asset = self._endpoint("/assets/{asset_path:path}")("app.js")
        self.assertEqual(dashboard.headers["cache-control"], "no-store, max-age=0")
        self.assertEqual(asset.headers["cache-control"], "no-store, max-age=0")

    def test_task_api_creates_group_and_task(self) -> None:
        group = self._endpoint("/api/task-groups", "POST")(TaskGroupPayload(name="WorkTimer"))
        task = self._endpoint("/api/tasks", "POST")(TaskPayload(title="Новая панель", group_id=group["id"]))
        self.assertEqual(task["title"], "Новая панель")
        self.assertEqual(self._endpoint("/api/tasks")()["items"][0]["group_id"], group["id"])


    def test_creates_stream_preset(self) -> None:
        created = self._endpoint("/api/scenarios/presets/{preset_name}", "POST")("stream")
        self.assertEqual(created["name"], "Стрим")
        self.assertEqual(created["phases"][0]["repeat_policy"], "once_at_start")


if __name__ == "__main__":
    unittest.main()
