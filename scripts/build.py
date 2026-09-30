"""Build two Windows release outputs; keep all tooling files outside Build."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.product import AUTHOR, COPYRIGHT, DONATIONS, SITE_URL, SUPPORT_URL, VERSION  # noqa: E402
from scripts.release_documents import prepare_release_documents, write_version_resource  # noqa: E402

BUILD = ROOT / "Build"
WORK = ROOT / ".build-work"
STAGING = WORK / "release"
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
    parser.add_argument("--sign-thumbprint", help="Code signing certificate SHA-1 thumbprint in CurrentUser store")
    parser.add_argument("--signtool", default="signtool", help="Path to Microsoft SignTool")
    parser.add_argument("--timestamp-url", help="HTTPS RFC3161 timestamp server supplied by the certificate issuer")
    args = parser.parse_args()
    if bool(args.sign_thumbprint) != bool(args.timestamp_url):
        parser.error("Signing requires both --sign-thumbprint and --timestamp-url")
    if args.sign_thumbprint and (len(args.sign_thumbprint) != 40 or
                                not all(c in "0123456789abcdefABCDEF" for c in args.sign_thumbprint)):
        parser.error("Certificate thumbprint must contain 40 hexadecimal characters")
    if args.timestamp_url and not args.timestamp_url.startswith("https://"):
        parser.error("Timestamp URL must use HTTPS")
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
    resource = WORK / "version-info.txt"
    write_version_resource(resource)
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
        "--version-file",
        str(resource),
        "--add-data",
        f"{ROOT / 'web'};web",
        "--collect-submodules",
        "uvicorn",
        "--exclude-module",
        "pystray",
        "--hidden-import",
        "six",
        "--copy-metadata",
        "six",
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
        "keyboard",
        "main.py",
    )
    portable = STAGING / PORTABLE_NAME
    owned_path(portable, WORK)
    (STAGING / "WorkTimer").rename(portable)
    prepare_release_documents(portable)
    if args.sign_thumbprint:
        sign_file(portable / "WorkTimer.exe", args)
    run(sys.executable, "scripts/smoke_runtime.py", "--exe", str(portable / "WorkTimer.exe"))
    run(sys.executable, "scripts/smoke_lgpl.py", "--exe", str(portable / "WorkTimer.exe"))
    setup_license = WORK / "License.ru.txt"
    setup_license.write_text(
        "WorkTimer — бесплатное приложение для личного и коммерческого использования.\n\n"
        "Собственный код и документация — MIT. Можно использовать, изменять и распространять копии,\n"
        "включая продажу, сохраняя уведомление об авторе и лицензию. Программа предоставляется как есть.\n"
        "Ограничения ответственности действуют в пределах применимого законодательства.\n\n"
        + (ROOT / "LICENSE").read_text(encoding="utf-8")
        + "\n\nСторонние компоненты сохраняют собственные лицензии.\n"
        + (ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8"), encoding="utf-8-sig",
    )
    setup_info = WORK / "Setup-info.ru.txt"
    setup_info.write_text(
        "WorkTimer — локальный таймер для работы и стримов.\n\n"
        "Сценарии, Pomodoro, задачи, история времени и оверлеи OBS.\n"
        "Windows 10/11 x64; современный браузер. Python отдельно не нужен.\n"
        "Программа работает в трее; закрытие браузера не завершает таймер.\n"
        "Нет аккаунтов, рекламы и телеметрии. Данные сохраняются локально.\n"
        "Удаление программы сохраняет историю. Правила удаления данных — в руководстве.\n\n"
        f"Автор: {AUTHOR}\nСайт: {SITE_URL}\nВопросы: {SUPPORT_URL}\n"
        "YouTube: https://www.youtube.com/@promptix\nTelegram: https://t.me/promptix_ru\n"
        f"Поддержка разработки добровольна:\n{'\n'.join(url for _, url in DONATIONS)}\n"
        "После установки справка и юридические документы доступны без интернета.\n",
        encoding="utf-8-sig",
    )
    run(
        iscc,
        f"/DAppVersion={VERSION}",
        f"/DSourceDir={portable}",
        f"/DOutputDir={STAGING}",
        f"/DLicensePath={setup_license}",
        f"/DInfoPath={setup_info}",
        f"/DPublisherURL={SITE_URL}",
        f"/DSupportURL={SUPPORT_URL}",
        f"/DPublisherName={AUTHOR}",
        f"/DCopyrightNotice={COPYRIGHT}",
        str(ROOT / "scripts/installer.iss"),
    )
    if args.sign_thumbprint:
        sign_file(STAGING / INSTALLER_NAME, args)
    publish_release(STAGING)
    run(sys.executable, "scripts/github_release.py")
    print(f"Готово: Build/{PORTABLE_NAME}/WorkTimer.exe и Build/{INSTALLER_NAME}")


def sign_file(path: Path, args):
    run(args.signtool, "sign", "/sha1", args.sign_thumbprint, "/fd", "SHA256", "/tr", args.timestamp_url,
        "/td", "SHA256", str(path))
    run(args.signtool, "verify", "/pa", str(path))


if __name__ == "__main__":
    main()
