"""Opt-in installation of stable GitHub releases; no remote code or shell commands."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from app.product import RELEASES_URL, REPOSITORY, VERSION
from app.storage import SQLiteDatabase
from infrastructure.windows_setup import launch_installer

logger = logging.getLogger(__name__)
MAX_INSTALLER = 300 * 1024 * 1024
CHECK_INTERVAL = 24 * 60 * 60
REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\{6EF693C7-8D5C-4B82-9E62-3512D8055A93}_is1"


def version_parts(value: str) -> tuple[int, int, int]:
    if not isinstance(value, str) or not re.fullmatch(r"v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Релиз должен иметь версию вида v1.2.3")
    return tuple(int(part) for part in value.removeprefix("v").split("."))


def installed_directory() -> Path | None:
    if os.name != "nt" or not getattr(sys, "frozen", False):
        return None
    import winreg

    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, REGISTRY_KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                location = Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve()
            if location == Path(sys.executable).resolve().parent:
                return location
        except (OSError, ValueError, TypeError):
            continue
    return None


def trusted_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https" and parsed.hostname in {
            "api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"
        }
        and parsed.port in (None, 443) and not parsed.username and not parsed.password
    )


class GitHubRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not trusted_url(newurl):
            raise ValueError("GitHub перенаправил загрузку на недопустимый адрес")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_github(url: str):
    if not trusted_url(url):
        raise ValueError("Недопустимый адрес обновления")
    return build_opener(GitHubRedirectHandler()).open(
        Request(url, headers={"User-Agent": f"WorkTimer/{VERSION}", "Accept": "application/vnd.github+json"}),
        timeout=15,
    )


@dataclass(frozen=True)
class Release:
    version: str
    url: str
    size: int
    sha256: str


def latest_release() -> Release | None:
    with open_github(f"https://api.github.com/repos/{REPOSITORY}/releases/latest") as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("Слишком большой ответ GitHub")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Неверный ответ GitHub")
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name", "")
    remote = version_parts(tag)
    if remote <= version_parts(VERSION):
        return None
    version = tag.removeprefix("v")
    name = f"WorkTimer-Setup-{version}.exe"
    expected_url = f"{RELEASES_URL}/download/{tag}/{name}"
    assets = data.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("Неверный список файлов релиза")
    asset = next((item for item in assets if isinstance(item, dict) and item.get("name") == name), None)
    if not asset or asset.get("browser_download_url") != expected_url:
        raise ValueError("В релизе нет установщика WorkTimer для Windows")
    size = asset.get("size")
    if type(size) is not int or not 0 < size <= MAX_INSTALLER:
        raise ValueError("Недопустимый размер установщика")
    digest = asset.get("digest") or ""
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        checksum_url = f"{RELEASES_URL}/download/{tag}/SHA256SUMS"
        checksum = next((item for item in assets if isinstance(item, dict) and item.get("name") == "SHA256SUMS"), None)
        if not checksum or checksum.get("browser_download_url") != checksum_url:
            raise ValueError("В релизе нет SHA-256 для безопасной проверки установщика")
        with open_github(checksum_url) as response:
            content = response.read(16385)
        if len(content) > 16384:
            raise ValueError("Слишком большой файл контрольных сумм")
        entries = [line.split() for line in content.decode("utf-8").splitlines()]
        matches = [entry[0] for entry in entries if len(entry) == 2 and entry[1] == name]
        if len(matches) != 1 or not re.fullmatch(r"[0-9a-fA-F]{64}", matches[0]):
            raise ValueError("Не найдена контрольная сумма установщика")
        digest = "sha256:" + matches[0]
    return Release(version, expected_url, size, digest[7:].lower())


class UpdateService:
    def __init__(
        self, database: SQLiteDatabase, *, on_quit: Callable[[], None],
        prepare: Callable[[], None], port: int = 8765, on_available: Callable[[str], None] | None = None,
        no_browser: bool = False, no_tray: bool = False, no_hotkeys: bool = False,
    ):
        self.database = database
        self.on_quit = on_quit
        self.prepare = prepare
        self.port = port
        self.on_available = on_available
        self.restart_flags = {"NOBROWSER": no_browser, "NOTRAY": no_tray, "NOHOTKEYS": no_hotkeys}
        self.directory = installed_directory()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None
        self._scheduler: threading.Thread | None = None
        self._release: Release | None = None
        self._last_request = 0.0
        self._state = {"status": "idle", "message": "Обновления ещё не проверялись", "downloaded": 0,
                       "total": 0, "latest_version": None, "checked_at": None}

    def status(self) -> dict:
        with self._lock:
            return {**self._state, "current_version": VERSION, "releases_url": RELEASES_URL,
                    "can_install": self.directory is not None,
                    "check_retry_after": max(0, int(60 - (time.monotonic() - self._last_request)))}

    def _set(self, **values):
        with self._lock:
            self._state.update(values)

    def start(self):
        self._scheduler = threading.Thread(target=self._schedule, name="update-scheduler", daemon=True)
        self._scheduler.start()

    def stop(self):
        self._stop.set()

    def _automatic_enabled(self) -> bool:
        preferences = self.database.get_setting("app_preferences", {})
        return not isinstance(preferences, dict) or preferences.get("auto_check_updates", True) is True

    def _schedule(self):
        if self._stop.wait(10):
            return
        while not self._stop.is_set():
            try:
                last = self.database.get_setting("update_last_check", 0)
                if self._automatic_enabled() and time.time() - float(last or 0) >= CHECK_INTERVAL:
                    self.check()
            except Exception:
                logger.exception("Не удалось запланировать проверку обновлений")
            if self._stop.wait(60):
                return

    def check(self) -> dict:
        with self._lock:
            if self._stop.is_set():
                raise ValueError("WorkTimer завершает работу")
            if self._state["status"] in {"checking", "downloading", "authorizing", "installing"}:
                return self.status()
            if time.monotonic() - self._last_request < 60:
                return self.status()
            self._last_request = time.monotonic()
            self._set(status="checking", message="Проверяем GitHub Releases…")
            self._worker = threading.Thread(target=self._check, name="update-check", daemon=True)
            self._worker.start()
            return self.status()

    def _check(self):
        try:
            release = latest_release()
            checked = time.time()
            # Persist failures too, to avoid hammering an unavailable/private repository on every launch.
            self.database.set_setting("update_last_check", checked)
            with self._lock:
                self._release = release
                self._set(status="available" if release else "up_to_date", checked_at=checked,
                          latest_version=release.version if release else None,
                          message=f"Доступна версия {release.version}" if release else "Установлена актуальная версия")
            if release and self.on_available:
                self.on_available(release.version)
        except HTTPError as error:
            error.close()
            messages = {404: "Публичных релизов пока нет или репозиторий ещё закрыт",
                        403: "GitHub ограничил запросы. Повторите проверку позже",
                        429: "GitHub ограничил запросы. Повторите проверку позже"}
            self._failed(messages.get(error.code, "GitHub временно недоступен"))
        except (URLError, TimeoutError, OSError):
            self._failed("Нет связи с GitHub. Таймер продолжает работать; проверьте обновления позже")
        except Exception:
            logger.exception("Ошибка проверки обновления")
            self._failed("Не удалось проверить релиз: проверьте установщик и контрольные суммы на GitHub")

    def _failed(self, message: str):
        self.database.set_setting("update_last_check", time.time())
        self._set(status="error", message=message)

    def install(self) -> dict:
        with self._lock:
            if self._stop.is_set():
                raise ValueError("WorkTimer завершает работу")
            if self.directory is None:
                raise ValueError("Обновление через установщик доступно установленной версии Windows. Откройте релизы")
            if self._state["status"] in {"downloading", "authorizing", "installing"}:
                return self.status()
            if self._release is None or self._state["status"] not in {"available", "error"}:
                raise ValueError("Сначала проверьте наличие новой версии")
            self._set(status="downloading", message="Скачиваем обновление…", downloaded=0, total=self._release.size)
            self._worker = threading.Thread(target=self._install, args=(self._release,), name="update-install", daemon=True)
            self._worker.start()
            return self.status()

    def _install(self, release: Release):
        folder = None
        launched = False
        try:
            cache = self.database.path.parent / "updates"
            cache.mkdir(parents=True, exist_ok=True)
            folder = Path(tempfile.mkdtemp(prefix="download-", dir=cache))
            installer = folder / f"WorkTimer-Setup-{release.version}.exe"
            digest = hashlib.sha256()
            downloaded = 0
            deadline = time.monotonic() + 15 * 60
            with open_github(release.url) as response, installer.open("xb") as output:
                while chunk := response.read(128 * 1024):
                    if self._stop.is_set():
                        raise ValueError("Загрузка отменена: WorkTimer завершает работу")
                    if time.monotonic() > deadline:
                        raise ValueError("Загрузка заняла слишком много времени. Повторите попытку позже")
                    downloaded += len(chunk)
                    if downloaded > release.size:
                        raise ValueError("Размер установщика не совпадает с релизом")
                    output.write(chunk)
                    digest.update(chunk)
                    self._set(downloaded=downloaded)
            if downloaded != release.size or digest.hexdigest() != release.sha256:
                raise ValueError("Проверка SHA-256 не пройдена. Установщик не запущен; повторите загрузку")
            with installer.open("rb") as executable:
                if executable.read(2) != b"MZ":
                    raise ValueError("Загруженный файл не является Windows-установщиком")
            if self._stop.is_set():
                raise ValueError("Установка отменена: WorkTimer завершает работу")
            self._set(status="authorizing", message="Подтвердите запрос прав администратора Windows для обновления")
            # Keep the timer alive until Setup acknowledges its post-UAC startup.
            launched = True
            launch_installer(
                [str(installer), "/SP-", "/SILENT", "/NORESTART", "/NOCLOSEAPPLICATIONS",
                 f"/DIR={self.directory}", "/WORKTIMERUPDATE=1", f"/WORKTIMERPID={os.getpid()}",
                 "/WORKTIMERHANDOFF=1",
                 f"/WORKTIMERPORT={self.port}", f"/WORKTIMERDATA={self.database.path.parent}",
                 *(f"/WORKTIMER{flag}={int(enabled)}" for flag, enabled in self.restart_flags.items()),
                 f"/LOG={folder / 'install.log'}"],
                cwd=folder, cancelled=self._stop,
            )
            self.prepare()
            self.database.backup(label=f"before-update-{release.version}")
            self._set(status="installing", message="Установщик запущен. WorkTimer перезапустится после обновления")
            self.on_quit()
        except Exception as error:
            logger.exception("Обновление не установлено")
            self._set(status="error", message=str(error) if isinstance(error, ValueError) else
                      "Обновление не установлено. Программа и данные сохранены; повторите попытку")
        finally:
            if folder and not launched:
                (folder / f"WorkTimer-Setup-{release.version}.exe").unlink(missing_ok=True)
                folder.rmdir()
