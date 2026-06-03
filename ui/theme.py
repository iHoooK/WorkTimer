"""
ui/theme.py — Тема «Dark Fantasy / Neural» (v2).

Палитра вдохновлена тёмным фэнтези + эстетикой нейросетей:
  глубокий фиолетово-чёрный фон, золотые и голубые акценты, пурпурное свечение.
"""

from __future__ import annotations

# ===========================================================================
# Цвета
# ===========================================================================

COLORS: dict[str, str] = {
    # Фоны
    "bg":           "#08061a",
    "panel":        "#100e28",
    "panel_light":  "#17143a",
    "border":       "#2d2660",
    "border_glow":  "#6d28d9",

    # Акценты режимов
    "work":         "#f59e0b",   # янтарно-золотой
    "rest":         "#06b6d4",   # голубой циан

    # Текст
    "text":         "#f0ebff",
    "subtext":      "#6b5fa8",
    "accent_text":  "#a78bfa",

    # Кнопки
    "btn_work":         "#f59e0b",
    "btn_rest":         "#06b6d4",
    "btn_neutral":      "#1e1a45",
    "btn_hover":        "#2d2660",
    "btn_work_hover":   "#d97706",
    "btn_rest_hover":   "#0891b2",

    # Специальные
    "dnd_on":       "#dc2626",
    "success":      "#10b981",
    "warning":      "#f59e0b",
    "danger":       "#ef4444",

    # Эффекты
    "glow_work":    "#fbbf24",
    "glow_rest":    "#22d3ee",
    "glow_purple":  "#a855f7",
}

# ===========================================================================
# Шрифты
# ===========================================================================

FONTS: dict[str, tuple] = {
    # Таймер
    "clock":        ("Courier New", 64, "bold"),
    "clock_big":    ("Courier New", 120, "bold"),

    # Заголовки
    "title":        ("Segoe UI", 11, "bold"),
    "mode":         ("Segoe UI", 13, "bold"),
    "section":      ("Segoe UI", 10),

    # Кнопки
    "btn_icon":     ("Segoe UI Emoji", 16),
    "btn_sm":       ("Segoe UI", 10, "bold"),
    "btn_text":     ("Segoe UI", 12, "bold"),

    # Поля и диалоги
    "entry":        ("Courier New", 13),
    "label":        ("Segoe UI", 10),
    "label_bold":   ("Segoe UI", 10, "bold"),
    "dialog_title": ("Segoe UI", 14, "bold"),
    "dialog_msg":   ("Segoe UI", 10),
    "profile_btn":  ("Segoe UI", 10, "bold"),

    # Алиасы для совместимости со старыми компонентами
    "btn_xs":       ("Segoe UI", 10, "bold"),
    "btn":          ("Segoe UI", 12, "bold"),
    "dialog":       ("Segoe UI", 14, "bold"),
}

# ===========================================================================
# Вспомогательные функции
# ===========================================================================

def accent_for_mode(mode: str) -> str:
    return COLORS["work"] if mode == "work" else COLORS["rest"]

def hover_for_mode(mode: str) -> str:
    return COLORS["btn_work_hover"] if mode == "work" else COLORS["btn_rest_hover"]

def glow_for_mode(mode: str) -> str:
    return COLORS["glow_work"] if mode == "work" else COLORS["glow_rest"]
