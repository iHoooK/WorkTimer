from __future__ import annotations

import base64
import csv
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient

from app.domain import Phase, Scenario, Task
from app.services import ScenarioController
from app.storage import SQLiteDatabase
from app.web import create_web_app
from core.events import EventBus
from core.timer import TimerEngine


class HTTPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = SQLiteDatabase(Path(self.temp.name) / "test.db")
        self.db.migrate()
        self.bus = EventBus()
        self.timer = TimerEngine(self.bus)
        self.controller = ScenarioController(self.db, self.timer, self.bus)
        self.client = TestClient(
            create_web_app(self.db, controller=self.controller),
            base_url="http://127.0.0.1",
            raise_server_exceptions=False,
        )
        self.client.headers["x-worktimer-token"] = self.client.get("/api/bootstrap").json()["token"]

    def tearDown(self):
        self.controller.stop()
        self.timer.close()
        self.client.close()
        self.temp.cleanup()

    def scenario(self):
        response = self.client.post(
            "/api/scenarios",
            json={
                "name": "Live",
                "progress_total": 3,
                "phases": [
                    {
                        "name": "Focus",
                        "duration_seconds": 90,
                        "color_role": "work",
                        "progress_marker": True,
                        "sound_enabled": False,
                        "notification_enabled": False,
                    },
                    {"name": "Rest", "duration_seconds": 30, "color_role": "rest"},
                ],
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_foreign_origin_and_missing_token_never_change_timer(self):
        self.assertEqual(
            self.client.post("/api/timer/free", headers={"origin": "https://evil.example"}).status_code, 403
        )
        self.assertEqual(self.client.post("/api/timer/free", headers={"x-worktimer-token": ""}).status_code, 403)
        self.assertEqual(self.timer.state.phase.value, "idle")

    def test_localhost_host_guard_and_traversal(self):
        self.assertEqual(self.client.get("/api/health", headers={"host": "evil.example"}).status_code, 400)
        self.assertEqual(self.client.get("/assets/%2e%2e%2f%2e%2e%2fREADME.md").status_code, 404)

    def test_live_extension_and_save_preserve_second_of_three(self):
        scenario = self.scenario()
        self.client.post(f"/api/scenarios/{scenario['id']}/select")
        self.client.post("/api/timer/toggle")
        self.client.post("/api/timer/next")
        before = self.client.post("/api/timer/next").json()
        self.assertEqual(before["progress_current"], 2)
        added = self.client.post("/api/timer/add-cycle").json()
        self.assertEqual(added["progress_total"], 4)
        self.assertEqual(added["run_id"], before["run_id"])
        scenario["progress_total"] = 5
        saved = self.client.put(f"/api/scenarios/{scenario['id']}", json=scenario)
        self.assertEqual(saved.status_code, 200, saved.text)
        state = self.client.get("/api/state").json()
        self.assertEqual(state["progress_current"], 2)
        self.assertEqual(state["progress_total"], 5)
        self.assertEqual(state["run_id"], before["run_id"])
        self.assertEqual(state["phase"], "running")
        self.assertFalse(saved.json()["phases"][0]["sound_enabled"])
        self.assertEqual(saved.json()["phases"][0]["duration_seconds"], 90)

    def test_finite_duplicate_and_conflicting_names(self):
        scenario = self.scenario()
        duplicate = self.client.post(f"/api/scenarios/{scenario['id']}/duplicate")
        self.assertEqual(duplicate.status_code, 201)
        self.assertEqual(duplicate.json()["progress_total"], 3)
        self.assertEqual(self.client.post("/api/scenarios", json=scenario).status_code, 409)

    def test_invalid_objects_and_fields_are_client_errors(self):
        self.assertEqual(self.client.post("/api/scenarios/9999/select").status_code, 404)
        self.assertEqual(self.client.post("/api/task-groups", json={"name": "Bad", "parent_id": 9999}).status_code, 422)
        self.assertEqual(self.client.post("/api/scenarios", json={"name": "", "phases": []}).status_code, 422)
        self.assertEqual(self.client.get("/api/analytics?date_from=invalid").status_code, 422)
        self.assertEqual(self.client.get("/api/analytics?date_from=2026-02-01&date_to=2026-01-01").status_code, 422)

    def test_filters_apply_to_entries_and_all_analytics(self):
        scenario = self.scenario()
        for phase in scenario["phases"]:
            entry = self.db.create_time_entry(task_id=None, scenario_id=scenario["id"], phase_id=phase["id"])
            self.db.finish_time_entry(entry, 30)
        selected = self.client.get("/api/analytics?date_from=2020-01-01&date_to=2020-01-02").json()
        self.assertEqual(selected["total_seconds"], 0)
        self.assertEqual(selected["tasks"], [])
        self.assertEqual(len(selected["days"]), 2)
        actual = self.client.get(f"/api/analytics?date_from={date.today()}&date_to={date.today()}").json()
        self.assertEqual(actual["work_seconds"], 30)
        self.assertEqual(actual["rest_seconds"], 30)
        self.assertEqual(actual["total_seconds"], 60)

    def test_csv_exports_beyond_thousand_and_escapes_formula(self):
        task = self.db.save_task(Task(" =SUM(1,2)"))
        with self.db._connection() as conn:
            conn.executemany(
                "INSERT INTO time_entries(task_id, started_at, ended_at, elapsed_seconds, phase_role, task_title_snapshot) VALUES (?, ?, ?, 1, 'work', ?)",
                [(task.id, "2026-01-01", "2026-01-01", " =SUM(1,2)")] * 1005,
            )
        response = self.client.get("/api/history.csv")
        rows = list(csv.reader(io.StringIO(response.text.lstrip("\ufeff"))))
        self.assertEqual(len(rows), 1006)
        self.assertTrue(rows[1][3].startswith("'"))
        page = self.client.get("/api/history?limit=100&offset=1000").json()
        self.assertEqual(len(page["items"]), 5)
        self.assertFalse(page["has_more"])

    def test_backup_roundtrip_and_invalid_import_keep_original(self):
        scenario = self.scenario()
        exported = self.client.get("/api/data/export")
        self.assertEqual(exported.status_code, 200)
        invalid = self.client.post("/api/data/import", json={"data": base64.b64encode(b"not a database").decode()})
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(self.db.get_scenario(scenario["id"]).name, "Live")
        self.db.save_scenario(Scenario("Extra", (Phase("Work", 60),)))
        restored = self.client.post("/api/data/import", json={"data": base64.b64encode(exported.content).decode()})
        self.assertEqual(restored.status_code, 200, restored.text)
        self.assertEqual(len(self.db.list_scenarios()), 1)
        self.assertTrue(list((self.db.path.parent / "backups").glob("*.db")))

    def test_group_depth_and_archive_restore(self):
        parent = self.client.post("/api/task-groups", json={"name": "Main"}).json()
        child = self.client.post("/api/task-groups", json={"name": "Child", "parent_id": parent["id"]}).json()
        self.assertEqual(
            self.client.post("/api/task-groups", json={"name": "Too deep", "parent_id": child["id"]}).status_code, 422
        )
        scenario = self.scenario()
        self.assertEqual(self.client.delete(f"/api/scenarios/{scenario['id']}").status_code, 204)
        self.assertEqual(self.client.post(f"/api/scenarios/{scenario['id']}/restore").status_code, 200)
        self.assertFalse(self.db.get_scenario(scenario["id"]).is_archived)


if __name__ == "__main__":
    unittest.main()
