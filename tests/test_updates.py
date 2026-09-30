from __future__ import annotations

import hashlib
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from fastapi.testclient import TestClient

from app.product import RELEASES_URL, VERSION
from app.services import ScenarioController
from app.services.updates import Release, UpdateService, installed_directory, latest_release, version_parts
from app.storage import SQLiteDatabase
from app.web import create_web_app
from core.events import EventBus
from core.timer import TimerEngine

NEW_VERSION = "99.0.0"
PAYLOAD = b"MZ verified installer fixture"


def release_data(**overrides):
    asset = {"name": f"WorkTimer-Setup-{NEW_VERSION}.exe",
             "browser_download_url": f"{RELEASES_URL}/download/v{NEW_VERSION}/WorkTimer-Setup-{NEW_VERSION}.exe",
             "size": len(PAYLOAD), "digest": "sha256:" + hashlib.sha256(PAYLOAD).hexdigest()}
    return {"tag_name": f"v{NEW_VERSION}", "draft": False, "prerelease": False,
            "assets": [asset], **overrides}


class ReleaseTests(unittest.TestCase):
    def fetch(self, data):
        with patch("app.services.updates.open_github", return_value=io.BytesIO(json.dumps(data).encode())):
            return latest_release()

    def test_numeric_versions_and_no_downgrades_or_prereleases(self):
        self.assertGreater(version_parts("v1.10.0"), version_parts("1.9.9"))
        for invalid in ("v1.2", "1.2.3-beta", "../1.2.3", "01.2.3", None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                version_parts(invalid)
        self.assertIsNone(self.fetch(release_data(tag_name=VERSION)))
        self.assertIsNone(self.fetch(release_data(tag_name="v0.1.0")))
        self.assertIsNone(self.fetch(release_data(prerelease=True)))
        self.assertIsNone(self.fetch(release_data(draft=True)))

    def test_valid_release_and_reject_remote_assets_and_bad_hash(self):
        self.assertEqual(self.fetch(release_data()).version, NEW_VERSION)
        for overrides in ({"browser_download_url": "https://evil.example/setup.exe"},
                          {"browser_download_url": "https://github.com/other/repo/setup.exe"},
                          {"digest": "sha256:bad"}, {"size": 0}, {"size": True},
                          {"size": 400 * 1024 * 1024}, {"name": "arbitrary.exe"}):
            data = release_data()
            data["assets"][0].update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.fetch(data)

    def test_checksum_fallback_is_bound_to_installer(self):
        data = release_data()
        data["assets"][0].pop("digest")
        data["assets"].append({"name": "SHA256SUMS", "browser_download_url": f"{RELEASES_URL}/download/v{NEW_VERSION}/SHA256SUMS"})
        checksum = f"{hashlib.sha256(PAYLOAD).hexdigest()}  WorkTimer-Setup-{NEW_VERSION}.exe\n".encode()
        with patch("app.services.updates.open_github", side_effect=[io.BytesIO(json.dumps(data).encode()), io.BytesIO(checksum)]):
            self.assertEqual(latest_release().sha256, hashlib.sha256(PAYLOAD).hexdigest())

    def test_redirects_reject_non_github_and_http(self):
        from app.services.updates import GitHubRedirectHandler

        for url in ("http://github.com/file", "https://evil.example/file", "https://github.com@evil.example/file"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                GitHubRedirectHandler().redirect_request(None, None, 302, "", {}, url)


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = SQLiteDatabase(self.root / "worktimer.db")
        self.db.migrate()
        self.quit = Mock()
        self.prepare = Mock()
        self.notice = Mock()
        with patch("app.services.updates.installed_directory", return_value=self.root / "Program Files"):
            self.service = UpdateService(self.db, on_quit=self.quit, prepare=self.prepare, on_available=self.notice)
        self.release = Release(NEW_VERSION, f"{RELEASES_URL}/download/v{NEW_VERSION}/WorkTimer-Setup-{NEW_VERSION}.exe",
                               len(PAYLOAD), hashlib.sha256(PAYLOAD).hexdigest())

    def tearDown(self):
        self.service.stop()
        if self.service._worker:
            self.service._worker.join(5)
        self.temp.cleanup()

    def offer(self):
        with patch("app.services.updates.latest_release", return_value=self.release):
            self.service.check()
            self.service._worker.join(5)
        self.assertEqual(self.service.status()["status"], "available")

    def test_check_is_background_throttled_and_handles_offline_and_private_repo(self):
        self.offer()
        self.notice.assert_called_once_with(NEW_VERSION)
        with patch("app.services.updates.latest_release") as fetch:
            self.service.check()
            fetch.assert_not_called()
        self.service._last_request = 0
        with patch("app.services.updates.latest_release", side_effect=HTTPError("https://api.github.com", 404, "", {}, None)):
            self.service.check()
            self.service._worker.join(5)
        self.assertIn("закрыт", self.service.status()["message"])
        self.assertGreater(self.db.get_setting("update_last_check"), time.time() - 10)
        self.service._last_request = 0
        with patch("app.services.updates.latest_release", side_effect=TimeoutError):
            self.service.check()
            self.service._worker.join(5)
        self.assertEqual(self.service.status()["status"], "error")
        self.quit.assert_not_called()

    def test_install_checks_hash_then_waits_for_uac_before_backup_and_quit(self):
        self.offer()
        self.db.set_setting("private", "keep")
        def authorize(*args, **kwargs):
            self.assertEqual(self.service.status()["status"], "authorizing")
            self.prepare.assert_not_called()
            self.quit.assert_not_called()
            self.assertFalse(list((self.root / "backups").glob("*before-update*.db")))

        with patch("app.services.updates.open_github", return_value=io.BytesIO(PAYLOAD)), patch("app.services.updates.launch_installer", side_effect=authorize) as launch:
            self.service.install()
            self.service._worker.join(5)
        self.assertEqual(self.service.status()["status"], "installing")
        self.prepare.assert_called_once()
        self.quit.assert_called_once()
        args, kwargs = launch.call_args
        self.assertNotIn("shell", kwargs)
        self.assertIn(f"/DIR={self.root / 'Program Files'}", args[0])
        self.assertIn(f"/WORKTIMERDATA={self.root}", args[0])
        self.assertIn("/WORKTIMERHANDOFF=1", args[0])
        self.assertTrue(list((self.root / "backups").glob("*before-update*.db")))
        self.assertEqual(self.db.get_setting("private"), "keep")

    def test_corruption_truncation_oversize_and_non_exe_never_launch_or_stop_app(self):
        for content in (b"MZ tampered payload", PAYLOAD[:-1], PAYLOAD + b"extra", b"not an exe"):
            self.offer()
            if content == b"not an exe":
                self.service._release = Release(NEW_VERSION, self.release.url, len(content), hashlib.sha256(content).hexdigest())
            with patch("app.services.updates.open_github", return_value=io.BytesIO(content)), patch("app.services.updates.launch_installer") as launch:
                self.service.install()
                self.service._worker.join(5)
            self.assertEqual(self.service.status()["status"], "error")
            launch.assert_not_called()
            self.quit.assert_not_called()
            self.prepare.assert_not_called()
            self.assertFalse(list((self.root / "updates").glob("*/WorkTimer*.exe")))
            self.service._last_request = 0

    def test_failed_launch_keeps_app_and_can_retry(self):
        self.offer()
        with patch("app.services.updates.open_github", return_value=io.BytesIO(PAYLOAD)), patch("app.services.updates.launch_installer", side_effect=OSError):
            self.service.install()
            self.service._worker.join(5)
        self.assertEqual(self.service.status()["status"], "error")
        self.quit.assert_not_called()
        self.prepare.assert_not_called()
        self.assertEqual(self.db.get_setting("app_preferences", {}).get("auto_check_updates", True), True)

    def test_cancelled_uac_keeps_timer_alive_without_backup_and_allows_retry(self):
        self.offer()
        with patch("app.services.updates.open_github", return_value=io.BytesIO(PAYLOAD)), patch("app.services.updates.launch_installer", side_effect=ValueError("Запрос Windows отменён")):
            self.service.install()
            self.service._worker.join(5)
        self.assertEqual(self.service.status()["status"], "error")
        self.prepare.assert_not_called()
        self.quit.assert_not_called()
        self.assertFalse(list((self.root / "backups").glob("*before-update*.db")))
        with patch("app.services.updates.open_github", return_value=io.BytesIO(PAYLOAD)), patch("app.services.updates.launch_installer"):
            self.service.install()
            self.service._worker.join(5)
        self.quit.assert_called_once()

    def test_portable_cannot_install_and_automatic_check_can_be_disabled(self):
        self.service.directory = None
        self.offer()
        with self.assertRaises(ValueError):
            self.service.install()
        self.db.set_setting("app_preferences", {"auto_check_updates": False})
        self.assertFalse(self.service._automatic_enabled())

    def test_update_api_requires_token_and_same_origin_for_network_and_install(self):
        with TestClient(create_web_app(self.db, updates=self.service), base_url="http://127.0.0.1") as client:
            for endpoint in ("check", "install"):
                self.assertEqual(client.post(f"/api/updates/{endpoint}").status_code, 403)
            token = client.get("/api/bootstrap").json()["token"]
            self.assertEqual(client.post("/api/updates/check", headers={"x-worktimer-token": token, "origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(client.get("/api/updates").json()["current_version"], VERSION)
            with patch.object(self.service, "check", return_value=self.service.status()) as check:
                self.assertEqual(client.post("/api/updates/check", headers={"x-worktimer-token": token}).status_code, 200)
                check.assert_called_once()

    def test_live_session_pause_is_saved_in_backup_and_recovers(self):
        timer = TimerEngine(EventBus())
        controller = ScenarioController(self.db, timer)
        try:
            controller.start_free()
            controller.pause_for_update()
            backup = self.db.backup(label="before-update-test")
            copied = SQLiteDatabase(backup)
            restored_timer = TimerEngine(EventBus())
            try:
                restored = ScenarioController(copied, restored_timer)
                self.assertEqual(restored.to_dict()["phase"], "paused")
                self.assertEqual(restored.to_dict()["mode"], "free")
            finally:
                restored_timer.close()
        finally:
            controller.suspend_for_exit()
            timer.close()


class InstalledDirectoryTests(unittest.TestCase):
    def test_machine_install_and_legacy_user_install_match_running_exe_only(self):
        import winreg

        machine = Path("C:/Program Files/WorkTimer").resolve()
        user = Path("C:/Users/Example/AppData/Local/Programs/WorkTimer").resolve()
        for executable, expected in ((machine / "WorkTimer.exe", machine),
                                     (user / "WorkTimer.exe", user),
                                     (Path("C:/Portable/WorkTimer.exe"), None)):
            with self.subTest(executable=executable), patch("sys.frozen", True, create=True), patch("sys.executable", str(executable)), patch("winreg.OpenKey") as open_key, patch("winreg.QueryValueEx", side_effect=[(str(machine), 1), (str(user), 1)]):
                self.assertEqual(installed_directory(), expected)
                self.assertEqual(open_key.call_args_list[0].args[0], winreg.HKEY_LOCAL_MACHINE)
                if expected != machine:
                    self.assertEqual(open_key.call_args_list[1].args[0], winreg.HKEY_CURRENT_USER)


if __name__ == "__main__":
    unittest.main()
