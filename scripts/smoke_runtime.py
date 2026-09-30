"""Real TCP/process checks for source or frozen Windows runtime, with isolated data."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe")
    args = parser.parse_args()
    base_dir = ROOT / ".build-work" / "smoke"
    base_dir.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="runtime-", dir=base_dir))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    command = [args.exe] if args.exe else [sys.executable, str(ROOT / "main.py")]
    command += ["--data-dir", str(directory), "--port", str(port), "--no-browser"]
    process = None
    token = ""

    def request(path, method="GET", payload=None):
        headers = {"X-WorkTimer-Token": token, "Content-Type": "application/json"}
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)

    def launch():
        nonlocal process, token
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"Runtime exited {process.returncode}. See {directory / 'worktimer.log'}")
            try:
                data = request("/api/bootstrap")
                token = data["token"]
                return data
            except OSError, urllib.error.URLError:
                time.sleep(0.1)
        raise AssertionError("Runtime did not become ready")

    try:
        launch()
        assert request("/api/health")["app"] == "WorkTimer"
        about = request("/api/about")
        assert about["version"] == request("/api/health")["version"] and about["author"]
        assert "WorkTimer" in request("/api/diagnostics")["text"]
        second = subprocess.run(
            command, cwd=ROOT, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        assert second.returncode == 0 and process.poll() is None
        phase = {
            "name": "Работа",
            "duration_seconds": 90,
            "color_role": "work",
            "repeat_policy": "every_cycle",
            "progress_marker": True,
            "sound_enabled": False,
            "notification_enabled": False,
            "note": "Проверка EXE",
        }
        saved = request("/api/scenarios", "POST", {"name": "Проверка релиза", "progress_total": 3, "phases": [phase]})
        request(f"/api/scenarios/{saved['id']}/select", "POST")
        request("/api/timer/toggle", "POST")
        time.sleep(1.3)
        before = request("/api/state")
        after = request("/api/timer/add-cycle", "POST")
        assert before["run_id"] == after["run_id"] and after["progress_total"] == 4
        assert after["elapsed_seconds"] >= before["elapsed_seconds"] >= 1
        request(f"/api/scenarios/{saved['id']}", "PUT", {**saved, "progress_total": 5})
        assert request("/api/state")["run_id"] == before["run_id"]
        time.sleep(1.1)
        process.kill()
        process.wait(timeout=10)
        restored = launch()["state"]
        assert restored["phase"] == "paused" and restored["recovered"] and restored["elapsed_seconds"] >= 1
        assert restored["progress_current"] == 1 and restored["progress_total"] == 5
        request("/api/timer/toggle", "POST")
        request("/api/timer/stop", "POST")
        history = request("/api/history")["items"]
        assert history and history[0]["phase_name"] == "Работа" and history[0]["elapsed_seconds"] >= 1
        for path in [
            "/",
            "/assets/modules/main.js",
            "/favicon.ico",
            "/overlay/minimal",
            "/overlay/scene",
            "/overlay/progress",
            "/help/HELP.html",
            "/help/LICENSE.html",
            "/help/PRIVACY.html",
            "/help/THIRD_PARTY_NOTICES.html",
            "/help/CHANGELOG.html",
            "/help/docs.css",
            "/help/LICENSE.txt",
        ]:
            with urllib.request.urlopen(base + path, timeout=5) as response:
                assert response.status == 200 and response.read()
        conflict = command.copy()
        conflict[conflict.index("--data-dir") + 1] = str(directory / "conflict")
        result = subprocess.run(
            conflict, cwd=ROOT, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        assert result.returncode == 1 and process.poll() is None
        # An open dashboard/OBS SSE connection must finish normally on exit.
        with urllib.request.urlopen(base + "/api/events", timeout=5) as event_stream:
            assert event_stream.readline().startswith(b"event: state")
            request("/api/app/quit", "POST")
            assert process.wait(timeout=12) == 0
            event_stream.read()
        logs = (directory / "worktimer.log").read_text(encoding="utf-8")
        assert "TrayManager: иконка создана" in logs and "HotkeyManager: зарегистрировано 3 / 3" in logs
        assert "[ERROR]" not in logs and "Traceback" not in logs
        evidence = {
            "passed": True,
            "binary": args.exe or "source",
            "single_instance": True,
            "cycle_edit_without_reset": True,
            "crash_recovery_paused": True,
            "tray_and_hotkeys_started": True,
            "port_conflict_handled": True,
            "graceful_quit": True,
            "graceful_quit_with_open_sse": True,
            "offline_help_and_legal_documents": True,
            "restored_elapsed_seconds": restored["elapsed_seconds"],
        }
        (directory / "result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(evidence, ensure_ascii=False))
    finally:
        if process and process.poll() is None:
            process.kill()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
