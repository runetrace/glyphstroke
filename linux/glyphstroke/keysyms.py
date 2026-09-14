"""Разбор комбинаций вида ``ctrl+alt+t`` в коды ядра ``KEY_*``.

Нажатия отправляются через uinput, то есть на уровне ядра, поэтому доходят
до любого приложения — и в X11, и в Wayland, где синтетические события
X-сервера (xdotool) не работают в принципе.
"""

from __future__ import annotations

from evdev import ecodes

from .i18n import _

#: человеческие имена → имена ядра
ALIASES = {
    "ctrl": "KEY_LEFTCTRL", "control": "KEY_LEFTCTRL", "lctrl": "KEY_LEFTCTRL",
    "rctrl": "KEY_RIGHTCTRL",
    "alt": "KEY_LEFTALT", "lalt": "KEY_LEFTALT", "ralt": "KEY_RIGHTALT",
    "altgr": "KEY_RIGHTALT",
    "shift": "KEY_LEFTSHIFT", "lshift": "KEY_LEFTSHIFT", "rshift": "KEY_RIGHTSHIFT",
    "super": "KEY_LEFTMETA", "win": "KEY_LEFTMETA", "meta": "KEY_LEFTMETA",
    "cmd": "KEY_LEFTMETA", "rsuper": "KEY_RIGHTMETA",
    "esc": "KEY_ESC", "escape": "KEY_ESC",
    "enter": "KEY_ENTER", "return": "KEY_ENTER",
    "del": "KEY_DELETE", "ins": "KEY_INSERT",
    "pgup": "KEY_PAGEUP", "pgdn": "KEY_PAGEDOWN", "pagedown": "KEY_PAGEDOWN",
    "pageup": "KEY_PAGEUP",
    # имена в стиле X11 и macOS: встречаются в перенесённых файлах жестов
    "bracketleft": "KEY_LEFTBRACE", "bracketright": "KEY_RIGHTBRACE",
    "apostrophe": "KEY_APOSTROPHE", "semicolon": "KEY_SEMICOLON",
    "comma": "KEY_COMMA", "period": "KEY_DOT", "slash": "KEY_SLASH",
    "backslash": "KEY_BACKSLASH", "grave": "KEY_GRAVE",
    "up": "KEY_UP", "down": "KEY_DOWN", "left": "KEY_LEFT", "right": "KEY_RIGHT",
    "space": "KEY_SPACE", "tab": "KEY_TAB", "backspace": "KEY_BACKSPACE",
    "plus": "KEY_EQUAL", "minus": "KEY_MINUS", "equal": "KEY_EQUAL",
    "printscreen": "KEY_SYSRQ", "print": "KEY_SYSRQ", "prtsc": "KEY_SYSRQ",
    "volup": "KEY_VOLUMEUP", "voldown": "KEY_VOLUMEDOWN", "mute": "KEY_MUTE",
    "play": "KEY_PLAYPAUSE", "next": "KEY_NEXTSONG", "prev": "KEY_PREVIOUSSONG",
    "menu": "KEY_COMPOSE", "capslock": "KEY_CAPSLOCK",
}

MODIFIERS = {
    "KEY_LEFTCTRL", "KEY_RIGHTCTRL", "KEY_LEFTALT", "KEY_RIGHTALT",
    "KEY_LEFTSHIFT", "KEY_RIGHTSHIFT", "KEY_LEFTMETA", "KEY_RIGHTMETA",
}

