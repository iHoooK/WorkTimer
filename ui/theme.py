"""
ui/theme.py - modern WorkTimer palettes and theme selection helpers.
"""

from __future__ import annotations

import sys

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEME_MODES = {THEME_SYSTEM, THEME_LIGHT, THEME_DARK}

_THEMES: dict[str, dict[str, str]] = {
    THEME_DARK: {
        "bg": "#0b1020",
        "panel": "#111827",
        "panel_light": "#172033",
        "border": "#293548",
        "border_glow": "#3b82f6",
        "work": "#38bdf8",
        "rest": "#34d399",
        "prep": "#a78bfa",
        "custom": "#f59e0b",
        "text": "#f8fafc",
        "subtext": "#94a3b8",
        "accent_text": "#bfdbfe",
        "btn_work": "#0284c7",
        "btn_rest": "#059669",
        "btn_neutral": "#1f2937",
        "btn_hover": "#334155",
        "btn_work_hover": "#0369a1",
        "btn_rest_hover": "#047857",
        "dnd_on": "#ef4444",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "danger": "#ef4444",
        "glow_work": "#7dd3fc",
        "glow_rest": "#6ee7b7",
        "glow_purple": "#c4b5fd",
    },
    THEME_LIGHT: {
        "bg": "#f6f8fb",
        "panel": "#ffffff",
        "panel_light": "#eef2f7",
        "border": "#d8e0eb",
        "border_glow": "#2563eb",
        "work": "#2563eb",
        "rest": "#0f766e",
        "prep": "#7c3aed",
        "custom": "#d97706",
        "text": "#0f172a",
        "subtext": "#64748b",
        "accent_text": "#1d4ed8",
        "btn_work": "#2563eb",
        "btn_rest": "#0f766e",
        "btn_neutral": "#e2e8f0",
        "btn_hover": "#cbd5e1",
        "btn_work_hover": "#1d4ed8",
        "btn_rest_hover": "#115e59",
        "dnd_on": "#dc2626",
        "success": "#16a34a",
        "warning": "#d97706",
        "danger": "#dc2626",
        "glow_work": "#60a5fa",
        "glow_rest": "#2dd4bf",
        "glow_purple": "#8b5cf6",
    },
}

_active_theme = THEME_DARK
COLORS: dict[str, str] = dict(_THEMES[_active_theme])

FONTS: dict[str, tuple] = {
    "clock": ("Courier New", 64, "bold"),
    "clock_big": ("Courier New", 120, "bold"),
    "title": ("Segoe UI", 11, "bold"),
    "mode": ("Segoe UI", 13, "bold"),
    "section": ("Segoe UI", 10),
    "btn_icon": ("Segoe UI Emoji", 16),
    "btn_sm": ("Segoe UI", 10, "bold"),
    "btn_text": ("Segoe UI", 12, "bold"),
    "entry": ("Courier New", 13),
    "label": ("Segoe UI", 10),
    "label_bold": ("Segoe UI", 10, "bold"),
    "dialog_title": ("Segoe UI", 14, "bold"),
    "dialog_msg": ("Segoe UI", 10),
    "profile_btn": ("Segoe UI", 10, "bold"),
    "btn_xs": ("Segoe UI", 10, "bold"),
    "btn": ("Segoe UI", 12, "bold"),
    "dialog": ("Segoe UI", 14, "bold"),
}


def normalize_theme_mode(value: object) -> str:
    mode = str(value or THEME_SYSTEM).strip().lower()
    return mode if mode in THEME_MODES else THEME_SYSTEM


def get_system_theme_mode() -> str:
    if not sys.platform.startswith("win"):
        return THEME_DARK
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return THEME_LIGHT if int(value) else THEME_DARK
    except Exception:
        return THEME_DARK


def resolve_theme_mode(preference: object) -> str:
    mode = normalize_theme_mode(preference)
    return get_system_theme_mode() if mode == THEME_SYSTEM else mode


def set_theme_mode(mode: object) -> str:
    global _active_theme
    resolved = resolve_theme_mode(mode)
    _active_theme = resolved
    COLORS.clear()
    COLORS.update(_THEMES[resolved])
    try:
        import customtkinter as ctk

        ctk.set_appearance_mode("Light" if resolved == THEME_LIGHT else "Dark")
    except Exception:
        pass
    return resolved


def get_active_theme_mode() -> str:
    return _active_theme


def accent_for_mode(mode: str) -> str:
    return COLORS["work"] if mode == "work" else COLORS["rest"]


def accent_for_phase_role(role: str) -> str:
    role = (role or "").strip().lower()
    if role in {"work", "rest", "prep", "custom"}:
        return COLORS[role]
    return COLORS["accent_text"]


def hover_for_mode(mode: str) -> str:
    return COLORS["btn_work_hover"] if mode == "work" else COLORS["btn_rest_hover"]


def glow_for_mode(mode: str) -> str:
    return COLORS["glow_work"] if mode == "work" else COLORS["glow_rest"]
