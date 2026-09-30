"""Build two Windows release outputs; keep all tooling files outside Build."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "Build"
WORK = ROOT / ".build-work"
STAGING = WORK / "release"
VERSION = "1.0.0"
PORTABLE_NAME = "Work Timer Portable"
INSTALLER_NAME = f"WorkTimer-Setup-{VERSION}.exe"


def run(*arguments):
    subprocess.run(arguments, cwd=ROOT, check=True)


def owned_path(path: Path, parent: Path) -> Path:
    """Reject paths outside the workspace or their explicitly owned directory."""
    root = ROOT.resolve()
    allowed = parent.resolve()
    target = path.resolve()
    if allowed == root or not allowed.is_relative_to(root):
        raise ValueError(f"Unsafe build directory: {parent}")
    if target == allowed or not target.is_relative_to(allowed):
        raise ValueError(f"Unsafe build target: {path}")
    return target


def remove_owned(path: Path, parent: Path):
    owned_path(path, parent)
    if path.is_symlink():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def publish_release(staging: Path):
    expected = {PORTABLE_NAME, INSTALLER_NAME}
    if {path.name for path in staging.iterdir()} != expected:
        raise RuntimeError("Release staging must contain only portable and installer")
    portable = staging / PORTABLE_NAME
    installer = staging / INSTALLER_NAME
    if not (portable / "WorkTimer.exe").is_file() or not installer.is_file():
        raise RuntimeError("Missing release executable")
    BUILD.mkdir(exist_ok=True)
    # Remove legacy ZIP/log/spec/test-data outputs only after a new release passes.
    for path in BUILD.iterdir():
        remove_owned(path, BUILD)
    for name in (PORTABLE_NAME, INSTALLER_NAME):
        source = staging / name
        destination = BUILD / name
        owned_path(source, WORK)
        owned_path(destination, BUILD)
        shutil.move(str(source), str(destination))
    if {path.name for path in BUILD.iterdir()} != expected:
        raise RuntimeError("Unexpected files in Build")


def compiler():
    candidates = [
        os.environ.get("ISCC"),
        shutil.which("ISCC"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("Установите Inno Setup 6 или задайте ISCC — путь к ISCC.exe. https://jrsoftware.org/isdl.php")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Windows EXE собирается на Windows. Используйте Git Bash, не WSL.")
    iscc = compiler()
    owned_path(STAGING, WORK)
    WORK.mkdir(exist_ok=True)
    os.environ["PYINSTALLER_CONFIG_DIR"] = str(WORK / "cache")
    if STAGING.exists():
        remove_owned(STAGING, WORK)
    STAGING.mkdir()
    if not args.skip_tests:
        run(sys.executable, "-m", "ruff", "check", "app", "core", "infrastructure", "main.py", "scripts", "tests")
        run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q")
        run(sys.executable, "-m", "pip", "check")
    run(sys.executable, "scripts/make_icon.py")
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "WorkTimer",
        "--distpath",
        str(STAGING),
        "--workpath",
        str(WORK / "pyinstaller"),
        "--specpath",
        str(WORK),
        "--icon",
        str(ROOT / "web/assets/worktimer.ico"),
        "--add-data",
        f"{ROOT / 'web'};web",
        "--collect-submodules",
        "uvicorn",
        "--hidden-import",
        "pystray._win32",
        "--hidden-import",
        "plyer.platforms.win.notification",
        "--recursive-copy-metadata",
        "fastapi",
        "--recursive-copy-metadata",
        "uvicorn",
        "--recursive-copy-metadata",
        "pillow",
        "--recursive-copy-metadata",
        "plyer",
        "--recursive-copy-metadata",
        "pystray",
        "--recursive-copy-metadata",
        "keyboard",
        "main.py",
    )
    portable = STAGING / PORTABLE_NAME
    owned_path(portable, WORK)
    (STAGING / "WorkTimer").rename(portable)
    run(sys.executable, "scripts/smoke_runtime.py", "--exe", str(portable / "WorkTimer.exe"))
    run(
        iscc,
        f"/DAppVersion={VERSION}",
        f"/DSourceDir={portable}",
        f"/DOutputDir={STAGING}",
        str(ROOT / "scripts/installer.iss"),
    )
    publish_release(STAGING)
    print(f"Готово: Build/{PORTABLE_NAME}/WorkTimer.exe и Build/{INSTALLER_NAME}")


if __name__ == "__main__":
    main()
