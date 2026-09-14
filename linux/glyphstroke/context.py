"""Определение активного окна и того, развёрнуто ли оно во весь экран.

Единого способа под Linux нет, поэтому пробуем по очереди то, что доступно
в текущей сессии, и кешируем результат на четверть секунды.

* **X11** — свойства корневого окна через python-xlib (или ``xprop``).
* **sway / Hyprland / Wayfire** — родные IPC-команды.
* **GNOME Wayland** — способа нет: Mutter намеренно не отдаёт список окон
  приложениям. Жесты с фильтром по приложению там просто не сработают,
  глобальные работают как обычно.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time

from .i18n import _

log = logging.getLogger("glyphstroke.context")

CACHE_TTL_S = 0.25


#: сколько секунд доверять последнему сообщению от оболочки
SHELL_TTL_S = 10.0


class WindowContext:
    def __init__(self) -> None:
        self._cache: tuple[str | None, bool | None] = (None, None)
        self._cached_at = 0.0
        self._shell: str | None = None
        self._shell_at = 0.0
        self._backend = self._detect_backend()
        log.info(_("определение активного окна: %s"), self._backend or _("недоступно"))

    def _detect_backend(self) -> str | None:
        if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
            return "sway"
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
            return "hyprland"
        if os.environ.get("DISPLAY"):
            try:
                import Xlib.display  # noqa: F401
                return "xlib"
            except Exception:
                if shutil.which("xprop"):
                    return "xprop"
        return None

    def set_shell_window(self, app: str, title: str) -> None:
        """Что сообщила оболочка: в Wayland это единственный источник."""
        self._shell = None if app in ("", "-") else f"{app} | {title}"
        self._shell_at = time.monotonic()

    def active_app(self) -> str | None:
        """Строка ``класс окна | заголовок`` или ``None``."""
        now = time.monotonic()
        if self._shell is not None and now - self._shell_at < SHELL_TTL_S:
            return self._shell
        return self._current()[0]

    def fullscreen(self) -> bool | None:
        """Развёрнуто ли активное окно во весь экран. ``None`` — узнать нечем.

        Про это спрашивают, когда включено «не мешать в полноэкранных»: в игре
        мышь должна принадлежать игре, а не нам.
        """
        return self._current()[1]

    def _current(self) -> tuple[str | None, bool | None]:
        now = time.monotonic()
        if now - self._cached_at < CACHE_TTL_S:
            return self._cache
        self._cached_at = now
        try:
            self._cache = (getattr(self, f"_via_{self._backend}")()
                           if self._backend else (None, None))
        except Exception as exc:
            log.debug(_("не удалось определить окно: %s"), exc)
            self._cache = (None, None)
        return self._cache

    # --- реализации ---
    def _via_sway(self) -> tuple[str | None, bool | None]:
        out = subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True,
                             text=True, timeout=1).stdout
        node = _find_focused(json.loads(out))
        if not node:
            return (None, False)
        app = node.get("app_id") or (node.get("window_properties") or {}).get("class", "")
        # в новых выпусках это fullscreen_mode (0, 1, 2), в старых — fullscreen
        full = bool(node.get("fullscreen_mode") or node.get("fullscreen"))
        return (f"{app} | {node.get('name', '')}", full)

    def _via_hyprland(self) -> tuple[str | None, bool | None]:
        out = subprocess.run(["hyprctl", "-j", "activewindow"], capture_output=True,
                             text=True, timeout=1).stdout
        data = json.loads(out or "{}")
        return (f"{data.get('class', '')} | {data.get('title', '')}",
                bool(data.get("fullscreen")))

    def _via_xlib(self) -> tuple[str | None, bool | None]:
        import Xlib.display
        display = getattr(self, "_display", None)
        if display is None:
            display = self._display = Xlib.display.Display()
        root = display.screen().root
        net_active = display.intern_atom("_NET_ACTIVE_WINDOW")
        win_id = root.get_full_property(net_active, 0).value[0]
        if not win_id:
            return (None, False)
        window = display.create_resource_object("window", win_id)
        cls = window.get_wm_class() or ("", "")
        name = window.get_wm_name() or ""
        full = False
        state = window.get_full_property(display.intern_atom("_NET_WM_STATE"), 0)
        if state is not None:
            wanted = display.intern_atom("_NET_WM_STATE_FULLSCREEN")
            full = wanted in list(state.value)
        return (f"{cls[1] or cls[0]} | {name}", full)

    def _via_xprop(self) -> tuple[str | None, bool | None]:
        root = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                              capture_output=True, text=True, timeout=1).stdout
        win_id = root.strip().split()[-1]
        if not win_id.startswith("0x"):
            return (None, False)
        info = subprocess.run(
            ["xprop", "-id", win_id, "WM_CLASS", "_NET_WM_NAME", "_NET_WM_STATE"],
            capture_output=True, text=True, timeout=1).stdout
        cls = title = ""
        full = False
        for line in info.splitlines():
            if line.startswith("WM_CLASS"):
                cls = line.split("=", 1)[-1].strip().strip('"').split('", "')[-1]
            elif "_NET_WM_NAME" in line:
                title = line.split("=", 1)[-1].strip().strip('"')
            elif line.startswith("_NET_WM_STATE"):
                full = "_NET_WM_STATE_FULLSCREEN" in line
        return (f"{cls} | {title}", full)


def window_at_pointer() -> tuple[str, str] | None:
    """Класс окна под курсором в X11 — для мишени в редакторе.

    В GNOME на это отвечает расширение оболочки, а в остальных сеансах X11
    спросить сервер может любой клиент. python-xlib ради этого не нужен:
    libX11 есть везде, где есть X, и от неё требуется три вызова.
    Возвращает (класс окна, название) или ``None``.
    """
    import ctypes
    import ctypes.util

    if not os.environ.get("DISPLAY"):
        return None
    library = ctypes.util.find_library("X11")
    if not library:
        return None
    try:
        x11 = ctypes.cdll.LoadLibrary(library)
    except OSError:
        return None
    c_ulong, c_int, c_uint = ctypes.c_ulong, ctypes.c_int, ctypes.c_uint
    c_void_p, pointer_to = ctypes.c_void_p, ctypes.POINTER

    class ClassHint(ctypes.Structure):
        # строки отдаются указателями: их надо освободить через XFree
        _fields_ = [("res_name", c_void_p), ("res_class", c_void_p)]

    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XOpenDisplay.restype = c_void_p
    x11.XCloseDisplay.argtypes = [c_void_p]
    x11.XDefaultRootWindow.argtypes = [c_void_p]
    x11.XDefaultRootWindow.restype = c_ulong
    x11.XQueryPointer.argtypes = [c_void_p, c_ulong, pointer_to(c_ulong),
                                  pointer_to(c_ulong), pointer_to(c_int),
                                  pointer_to(c_int), pointer_to(c_int),
                                  pointer_to(c_int), pointer_to(c_uint)]
    x11.XQueryPointer.restype = c_int
    x11.XGetClassHint.argtypes = [c_void_p, c_ulong, pointer_to(ClassHint)]
    x11.XGetClassHint.restype = c_int
    x11.XFree.argtypes = [c_void_p]

    display = x11.XOpenDisplay(None)
    if not display:
        return None
    try:
        root = window = x11.XDefaultRootWindow(display)
        # спускаемся по дереву к окну под курсором: у рамки оконного
        # менеджера класса нет, он у окна приложения внутри неё
        for _depth in range(32):
            if window != root:
                hint = ClassHint()
                if x11.XGetClassHint(display, window, ctypes.byref(hint)):
                    names = []
                    for raw in (hint.res_class, hint.res_name):
                        names.append(ctypes.string_at(raw).decode("utf-8", "replace")
                                     if raw else "")
                        if raw:
                            x11.XFree(raw)
                    wm_class = names[0] or names[1]
                    if wm_class:
                        return wm_class, wm_class
            root_back, child = c_ulong(), c_ulong()
            coords = [c_int() for _index in range(4)]
            mask = c_uint()
            if not x11.XQueryPointer(display, window, ctypes.byref(root_back),
                                     ctypes.byref(child),
                                     *(ctypes.byref(value) for value in coords),
                                     ctypes.byref(mask)):
                return None
            if not child.value:
                return None
            window = child.value
        return None
    finally:
        x11.XCloseDisplay(display)


def _find_focused(node: dict) -> dict | None:
    if node.get("focused"):
        return node
    for child in node.get("nodes", []) + node.get("floating_nodes", []):
        found = _find_focused(child)
        if found:
            return found
    return None