#: символ → (имя клавиши, нужен ли shift). Раскладка US — для латиницы и
#: цифр совпадает с большинством раскладок, знаки препинания могут разойтись
_PUNCT = {
    " ": ("KEY_SPACE", False), "\t": ("KEY_TAB", False), "\n": ("KEY_ENTER", False),
    "-": ("KEY_MINUS", False), "=": ("KEY_EQUAL", False), "[": ("KEY_LEFTBRACE", False),
    "]": ("KEY_RIGHTBRACE", False), "\\": ("KEY_BACKSLASH", False),
    ";": ("KEY_SEMICOLON", False), "'": ("KEY_APOSTROPHE", False),
    "`": ("KEY_GRAVE", False), ",": ("KEY_COMMA", False), ".": ("KEY_DOT", False),
    "/": ("KEY_SLASH", False),
    "_": ("KEY_MINUS", True), "+": ("KEY_EQUAL", True), "{": ("KEY_LEFTBRACE", True),
    "}": ("KEY_RIGHTBRACE", True), "|": ("KEY_BACKSLASH", True),
    ":": ("KEY_SEMICOLON", True), '"': ("KEY_APOSTROPHE", True),
    "~": ("KEY_GRAVE", True), "<": ("KEY_COMMA", True), ">": ("KEY_DOT", True),
    "?": ("KEY_SLASH", True),
    "!": ("KEY_1", True), "@": ("KEY_2", True), "#": ("KEY_3", True),
    "$": ("KEY_4", True), "%": ("KEY_5", True), "^": ("KEY_6", True),
    "&": ("KEY_7", True), "*": ("KEY_8", True), "(": ("KEY_9", True),
    ")": ("KEY_0", True),
}


class KeyParseError(ValueError):
    pass


def key_name(token: str) -> str:
    """``ctrl`` → ``KEY_LEFTCTRL``, ``a`` → ``KEY_A``, ``f5`` → ``KEY_F5``."""
    token = token.strip()
    if not token:
        raise KeyParseError(_("пустое имя клавиши"))
    low = token.lower()
    if low in ALIASES:
        return ALIASES[low]
    upper = token.upper()
    for candidate in (upper, f"KEY_{upper}", f"BTN_{upper}"):
        if candidate in ecodes.ecodes:
            return candidate
    # «Page_Up» пишут и так, и «PageUp»: ядро знает только KEY_PAGEUP.
    # Без этого стартовый жест с ctrl+Page_Up молча не срабатывал.
    squashed = upper.replace("_", "")
    if squashed != upper:
        for candidate in (squashed, f"KEY_{squashed}", f"BTN_{squashed}"):
            if candidate in ecodes.ecodes:
                return candidate
        if squashed.lower() in ALIASES:
            return ALIASES[squashed.lower()]
    if low in _PUNCT:
        return _PUNCT[low][0]
    raise KeyParseError(_("неизвестная клавиша: {0}").format(token))


def key_code(token: str) -> int:
    return ecodes.ecodes[key_name(token)]


def parse_combo(combo: str) -> tuple[list[int], list[int]]:
    """``ctrl+shift+t`` → (коды модификаторов, коды обычных клавиш)."""
    mods: list[int] = []
    keys: list[int] = []
    for token in combo.replace("-", "+").split("+"):
        token = token.strip()
        if not token:
            continue
        name = key_name(token)
        (mods if name in MODIFIERS else keys).append(ecodes.ecodes[name])
    if not mods and not keys:
        raise KeyParseError(_("пустая комбинация: {0}").format(combo))
    return mods, keys


def parse_sequence(text: str) -> list[tuple[list[int], list[int]]]:
    """``ctrl+c ctrl+v`` → две комбинации подряд."""
    return [parse_combo(part) for part in text.split() if part.strip()]


def char_to_key(ch: str) -> tuple[int, bool] | None:
    """Символ → (код клавиши, нужен ли shift) для действия «ввести текст»."""
    if ch in _PUNCT:
        name, shift = _PUNCT[ch]
        return ecodes.ecodes[name], shift
    if ch.isdigit():
        return ecodes.ecodes[f"KEY_{ch}"], False
    if "a" <= ch.lower() <= "z" and ch.isascii():
        return ecodes.ecodes[f"KEY_{ch.upper()}"], ch.isupper()
    return None


def button_code(token: str) -> int:
    """``right`` → ``BTN_RIGHT``."""
    low = token.strip().lower()
    named = {"left": "BTN_LEFT", "right": "BTN_RIGHT", "middle": "BTN_MIDDLE",
             "side": "BTN_SIDE", "extra": "BTN_EXTRA", "back": "BTN_BACK",
             "forward": "BTN_FORWARD"}
    name = named.get(low, low.upper())
    if not name.startswith("BTN_"):
        name = f"BTN_{name}"
    if name not in ecodes.ecodes:
        raise KeyParseError(_("неизвестная кнопка мыши: {0}").format(token))
    return ecodes.ecodes[name]
