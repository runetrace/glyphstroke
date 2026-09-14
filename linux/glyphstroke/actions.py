"""Выполнение действий, привязанных к жесту.

Типы действий:

``command``  запустить команду через ``/bin/sh -c`` (отвязанно от демона)
``app``      запустить приложение: путь к ``.desktop``-файлу или к программе
``keys``     послать комбинацию, например ``ctrl+w`` или ``ctrl+c ctrl+v``
``text``     набрать строку посимвольно
``button``   щёлкнуть кнопкой мыши (``middle``, ``left``…)
``scroll``   прокрутить колесо (``up 3``, ``down``, ``left 2``)
``window``   действие над окном, где начали рисовать: ``minimize``,
             ``maximize``, ``unmaximize``, ``close``, ``fullscreen``,
             ``activate``, ``above`` — выполняет расширение оболочки
``standard`` стандартное действие системы по имени: ``copy``, ``paste``,
             ``minimize``… Разворачивается в ``keys`` или ``window`` прямо
             перед выполнением, см. glyphstroke/standard.py
``delay``    пауза в миллисекундах между действиями
``none``     ничего не делать (заглушка для черновиков)
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import time
from typing import Callable

from evdev import UInput, ecodes

from . import keysyms, standard

from .i18n import _

log = logging.getLogger("glyphstroke.actions")

#: пауза между нажатием и отпусканием — меньше приложения иногда не замечают
KEY_HOLD_S = 0.012

PointerEmit = Callable[[int, int, int], None]  # (type, code, value)


class VirtualKeyboard:
    """uinput-клавиатура. Создаётся лениво: без действий ``keys`` не нужна."""

    def __init__(self, name: str = "glyphstroke-virtual-keyboard"):
        self.name = name
        self._ui: UInput | None = None

    @property
    def ui(self) -> UInput:
        if self._ui is None:
            keys = [c for c in range(1, 249)]
            self._ui = UInput({ecodes.EV_KEY: keys}, name=self.name, version=1)
            time.sleep(0.05)  # даём compositor'у заметить новое устройство
        return self._ui

    def tap(self, mods: list[int], keys: list[int]) -> None:
        ui = self.ui
        for code in mods:
            ui.write(ecodes.EV_KEY, code, 1)
        ui.syn()
        for code in keys:
            ui.write(ecodes.EV_KEY, code, 1)
            ui.syn()
            time.sleep(KEY_HOLD_S)
            ui.write(ecodes.EV_KEY, code, 0)
            ui.syn()
        if not keys:
            time.sleep(KEY_HOLD_S)
        for code in reversed(mods):
            ui.write(ecodes.EV_KEY, code, 0)
        ui.syn()

    def type_text(self, text: str) -> None:
        shift = ecodes.ecodes["KEY_LEFTSHIFT"]
        for ch in text:
            mapped = keysyms.char_to_key(ch)
            if mapped is None:
                log.warning(_("символ %r не набирается через uinput, пропущен"), ch)
                continue
            code, need_shift = mapped
            self.tap([shift] if need_shift else [], [code])
            time.sleep(0.004)

    def close(self) -> None:
        if self._ui is not None:
            self._ui.close()
            self._ui = None


class ActionRunner:
    def __init__(self, pointer_emit: PointerEmit | None = None,
                 keyboard: VirtualKeyboard | None = None,
                 env: dict[str, str] | None = None,
                 keys_sender: Callable[[str], bool] | None = None,
                 window_sender: Callable[[str], bool] | None = None):
        self.pointer_emit = pointer_emit
        self.keyboard = keyboard or VirtualKeyboard()
        self.env = env or dict(os.environ)
        #: если задан и вернул True, значит сочетание отправил кто-то другой —
        #: например, расширение оболочки, которому раскладка не мешает
        self.keys_sender = keys_sender
        #: действия над окнами умеет только оболочка: в Wayland приложению
        #: не дают ни списка окон, ни права их двигать
        self.window_sender = window_sender
        self.last_keys_transport = "uinput"

    # --- отдельные действия ---
    def run_command(self, value: str) -> None:
        if not value.strip():
            return
        log.info(_("команда: %s"), value)
        subprocess.Popen(
            ["/bin/sh", "-c", value],
            env=self.env,
            cwd=os.path.expanduser("~"),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    #: где искать приложение, если задано именем вроде ``firefox.desktop``
    DESKTOP_DIRS = (
        "~/.local/share/applications",
        "/usr/local/share/applications",
        "/usr/share/applications",
        "/var/lib/flatpak/exports/share/applications",
        "/var/lib/snapd/desktop/applications",
    )

    def run_app(self, value: str) -> None:
        target = (value or "").strip()
        if not target:
            return
        path = self.resolve_app(target)
        if path is None:
            log.error(_("приложение не найдено: %s"), target)
            return
        if path.suffix == ".desktop":
            # gio знает про Terminal=true, подстановки и запуск в своей группе
            if shutil.which("gio"):
                self.run_command(f"gio launch {shlex.quote(str(path))}")
                return
            command = self.desktop_exec(path)
            if command:
                self.run_command(command)
                return
            log.error(_("в %s нет строки Exec"), path)
            return
        self.run_command(shlex.quote(str(path)))

    def resolve_app(self, target: str):
        """Путь к ``.desktop``-файлу или к программе. ``None`` — не нашли."""
        from pathlib import Path

        path = Path(target).expanduser()
        if path.is_absolute() or target.startswith("."):
            return path if path.exists() else None
        if target.endswith(".desktop"):
            for directory in self.DESKTOP_DIRS:
                candidate = Path(directory).expanduser() / target
                if candidate.exists():
                    return candidate
            return None
        found = shutil.which(target)
        return Path(found) if found else None

    @staticmethod
    def desktop_exec(path) -> str | None:
        """Строка Exec из .desktop без подстановок вроде %U и %f."""
        section = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line
                continue
            if section == "[Desktop Entry]" and line.startswith("Exec="):
                return re.sub(r"\s*%[A-Za-z]", "", line[len("Exec="):]).strip()
        return None

    def run_keys(self, value: str) -> None:
        # разбираем в любом случае: так опечатка в сочетании видна сразу,
        # каким бы способом ни отправляли
        combos = keysyms.parse_sequence(value)
        if self.keys_sender is not None and self.keys_sender(value):
            self.last_keys_transport = "shell"   # признак, не текст
            return
        self.last_keys_transport = "uinput"
        for mods, keys in combos:
            self.keyboard.tap(mods, keys)
            time.sleep(0.02)

    def run_text(self, value: str) -> None:
        self.keyboard.type_text(value)

    def run_button(self, value: str) -> None:
        parts = value.split()
        code = keysyms.button_code(parts[0] if parts else "left")
        count = int(parts[1]) if len(parts) > 1 else 1
        for _unused in range(count):
            self._pointer(ecodes.EV_KEY, code, 1)
            self._pointer(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
            time.sleep(KEY_HOLD_S)
            self._pointer(ecodes.EV_KEY, code, 0)
            self._pointer(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
            time.sleep(0.03)

    def run_scroll(self, value: str) -> None:
        parts = value.split()
        direction = (parts[0] if parts else "down").lower()
        amount = int(parts[1]) if len(parts) > 1 else 3
        axis, sign = {
            "up": (ecodes.REL_WHEEL, 1), "down": (ecodes.REL_WHEEL, -1),
            "left": (ecodes.REL_HWHEEL, -1), "right": (ecodes.REL_HWHEEL, 1),
        }.get(direction, (ecodes.REL_WHEEL, -1))
        for _unused in range(abs(amount)):
            self._pointer(ecodes.EV_REL, axis, sign)
            self._pointer(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)
            time.sleep(0.01)

    WINDOW_COMMANDS = ("minimize", "maximize", "unmaximize", "close",
                       "fullscreen", "unfullscreen", "activate", "above",
                       "unabove")

    def run_window(self, value: str) -> None:
        command = (value or "minimize").strip().lower()
        if command not in self.WINDOW_COMMANDS:
            raise ValueError(
                _("не знаю такого действия над окном: {0}. Есть: {1}").format(command, ', '.join(self.WINDOW_COMMANDS)))
        if self.window_sender is not None and self.window_sender(command):
            return
        # запасной путь для X11
        if shutil.which("xdotool"):
            fallback = {
                "minimize": "windowminimize", "close": "windowkill",
                "activate": "windowactivate",
            }.get(command)
            if fallback:
                self.run_command(f"xdotool getactivewindow {fallback}")
                return
        log.warning(_("действие «окно: %s» требует расширения оболочки — "
                    "поставьте его: glyphstroke shell-extension install"), command)

    def run_standard(self, value: str) -> None:
        """Стандартное действие системы: разворачиваем и выполняем.

        Разворот происходит здесь, а не при чтении файла, намеренно: в файле
        жеста остаётся имя действия, и тот же файл на другой системе выполнит
        её собственное сочетание клавиш.
        """
        resolved = standard.resolve(value)
        if resolved is None:
            raise ValueError(
                _("не знаю такого стандартного действия: {0}").format(value))
        kind, argument = resolved
        if kind == "window":
            self.run_window(argument)
        else:
            self.run_keys(argument)

    def _pointer(self, etype: int, code: int, value: int) -> None:
        if self.pointer_emit is None:
            log.warning(_("действие требует виртуальной мыши, но её нет"))
            return
        self.pointer_emit(etype, code, value)

    # --- точка входа ---
    def run(self, actions) -> None:
        for action in actions:
            try:
                self.run_one(action)
            except Exception as exc:
                log.error(_("действие %s (%r) не выполнено: %s"),
                          action.type, action.value, exc)

    def run_one(self, action) -> None:
        handler = {
            "command": self.run_command,
            "app": self.run_app,
            "keys": self.run_keys,
            "text": self.run_text,
            "button": self.run_button,
            "scroll": self.run_scroll,
            "window": self.run_window,
            "standard": self.run_standard,
            "delay": lambda v: time.sleep(max(0.0, float(v or 0)) / 1000.0),
            "none": lambda v: None,
        }.get(action.type)
        if handler is None:
            log.error(_("неизвестный тип действия: %s"), action.type)
            return
        handler(action.value)

    def close(self) -> None:
        self.keyboard.close()
