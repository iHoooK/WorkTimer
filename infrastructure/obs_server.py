"""
infrastructure/obs_server.py — Мини HTTP-сервер для OBS Browser Source.

Запускается в фоновом daemon-потоке при старте приложения.

Эндпоинты:
  GET /          → HTML-оверлей (таймер для стрима)
  GET /api/state → JSON с текущим состоянием таймера

Использование в OBS:
  Источники → + → Браузер → URL: http://localhost:8765
  Ширина: 280, Высота: 120  (или под свой оверлей)
  ✓ Управлять звуком через OBS — выключить
  ✓ Обновлять браузер при активации сцены — включить

Архитектура:
  AppController.on_tick() → obs_server.update(state)
  HTTP-запрос → obs_server.get_state() → JSON-ответ
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8765

# ===========================================================================
# HTML-оверлей (встроен в Python-файл, не требует внешних файлов)
# ===========================================================================

_HTML = """\
<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>Focus Timer</title>
<style>
  *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }

  body {
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 100vh;
    font-family: 'Courier New', Courier, monospace;
  }

  .widget {
    background: rgba(8, 6, 26, 0.88);
    border: 1px solid rgba(109, 40, 217, 0.55);
    border-radius: 14px;
    padding: 14px 32px 16px;
    text-align: center;
    min-width: 230px;
    box-shadow: 0 0 28px rgba(109, 40, 217, 0.25), inset 0 0 40px rgba(8,6,26,0.5);
    transition: border-color 0.6s ease;
    position: relative;
    overflow: hidden;
  }

  /* Лёгкая анимированная линия сверху */
  .widget::before {
    content: '';
    position: absolute;
    top: 0; left: -100%; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent), transparent);
    animation: scan 3s linear infinite;
  }
  @keyframes scan { to { left: 100%; } }

  .mode {
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 4px;
    color: var(--accent);
    margin-bottom: 6px;
    opacity: 0.9;
    transition: color 0.5s ease;
  }

  .time {
    font-size: 54px;
    font-weight: bold;
    color: #f0ebff;
    line-height: 1;
    letter-spacing: 2px;
    text-shadow: 0 0 18px rgba(240,235,255,0.2);
  }

  .progress-wrap {
    margin-top: 10px;
    height: 3px;
    background: rgba(45, 38, 96, 0.7);
    border-radius: 2px;
    overflow: hidden;
  }

  .progress-fill {
    height: 100%;
    background: var(--accent);
    border-radius: 2px;
    transition: width 0.9s linear, background 0.5s ease;
    box-shadow: 0 0 6px var(--accent);
  }

  /* CSS-переменные меняются через JS */
  :root {
    --accent: #f59e0b;
  }
</style>
</head>
<body>
<div class="widget">
  <div class="mode" id="mode">РАБОТА</div>
  <div class="time"  id="time">00:00</div>
  <div class="progress-wrap">
    <div class="progress-fill" id="bar" style="width:0%"></div>
  </div>
</div>

<script>
const modeEl = document.getElementById('mode');
const timeEl = document.getElementById('time');
const barEl  = document.getElementById('bar');

const COLORS = { work: '#f59e0b', rest: '#06b6d4', prep: '#a855f7', custom: '#a78bfa' };

async function poll() {
  try {
    const res  = await fetch('/api/state');
    if (!res.ok) return;
    const data = await res.json();

    const role = data.phase_role || data.mode || 'custom';
    const accent = COLORS[role] || COLORS.custom;

    document.documentElement.style.setProperty('--accent', accent);
    modeEl.textContent = data.phase_name || (role === 'rest' ? 'ОТДЫХ' : 'РАБОТА');
    timeEl.textContent = data.time   || '--:--';
    barEl.style.width  = ((data.progress || 0) * 100).toFixed(1) + '%';
  } catch (_) { /* сервер ещё не готов */ }
}

poll();
setInterval(poll, 250);  // 4 раза в секунду — гарантированно ловим каждый тик Python
</script>
</body>
</html>
"""


# ===========================================================================
# Общее состояние (пишет AppController, читает HTTP-handler)
# ===========================================================================

class _SharedState:
    """Thread-safe состояние таймера для OBS-сервера."""

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        self._time     = "00:00"
        self._mode     = "work"
        self._phase_name = "Работа"
        self._phase_role = "work"
        self._progress = 0.0
        self._phase    = "idle"

    def update(self, time_str: str, mode: str, progress: float, phase: str, phase_name: str, phase_role: str) -> None:
        with self._lock:
            self._time     = time_str
            self._mode     = mode
            self._phase_name = phase_name
            self._phase_role = phase_role
            self._progress = progress
            self._phase    = phase

    def to_json(self) -> bytes:
        with self._lock:
            d = {
                "time":     self._time,
                "mode":     self._mode,
                "phase_name": self._phase_name,
                "phase_role": self._phase_role,
                "progress": round(self._progress, 4),
                "phase":    self._phase,
            }
        return json.dumps(d, ensure_ascii=False).encode()


# ===========================================================================
# HTTP-handler
# ===========================================================================

def _make_handler(state: _SharedState):
    """Фабрика handler-класса с замыканием на state."""

    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):                               # noqa: N802
            if self.path in ("/", "/index.html"):
                body = _HTML.encode("utf-8")
                self._respond(200, "text/html; charset=utf-8", body)
            elif self.path == "/api/state":
                self._respond(200, "application/json", state.to_json())
            else:
                self._respond(404, "text/plain", b"Not found")

        def _respond(self, code: int, ctype: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            # Не кэшировать — OBS и браузер всегда должны читать свежие данные
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):              # подавляем стандартный лог
            pass

    return _Handler


# ===========================================================================
# OBSServer — публичный класс
# ===========================================================================

class OBSServer:
    """
    Мини HTTP-сервер для OBS Browser Source.

    Использование:
        server = OBSServer(port=8765)
        server.start()          # запускает фоновый поток
        server.update(state)    # вызывается AppController на каждый тик
        server.stop()           # при выходе из приложения
    """

    def __init__(self, port: int = DEFAULT_PORT) -> None:
        self._port    = port
        self._state   = _SharedState()
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        """
        Запустить сервер в daemon-потоке.

        Returns:
            True — успешно запущен, False — порт занят или ошибка.
        """
        try:
            handler = _make_handler(self._state)
            self._server = HTTPServer(("127.0.0.1", self._port), handler)
        except OSError as e:
            logger.warning("OBSServer: не удалось запустить на порту %d — %s", self._port, e)
            return False

        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="obs-http-server",
            daemon=True,
        )
        self._thread.start()
        logger.info("OBSServer: запущен → http://localhost:%d", self._port)
        return True

    def update(self, timer_state) -> None:
        """
        Обновить состояние таймера.
        Вызывать из AppController._on_tick().

        Args:
            timer_state: core.timer.TimerState
        """
        self._state.update(
            time_str=timer_state.format_time(),
            mode=timer_state.mode.value,
            progress=timer_state.progress,
            phase=timer_state.phase.value,
            phase_name=timer_state.phase_name,
            phase_role=timer_state.phase_role,
        )

    def stop(self) -> None:
        """Остановить сервер (вызывается при выходе из приложения)."""
        if self._server:
            self._server.shutdown()
            self._server = None
        logger.info("OBSServer: остановлен")

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"http://localhost:{self._port}"

    @property
    def is_running(self) -> bool:
        return self._server is not None
