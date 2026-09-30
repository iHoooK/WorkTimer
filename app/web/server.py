"""Loopback API, read-only OBS streams and authenticated local commands."""

from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import logging
import platform
import secrets
import sqlite3
import struct
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.documentation import DOC_CSS, DOCUMENTS, document_source, render_document
from app.domain import Phase, PhaseRepeatPolicy, Scenario, Task, TaskGroup, TaskStatus
from app.product import AUTHOR, COPYRIGHT, DONATIONS, LINKS, NAME, SITE_URL, SUPPORT_URL, VERSION
from app.services import ScenarioController
from app.services.updates import UpdateService
from app.storage import SQLiteDatabase

logger = logging.getLogger(__name__)


class PhasePayload(BaseModel):
    id: int | None = Field(default=None, ge=1)
    name: str = Field(min_length=1, max_length=80)
    duration_seconds: int = Field(ge=1, le=86400)
    color_role: str = Field(default="custom", min_length=1, max_length=40)
    repeat_policy: PhaseRepeatPolicy = PhaseRepeatPolicy.EVERY_CYCLE
    sound_enabled: bool = True
    notification_enabled: bool = True
    note: str = Field(default="", max_length=1000)
    progress_marker: bool = False


class ScenarioPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phases: list[PhasePayload] = Field(min_length=1, max_length=100)
    progress_total: int = Field(default=0, ge=0, le=100)


class TaskGroupPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = Field(default=None, ge=1)
    is_archived: bool = False


class TaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    group_id: int | None = Field(default=None, ge=1)
    description: str = Field(default="", max_length=5000)
    estimate_seconds: int | None = Field(default=None, ge=1, le=31536000)
    status: TaskStatus = TaskStatus.OPEN
    tags: list[str] = Field(default_factory=list, max_length=20)


class PomodoroPayload(BaseModel):
    work_seconds: int = Field(default=1500, ge=60, le=14400)
    break_seconds: int = Field(default=300, ge=60, le=7200)
    long_break_seconds: int = Field(default=900, ge=60, le=10800)
    cycles_before_long_break: int = Field(default=4, ge=2, le=12)


class PreferencesPayload(BaseModel):
    auto_check_updates: bool = True
    sound_enabled: bool = True
    dnd: bool = False
    warning_seconds: int = Field(default=60, ge=0, le=1800)
    pomodoro_work_minutes: int = Field(default=25, ge=1, le=240)
    pomodoro_break_minutes: int = Field(default=5, ge=1, le=120)
    pomodoro_long_break_minutes: int = Field(default=15, ge=1, le=180)
    pomodoro_cycles_before_long_break: int = Field(default=4, ge=2, le=12)
    auto_start_next_phase: bool = False
    overlay_accent: str = Field(default="#22c7ff", pattern=r"^#[0-9a-fA-F]{6}$")


class TimeEntryCorrectionPayload(BaseModel):
    elapsed_seconds: int = Field(ge=0, le=31536000)


class BackupPayload(BaseModel):
    data: str = Field(min_length=1, max_length=70000000)


def _preset_scenario(name: str) -> Scenario:
    presets = {
        "stream": Scenario(
            "Стрим",
            (
                Phase("Подготовка к стриму", 600, color_role="prep", repeat_policy=PhaseRepeatPolicy.ONCE_AT_START),
                Phase("Работа", 1800, color_role="work", progress_marker=True),
                Phase("Отдых", 300, color_role="rest"),
            ),
            progress_total=4,
        ),
        "deep-work": Scenario(
            "Глубокая работа", (Phase("Фокус", 3000, color_role="work"), Phase("Перерыв", 600, color_role="rest"))
        ),
        "pomodoro": Scenario(
            "Pomodoro 25/5", (Phase("Фокус", 1500, color_role="work"), Phase("Отдых", 300, color_role="rest"))
        ),
    }
    if name not in presets:
        raise ValueError("Неизвестный пресет")
    return presets[name]


def _scenario_to_dict(scenario: Scenario) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "name": scenario.name,
        "is_archived": scenario.is_archived,
        "progress_total": scenario.progress_total,
        "phases": [{**asdict(p), "repeat_policy": p.repeat_policy.value} for p in scenario.phases],
    }


