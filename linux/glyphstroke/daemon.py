"""Демон: связывает перехват, распознавание и действия.

Держит эксклюзивный захват мышей, отдаёт росчерки распознавателю и запускает
привязанные действия. Перечитывает настройки по SIGHUP (редактор шлёт его
после сохранения) и раз в две секунды проверяет, не появилась ли новая мышь.
"""

from __future__ import annotations

import errno
import logging
import os
import queue
import selectors
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote

from evdev import ecodes

from . import capture, shellext, update
from .actions import ActionRunner
from .ipc import OverlayServer
from .config import (Gesture, Settings, app_matches, bound_events, find_conflicts,
                     load_gestures, migrate_legacy_config)
from .context import WindowContext
from .menu import MenuChoice, MenuSession
from .recognizer import Recognizer, direction_code, resample
from .version import __version__

from . import i18n
from .i18n import _

log = logging.getLogger("glyphstroke.daemon")

#: как часто сверять список файлов в /dev/input (сама сверка стоит микросекунды)
#: как назвать особый жест в шпаргалке
EVENT_HINTS = {
    "rocker-left": "щёлкнуть левой",
    "rocker-right": "щёлкнуть правой при зажатой левой",
    "rocker-middle": "щёлкнуть средней",
    "wheel-up": "колесо вверх",
    "wheel-down": "колесо вниз",
    "wheel-left": "колесо влево",
    "wheel-right": "колесо вправо",
}

RESCAN_INTERVAL_S = 2.0
TICK_S = 0.05


def summarize(actions) -> str:
    """Действия одной строкой — для журнала и для «glyphstroke watch»."""
    return "; ".join(f"{a.type} {a.value}".strip() for a in actions)


