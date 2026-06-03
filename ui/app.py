"""
ui/app.py — AppController: Facade + Dependency Injection.

Единственное место, где core-слой встречается с UI-слоем.
AppController получает все зависимости через конструктор (DI),
подписывается на события EventBus и дёргает нужные сервисы.

SOLID:
  S — Controller только оркестрирует; не содержит бизнес-логику таймера.
  D — Зависит от абстракций (IStorage, ISoundStrategy), не от реализаций.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from core.events   import EventBus, Event
from core.timer    import TimerEngine, TimerMode, TimerPhase, TimerState
from core.timer    import EVENT_TICK, EVENT_FINISHED, EVENT_STARTED
from core.timer    import EVENT_PAUSED, EVENT_RESUMED, EVENT_STOPPED
from core.profiles import Profile, ProfileRepository
from core.settings import AppSettings, SettingsRepository
from ui.theme      import COLORS

if TYPE_CHECKING:
    from infrastructure.sound         import SoundService
    from infrastructure.notifications import NotificationService
    from infrastructure.tray          import TrayManager
    from infrastructure.hotkeys       import HotkeyManager
    from ui.main_window               import MainWindow

logger = logging.getLogger(__name__)


class AppController:
    """
    Главный оркестратор приложения (Facade).

    Получает все зависимости через __init__ (DI).
    MainWindow вызывает методы AppController в ответ на UI-события.
    AppController обновляет MainWindow через прямой вызов его методов.

    Порядок инициализации:
        1. Создать все зависимости в main.py
        2. Создать AppController(...)
        3. Создать MainWindow(controller=self)
        4. Вызвать controller.set_window(window)
        5. Вызвать controller.on_startup()
        6. window.mainloop()
    """

    def __init__(
        self,
        bus:           EventBus,
        timer:         TimerEngine,
        profiles:      ProfileRepository,
        settings:      SettingsRepository,
        sound:         "SoundService",
        notifications: "NotificationService",
        tray:          "TrayManager",
        hotkeys:       "HotkeyManager",
        obs=None,      # Optional[OBSServer] — не импортируем напрямую, чтобы избежать цикла
    ) -> None:
        self._bus           = bus
        self._timer         = timer
        self._profiles      = profiles
        self._settings      = settings
        self._sound         = sound
        self._notifications = notifications
        self._tray          = tray
        self._hotkeys       = hotkeys
        self._obs           = obs        # OBSServer | None

        # Ссылка на окно — устанавливается после создания MainWindow
        self._window: Optional["MainWindow"] = None

        # Диалоговое окно (только одно за раз)
        self._confirm_win = None

        # Подписка на события таймера
        self._subscribe_events()

    # ===========================================================================
    # Шаг 14.1 — Инициализация
    # ===========================================================================

    def set_window(self, window: "MainWindow") -> None:
        """Установить ссылку на главное окно после его создания."""
        self._window = window

    def on_startup(self) -> None:
        """Инициализация после создания окна: загрузка данных, применение настроек."""
        # Применить настройки
        settings = self._settings.get()
        self._notifications.dnd  = settings.dnd
        self._sound.enabled      = settings.sound_enabled

        # Применить always_on_top
        if self._window:
            self._window.apply_always_on_top(settings.always_on_top)

        # Наполнить UI профилями
        self._refresh_profiles_ui()

        # Загрузить значения текущего профиля в панель настроек
        self._refresh_settings_ui()

        # Настроить горячие клавиши
        self._hotkeys.register({
            "ctrl+alt+space": lambda: self._window.after(0, self.toggle_timer)
                              if self._window else None,
            "ctrl+alt+s":     lambda: self._window.after(0, self.stop_timer)
                              if self._window else None,
        })

        # Настроить трей
        self._tray.setup(
            on_show=        self._bring_to_front,
            on_start_pause= self.toggle_timer,
            on_stop=        self.stop_timer,
            on_quit=        self.quit,
        )

        logger.info("AppController: запуск завершён")

    # ===========================================================================
    # Шаг 14.2 — Обработчики событий таймера
    # ===========================================================================

    def _subscribe_events(self) -> None:
        self._bus.subscribe(EVENT_TICK,     self._on_tick)
        self._bus.subscribe(EVENT_FINISHED, self._on_finished)
        self._bus.subscribe(EVENT_STARTED,  self._on_state_change)
        self._bus.subscribe(EVENT_PAUSED,   self._on_state_change)
        self._bus.subscribe(EVENT_RESUMED,  self._on_state_change)
        self._bus.subscribe(EVENT_STOPPED,  self._on_state_change)

    def _on_tick(self, event: Event) -> None:
        """Каждую секунду: обновить UI, трей, OBS."""
        state: TimerState = event.data
        if self._window:
            self._window.after(0, lambda s=state: self._window.update_timer(s))

        # OBS-сервер
        if self._obs:
            self._obs.update(state)

        # Обновить подсказку трея
        mode_text = "Работа" if state.mode == TimerMode.WORK else "Отдых"
        self._tray.update_tooltip(
            f"Focus Timer — {mode_text} {state.format_time()}"
        )

    def _on_finished(self, event: Event) -> None:
        """Таймер завершился: звук + уведомление + диалог."""
        state: TimerState = event.data

        if self._window:
            self._window.after(0, lambda s=state: self._handle_finish(s))

    def _handle_finish(self, state: TimerState) -> None:
        """Запускается в UI-потоке после завершения таймера."""
        from ui.dialogs.confirm_dialog import ConfirmDialog
        from ui.theme import COLORS

        if state.mode == TimerMode.WORK:
            self._sound.play_work_end()
            self._notifications.notify(
                "⏰ Время работы истекло!",
                "Пора отдохнуть. Подтвердите начало отдыха.",
            )
            # Автопереключение если включено
            if self._settings.get().auto_switch:
                self.switch_to_break()
                return

            if self._confirm_win and self._confirm_win.winfo_exists():
                self._confirm_win.destroy()
            self._confirm_win = ConfirmDialog.show(
                parent=self._window,
                title="Время работы вышло!",
                message="Начать таймер отдыха?",
                yes_label="Начать отдых",
                color=COLORS["rest"],
                on_yes=self.switch_to_break,
                on_no=self._on_confirm_cancelled,
            )
        else:
            self._sound.play_break_end()
            self._notifications.notify(
                "✅ Отдых завершён!",
                "Время вернуться к работе.",
            )
            if self._settings.get().auto_switch:
                self.switch_to_work()
                return

            if self._confirm_win and self._confirm_win.winfo_exists():
                self._confirm_win.destroy()
            self._confirm_win = ConfirmDialog.show(
                parent=self._window,
                title="Отдых завершён!",
                message="Начать новый рабочий цикл?",
                yes_label="Начать работу",
                color=COLORS["work"],
                on_yes=self.switch_to_work,
                on_no=self._on_confirm_cancelled,
            )

    def _on_state_change(self, event: Event) -> None:
        """При любом изменении фазы — обновить UI и OBS."""
        state: TimerState = event.data
        if self._window:
            self._window.after(0, lambda s=state: self._window.update_timer(s))
        if self._obs:
            self._obs.update(state)

    def _on_confirm_cancelled(self) -> None:
        """Пользователь нажал «Отмена» в диалоге после завершения."""
        if self._window:
            self._window.settings_panel.set_status("Остановлено", None)

    # ===========================================================================
    # Шаг 14.3 — Управление таймером
    # ===========================================================================

    def toggle_timer(self) -> None:
        """Старт / Пауза / Возобновить — в зависимости от текущей фазы."""
        state = self._timer.state
        if state.phase == TimerPhase.RUNNING:
            self._timer.pause()
        elif state.phase == TimerPhase.PAUSED:
            self._timer.resume()
        else:
            # IDLE или FINISHED — запустить заново
            profile = self._profiles.get_active()
            mode    = TimerMode.WORK  # всегда начинаем с работы при ручном старте
            self._timer.start(
                duration_seconds=profile.work_seconds,
                mode=mode,
            )

    def stop_timer(self) -> None:
        """Остановить таймер и сбросить UI."""
        self._timer.stop()
        if self._window:
            self._window.after(0, self._reset_ui)

    def switch_to_break(self) -> None:
        """Переключить на режим отдыха и запустить таймер."""
        profile = self._profiles.get_active()
        self._timer.start(
            duration_seconds=profile.break_seconds,
            mode=TimerMode.BREAK,
        )

    def switch_to_work(self) -> None:
        """Переключить на режим работы и запустить таймер."""
        profile = self._profiles.get_active()
        self._timer.start(
            duration_seconds=profile.work_seconds,
            mode=TimerMode.WORK,
        )

    # ===========================================================================
    # Шаг 14.3 — Управление профилями и настройками
    # ===========================================================================

    def select_profile(self, name: str) -> None:
        """Выбрать профиль, остановить таймер, обновить UI."""
        self.stop_timer()
        try:
            self._profiles.set_active(name)
        except KeyError:
            logger.warning("AppController: профиль %r не найден", name)
            return
        self._refresh_profiles_ui()
        self._refresh_settings_ui()

    def save_profile_settings(self, name: str, work_total_seconds: int, break_total_seconds: int) -> None:
        """Сохранить / переименовать активный профиль."""
        active   = self._profiles.get_active()
        old_name = active.name
        try:
            new_profile = Profile(
                name=name,
                work_seconds=work_total_seconds,
                break_seconds=break_total_seconds,
            )
            new_profile.validate()
        except ValueError as e:
            if self._window:
                self._window.settings_panel.flash_status(
                    f"⚠ {e}", COLORS["warning"], self._window
                )
            return

        self.stop_timer()

        if name != old_name:
            # Переименование: сохраняем под новым именем, удаляем старое
            self._profiles.save(new_profile)
            try:
                self._profiles.delete(old_name)
            except (KeyError, RuntimeError):
                pass
            self._profiles.set_active(name)
        else:
            self._profiles.save(new_profile)

        self._refresh_profiles_ui()
        self._refresh_settings_ui()
        if self._window:
            self._window.settings_panel.flash_status(
                "✔ Сохранено", COLORS["success"], self._window
            )

    def create_profile(self, name: str, work_total_seconds: int, break_total_seconds: int) -> None:
        """Создать новый профиль и сделать его активным."""
        try:
            profile = Profile(name=name, work_seconds=work_total_seconds, break_seconds=break_total_seconds)
            profile.validate()
        except ValueError as e:
            logger.warning("AppController.create_profile: %s", e)
            return

        self._profiles.save(profile)
        self._profiles.set_active(name)
        self.stop_timer()
        self._refresh_profiles_ui()
        self._refresh_settings_ui()

    def delete_profile(self, name: str) -> None:
        """Удалить профиль."""
        try:
            self._profiles.delete(name)
        except (KeyError, RuntimeError) as e:
            logger.warning("AppController.delete_profile: %s", e)
            return
        self.stop_timer()
        self._refresh_profiles_ui()
        self._refresh_settings_ui()

    def show_add_profile_dialog(self) -> None:
        """Показать диалог создания профиля."""
        if self._window is None:
            return
        from ui.dialogs.profile_dialog import ProfileDialog
        ProfileDialog.show_create(
            parent=self._window,
            on_create=self.create_profile,
        )

    def show_delete_profile_dialog(self) -> None:
        """Показать диалог удаления профиля."""
        if self._window is None:
            return
        from ui.dialogs.profile_dialog import ProfileDialog
        profiles = [p.name for p in self._profiles.get_all()]
        active   = self._profiles.get_active().name
        ProfileDialog.show_delete(
            parent=self._window,
            profiles=profiles,
            active=active,
            on_delete=self.delete_profile,
        )

    def set_always_on_top(self, value: bool) -> None:
        """Применить и сохранить настройку «Поверх окон»."""
        settings = self._settings.get()
        settings.always_on_top = value
        self._settings.save(settings)
        if self._window:
            self._window.apply_always_on_top(value)

    def toggle_dnd(self) -> None:
        """Переключить Do Not Disturb."""
        settings = self._settings.get()
        settings.dnd = not settings.dnd
        self._settings.save(settings)
        self._notifications.dnd = settings.dnd
        if self._window:
            self._window.update_dnd_button(settings.dnd)
            # Также обновить кнопку в окне настроекесли оно открыто
            sw = self._window.get_settings_window()
            if sw and sw.winfo_exists():
                sw.update_dnd_button(settings.dnd)

    # ===========================================================================
    # Вспомогательные методы
    # ===========================================================================

    def _refresh_profiles_ui(self) -> None:
        """Обновить селектор сцен в главном окне и в окне настроек."""
        if self._window is None:
            return
        profiles = [p.name for p in self._profiles.get_all()]
        active   = self._profiles.get_active().name
        self._window.refresh_profile_selector(profiles, active)

    def _refresh_settings_ui(self) -> None:
        """Заполнить SettingsPanel значениями активного профиля и AppSettings."""
        if self._window is None:
            return
        profile  = self._profiles.get_active()
        settings = self._settings.get()
        self._window.settings_panel.load_profile(
            name=profile.name,
            work_minutes=profile.work_minutes,
            work_seconds=profile.work_extra_sec,
            break_minutes=profile.break_minutes,
            break_seconds=profile.break_extra_sec,
        )
        self._window.settings_panel.load_settings(
            always_on_top=settings.always_on_top,
        )

    def _reset_ui(self) -> None:
        """Сбросить UI в начальное состояние."""
        if self._window is None:
            return
        profile = self._profiles.get_active()
        from core.timer import TimerState, TimerPhase, TimerMode
        idle_state = TimerState(
            mode=TimerMode.WORK,
            phase=TimerPhase.IDLE,
            remaining_seconds=profile.work_seconds,
            total_seconds=profile.work_seconds,
            elapsed_seconds=0,
        )
        self._window.update_timer(idle_state)

    def _bring_to_front(self) -> None:
        """Показать окно и вывести на передний план."""
        if self._window is None:
            return
        if self._window.state() == "withdrawn":
            self._window.deiconify()
        self._window.lift()
        self._window.focus_force()

    # ===========================================================================
    # Lifecycle
    # ===========================================================================

    def quit(self) -> None:
        """Корректно завершить приложение."""
        self._timer.stop()
        self._tray.stop()
        self._hotkeys.cleanup()
        if self._obs:
            self._obs.stop()
        self._bus.clear()
        if self._window:
            self._window.after(0, self._window.destroy)
        logger.info("AppController: завершение работы")

    def on_window_close(self) -> None:
        """Вызывается при нажатии крестика окна."""
        if self._tray.available:
            # Свернуть в трей вместо закрытия
            self._window.withdraw()
        else:
            self.quit()
