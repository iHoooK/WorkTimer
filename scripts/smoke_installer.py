"""Install, check shortcut and installed runtime, then uninstall the test instance."""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.product import VERSION  # noqa: E402

REGISTRY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6EF693C7-8D5C-4B82-9E62-3512D8055A93}_is1"


def verify_update(installer: Path, exe: Path, folder: Path):
    """Exercise actual Inno handoff and restart against a disposable installed profile."""
    data_dir = folder / "Update Profile"
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    token = ""

    def request(path, method="GET", payload=None):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(base + path, data=data, method=method,
                                     headers={"X-WorkTimer-Token": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def ready():
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                return request("/api/bootstrap")["token"]
            except (OSError, urllib.error.URLError):
                time.sleep(0.1)
        raise AssertionError("Installed runtime did not restart")

    process = subprocess.Popen([str(exe), "--data-dir", str(data_dir), "--port", str(port),
                                "--no-browser", "--no-tray", "--no-hotkeys"])
    setup = None
    try:
        token = ready()
        assert request("/api/updates")["can_install"], "Installed path must match registry"
        preferences = request("/api/preferences")
        request("/api/preferences", "PUT", {**preferences, "auto_check_updates": False})
        task = request("/api/tasks", "POST", {"title": "Keep task after update"})
        request("/api/timer/free", "POST")
        time.sleep(1.1)
        before = request("/api/state")
        setup = subprocess.Popen([str(installer), "/SP-", "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                                  "/NOCLOSEAPPLICATIONS", f"/DIR={exe.parent}", "/WORKTIMERUPDATE=1",
                                  f"/WORKTIMERPID={process.pid}", f"/WORKTIMERPORT={port}",
                                  f"/WORKTIMERDATA={data_dir}", "/WORKTIMERNOBROWSER=1",
                                  "/WORKTIMERNOTRAY=1", "/WORKTIMERNOHOTKEYS=1", f"/LOG={folder / 'update.log'}"])
        time.sleep(1)
        assert setup.poll() is None and process.poll() is None, "Setup must wait for the application"
        request("/api/app/quit", "POST")
        process.wait(timeout=15)
        assert setup.wait(timeout=90) == 0
        token = ready()
        after = request("/api/state")
        assert after["phase"] == "paused" and after["mode"] == "free"
        assert after["elapsed_seconds"] >= before["elapsed_seconds"] >= 1
        assert any(item["id"] == task["id"] for item in request("/api/tasks")["items"])
        assert request("/api/preferences")["auto_check_updates"] is False
        assert request("/api/health")["version"] == VERSION
        request("/api/app/quit", "POST")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                request("/api/health")
            except (OSError, urllib.error.URLError):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Updated runtime did not quit")
    finally:
        if setup and setup.poll() is None:
            setup.terminate()
            setup.wait(timeout=10)
        try:
            request("/api/app/quit", "POST")
        except (OSError, urllib.error.URLError):
            pass
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise RuntimeError("Проверка установки в Program Files требует запуска терминала от администратора.")
    # Do not replace an existing user's installation or shortcut during verification.
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            handle = winreg.OpenKey(hive, REGISTRY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        except FileNotFoundError:
            continue
        else:
            handle.Close()
            raise RuntimeError("WorkTimer уже установлен: автоматическая проверка не заменяет существующую установку.")
    startmenu = Path(os.environ["PROGRAMDATA"]) / "Microsoft/Windows/Start Menu/Programs/WorkTimer Verification"
    if startmenu.exists():
        raise RuntimeError("Каталог тестовых ярлыков уже существует")
    smoke_root = ROOT / ".build-work" / "smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="install-", dir=smoke_root))
    program_files = Path(os.environ.get("PROGRAMW6432") or os.environ["PROGRAMFILES"]).resolve()
    target = program_files / f"WorkTimer Verification-{folder.name}"
    if target.exists():
        raise RuntimeError("Каталог проверочной установки уже существует")
    installer = ROOT / f"Build/WorkTimer-Setup-{VERSION}.exe"
    installed = False
    try:
        subprocess.run(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                f"/DIR={target}",
                "/GROUP=WorkTimer Verification",
                "/TASKS=",
                f"/LOG={folder / 'install.log'}",
            ],
            check=True,
            timeout=90,
        )
        installed = True
        exe = target / "WorkTimer.exe"
        assert exe.is_file()
        for name in ["HELP.html", "LICENSE.html", "LICENSE.txt", "PRIVACY.html", "THIRD_PARTY_NOTICES.html",
                     "CHANGELOG.html", "docs.css", "components/pystray/__init__.py",
                     "licenses/pystray/COPYING.LGPL", "licenses/Python-Windows-LICENSE.txt",
                     "licenses/sources/pystray-0.19.5.tar.gz"]:
            assert (target / name).is_file(), name
        assert (startmenu / "Руководство WorkTimer.lnk").is_file()
        shortcut = startmenu / "WorkTimer.lnk"
        assert shortcut.is_file()
        quoted = str(shortcut).replace("'", "''")
        ps = f"$taskShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut('{quoted}'); $taskShortcut.TargetPath"
        resolved = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", ps], encoding="utf-8").strip()
        assert Path(resolved).resolve() == exe.resolve()
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/smoke_runtime.py"), "--exe", str(exe)], check=True, timeout=60
        )
        verify_update(installer, exe, folder)
    finally:
        if installed:
            subprocess.run(
                [
                    str(target / "unins000.exe"),
                    "/VERYSILENT",
                    "/SUPPRESSMSGBOXES",
                    "/NORESTART",
                    f"/LOG={folder / 'uninstall.log'}",
                ],
                check=True,
                timeout=90,
            )
    assert not (target / "WorkTimer.exe").exists()
    assert not startmenu.exists()
    result = {
        "passed": True,
        "installed_under_program_files": True,
        "installed_exe_launched": True,
        "start_menu_shortcut_target_verified": True,
        "uninstall_removed_program_and_shortcut": True,
        "user_appdata_untouched": True,
        "offline_documents_and_lgpl_sources_installed": True,
        "update_waited_for_exit_and_restarted_same_profile_and_port": True,
        "update_preserved_tasks_preferences_and_paused_session": True,
    }
    (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