class Daemon:
    def __init__(self, settings: Settings | None = None, dry_run: bool = False):
        migrate_legacy_config()
        self.settings = settings or Settings.load()
        self.dry_run = dry_run
        self.gestures: list[Gesture] = []
        self.recognizer = Recognizer([])
        self.devices: list = []
        self.machines: dict[int, capture.StrokeMachine] = {}
        self.mirror: capture.Mirror | None = None
        self.selector = selectors.DefaultSelector()
        self.context = WindowContext()
        self.runner: ActionRunner | None = None
        self.overlay: subprocess.Popen | None = None
        self.overlay_server: OverlayServer | None = None
        self._running = False
        self._reload_requested = False
        # Распознавание и действия уходят в отдельный поток: они занимают
        # десятки миллисекунд, а основной цикл в это время обязан продолжать
        # пересылать движения мыши, иначе курсор дёргается
        self._work: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._known_paths: set[str] = set()
        #: открытое меню под жестом; пока оно есть, мышь принадлежит ему
        self.menu: MenuSession | None = None
        #: что сообщила оболочка про полноэкранное окно; None — не сообщала
        self._shell_fullscreen: bool | None = None
        #: перехват сняли мы сами из-за полноэкранного окна, а не человек
        self._auto_paused = False
        #: перехват можно приостановить: устройства отпускаются, и правая
        #: кнопка снова работает как обычно — это удобнее, чем выключать службу
        self.paused = False
        self._pause_request: bool | None = None
        #: тачпады и клавиатуры для рисования пальцем: их только читаем
        self.touchpads: list = []
        self.keyboards: list = []
        self.touch_machines: dict[int, capture.TouchpadMachine] = {}
        #: код назначенной клавиши; None — рисование на тачпаде выключено
        self.touch_key: int | None = None
        #: на каких клавиатурах клавиша сейчас зажата
        self._key_pressed: set[int] = set()
        #: сказали ли оболочке, что Super занят росчерком
        self._overlay_key_held = False
        self.load_gestures()

    # --- конфигурация ---
    def load_gestures(self) -> None:
        self.gestures = [g for g in load_gestures() if g.enabled]
        self.recognizer = Recognizer(
            [g.to_def() for g in self.gestures],
            min_score=self.settings.min_score,
            min_margin=self.settings.min_margin,
        )
        self.events = bound_events(self.gestures)
        self._recognizers: dict[str, Recognizer] = {}
        for machine in self.machines.values():
            machine.bound_events = set(self.events)
        log.info(_("загружено жестов: %d (особых: %d)"),
                 len(self.gestures), len(self.events))
        for code, names in find_conflicts(self.gestures).items():
            log.warning(_("код %s занят жестами %s — не сработает ни один"),
                        code, ", ".join(names))

    def reload(self) -> None:
        self.settings = Settings.load()
        self.load_gestures()
        self.apply_auto_pause()
        if self.mirror is not None and \
                capture.key_code(self.settings.touchpad_key) != self.touch_key:
            # клавишу сменили: клавиатуры с прежней читать больше незачем
            self.close_touch_devices()
            self.open_touch_devices()
        for machine in self.machines.values():
            machine.min_stroke_px = self.settings.min_stroke_px
            machine.press_passthrough_ms = self.settings.press_passthrough_ms
            machine.hint_delay_ms = self.settings.hint_delay_ms

    # --- устройства ---
    @property
    def trigger_code(self) -> int:
        name = self.settings.trigger_button.upper()
        if not name.startswith("BTN_"):
            name = f"BTN_{name}"
        return ecodes.ecodes.get(name, ecodes.BTN_RIGHT)

    def open_devices(self) -> None:
        found = capture.find_pointers(
            include=self.settings.device_include,
            exclude=self.settings.device_exclude,
            allow_touchpads=self.settings.allow_touchpads,
        )
        self.devices = found
        self.open_touch_devices()
        if not found and not (self.touchpads and self.keyboards):
            self.close_touch_devices()
            raise RuntimeError(
                _("не найдено ни одной мыши. Проверьте права на /dev/input/event* "
                "(нужна группа input) или задайте device_include в settings.yaml")
            )
        if not found:
            log.info(_("мышей нет — жесты рисуются на тачпаде, пока зажата %s"),
                     capture.key_label(self.settings.touchpad_key))
        self.mirror = capture.Mirror(capture.build_mirror(found))
        time.sleep(0.2)  # даём системе подхватить виртуальное устройство
        monitor_only = self.settings.capture_mode == "monitor"
        for dev in found:
            if not monitor_only:
                try:
                    dev.grab()
                except OSError as exc:
                    log.error(_("не удалось захватить %s: %s"), dev.name, exc)
                    continue
            self.machines[dev.fd] = self.make_machine(monitor_only)
            self.selector.register(dev, selectors.EVENT_READ, dev)
            log.info(_("перехват: %s (%s)"), dev.name, dev.path)
        self._known_paths = set(capture.event_paths())
        self.runner = ActionRunner(pointer_emit=self._pointer_emit,
                                   keys_sender=self._send_keys_via_shell,
                                   window_sender=self._send_window_via_shell)
        # клавиатуру создаём сразу: если сделать это при первом же действии,
        # система не успеет заметить устройство и проглотит первое нажатие
        try:
            self.runner.keyboard.ui
        except OSError as exc:
            log.warning(_("виртуальная клавиатура недоступна: %s"), exc)

    def _send_keys_via_shell(self, combo: str) -> bool:
        """Отдать сочетание расширению оболочки, если оно на связи.

        Демон нажимает клавиши кодами, а композитор читает их через текущую
        раскладку: при русской ``KEY_C`` превращается в «с», и приложение не
        узнаёт Ctrl+C. Расширение шлёт символ, а не код, поэтому раскладка
        перестаёт мешать.
        """
        if self.settings.keys_via == "uinput":
            return False
        if self.overlay_server is None:
            return False
        if self.settings.keys_via != "shell" and not self.overlay_server.has("keys"):
            return False
        return self.overlay_server.broadcast(f"dokeys\t{combo}") > 0

    def _greeting(self) -> str:
        return (f"hello\t{__version__}\t{os.getpid()}\t"
                f"{'paused' if self.paused else 'active'}")

    # --- пауза ---
    def handle_command(self, parts: list[str]) -> None:
        """Команды от клиентов канала: пауза, возврат, вопрос о состоянии."""
        command = parts[0]
        if command in ("pause", "resume", "toggle"):
            # решение человека старше нашего: больше не возвращаем перехват сами
            self._auto_paused = False
        if command == "pause":
            self._pause_request = True
        elif command == "resume":
            self._pause_request = False
        elif command == "toggle":
            self._pause_request = not self.paused
        elif command == "fullscreen" and len(parts) >= 2:
            self.set_shell_fullscreen(parts[1] == "1")
        elif command == "window" and len(parts) >= 2:
            self.context.set_shell_window(parts[1], " ".join(parts[2:]))
        elif command in ("state?", "state"):
            self.broadcast_state()
        elif command == "pick":
            self.request_pick()
        elif command == "picked":
            self.relay_pick(parts[1:])
        else:
            log.debug(_("неизвестная команда: %s"), " ".join(parts))

    def broadcast_state(self) -> None:
        if self.overlay_server is not None:
            self.overlay_server.broadcast(
                f"state\t{'paused' if self.paused else 'active'}")

    # --- мишень редактора ---
    def request_pick(self) -> None:
        """Редактор спрашивает, какое окно лежит под курсором.

        Знает это только оболочка: в Wayland приложению не дают ни позиции
        курсора, ни списка окон. Если её нет на связи, отвечаем сразу — так
        редактор не ждёт впустую и в X11 может спросить сервер сам.
        """
        if self.overlay_server is None:
            return
        if self.overlay_server.has("pick"):
            self.overlay_server.broadcast("dopick")
        else:
            self.overlay_server.broadcast("picked\t-\tnoshell")

    def relay_pick(self, fields: list[str]) -> None:
        """Ответ оболочки разослать всем — редактор среди слушателей.

        Класс и название приходят закодированными, как в адресной строке:
        команды канала делятся по пробелам, а в названиях приложений пробелы
        встречаются.
        """
        if self.overlay_server is None:
            return
        values = [unquote(value).replace("\t", " ").replace("\n", " ").strip()
                  for value in fields[:2]]
        wm_class, detail = (values + ["", ""])[:2]
        if wm_class in ("", "-"):
            self.overlay_server.broadcast(f"picked\t-\t{detail or 'nowindow'}")
            return
        self.overlay_server.broadcast(f"picked\t{wm_class}\t{detail or wm_class}")

    def apply_pause(self, paused: bool) -> None:
        """Отпустить мышь или забрать её обратно.

        На паузе именно отпускаем устройства, а не пересылаем события мимо
        себя: так правая кнопка работает ровно как без нашей программы, без
        лишнего звена в цепочке.
        """
        if paused == self.paused:
            return
        self.paused = paused
        self.close_menu()
        for dev in self.devices:
            try:
                dev.ungrab() if paused else dev.grab()
            except OSError as exc:
                log.error("%s: %s", dev.name, exc)
        for machine in self.machines.values():
            machine._reset()
        for touch in self.touch_machines.values():
            touch.reset()
        self.free_overlay_key()
        self.overlay_send("end")
        log.info(_("перехват %s"), _("приостановлен") if paused else _("включён"))
        self.broadcast_state()

    # --- полноэкранные приложения ---
    def set_shell_fullscreen(self, active: bool) -> None:
        """Оболочка сообщила, что активное окно развернули или свернули."""
        self._shell_fullscreen = active
        self.apply_auto_pause()

    def fullscreen_now(self) -> bool | None:
        """Во весь ли экран активное окно. ``None`` — узнать нечем.

        В GNOME про окна знает только оболочка, поэтому там верим ей; в X11,
        sway и Hyprland спрашиваем сами.
        """
        if self.overlay_server is not None and self.overlay_server.has("fullscreen"):
            return self._shell_fullscreen
        return self.context.fullscreen()

    def apply_auto_pause(self) -> None:
        """Отпустить мышь на время полноэкранного окна и вернуть её потом.

        Своя пометка нужна, чтобы не спорить с человеком: перехват возвращаем
        только тогда, когда сами же его и сняли.
        """
        if not self.settings.pause_in_fullscreen:
            if self._auto_paused:
                self._auto_paused = False
                self._pause_request = False
            return
        state = self.fullscreen_now()
        if state is None:
            return
        if state and not self.paused and not self._auto_paused:
            log.info(_("окно во весь экран — отпускаю мышь"))
            self._auto_paused = True
            self._pause_request = True
        elif not state and self._auto_paused:
            log.info(_("полноэкранное окно закрылось — забираю мышь обратно"))
            self._auto_paused = False
            self._pause_request = False

    def _send_window_via_shell(self, command: str) -> bool:
        if self.overlay_server is None or not self.overlay_server.has("window"):
            return False
        return self.overlay_server.broadcast(f"dowindow\t{command}") > 0

    def focus_target_window(self) -> None:
        """Сделать активным окно, над которым начали рисовать.

        Без этого действие уходит в окно, которое было в фокусе: правый клик
        мы придерживаем, поэтому окно под курсором фокус само не получает. На
        двух экранах это особенно заметно.
        """
        if not self.settings.focus_under_cursor:
            return
        if self.overlay_server is None or not self.overlay_server.has("window"):
            return
        if self.overlay_server.broadcast("dofocus") > 0:
            time.sleep(0.06)  # даём оболочке переключить фокус до нажатий

    def make_machine(self, monitor_only: bool) -> capture.StrokeMachine:
        machine = capture.StrokeMachine(
            self.mirror, self.trigger_code, self.settings.min_stroke_px,
            monitor_only=monitor_only,
            press_passthrough_ms=self.settings.press_passthrough_ms,
            hint_delay_ms=self.settings.hint_delay_ms,
        )
        machine.bound_events = set(self.events)
        return machine

    def _pointer_emit(self, etype: int, code: int, value: int) -> None:
        if self.mirror:
            self.mirror.emit(etype, code, value)

    def rescan_devices(self) -> None:
        """Подключить мышь, воткнутую после старта.

        Сначала сверяем только имена файлов — это микросекунды. Открываем и
        расспрашиваем устройство лишь тогда, когда путь действительно новый:
        полный обход /dev/input стоит десятки миллисекунд и раньше давал
        заметный рывок курсора каждые две секунды.
        """
        paths = set(capture.event_paths())
        appeared = sorted(paths - self._known_paths)
        self._known_paths = paths
        if not appeared:
            return
        known = {dev.path for dev in self.devices}
        fresh = [
            dev for dev in capture.find_pointers(
                include=self.settings.device_include,
                exclude=self.settings.device_exclude,
                allow_touchpads=self.settings.allow_touchpads,
                paths=appeared,
            )
            if dev.path not in known
        ]
        for dev in fresh:
            try:
                if self.settings.capture_mode != "monitor":
                    dev.grab()
                self.selector.register(dev, selectors.EVENT_READ, dev)
            except OSError as exc:
                log.error(_("новое устройство %s не открылось: %s"), dev.name, exc)
                dev.close()
                continue
            self.machines[dev.fd] = self.make_machine(
                self.settings.capture_mode == "monitor")
            self.devices.append(dev)
            log.info(_("подключена мышь: %s (%s)"), dev.name, dev.path)
        self.open_touch_devices(paths=appeared)

    def drop_device(self, dev) -> None:
        log.info(_("устройство отключено: %s"), dev.path)
        try:
            self.selector.unregister(dev)
        except (KeyError, ValueError):
            pass
        self.machines.pop(dev.fd, None)
        self.touch_machines.pop(dev.fd, None)
        if dev in self.touchpads:
            self.touchpads.remove(dev)
        if dev in self.keyboards:
            self.keyboards.remove(dev)
            if dev.fd in self._key_pressed:
                # клавиатуру выдернули с зажатой клавишей — считаем её отпущенной
                self._key_pressed.discard(dev.fd)
                self.apply_key_state()
        if dev in self.devices:
            self.devices.remove(dev)
        try:
            dev.close()
        except Exception:
            pass

    # --- тачпад ---
    def open_touch_devices(self, paths: list[str] | None = None) -> None:
        """Найти тачпады и клавиатуры для рисования пальцем с клавишей.

        Ни то, ни другое не захватывается: тачпад остаётся системе целиком, а
        с клавиатуры демону нужна одна назначенная клавиша. Клавиатуры без
        тачпада не читаем вовсе. ``paths`` — только появившиеся устройства.
        """
        self.touch_key = capture.key_code(self.settings.touchpad_key)
        if self.touch_key is None:
            return
        busy = {dev.path for dev in self.devices + self.touchpads + self.keyboards}
        had_touchpads = bool(self.touchpads)
        for dev in capture.find_touchpads(self.settings.device_exclude, paths=paths):
            # тачпад, перехваченный как мышь (allow_touchpads), рисует и так
            if dev.path in busy or not self._register_side(dev, self.touchpads):
                dev.close()
                continue
            self.touch_machines[dev.fd] = capture.TouchpadMachine.for_device(dev)
            log.info(_("тачпад для рисования: %s (%s)"), dev.name, dev.path)
        if not self.touchpads:
            return
        # тачпад появился только сейчас — клавиатуры ищем все, а не среди новых
        keyboard_paths = paths if had_touchpads else None
        for dev in capture.find_keyboards(self.touch_key, paths=keyboard_paths):
            if dev.path in busy or not self._register_side(dev, self.keyboards):
                dev.close()
                continue
            log.info(_("клавиша для тачпада на устройстве: %s (%s)"), dev.name, dev.path)

    def _register_side(self, dev, bucket: list) -> bool:
        try:
            self.selector.register(dev, selectors.EVENT_READ, dev)
        except (OSError, ValueError, KeyError) as exc:
            log.error(_("новое устройство %s не открылось: %s"), dev.name, exc)
            return False
        bucket.append(dev)
        return True

    def close_touch_devices(self) -> None:
        for dev in self.touchpads + self.keyboards:
            try:
                self.selector.unregister(dev)
            except (KeyError, ValueError):
                pass
            try:
                dev.close()
            except Exception:
                pass
        self.touchpads, self.keyboards = [], []
        self.touch_machines = {}
        self._key_pressed = set()
        self.free_overlay_key()

    def read_side_device(self, dev) -> None:
        """Тачпад или клавиатура, которые мы только читаем."""
        machine = self.touch_machines.get(dev.fd)
        try:
            events = list(dev.read())
        except BlockingIOError:
            return
        except OSError as exc:
            if exc.errno in (errno.ENODEV, errno.EBADF):
                self.drop_device(dev)
                return
            raise
        for event in events:
            if machine is not None:
                self.handle_touch_event(machine, event)
            else:
                self.handle_key_event(dev.fd, event)

    def handle_key_event(self, fd: int, event) -> None:
        """Из всего потока клавиатуры важна одна назначенная клавиша."""
        if event.type != ecodes.EV_KEY or event.code != self.touch_key \
                or event.value not in (0, 1):
            return
        if event.value:
            self._key_pressed.add(fd)
        else:
            self._key_pressed.discard(fd)
        self.apply_key_state()

    def apply_key_state(self) -> None:
        """Сообщить тачпадам, зажата ли клавиша.

        Состояние помним и на паузе, и при открытом меню, только росчерка тогда
        не начинаем: иначе после возврата перехвата демон считал бы отпущенной
        клавишу, которую держат.
        """
        held = bool(self._key_pressed)
        for machine in list(self.touch_machines.values()):
            if self.paused or self.menu is not None:
                machine.key_held = held
                machine.reset()
                continue
            self.handle_stroke_events(machine, machine.set_key(held))
        if not held:
            self.free_overlay_key()

    def handle_touch_event(self, machine: capture.TouchpadMachine, event) -> None:
        if self.paused:
            machine.observe(event)
            return
        session = self.menu
        if session is not None:
            # меню открыто: палец водит по списку, росчерков не рисуем
            machine.observe(event)
            self.apply_menu_outcome(session, session.handle_touch(event, machine.units_per_mm))
            return
        self.handle_stroke_events(machine, machine.handle(event))

    @property
    def touch_key_is_super(self) -> bool:
        return self.touch_key in (ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA)

    def hold_overlay_key(self) -> None:
        """Super держат ради росчерка: его отпускание не должно открыть обзор.

        Одиночный Super оболочка GNOME ловит сама, демон этого нажатия не
        касается. Поэтому говорим расширению заранее, а гасит обзор оно.
        """
        if not self.touch_key_is_super or self._overlay_key_held:
            return
        self._overlay_key_held = True
        if self.overlay_server is not None:
            self.overlay_server.broadcast("overlay-key-hold")

    def free_overlay_key(self) -> None:
        if self._overlay_key_held and self.overlay_server is not None:
            self.overlay_server.broadcast("overlay-key-free")
        self._overlay_key_held = False

    # --- обновления ---
    def start_update_check(self) -> None:
        """Раз в сутки узнавать, не вышла ли версия новее.

        Демон для этого годится лучше редактора: он работает всегда, а
        редактор открывают раз в месяц. Сам он ничего не ставит — только
        запоминает ответ, чтобы редактор показал полоску, а «glyphstroke doctor»
        строку. Проверка выключается настройкой check_updates.
        """
        if not getattr(self.settings, "check_updates", True):
            return

        def loop() -> None:
            # Пауза перед первым запросом: при входе в систему сеть обычно ещё
            # не поднялась, да и мешать старту сеанса незачем.
            time.sleep(30)
            while self._running:
                try:
                    release = update.check(self.settings)
                    if release is not None:
                        log.info(_("вышла версия %s — установленная %s"),
                                 release.version, __version__)
                except Exception as exc:            # noqa: BLE001 - сеть не повод падать
                    log.debug(_("проверка обновлений не удалась: %s"), exc)
                for _unused in range(int(update.CHECK_INTERVAL_S)):
                    if not self._running:
                        return
                    time.sleep(1)

        threading.Thread(target=loop, name="glyphstroke-update", daemon=True).start()

    # --- расширение оболочки ---
    def ensure_shell_extension(self) -> None:
        """Обновить копию расширения в домашнем каталоге пользователя.

        Делает это демон, а не установщик пакета: GNOME берёт расширения из
        ~/.local/share конкретного человека и включает их через сессионную
        шину, а postinst работает от root и вне сеанса. Демон же запущен
        ровно там, где нужно, — в сеансе пользователя.
        """
        try:
            result = shellext.ensure_current()
        except Exception as exc:                      # noqa: BLE001 - не роняем демон из-за расширения
            log.warning(_("не удалось проверить расширение оболочки: %s"), exc)
            return
        if result == "installed":
            log.info(_("расширение оболочки установлено; чтобы след и мишень "
                       "заработали, перезайдите в систему"))
        elif result == "updated":
            log.info(_("расширение оболочки обновлено; чтобы оболочка подхватила "
                       "новую версию, перезайдите в систему"))
        elif result == "failed":
            log.warning(_("расширение оболочки установить не вышло; поставьте вручную: "
                          "glyphstroke shell-extension install"))

    # --- след на экране ---
    def start_channel(self) -> None:
        """Канал открыт всегда, независимо от настроек следа.

        Через него не только рисуется след: расширение оболочки нажимает
        клавиши и работает с окнами, «glyphstroke watch» смотрит разбор росчерков,
        а пауза перехвата приходит именно сюда. Привязывать всё это к
        рисованию следа было бы странно.
        """
        try:
            self.overlay_server = OverlayServer(
                greeting=self._greeting, on_command=self.handle_command)
            self.overlay_server.start()
        except OSError as exc:
            log.warning(_("канал не открылся: %s"), exc)
            self.overlay_server = None

    def start_overlay(self) -> None:
        if not self.settings.overlay.enabled:
            return
        # В сеансе Wayland позицию курсора приложению не отдают. Если при этом
        # в окружении есть DISPLAY, окно молча подцепится к Xwayland и начнёт
        # получать бессмысленные координаты — след получается ломаной линией
        # из чужих точек. Поэтому смотрим на тип сеанса, а не на DISPLAY.
        if os.environ.get("WAYLAND_DISPLAY") or \
                os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
            log.info(_("след не рисуем: в сеансе Wayland нет глобальной позиции курсора"))
            return
        if not os.environ.get("DISPLAY"):
            log.info(_("след не рисуем: графической сессии не видно"))
            return
        try:
            self.overlay = subprocess.Popen(
                [sys.executable, "-m", "glyphstroke.overlay",
                 "--color", self.settings.overlay.color,
                 "--width", str(self.settings.overlay.width),
                 "--opacity", str(self.settings.overlay.opacity),
                 "--fade-ms", str(self.settings.overlay.fade_ms)],
                env=dict(os.environ, GDK_BACKEND="x11"),
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True,
            )
            # запись в трубу не должна подвешивать цикл пересылки
            os.set_blocking(self.overlay.stdin.fileno(), False)
        except Exception as exc:
            log.warning(_("не удалось запустить отрисовку следа: %s"), exc)

    def overlay_send(self, command: str) -> None:
        if self.overlay_server is not None:
            if command == "begin":
                overlay = self.settings.overlay
                self.overlay_server.broadcast(
                    f"begin {overlay.color} {overlay.width} {overlay.opacity:.2f}")
            else:
                self.overlay_server.broadcast(command)
        if not self.overlay or not self.overlay.stdin:
            return
        if self.overlay.poll() is not None:
            self.overlay = None
            return
        try:
            self.overlay.stdin.write(command + "\n")
            self.overlay.stdin.flush()
        except (BrokenPipeError, ValueError):
            self.overlay = None
        except BlockingIOError:
            pass  # окно следа не успевает читать — пропускаем команду

    # --- реакция на росчерк ---
    def announce(self, code: str, name: str | None, score: float,
                 runner_up: str | None, runner_score: float) -> None:
        """Рассказать в канал, что распознано, — это видно в «glyphstroke watch»."""
        if self.overlay_server is None:
            return
        self.overlay_server.broadcast("\t".join([
            "stroke", code or "-", name or "-", f"{score:.2f}",
            runner_up or "-", f"{runner_score:.2f}",
        ]))

    def announce_points(self, points: list[tuple[float, float]]) -> None:
        """Отдать сам росчерк — чтобы его можно было сохранить и разобрать."""
        if self.overlay_server is None or not points:
            return
        compact = " ".join(f"{x:.0f},{y:.0f}" for x, y in resample(points))
        self.overlay_server.broadcast(f"points\t{compact}")

    def recognizer_for(self, app: str | None, specific: bool) -> Recognizer:
        """Распознаватель для жестов этого приложения либо для общих.

        Разбор идёт в два захода: сперва жесты, привязанные к текущему окну,
        потом общие. Так один и тот же росчерк может делать разное в разных
        приложениях, и при этом не спорить сам с собой.
        """
        key = f"{'app' if specific else 'all'}:{app or '-'}"
        cached = self._recognizers.get(key)
        if cached is None:
            subset = [g for g in self.gestures
                      if (bool(g.apps) == specific and not g.event
                          and (not specific or g.matches_app(app)))]
            cached = Recognizer([g.to_def() for g in subset],
                                min_score=self.settings.min_score,
                                min_margin=self.settings.min_margin)
            self._recognizers[key] = cached
        return cached

    def is_excluded(self, app: str | None) -> bool:
        """Приложение из списка исключений: перехват в нём не нужен."""
        if not self.settings.excluded_apps or not app:
            return False
        return any(app_matches(pattern, app) for pattern in self.settings.excluded_apps)

    def on_stroke(self, points: list[tuple[float, float]]) -> bool:
        """Распознать и выполнить. ``True`` — жест найден."""
        app = self.context.active_app()
        match = self.recognizer_for(app, specific=True).recognize(points)
        if match.name is None:
            match = self.recognizer_for(app, specific=False).recognize(points)
        self.announce(match.code, match.name, match.score,
                      match.runner_up, match.runner_up_score)
        self.announce_points(points)
        if match.name is None:
            log.info(_("не распознано (код %s, ближайший %s %.2f)"),
                     match.code or "-", match.runner_up or "-", match.runner_up_score)
            return False
        gesture = next((g for g in self.gestures if g.name == match.name), None)
        if gesture is None:
            return False
        log.info(_("жест «%s» (%.2f, код %s), окно: %s"),
                 gesture.name, match.score, match.code or "-", app or _("неизвестно"))
        return self.run_gesture(gesture, app)

    def on_event(self, name: str) -> bool:
        """Особый жест: щелчок другой кнопкой или колесо при удержании."""
        app = self.context.active_app()
        candidates = [g for g in self.gestures if g.event == name and g.enabled]
        # жест приложения важнее общего — как и с росчерками
        gesture = next((g for g in candidates if g.apps and g.matches_app(app)), None)
        gesture = gesture or next((g for g in candidates if not g.apps), None)
        if gesture is None:
            log.info(_("особый жест %s не привязан к этому окну (%s)"), name, app)
            return False
        log.info(_("особый жест «%s» (%s), окно: %s"),
                 gesture.name, name, app or _("неизвестно"))
        self.announce(name, gesture.name, 1.0, None, 0.0)
        return self.run_gesture(gesture, app)

    def run_gesture(self, gesture: Gesture, app: str | None) -> bool:
        """Выполнить действия жеста и рассказать об этом."""
        self.focus_target_window()
        if self.dry_run:
            print(f"[dry-run] {gesture.name}: {summarize(gesture.actions)}")
            for item in gesture.menu:
                print(f"[dry-run]   • {item.name}: {summarize(item.actions)}")
            return True
        self.perform(gesture.name, gesture.actions, app)
        self.open_menu(gesture, app)
        return True

    def perform(self, name: str, actions, app: str | None) -> None:
        """Выполнить набор действий и рассказать в канал, что именно ушло."""
        if self.runner:
            self.runner.run(actions)
        if self.settings.show_gesture_name and self.overlay_server is not None:
            self.overlay_server.broadcast(f"notify\t{name}")
        # Сообщаем, что именно ушло в систему: если действие выполнено, а в окне
        # ничего не изменилось, значит, приложение не знает такого сочетания
        if self.overlay_server is not None:
            transport = self.runner.last_keys_transport if self.runner else "-"
            has_keys = any(a.type == "keys" for a in actions)
            self.overlay_server.broadcast("\t".join([
                "action", name, summarize(actions), app or "-",
                transport if has_keys else "-",
            ]))

    # --- меню под жестом ---
    def can_draw_menu(self) -> bool:
        """Есть ли кому нарисовать меню.

        Открывать список, которого не видно, нельзя: мышь ушла бы в невидимое
        меню, и человек не понял бы, почему она перестала слушаться.
        """
        if self.overlay_server is not None and self.overlay_server.has("menu"):
            return True
        return self.overlay is not None and self.overlay.poll() is None

    def open_menu(self, gesture: Gesture, app: str | None) -> bool:
        """Показать меню жеста. ``False`` — меню нет или показывать некому."""
        if not gesture.menu:
            return False
        if not self.can_draw_menu():
            log.warning(_("у жеста «%s» есть меню, но рисовать его некому: "
                          "поставьте расширение оболочки командой "
                          "«glyphstroke shell-extension install»"), gesture.name)
            return False
        session = MenuSession(gesture.name, list(gesture.menu),
                              step_px=self.settings.menu_step_px,
                              timeout_ms=self.settings.menu_timeout_ms, app=app)
        self.menu = session
        self.overlay_send("\t".join(["menu", session.name, *session.labels]))
        log.info(_("меню «%s»: %d пунктов"), session.name, len(session.items))
        return True

    def handle_menu_event(self, event) -> None:
        """События мыши, пока меню открыто. Наружу не уходит ничего."""
        session = self.menu
        if session is None:
            return
        self.apply_menu_outcome(session, session.handle(event))

    def apply_menu_outcome(self, session: MenuSession, outcome: str | None) -> None:
        if outcome == "highlight":
            self.overlay_send(f"menu-select\t{session.index}")
        elif outcome in ("choose", "cancel"):
            self.finish_menu(session)

    def finish_menu(self, session: MenuSession) -> None:
        """Закрыть меню и, если пункт выбран, поставить его в очередь."""
        if self.menu is session:
            self.menu = None
        self.overlay_send("menu-hide")
        item = session.chosen
        if self.overlay_server is not None:
            self.overlay_server.broadcast(
                "\t".join(["menu-choice", session.name, item.name if item else "-"]))
        if item is None:
            log.info(_("меню «%s» закрыто без выбора"), session.name)
            return
        log.info(_("меню «%s»: выбран пункт «%s»"), session.name, item.name)
        self._work.put((None, MenuChoice(session.name, item, session.app)))

    def run_menu_item(self, choice: MenuChoice) -> None:
        if self.dry_run:
            print(f"[dry-run] {choice.gesture} → {choice.item.name}: "
                  f"{summarize(choice.item.actions)}")
            return
        self.focus_target_window()
        self.perform(f"{choice.gesture} → {choice.item.name}",
                     choice.item.actions, choice.app)

    # --- шпаргалка ---
    def hint_text(self) -> str:
        """Список жестов для показа на экране: название и как его сделать."""
        items = []
        for gesture in self.gestures:
            if gesture.event:
                how = _(EVENT_HINTS.get(gesture.event, gesture.event))
            elif gesture.directions:
                how = ", ".join(gesture.directions)
            elif gesture.templates:
                how = _("росчерк")
            else:
                continue
            items.append(f"{gesture.name}|{how}")
        return "\t".join(items)

    def show_hint(self) -> None:
        if not self.settings.hint_delay_ms or self.overlay_server is None:
            return
        text = self.hint_text()
        if text:
            self.overlay_server.broadcast(f"hint\t{text}")

    def hide_hint(self) -> None:
        if self.overlay_server is not None:
            self.overlay_server.broadcast("hint-hide")

    def handle_stroke_events(self, machine, events) -> None:
        """Из цикла пересылки только помечаем след и ставим работу в очередь."""
        for ev in events:
            if ev.kind == "begin":
                if self.is_excluded(self.context.active_app()):
                    # в этом приложении мы вообще не мешаемся
                    machine.passthrough_now()
                    continue
                self.overlay_send("begin")
                if isinstance(machine, capture.TouchpadMachine):
                    self.hold_overlay_key()
            elif ev.kind in ("cancel", "click"):
                self.overlay_send("end")
                self.hide_hint()
            elif ev.kind == "hint":
                self.show_hint()
            elif ev.kind == "event":
                self.hide_hint()
                self._work.put((machine, ev.event))
            elif ev.kind == "finish":
                self.overlay_send("end")
                self.hide_hint()
                self._work.put((machine, ev.points))

    def _work_loop(self) -> None:
        """Распознавание и действия — вне цикла пересылки событий мыши."""
        while True:
            item = self._work.get()
            if item is None:
                return
            machine, payload = item
            if isinstance(payload, MenuChoice):  # выбран пункт меню
                try:
                    self.run_menu_item(payload)
                except Exception:
                    log.exception(_("сбой при выполнении пункта меню"))
                continue
            if isinstance(payload, str):        # особый жест: rocker или колесо
                try:
                    self.on_event(payload)
                except Exception:
                    log.exception(_("сбой при выполнении особого жеста"))
                continue
            points = payload
            try:
                recognized = self.on_stroke(points)
            except Exception:
                log.exception(_("сбой при разборе росчерка"))
                recognized = False
            if not recognized and not machine.monitor_only \
                    and self.settings.unrecognized == "passthrough":
                machine.mirror.click(machine.trigger)

    # --- основной цикл ---
    def run(self) -> int:
        # Расширение ставим раньше, чем открываем устройства: копия в домашний
        # каталог не зависит от доступа к мыши, а вот открытие может упасть на
        # свежей установке (группа input подхватывается только при перезаходе).
        # Пусть даже перехват ещё не заработает — расширение уже на месте.
        self.ensure_shell_extension()
        self.open_devices()
        self.start_channel()
        self.start_overlay()
        self._worker = threading.Thread(target=self._work_loop, name="glyphstroke-actions",
                                        daemon=True)
        self._worker.start()
        signal.signal(signal.SIGHUP, lambda *_: setattr(self, "_reload_requested", True))
        signal.signal(signal.SIGTERM, lambda *_: setattr(self, "_running", False))
        self._running = True
        # Проверку запускаем после флага работы: поток смотрит на него, чтобы
        # не пережить остановку демона.
        self.start_update_check()
        last_rescan = time.monotonic()
        log.info(_("демон %s запущен, кнопка-модификатор: %s"),
                 __version__, self.settings.trigger_button)
        try:
            while self._running:
                for key, _mask in self.selector.select(timeout=TICK_S):
                    dev = key.data
                    machine = self.machines.get(dev.fd)
                    if machine is None:
                        # тачпад или клавиатура: их читаем, не захватывая
                        self.read_side_device(dev)
                        continue
                    try:
                        for event in dev.read():
                            if self.paused:
                                continue
                            if self.menu is not None:
                                # меню забирает мышь целиком: ни движение,
                                # ни щелчки до системы не доходят
                                self.handle_menu_event(event)
                                continue
                            self.handle_stroke_events(machine, machine.handle(event))
                    except OSError as exc:
                        if exc.errno in (errno.ENODEV, errno.EBADF):
                            self.drop_device(dev)
                        else:
                            raise
                if self._pause_request is not None:
                    request, self._pause_request = self._pause_request, None
                    self.apply_pause(request)
                session = self.menu
                if session is not None and session.expired():
                    log.info(_("меню закрылось само: мышь не двигалась"))
                    session.cancel()
                    self.finish_menu(session)
                for machine in list(self.machines.values()):
                    self.handle_stroke_events(machine, machine.tick())
                if self._reload_requested:
                    self._reload_requested = False
                    log.info(_("перечитываю настройки"))
                    self.reload()
                now = time.monotonic()
                if now - last_rescan > RESCAN_INTERVAL_S:
                    last_rescan = now
                    self.rescan_devices()
                    # там, где оболочка молчит, полноэкранное окно приходится
                    # проверять самим — но не чаще, чем ищем новые мыши
                    if self.settings.pause_in_fullscreen:
                        self.apply_auto_pause()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()
        return 0

    def close_menu(self) -> None:
        """Свернуть открытое меню, ничего не выбирая."""
        session = self.menu
        if session is None:
            return
        session.cancel()
        self.finish_menu(session)

    def shutdown(self) -> None:
        self.close_menu()
        self.close_touch_devices()
        if self._worker is not None and self._worker.is_alive():
            self._work.put(None)
            self._worker.join(timeout=3)
        for dev in list(self.devices):
            try:
                if self.settings.capture_mode != "monitor" and not self.paused:
                    dev.ungrab()
            except Exception:
                pass
            try:
                dev.close()
            except Exception:
                pass
        if self.runner:
            self.runner.close()
        if self.mirror:
            self.mirror.close()
        if self.overlay_server is not None:
            self.overlay_server.stop()
        if self.overlay:
            self.overlay_send("quit")
            try:
                self.overlay.wait(timeout=1)
            except Exception:
                self.overlay.kill()
        log.info(_("демон остановлен"))


def setup_logging(level: str = "info") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="glyphstroked", description=_("демон жестов мыши"))
    parser.add_argument("--dry-run", action="store_true",
                        help=_("показывать распознанное, но не выполнять действия"))
    parser.add_argument("--monitor", action="store_true",
                        help=_("не перехватывать кнопку, только следить"))
    parser.add_argument("--log-level", default=None)
    args = parser.parse_args(argv)

    settings = Settings.load()
    i18n.setup(settings.language)
    if args.monitor:
        settings.capture_mode = "monitor"
    setup_logging(args.log_level or settings.log_level)
    try:
        return Daemon(settings, dry_run=args.dry_run).run()
    except RuntimeError as exc:
        log.error("%s", exc)
        return 1
    except PermissionError as exc:
        log.error(_("нет прав: %s. Запустите «glyphstroke doctor»"), exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
