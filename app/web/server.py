"""Безопасный localhost-сервер для будущей web-панели WorkTimer."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response, StreamingResponse
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.domain.models import Phase, PhaseRepeatPolicy, Scenario, Task, TaskGroup, TaskStatus
from app.services.scenario_controller import ScenarioController
from app.storage.sqlite_database import SQLiteDatabase

logger = logging.getLogger(__name__)


class PhasePayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    duration_seconds: int = Field(ge=1, le=86_400)
    color_role: str = Field(default="custom", min_length=1, max_length=40)
    repeat_policy: PhaseRepeatPolicy = PhaseRepeatPolicy.EVERY_CYCLE
    sound_enabled: bool = True
    notification_enabled: bool = True
    note: str = Field(default="", max_length=1_000)
    progress_marker: bool = False


class ScenarioPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    phases: list[PhasePayload] = Field(min_length=1, max_length=100)
    progress_total: int = Field(default=0, ge=0, le=100)


class TaskGroupPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = Field(default=None, ge=1)


class TaskPayload(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    group_id: int | None = Field(default=None, ge=1)
    description: str = Field(default="", max_length=5_000)
    estimate_seconds: int | None = Field(default=None, ge=1, le=31_536_000)
    status: TaskStatus = TaskStatus.OPEN
    tags: list[str] = Field(default_factory=list, max_length=20)


class PomodoroPayload(BaseModel):
    work_seconds: int = Field(default=1_500, ge=60, le=14_400)
    break_seconds: int = Field(default=300, ge=60, le=7_200)
    long_break_seconds: int = Field(default=900, ge=60, le=10_800)
    cycles_before_long_break: int = Field(default=4, ge=2, le=12)


class PreferencesPayload(BaseModel):
    sound_enabled: bool = True
    dnd: bool = False
    warning_seconds: int = Field(default=60, ge=0, le=1_800)
    always_on_top: bool = False
    pomodoro_work_minutes: int = Field(default=25, ge=1, le=240)
    pomodoro_break_minutes: int = Field(default=5, ge=1, le=120)
    pomodoro_long_break_minutes: int = Field(default=15, ge=1, le=180)
    pomodoro_cycles_before_long_break: int = Field(default=4, ge=2, le=12)
    auto_start_next_phase: bool = False
    overlay_accent: str = Field(default="#22c7ff", pattern=r"^#[0-9a-fA-F]{6}$")


class TimeEntryCorrectionPayload(BaseModel):
    elapsed_seconds: int = Field(ge=0, le=31_536_000)


def _preset_scenario(name: str) -> Scenario:
    presets: dict[str, Scenario] = {
        "stream": Scenario("Стрим", (
            Phase("Подготовка к стриму", 600, repeat_policy=PhaseRepeatPolicy.ONCE_AT_START),
            Phase("Работа", 1800, color_role="work", progress_marker=True),
            Phase("Отдых", 300, color_role="rest"),
        ), progress_total=4),
        "deep-work": Scenario("Глубокая работа", (
            Phase("Фокус", 3_000, color_role="work"),
            Phase("Перерыв", 600, color_role="rest"),
        )),
        "pomodoro": Scenario("Pomodoro 25/5", (
            Phase("Фокус", 1_500, color_role="work"),
            Phase("Отдых", 300, color_role="rest"),
        )),
    }
    try:
        return presets[name]
    except KeyError as error:
        raise ValueError("Неизвестный пресет") from error


def _scenario_to_dict(scenario: Scenario) -> dict[str, Any]:
    return {
        "id": scenario.id,
        "name": scenario.name,
        "is_archived": scenario.is_archived,
        "progress_total": scenario.progress_total,
        "phases": [
            {
                "id": phase.id,
                "position": phase.position,
                "name": phase.name,
                "duration_seconds": phase.duration_seconds,
                "color_role": phase.color_role,
                "repeat_policy": phase.repeat_policy.value,
                "sound_enabled": phase.sound_enabled,
                "notification_enabled": phase.notification_enabled,
                "note": phase.note,
                "progress_marker": phase.progress_marker,
            }
            for phase in scenario.phases
        ],
    }


def _task_to_dict(task: Task) -> dict[str, Any]:
    return {"id": task.id, "group_id": task.group_id, "title": task.title, "description": task.description, "status": task.status.value, "estimate_seconds": task.estimate_seconds, "tags": list(task.tags), "position": task.position}


def create_web_app(
    database: SQLiteDatabase,
    state_provider: Callable[[], dict[str, Any]] | None = None,
    controller: ScenarioController | None = None,
) -> FastAPI:
    """Создать API, доступное исключительно через loopback-адрес сервера.

    Сервер запускается только на `127.0.0.1`; TrustedHost дополнительно
    отвергает запросы с подменённым Host. CORS намеренно не включён: панель
    и API имеют один origin, поэтому внешние сайты не получают доступ.
    """
    database.migrate()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "testserver"],
    )

    web_root = Path(__file__).resolve().parents[2] / "web"

    @app.get("/")
    def dashboard() -> FileResponse:
        return FileResponse(
            web_root / "index.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/overlay/{overlay_name}")
    def overlay(overlay_name: str) -> FileResponse:
        allowed = {"minimal", "scene", "progress"}
        if overlay_name not in allowed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
        return FileResponse(
            web_root / "overlays" / f"{overlay_name}.html",
            media_type="text/html",
            headers={"Cache-Control": "no-store, max-age=0"},
        )

    @app.get("/assets/{asset_path:path}")
    def asset(asset_path: str) -> FileResponse:
        candidate = (web_root / "assets" / asset_path).resolve()
        assets_root = (web_root / "assets").resolve()
        if assets_root not in candidate.parents or not candidate.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
        return FileResponse(candidate, headers={"Cache-Control": "no-store, max-age=0"})

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/preferences")
    def get_preferences() -> dict[str, Any]:
        stored = database.get_setting("app_preferences", {})
        defaults = PreferencesPayload().model_dump()
        return {**defaults, **stored} if isinstance(stored, dict) else defaults

    @app.put("/api/preferences")
    def save_preferences(payload: PreferencesPayload) -> dict[str, Any]:
        value = payload.model_dump()
        database.set_setting("app_preferences", value)
        return value

    @app.get("/api/state")
    def timer_state() -> dict[str, Any]:
        return state_provider() if state_provider is not None else {"phase": "idle", "time": "00:00"}

    @app.get("/api/events")
    async def state_events() -> StreamingResponse:
        """Поток состояния для панели; `/api/state` остаётся fallback-путём."""
        async def stream():
            while True:
                payload = state_provider() if state_provider is not None else {"phase": "idle", "time": "00:00"}
                yield f"event: state\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/scenarios")
    def list_scenarios() -> dict[str, list[dict[str, Any]]]:
        return {"items": [_scenario_to_dict(scenario) for scenario in database.list_scenarios()]}

    @app.get("/api/task-groups")
    def list_task_groups() -> dict[str, list[dict[str, Any]]]:
        return {"items": [{"id": group.id, "parent_id": group.parent_id, "name": group.name, "position": group.position, "is_archived": group.is_archived} for group in database.list_task_groups()]}

    @app.post("/api/task-groups", status_code=status.HTTP_201_CREATED)
    def create_task_group(payload: TaskGroupPayload) -> dict[str, Any]:
        try:
            group = database.save_task_group(TaskGroup(name=payload.name, parent_id=payload.parent_id))
            return {"id": group.id, "parent_id": group.parent_id, "name": group.name, "position": group.position, "is_archived": group.is_archived}
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.get("/api/tasks")
    def list_tasks() -> dict[str, list[dict[str, Any]]]:
        return {"items": [_task_to_dict(task) for task in database.list_tasks()]}

    @app.get("/api/analytics/tasks")
    def task_time_summary() -> dict[str, list[dict[str, object]]]:
        return {"items": database.time_summary_by_task()}

    @app.get("/api/analytics/days")
    def day_time_summary() -> dict[str, list[dict[str, object]]]:
        return {"items": database.time_summary_by_day()}

    @app.get("/api/analytics/scenarios")
    def scenario_time_summary() -> dict[str, list[dict[str, object]]]:
        return {"items": database.time_summary_by_scenario()}

    @app.get("/api/history")
    def time_history(
        task_id: int | None = None, group_id: int | None = None, scenario_id: int | None = None,
        date_from: str | None = None, date_to: str | None = None,
    ) -> dict[str, list[dict[str, object]]]:
        return {"items": database.list_time_entries(task_id=task_id, group_id=group_id, scenario_id=scenario_id, date_from=date_from, date_to=date_to)}

    @app.patch("/api/history/{entry_id}")
    def correct_history_entry(entry_id: int, payload: TimeEntryCorrectionPayload) -> dict[str, bool]:
        try:
            database.correct_time_entry(entry_id, payload.elapsed_seconds)
            return {"ok": True}
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Запись времени не найдена") from None

    @app.get("/api/history.csv")
    def export_history_csv(date_from: str | None = None, date_to: str | None = None) -> Response:
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(["started_at", "ended_at", "elapsed_seconds", "task", "scenario", "phase", "source"])
        def csv_cell(value: object) -> str:
            text = "" if value is None else str(value)
            return f"'{text}" if text[:1] in {"=", "+", "-", "@"} else text
        for entry in database.list_time_entries(limit=1_000, date_from=date_from, date_to=date_to):
            writer.writerow([csv_cell(entry[key]) for key in ("started_at", "ended_at", "elapsed_seconds", "task_title", "scenario_name", "phase_name", "source")])
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=worktimer-history.csv"})

    @app.post("/api/tasks", status_code=status.HTTP_201_CREATED)
    def create_task(payload: TaskPayload) -> dict[str, Any]:
        try:
            return _task_to_dict(database.save_task(Task(title=payload.title, group_id=payload.group_id, description=payload.description, estimate_seconds=payload.estimate_seconds, status=payload.status, tags=tuple(payload.tags))))
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.put("/api/tasks/{task_id}")
    def update_task(task_id: int, payload: TaskPayload) -> dict[str, Any]:
        try:
            return _task_to_dict(database.save_task(Task(id=task_id, title=payload.title, group_id=payload.group_id, description=payload.description, estimate_seconds=payload.estimate_seconds, status=payload.status, tags=tuple(payload.tags))))
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена") from None
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/api/tasks/{task_id}/select")
    def select_task(task_id: int) -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.select_task(task_id))

    @app.post("/api/tasks/clear-selection")
    def clear_task_selection() -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.select_task(None))

    def require_controller() -> ScenarioController:
        if controller is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Управление таймером ещё не готово")
        return controller

    def run_action(action: Callable[[ScenarioController], None]) -> dict[str, Any]:
        active_controller = require_controller()
        try:
            action(active_controller)
            return active_controller.to_dict()
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/api/timer/toggle")
    def toggle_timer() -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.start())

    @app.post("/api/timer/next")
    def next_timer_phase() -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.next_phase())

    @app.post("/api/timer/repeat")
    def repeat_timer_phase() -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.repeat_phase())

    @app.post("/api/timer/phase/{position}")
    def start_specific_phase(position: int) -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.start_phase(position))

    @app.post("/api/timer/restart")
    def restart_timer_scenario() -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.start_from_beginning())

    @app.post("/api/timer/free")
    def start_free_timer() -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.start_free())

    @app.post("/api/timer/pomodoro")
    def start_pomodoro(payload: PomodoroPayload) -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.start_pomodoro(payload.work_seconds, payload.break_seconds, payload.long_break_seconds, payload.cycles_before_long_break))

    @app.post("/api/timer/stop")
    def stop_timer() -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.stop())

    @app.post("/api/scenarios/{scenario_id}/select")
    def select_scenario(scenario_id: int) -> dict[str, Any]:
        return run_action(lambda active_controller: active_controller.select_scenario(scenario_id))

    @app.post("/api/scenarios", status_code=status.HTTP_201_CREATED)
    def create_scenario(payload: ScenarioPayload) -> dict[str, Any]:
        try:
            scenario = Scenario(
                name=payload.name,
                progress_total=payload.progress_total,
                phases=tuple(
                    Phase(
                        name=phase.name,
                        duration_seconds=phase.duration_seconds,
                        color_role=phase.color_role,
                        repeat_policy=phase.repeat_policy,
                        sound_enabled=phase.sound_enabled,
                        notification_enabled=phase.notification_enabled,
                        note=phase.note,
                        progress_marker=phase.progress_marker,
                        position=position,
                    )
                    for position, phase in enumerate(payload.phases)
                ),
            )
            return _scenario_to_dict(database.save_scenario(scenario))
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error
        except Exception:
            logger.exception("Не удалось сохранить сценарий")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Не удалось сохранить сценарий",
            ) from None

    @app.post("/api/scenarios/presets/{preset_name}", status_code=status.HTTP_201_CREATED)
    def create_scenario_preset(preset_name: str) -> dict[str, Any]:
        try:
            scenario = _preset_scenario(preset_name)
            existing_names = {item.name.casefold() for item in database.list_scenarios()}
            base_name, unique_name, suffix = scenario.name, scenario.name, 2
            while unique_name.casefold() in existing_names:
                unique_name = f"{base_name} {suffix}"
                suffix += 1
            created = database.save_scenario(Scenario(unique_name, scenario.phases, progress_total=scenario.progress_total))
            return _scenario_to_dict(created)
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.put("/api/scenarios/{scenario_id}")
    def update_scenario(scenario_id: int, payload: ScenarioPayload) -> dict[str, Any]:
        try:
            existing = database.get_scenario(scenario_id)
            scenario = Scenario(
                id=existing.id,
                name=payload.name,
                is_archived=existing.is_archived,
                progress_total=payload.progress_total,
                phases=tuple(
                    Phase(
                        name=phase.name,
                        duration_seconds=phase.duration_seconds,
                        color_role=phase.color_role,
                        repeat_policy=phase.repeat_policy,
                        sound_enabled=phase.sound_enabled,
                        notification_enabled=phase.notification_enabled,
                        note=phase.note,
                        progress_marker=phase.progress_marker,
                        position=position,
                    )
                    for position, phase in enumerate(payload.phases)
                ),
            )
            return _scenario_to_dict(database.save_scenario(scenario))
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сценарий не найден") from None
        except ValueError as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)) from error

    @app.post("/api/scenarios/{scenario_id}/duplicate", status_code=status.HTTP_201_CREATED)
    def duplicate_scenario(scenario_id: int) -> dict[str, Any]:
        try:
            return _scenario_to_dict(database.duplicate_scenario(scenario_id))
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сценарий не найден") from None

    @app.delete("/api/scenarios/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
    def archive_scenario(scenario_id: int) -> None:
        try:
            database.archive_scenario(scenario_id)
        except KeyError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сценарий не найден") from None

    return app


class LocalWebServer:
    """Запускает ASGI-сервер в daemon-потоке только на loopback-интерфейсе."""

    def __init__(self, app: FastAPI, port: int = 8765) -> None:
        self._app = app
        self._port = port
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        config = uvicorn.Config(self._app, host="127.0.0.1", port=self._port, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="worktimer-web", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._server = None
        self._thread = None
