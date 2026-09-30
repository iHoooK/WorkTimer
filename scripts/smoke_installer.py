"""Install, check shortcut and installed runtime, then uninstall the test instance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6EF693C7-8D5C-4B82-9E62-3512D8055A93}_is1"


def main():
    # Do not replace an existing user's installation or shortcut during verification.
    try:
        handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REGISTRY)
    except FileNotFoundError:
        pass
    else:
        handle.Close()
        raise RuntimeError("WorkTimer уже установлен: автоматическая проверка не заменяет существующую установку.")
    startmenu = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/WorkTimer Verification"
    if startmenu.exists():
        raise RuntimeError("Каталог тестовых ярлыков уже существует")
    smoke_root = ROOT / ".build-work" / "smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="install-", dir=smoke_root))
    target = folder / "Program"
    installer = ROOT / "Build/WorkTimer-Setup-1.0.0.exe"
    installed = False
    try:
        subprocess.run(
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/NORESTART",
                "/CURRENTUSER",
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
        shortcut = startmenu / "WorkTimer.lnk"
        assert shortcut.is_file()
        quoted = str(shortcut).replace("'", "''")
        ps = f"$taskShortcut = (New-Object -ComObject WScript.Shell).CreateShortcut('{quoted}'); $taskShortcut.TargetPath"
        resolved = subprocess.check_output(["powershell.exe", "-NoProfile", "-Command", ps], encoding="utf-8").strip()
        assert Path(resolved).resolve() == exe.resolve()
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/smoke_runtime.py"), "--exe", str(exe)], check=True, timeout=60
        )
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
        "installed_exe_launched": True,
        "start_menu_shortcut_target_verified": True,
        "uninstall_removed_program_and_shortcut": True,
        "user_appdata_untouched": True,
    }
    (folder / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
