"""Локальный HTTP API и web-панель WorkTimer."""

from .server import LocalWebServer, create_web_app

__all__ = ["LocalWebServer", "create_web_app"]