def _task_to_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "group_id": task.group_id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value,
        "estimate_seconds": task.estimate_seconds,
        "tags": list(task.tags),
        "position": task.position,
    }


def create_web_app(
    database: SQLiteDatabase,
    state_provider: Callable[[], dict[str, Any]] | None = None,
    controller: ScenarioController | None = None,
    on_quit: Callable[[], None] | None = None,
    updates: UpdateService | None = None,
) -> FastAPI:
    database.migrate()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.stopping = threading.Event()
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    token = secrets.token_urlsafe(32)
    web_root = Path(__file__).resolve().parents[2] / "web"
    product_root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
    state = state_provider or (controller.to_dict if controller else lambda: {"phase": "idle", "time": "00:00"})

    @app.middleware("http")
    async def local_boundary(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            allowed_origins = {f"http://{request.url.netloc}"}
            if origin is not None and origin not in allowed_origins:
                return JSONResponse({"detail": "Запрос с другого сайта запрещён"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "Запрос с другого сайта запрещён"}, status_code=403)
            if not secrets.compare_digest(request.headers.get("x-worktimer-token", ""), token):
                return JSONResponse({"detail": "Панель устарела: обновите страницу"}, status_code=403)
            length = request.headers.get("content-length", "0")
            if length.isdigit() and int(length) > 71000000:
                return JSONResponse({"detail": "Файл слишком большой"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(KeyError)
    async def missing(request: Request, error: KeyError):
        return JSONResponse({"detail": "Объект не найден"}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, error: ValueError):
        return JSONResponse({"detail": str(error)}, status_code=422)

    @app.exception_handler(sqlite3.IntegrityError)
    async def conflict(request: Request, error: sqlite3.IntegrityError):
        message = "Такое название уже существует" if "UNIQUE" in str(error) else "Проверьте связи и поля данных"
        return JSONResponse({"detail": message}, status_code=409)

    @app.exception_handler(Exception)
    async def failed(request: Request, error: Exception):
        logger.exception("Ошибка API %s", request.url.path, exc_info=error)
        return JSONResponse(
            {"detail": "Не удалось выполнить действие. Данные сохранены; проверьте журнал приложения."}, status_code=500
        )

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(
            web_root / "index.html", media_type="text/html", headers={"Cache-Control": "no-store, max-age=0"}
        )

    @app.get("/favicon.ico")
    def favicon():
        return FileResponse(web_root / "assets" / "worktimer.ico")

    @app.get("/help/licenses/{license_path:path}")
    def component_license(license_path: str):
        root = (product_root / "licenses").resolve()
        candidate = (root / license_path).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise HTTPException(404, "Не найдено")
        if candidate.suffix == ".gz":
            return FileResponse(candidate, filename=candidate.name)
        return FileResponse(candidate, media_type="text/plain; charset=utf-8")

    @app.get("/help/{document}")
    def help_document(document: str):
        if document == "docs.css":
            return Response(DOC_CSS, media_type="text/css")
        if document == "LICENSE.txt":
            return FileResponse(product_root / ("LICENSE.txt" if getattr(sys, "frozen", False) else "LICENSE"),
                                media_type="text/plain; charset=utf-8")
        if document not in DOCUMENTS:
            raise HTTPException(404, "Не найдено")
        if getattr(sys, "frozen", False):
            return FileResponse(product_root / document, media_type="text/html")
        return HTMLResponse(render_document(document, document_source(product_root, document)))

    @app.get("/api/about")
    def about():
        return {"name": NAME, "version": VERSION, "author": AUTHOR, "copyright": COPYRIGHT,
                "site": SITE_URL, "support": SUPPORT_URL, "links": LINKS, "donations": DONATIONS}

    @app.get("/api/diagnostics")
    def diagnostics(request: Request):
        if not secrets.compare_digest(request.headers.get("x-worktimer-token", ""), token):
            raise HTTPException(403, "Обновите страницу панели")
        return {"text": f"{NAME} {VERSION}\nОС: {platform.system()} {platform.release()} "
                f"({platform.version()})\nРазрядность: {struct.calcsize('P') * 8} bit\nPython: {platform.python_version()}"}

    def require_updates():
        if updates is None:
            raise HTTPException(503, "Проверка обновлений недоступна")
        return updates

    @app.get("/api/updates")
    def update_status():
        return require_updates().status()

    @app.post("/api/updates/check")
    def check_updates():
        return require_updates().check()

    @app.post("/api/updates/install")
    def install_update():
        return require_updates().install()

    @app.get("/overlay/{overlay_name}")
    def overlay(overlay_name: str) -> FileResponse:
        if overlay_name not in {"minimal", "scene", "progress"}:
            raise HTTPException(404, "Не найдено")
        return FileResponse(
            web_root / "overlays" / f"{overlay_name}.html", headers={"Cache-Control": "no-store, max-age=0"}
        )

    @app.get("/assets/{asset_path:path}")
    def asset(asset_path: str) -> FileResponse:
        root = (web_root / "assets").resolve()
        candidate = (root / asset_path).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise HTTPException(404, "Не найдено")
        return FileResponse(candidate, headers={"Cache-Control": "no-store, max-age=0"})

    def preferences():
        defaults = PreferencesPayload().model_dump()
        stored = database.get_setting("app_preferences", {})
        if isinstance(stored, dict):
            for key in defaults:
                if key in stored:
                    try:
                        value = PreferencesPayload.model_validate({key: stored[key]}).model_dump()[key]
                        defaults[key] = value
                    except ValueError:
                        pass
        return defaults

    @app.get("/api/health")
    def health():
        return {"status": "ok", "app": NAME, "version": VERSION}

    @app.get("/api/bootstrap")
    def bootstrap():
        return {
            "token": token,
            "preferences": preferences(),
            "state": state(),
            "migration_warning": database.get_setting("migration_warning"),
        }

    @app.get("/api/preferences")
    def get_preferences():
        return preferences()

    @app.put("/api/preferences")
    def save_preferences(payload: PreferencesPayload):
        value = payload.model_dump()
        database.set_setting("app_preferences", value)
        return value

    @app.get("/api/state")
    def timer_state():
        return state()

    @app.get("/api/events")
    async def state_events(request: Request):
        async def stream():
            while not app.state.stopping.is_set() and not await request.is_disconnected():
                yield f"event: state\ndata: {json.dumps(state(), ensure_ascii=False)}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    def require_controller():
        if controller is None:
            raise HTTPException(503, "Управление таймером недоступно")
        return controller

    def run_action(action):
        active = require_controller()
        try:
            action(active)
            return active.to_dict()
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except KeyError:
            raise HTTPException(404, "Объект не найден") from None

    @app.post("/api/timer/toggle")
    def toggle_timer():
        return run_action(lambda c: c.start())

    @app.post("/api/timer/next")
    def next_timer_phase():
        return run_action(lambda c: c.next_phase())

    @app.post("/api/timer/repeat")
    def repeat_timer_phase():
        return run_action(lambda c: c.repeat_phase())

    @app.post("/api/timer/restart")
    def restart_timer_scenario():
        return run_action(lambda c: c.start_from_beginning())

    @app.post("/api/timer/phase/{position}")
    def start_specific_phase(position: int):
        return run_action(lambda c: c.start_phase(position))

    @app.post("/api/timer/free")
    def start_free_timer():
        return run_action(lambda c: c.start_free())

    @app.post("/api/timer/pomodoro")
    def start_pomodoro(payload: PomodoroPayload):
        return run_action(lambda c: c.start_pomodoro(**payload.model_dump()))

    @app.post("/api/timer/stop")
    def stop_timer():
        return run_action(lambda c: c.stop())

    @app.post("/api/timer/add-cycle")
    def add_cycle():
        return run_action(lambda c: c.add_cycle())

    @app.get("/api/scenarios")
    def list_scenarios():
        return {"items": [_scenario_to_dict(s) for s in database.list_scenarios()]}

    def scenario_model(payload: ScenarioPayload, *, scenario_id: int | None = None):
        archived = database.get_scenario(scenario_id).is_archived if scenario_id else False
        return Scenario(
            payload.name,
            tuple(Phase(**p.model_dump(), position=i) for i, p in enumerate(payload.phases)),
            id=scenario_id,
            is_archived=archived,
            progress_total=payload.progress_total,
        )

    @app.post("/api/scenarios", status_code=201)
    def create_scenario(payload: ScenarioPayload):
        model = scenario_model(payload)
        return _scenario_to_dict(controller.save_scenario(model) if controller else database.save_scenario(model))

    @app.put("/api/scenarios/{scenario_id}")
    def update_scenario(scenario_id: int, payload: ScenarioPayload):
        model = scenario_model(payload, scenario_id=scenario_id)
        return _scenario_to_dict(controller.save_scenario(model) if controller else database.save_scenario(model))

    @app.post("/api/scenarios/{scenario_id}/select")
    def select_scenario(scenario_id: int):
        return run_action(lambda c: c.select_scenario(scenario_id))

    @app.post("/api/scenarios/presets/{preset_name}", status_code=201)
    def create_scenario_preset(preset_name: str):
        source = _preset_scenario(preset_name)
        names = {s.name.casefold() for s in database.list_scenarios()}
        name, number = source.name, 2
        while name.casefold() in names:
            name = f"{source.name} {number}"
            number += 1
        return _scenario_to_dict(
            database.save_scenario(Scenario(name, source.phases, progress_total=source.progress_total))
        )

    @app.post("/api/scenarios/{scenario_id}/duplicate", status_code=201)
    def duplicate_scenario(scenario_id: int):
        return _scenario_to_dict(database.duplicate_scenario(scenario_id))

    @app.delete("/api/scenarios/{scenario_id}", status_code=204)
    def archive_scenario(scenario_id: int):
        if controller:
            controller.archive_scenario(scenario_id)
        else:
            database.archive_scenario(scenario_id)

    @app.post("/api/scenarios/{scenario_id}/restore")
    def restore_scenario(scenario_id: int):
        database.restore_scenario(scenario_id)
        return {"ok": True}

    @app.get("/api/task-groups")
    def list_task_groups():
        return {
            "items": [
                {
                    "id": g.id,
                    "parent_id": g.parent_id,
                    "name": g.name,
                    "position": g.position,
                    "is_archived": g.is_archived,
                }
                for g in database.list_task_groups()
            ]
        }

    def save_group(payload: TaskGroupPayload, group_id: int | None = None):
        group = database.save_task_group(TaskGroup(**payload.model_dump(), id=group_id))
        return {"id": group.id, "name": group.name, "parent_id": group.parent_id, "is_archived": group.is_archived}

    @app.post("/api/task-groups", status_code=201)
    def create_task_group(payload: TaskGroupPayload):
        return save_group(payload)

    @app.put("/api/task-groups/{group_id}")
    def update_task_group(group_id: int, payload: TaskGroupPayload):
        return save_group(payload, group_id)

    @app.get("/api/tasks")
    def list_tasks(include_archived: bool = False):
        return {"items": [_task_to_dict(t) for t in database.list_tasks(include_archived=include_archived)]}

    def save_task(payload: TaskPayload, task_id: int | None = None):
        return _task_to_dict(
            database.save_task(Task(id=task_id, **{**payload.model_dump(), "tags": tuple(payload.tags)}))
        )

    @app.post("/api/tasks", status_code=201)
    def create_task(payload: TaskPayload):
        return save_task(payload)

    @app.put("/api/tasks/{task_id}")
    def update_task(task_id: int, payload: TaskPayload):
        return save_task(payload, task_id)

    @app.post("/api/tasks/{task_id}/select")
    def select_task(task_id: int):
        return run_action(lambda c: c.select_task(task_id))

    @app.post("/api/tasks/clear-selection")
    def clear_task_selection():
        return run_action(lambda c: c.select_task(None))

    def filters(task_id=None, group_id=None, scenario_id=None, date_from=None, date_to=None, phase_role=None):
        for value in (date_from, date_to):
            if value:
                date.fromisoformat(value)
        if date_from and date_to and date_from > date_to:
            raise ValueError("Начало периода позже окончания")
        return {
            "task_id": task_id,
            "group_id": group_id,
            "scenario_id": scenario_id,
            "date_from": date_from,
            "date_to": date_to,
            "phase_role": phase_role,
        }

    @app.get("/api/history")
    def time_history(
        task_id: int | None = None,
        group_id: int | None = None,
        scenario_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        phase_role: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ):
        selected = filters(task_id, group_id, scenario_id, date_from, date_to, phase_role)
        items = database.list_time_entries(limit=min(max(limit, 1), 1000), offset=max(offset, 0), **selected)
        return {"items": items, "offset": max(offset, 0), "has_more": len(items) == min(max(limit, 1), 1000)}

    @app.get("/api/analytics")
    def analytics(
        task_id: int | None = None,
        group_id: int | None = None,
        scenario_id: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        phase_role: str | None = None,
    ):
        return database.analytics(**filters(task_id, group_id, scenario_id, date_from, date_to, phase_role))

    @app.get("/api/analytics/tasks")
    def task_time_summary():
        return {"items": database.time_summary_by_task()}

    @app.get("/api/analytics/days")
    def day_time_summary():
        return {"items": database.time_summary_by_day()}

    @app.get("/api/analytics/scenarios")
    def scenario_time_summary():
        return {"items": database.time_summary_by_scenario()}

    @app.get("/api/sessions")
    def sessions():
        return {"items": database.list_sessions()}

    @app.patch("/api/history/{entry_id}")
    def correct_history_entry(entry_id: int, payload: TimeEntryCorrectionPayload):
        database.correct_time_entry(entry_id, payload.elapsed_seconds)
        return {"ok": True}

    @app.get("/api/history/{entry_id}/corrections")
    def corrections(entry_id: int):
        return {"items": database.correction_history(entry_id)}

    @app.get("/api/history.csv")
    def export_history_csv(
        date_from: str | None = None,
        date_to: str | None = None,
        task_id: int | None = None,
        group_id: int | None = None,
        scenario_id: int | None = None,
        phase_role: str | None = None,
    ):
        selected = filters(task_id, group_id, scenario_id, date_from, date_to, phase_role)

        def stream():
            output = io.StringIO(newline="")
            writer = csv.writer(output)
            columns = (
                "started_at",
                "ended_at",
                "elapsed_seconds",
                "task_title",
                "scenario_name",
                "phase_name",
                "phase_role",
                "source",
            )
            writer.writerow(columns)
            yield "\ufeff" + output.getvalue()
            for entry in database.iter_time_entries(**selected):
                output.seek(0)
                output.truncate(0)
                cells = []
                for key in columns:
                    text = "" if entry[key] is None else str(entry[key])
                    if text.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"} or text[:1] in {"\t", "\r", "\n"}:
                        text = "'" + text
                    cells.append(text)
                writer.writerow(cells)
                yield output.getvalue()

        return StreamingResponse(
            stream(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=worktimer-history.csv"},
        )

    @app.get("/api/data/export")
    def export_data(request: Request):
        if not secrets.compare_digest(request.headers.get("x-worktimer-token", ""), token):
            raise HTTPException(403, "Обновите страницу панели")
        path = database.backup()
        return FileResponse(path, filename="worktimer-backup.db", media_type="application/octet-stream")

    @app.post("/api/data/import")
    def import_data(payload: BackupPayload):
        try:
            data = base64.b64decode(payload.data, validate=True)
        except ValueError:
            raise HTTPException(422, "Некорректный файл") from None
        require_controller().import_backup(data)
        return {"ok": True, "state": state()}

    @app.post("/api/app/quit")
    def quit_app():
        if on_quit is None:
            raise HTTPException(503, "Выход доступен в desktop-приложении")
        threading.Timer(0.2, on_quit).start()
        return {"ok": True}

    return app


class LocalWebServer:
    def __init__(self, app: FastAPI, port: int = 8765) -> None:
        self._app = app
        self._port = port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self, timeout: float = 10) -> None:
        if self._thread and self._thread.is_alive():
            return
        if hasattr(self._app.state, "stopping"):
            self._app.state.stopping.clear()
        config = uvicorn.Config(
            self._app,
            host="127.0.0.1",
            port=self._port,
            log_level="warning",
            access_log=False,
            log_config=None,
            timeout_graceful_shutdown=2,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="worktimer-web", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + timeout
        while not self._server.started:
            if not self._thread.is_alive():
                raise RuntimeError(f"Не удалось открыть порт {self._port}. Возможно, он занят другим приложением.")
            if time.monotonic() >= deadline:
                self.stop()
                raise RuntimeError("Локальный сервер не запустился вовремя")
            time.sleep(0.05)

    def stop(self) -> None:
        if hasattr(self._app.state, "stopping"):
            self._app.state.stopping.set()
        if self._server:
            self._server.should_exit = True
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=5)
        if self._server and self._thread and self._thread.is_alive():
            self._server.force_exit = True
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None
