import customtkinter as ctk
import threading
import time
import json
import os
import sys
import math
from PIL import Image, ImageDraw

# ── optional deps ──────────────────────────────────────────────────────────────
try:
    from plyer import notification as plyer_notification
    PLYER_OK = True
except ImportError:
    PLYER_OK = False

try:
    import pystray
    PYSTRAY_OK = True
except ImportError:
    PYSTRAY_OK = False

try:
    import keyboard
    KEYBOARD_OK = True
except ImportError:
    KEYBOARD_OK = False

# ── winsound (built-in on Windows) ────────────────────────────────────────────
try:
    import winsound
    def beep_work():
        for _ in range(3):
            winsound.Beep(880, 200)
            time.sleep(0.1)
    def beep_rest():
        for _ in range(2):
            winsound.Beep(523, 300)
            time.sleep(0.15)
except ImportError:
    def beep_work(): pass
    def beep_rest(): pass

# ══════════════════════════════════════════════════════════════════════════════
CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".focus_timer_config.json")

DEFAULT_CONFIG = {
    "profiles": {
        "Работа":  {"work": 60, "rest": 10},
        "Учёба":   {"work": 50, "rest": 10},
        "Спорт":   {"work": 45, "rest": 15},
    },
    "active_profile": "Работа",
    "dnd": False,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
COLORS = {
    "bg":           "#0d0d0d",
    "panel":        "#161616",
    "border":       "#2a2a2a",
    "work":         "#e05c3a",
    "rest":         "#3abfe0",
    "text":         "#f0ece4",
    "subtext":      "#6b6b6b",
    "btn_work":     "#e05c3a",
    "btn_rest":     "#3abfe0",
    "btn_neutral":  "#2a2a2a",
    "btn_hover":    "#3a3a3a",
    "dnd_on":       "#9b59b6",
}

# ══════════════════════════════════════════════════════════════════════════════
class FocusTimer(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_config()

        # state
        self.mode        = "work"   # "work" | "rest"
        self.running     = False
        self.paused      = False
        self.remaining   = 0
        self.total       = 0
        self._tick_thread = None
        self._tray_icon   = None
        self._confirm_win = None

        self._build_ui()
        self._apply_profile()
        self._setup_hotkeys()
        self._setup_tray()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Map>", lambda e: self._on_restore())

    # ── UI BUILD ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.title("Focus Timer")
        self.geometry("400x560")
        self.resizable(False, False)
        self.configure(fg_color=COLORS["bg"])

        # ── header ──
        hdr = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=48)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        self.lbl_title = ctk.CTkLabel(
            hdr, text="FOCUS TIMER",
            font=("Courier New", 13, "bold"),
            text_color=COLORS["subtext"]
        )
        self.lbl_title.pack(side="left", padx=20)

        self.btn_dnd = ctk.CTkButton(
            hdr, text="🔕 DND", width=80, height=28,
            font=("Courier New", 11),
            fg_color=COLORS["dnd_on"] if self.cfg.get("dnd") else COLORS["btn_neutral"],
            hover_color=COLORS["btn_hover"],
            corner_radius=4,
            command=self._toggle_dnd
        )
        self.btn_dnd.pack(side="right", padx=12)

        # ── profile bar ──
        pbar = ctk.CTkFrame(self, fg_color=COLORS["panel"], corner_radius=0, height=40)
        pbar.pack(fill="x")
        pbar.pack_propagate(False)

        self.profile_btns = {}
        for name in self.cfg["profiles"]:
            b = ctk.CTkButton(
                pbar, text=name, width=90, height=28,
                font=("Courier New", 11),
                fg_color=COLORS["btn_neutral"],
                hover_color=COLORS["btn_hover"],
                corner_radius=4,
                command=lambda n=name: self._select_profile(n)
            )
            b.pack(side="left", padx=(12 if name == list(self.cfg["profiles"])[0] else 4, 0))
            self.profile_btns[name] = b

        # ── mode badge ──
        self.lbl_mode = ctk.CTkLabel(
            self, text="РАБОТА",
            font=("Courier New", 14, "bold"),
            text_color=COLORS["work"]
        )
        self.lbl_mode.pack(pady=(32, 0))

        # ── big clock ──
        self.lbl_clock = ctk.CTkLabel(
            self, text="60:00",
            font=("Courier New", 72, "bold"),
            text_color=COLORS["text"]
        )
        self.lbl_clock.pack(pady=(8, 0))

        # ── progress bar ──
        self.progress = ctk.CTkProgressBar(
            self, width=320, height=6,
            corner_radius=3,
            fg_color=COLORS["border"],
            progress_color=COLORS["work"]
        )
        self.progress.set(0)
        self.progress.pack(pady=20)

        # ── main buttons ──
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=4)

        self.btn_start = ctk.CTkButton(
            btn_row, text="▶  СТАРТ", width=140, height=48,
            font=("Courier New", 14, "bold"),
            fg_color=COLORS["work"], hover_color="#c04a2e",
            corner_radius=6,
            command=self._start_pause
        )
        self.btn_start.pack(side="left", padx=6)

        self.btn_stop = ctk.CTkButton(
            btn_row, text="■  СТОП", width=100, height=48,
            font=("Courier New", 13),
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"],
            corner_radius=6,
            command=self._stop
        )
        self.btn_stop.pack(side="left", padx=6)

        # ── settings section ──
        sep = ctk.CTkFrame(self, fg_color=COLORS["border"], height=1)
        sep.pack(fill="x", padx=24, pady=28)

        self.lbl_settings = ctk.CTkLabel(
            self, text="НАСТРОЙКИ ПРОФИЛЯ",
            font=("Courier New", 11),
            text_color=COLORS["subtext"]
        )
        self.lbl_settings.pack()

        sg = ctk.CTkFrame(self, fg_color="transparent")
        sg.pack(pady=12)

        # work time
        ctk.CTkLabel(sg, text="Работа (мин)", font=("Courier New", 11),
                     text_color=COLORS["subtext"]).grid(row=0, column=0, padx=12, pady=4, sticky="w")
        self.spin_work = ctk.CTkEntry(sg, width=70, font=("Courier New", 13),
                                      fg_color=COLORS["panel"], border_color=COLORS["border"],
                                      justify="center")
        self.spin_work.grid(row=0, column=1, padx=12)

        # rest time
        ctk.CTkLabel(sg, text="Отдых (мин)", font=("Courier New", 11),
                     text_color=COLORS["subtext"]).grid(row=1, column=0, padx=12, pady=4, sticky="w")
        self.spin_rest = ctk.CTkEntry(sg, width=70, font=("Courier New", 13),
                                      fg_color=COLORS["panel"], border_color=COLORS["border"],
                                      justify="center")
        self.spin_rest.grid(row=1, column=1, padx=12)

        self.btn_save = ctk.CTkButton(
            self, text="💾  Сохранить профиль", width=200, height=34,
            font=("Courier New", 12),
            fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"],
            corner_radius=6,
            command=self._save_profile
        )
        self.btn_save.pack(pady=8)

        # ── status line ──
        self.lbl_status = ctk.CTkLabel(
            self, text="Нажмите СТАРТ",
            font=("Courier New", 11),
            text_color=COLORS["subtext"]
        )
        self.lbl_status.pack(pady=(10, 0))

    # ── PROFILE ────────────────────────────────────────────────────────────────
    def _apply_profile(self):
        name = self.cfg["active_profile"]
        p = self.cfg["profiles"][name]
        mins = p["work"] if self.mode == "work" else p["rest"]
        self.remaining = mins * 60
        self.total     = self.remaining
        self._update_clock()
        self.progress.set(0)

        self.spin_work.delete(0, "end")
        self.spin_work.insert(0, str(p["work"]))
        self.spin_rest.delete(0, "end")
        self.spin_rest.insert(0, str(p["rest"]))

        # highlight active profile button
        accent = COLORS["work"] if self.mode == "work" else COLORS["rest"]
        for n, b in self.profile_btns.items():
            b.configure(fg_color=accent if n == name else COLORS["btn_neutral"])

    def _select_profile(self, name):
        self._stop()
        self.cfg["active_profile"] = name
        self.mode = "work"
        self._apply_profile()
        self._refresh_mode_ui()
        save_config(self.cfg)

    def _save_profile(self):
        name = self.cfg["active_profile"]
        try:
            w = int(self.spin_work.get())
            r = int(self.spin_rest.get())
            assert 1 <= w <= 240 and 1 <= r <= 60
        except Exception:
            self.lbl_status.configure(text="⚠ Введите корректные числа", text_color="#e0a03a")
            return
        self.cfg["profiles"][name] = {"work": w, "rest": r}
        save_config(self.cfg)
        self._stop()
        self._apply_profile()
        self.lbl_status.configure(text="✔ Сохранено", text_color=COLORS["rest"])
        self.after(2000, lambda: self.lbl_status.configure(
            text="Нажмите СТАРТ", text_color=COLORS["subtext"]))

    # ── TIMER LOGIC ────────────────────────────────────────────────────────────
    def _start_pause(self):
        if not self.running:
            self.running = True
            self.paused  = False
            if self.remaining == 0 or self.remaining == self.total:
                p = self.cfg["profiles"][self.cfg["active_profile"]]
                mins = p["work"] if self.mode == "work" else p["rest"]
                self.remaining = mins * 60
                self.total     = self.remaining
            self.btn_start.configure(text="⏸  ПАУЗА")
            self._tick_thread = threading.Thread(target=self._tick, daemon=True)
            self._tick_thread.start()
            self.lbl_status.configure(text="Идёт отсчёт…", text_color=COLORS["subtext"])
        elif self.paused:
            self.paused = False
            self.btn_start.configure(text="⏸  ПАУЗА")
            self.lbl_status.configure(text="Идёт отсчёт…", text_color=COLORS["subtext"])
        else:
            self.paused = True
            self.btn_start.configure(text="▶  ПРОДОЛЖИТЬ")
            self.lbl_status.configure(text="На паузе", text_color=COLORS["subtext"])

    def _stop(self):
        self.running = False
        self.paused  = False
        self.mode    = "work"
        self._apply_profile()
        self._refresh_mode_ui()
        self.btn_start.configure(text="▶  СТАРТ")
        self.lbl_status.configure(text="Нажмите СТАРТ", text_color=COLORS["subtext"])

    def _tick(self):
        while self.running and self.remaining > 0:
            if not self.paused:
                time.sleep(1)
                if not self.paused:
                    self.remaining -= 1
                    self.after(0, self._update_clock)
                    self.after(0, self._update_progress)
            else:
                time.sleep(0.2)
        if self.running and self.remaining == 0:
            self.after(0, self._on_timer_end)

    def _on_timer_end(self):
        self.running = False
        self.btn_start.configure(text="▶  СТАРТ")

        if self.mode == "work":
            beep_work()
            self._notify("⏰ Время работы истекло!", "Пора отдохнуть. Подтвердите начало отдыха.")
            self._show_confirm(
                "Время работы вышло!",
                "Начать таймер отдыха?",
                on_yes=self._switch_to_rest,
                yes_label="Начать отдых",
                color=COLORS["rest"]
            )
        else:
            beep_rest()
            self._notify("✅ Отдых завершён!", "Время вернуться к работе.")
            self._show_confirm(
                "Отдых завершён!",
                "Начать новый рабочий цикл?",
                on_yes=self._switch_to_work,
                yes_label="Начать работу",
                color=COLORS["work"]
            )

    def _switch_to_rest(self):
        self.mode = "rest"
        self._apply_profile()
        self._refresh_mode_ui()
        self._start_pause()

    def _switch_to_work(self):
        self.mode = "work"
        self._apply_profile()
        self._refresh_mode_ui()
        self._start_pause()

    # ── UI UPDATES ─────────────────────────────────────────────────────────────
    def _update_clock(self):
        m, s = divmod(max(self.remaining, 0), 60)
        self.lbl_clock.configure(text=f"{m:02d}:{s:02d}")
        # update tray tooltip
        if self._tray_icon:
            try:
                label = "Работа" if self.mode == "work" else "Отдых"
                self._tray_icon.title = f"Focus Timer — {label} {m:02d}:{s:02d}"
            except Exception:
                pass

    def _update_progress(self):
        if self.total > 0:
            ratio = 1 - self.remaining / self.total
            self.progress.set(ratio)

    def _refresh_mode_ui(self):
        if self.mode == "work":
            accent = COLORS["work"]
            self.lbl_mode.configure(text="РАБОТА", text_color=accent)
            self.btn_start.configure(fg_color=accent, hover_color="#c04a2e")
            self.progress.configure(progress_color=accent)
        else:
            accent = COLORS["rest"]
            self.lbl_mode.configure(text="ОТДЫХ", text_color=accent)
            self.btn_start.configure(fg_color=accent, hover_color="#289ab8")
            self.progress.configure(progress_color=accent)

        name = self.cfg["active_profile"]
        for n, b in self.profile_btns.items():
            b.configure(fg_color=accent if n == name else COLORS["btn_neutral"])

    # ── NOTIFICATIONS ──────────────────────────────────────────────────────────
    def _notify(self, title, msg):
        if self.cfg.get("dnd"):
            return
        if PLYER_OK:
            try:
                plyer_notification.notify(
                    title=title, message=msg,
                    app_name="Focus Timer", timeout=8
                )
            except Exception:
                pass
        # bring window to front
        self.after(0, self._bring_to_front)

    def _bring_to_front(self):
        if self.state() == "withdrawn":
            self.deiconify()
        self.lift()
        self.focus_force()

    # ── CONFIRM DIALOG ─────────────────────────────────────────────────────────
    def _show_confirm(self, title, msg, on_yes, yes_label="OK", color=COLORS["work"]):
        if self._confirm_win and self._confirm_win.winfo_exists():
            self._confirm_win.destroy()

        win = ctk.CTkToplevel(self)
        win.title("")
        win.geometry("320x180")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["panel"])
        win.grab_set()
        win.lift()
        win.focus_force()
        self._confirm_win = win

        ctk.CTkLabel(win, text=title, font=("Courier New", 15, "bold"),
                     text_color=color).pack(pady=(24, 4))
        ctk.CTkLabel(win, text=msg, font=("Courier New", 11),
                     text_color=COLORS["subtext"]).pack(pady=4)

        row = ctk.CTkFrame(win, fg_color="transparent")
        row.pack(pady=16)

        def _yes():
            win.destroy()
            on_yes()

        def _no():
            win.destroy()
            self.lbl_status.configure(text="Остановлено", text_color=COLORS["subtext"])

        ctk.CTkButton(row, text=yes_label, width=130, height=36,
                      font=("Courier New", 12, "bold"),
                      fg_color=color, hover_color=COLORS["btn_hover"],
                      corner_radius=5, command=_yes).pack(side="left", padx=8)
        ctk.CTkButton(row, text="Отмена", width=100, height=36,
                      font=("Courier New", 12),
                      fg_color=COLORS["btn_neutral"], hover_color=COLORS["btn_hover"],
                      corner_radius=5, command=_no).pack(side="left", padx=8)

    # ── DND ────────────────────────────────────────────────────────────────────
    def _toggle_dnd(self):
        self.cfg["dnd"] = not self.cfg.get("dnd", False)
        save_config(self.cfg)
        if self.cfg["dnd"]:
            self.btn_dnd.configure(fg_color=COLORS["dnd_on"], text="🔕 DND")
        else:
            self.btn_dnd.configure(fg_color=COLORS["btn_neutral"], text="🔕 DND")

    # ── TRAY ───────────────────────────────────────────────────────────────────
    def _make_tray_icon_image(self):
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill="#e05c3a")
        d.polygon([(24, 18), (24, 46), (48, 32)], fill="white")
        return img

    def _setup_tray(self):
        if not PYSTRAY_OK:
            return
        try:
            img = self._make_tray_icon_image()
            menu = pystray.Menu(
                pystray.MenuItem("Показать", self._tray_show, default=True),
                pystray.MenuItem("Старт / Пауза", lambda: self.after(0, self._start_pause)),
                pystray.MenuItem("Стоп", lambda: self.after(0, self._stop)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Выход", self._tray_quit),
            )
            self._tray_icon = pystray.Icon("focus_timer", img, "Focus Timer", menu)
            threading.Thread(target=self._tray_icon.run, daemon=True).start()
        except Exception:
            pass

    def _tray_show(self):
        self.after(0, self._bring_to_front)

    def _tray_quit(self):
        self.running = False
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    def _on_close(self):
        if PYSTRAY_OK and self._tray_icon:
            self.withdraw()
        else:
            self._tray_quit()

    def _on_restore(self):
        pass

    # ── HOTKEYS ────────────────────────────────────────────────────────────────
    def _setup_hotkeys(self):
        if not KEYBOARD_OK:
            return
        try:
            keyboard.add_hotkey("ctrl+alt+space", lambda: self.after(0, self._start_pause))
            keyboard.add_hotkey("ctrl+alt+s",     lambda: self.after(0, self._stop))
        except Exception:
            pass

# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = FocusTimer()
    app.mainloop()
