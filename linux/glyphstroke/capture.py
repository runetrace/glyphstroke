"""Перехват мыши: поиск устройств, зеркало через uinput, автомат росчерка.

Схема работы в режиме ``grab``:

    физическая мышь --(EVIOCGRAB, эксклюзивно)--> демон --> uinput-зеркало --> система

Все события пересылаются один в один, кроме нажатия кнопки-модификатора:
его демон придерживает. На отпускании решается, что это было. Обычный клик
дослан парой «нажал-отпустил» — приложение видит нормальный щелчок, только
на несколько миллисекунд позже. Росчерк, наоборот, не доходит до приложения,
поэтому контекстное меню не выскакивает.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

import evdev
from evdev import InputDevice, UInput, ecodes

from .i18n import _

log = logging.getLogger("glyphstroke.capture")

#: свои виртуальные устройства перехватывать нельзя; strokeit — прежнее имя
#: программы, его устройства тоже обходим стороной
VIRTUAL_PREFIX = ("glyphstroke-", "strokeit-")
MIRROR_NAME = "glyphstroke-virtual-pointer"

#: колёса высокого разрешения — без них ломается плавная прокрутка
EXTRA_REL = [ecodes.REL_WHEEL, ecodes.REL_HWHEEL, 11, 12]
EXTRA_KEYS = [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE]


# --- поиск устройств --------------------------------------------------------
def event_paths() -> list[str]:
    """Пути ``/dev/input/event*`` без открытия устройств.

    Открыть устройство и вычитать его возможности — это десяток ioctl и
    десятки миллисекунд на все устройства разом. В основном цикле, который
    пересылает движения мыши, такое стоит делать только для новых путей,
    а появление новых путей ловить вот этим дешёвым перечислением.
    """
    try:
        return sorted(f"/dev/input/{name}" for name in os.listdir("/dev/input")
                      if name.startswith("event"))
    except OSError:
        return []


def stable_link_map() -> dict[str, list[str]]:
    """``/dev/input/event3`` → его постоянные ссылки в by-id и by-path.

    Номера ``eventN`` перетасовываются при перезагрузке, а ссылка в by-id
    строится по производителю, модели и серийному номеру, поэтому привязка
    к ней переживает и перезагрузку, и смену разъёма.
    """
    links: dict[str, list[str]] = {}
    for base in ("/dev/input/by-id", "/dev/input/by-path"):
        try:
            names = os.listdir(base)
        except OSError:
            continue
        for name in names:
            link = f"{base}/{name}"
            try:
                links.setdefault(os.path.realpath(link), []).append(link)
            except OSError:
                continue
    return links


def device_aliases(dev: InputDevice, links: dict[str, list[str]] | None = None) -> list[str]:
    """Всё, по чему устройство можно опознать в настройках."""
    links = stable_link_map() if links is None else links
    return [dev.name or "", dev.path, *links.get(dev.path, [])]


def is_touchpad(dev: InputDevice, caps: dict | None = None) -> bool:
    caps = dev.capabilities() if caps is None else caps
    keys = set(caps.get(ecodes.EV_KEY, []))
    abs_codes = set(code for code, _info in caps.get(ecodes.EV_ABS, []))
    return (
        ecodes.BTN_TOOL_FINGER in keys
        or ecodes.BTN_TOUCH in keys
        or ecodes.ABS_MT_POSITION_X in abs_codes
    )


def looks_like_pointer(dev: InputDevice, caps: dict | None = None) -> bool:
    caps = dev.capabilities() if caps is None else caps
    rel = set(caps.get(ecodes.EV_REL, []))
    keys = set(caps.get(ecodes.EV_KEY, []))
    has_motion = {ecodes.REL_X, ecodes.REL_Y} <= rel
    has_buttons = bool(keys & {ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE})
    return has_motion and has_buttons


def find_pointers(include: list[str] | None = None,
                  exclude: list[str] | None = None,
                  allow_touchpads: bool = False,
                  paths: list[str] | None = None) -> list[InputDevice]:
    """Список мышей, которые стоит перехватывать.

    ``paths`` ограничивает проверку конкретными устройствами — так при
    горячем подключении открывается только то, что действительно появилось.
    """
    found: list[InputDevice] = []
    links = stable_link_map()
    for path in (sorted(paths) if paths is not None else sorted(evdev.list_devices())):
        try:
            dev = InputDevice(path)
        except OSError as exc:
            log.debug(_("нет доступа к %s: %s"), path, exc)
            continue
        name = dev.name or ""
        if name.startswith(VIRTUAL_PREFIX):
            dev.close()          # своё же зеркало перехватывать нельзя
            continue
        # шаблон из настроек сверяется и с именем, и с путями устройства,
        # поэтому привязаться можно к постоянной ссылке из by-id
        aliases = device_aliases(dev, links)
        matches = lambda patterns: any(  # noqa: E731
            re.search(p, alias, re.IGNORECASE) for p in patterns for alias in aliases)
        if exclude and matches(exclude):
            dev.close()
            continue
        if include:
            if not matches(include):
                dev.close()
                continue
        else:
            caps = dev.capabilities()
            if not looks_like_pointer(dev, caps) or \
                    (is_touchpad(dev, caps) and not allow_touchpads):
                dev.close()
                continue
        found.append(dev)
    return found


def build_mirror(devices: list[InputDevice], name: str = MIRROR_NAME) -> UInput:
    """Виртуальная мышь, повторяющая возможности всех перехваченных."""
    keys: set[int] = set(EXTRA_KEYS)
    # движение нужно и без мышей: на ноутбуке демон может стартовать с одним
    # тачпадом, а мышь воткнут позже
    rels: set[int] = set(EXTRA_REL) | {ecodes.REL_X, ecodes.REL_Y}
    abs_caps: dict[int, object] = {}
    for dev in devices:
        caps = dev.capabilities(absinfo=True)
        keys.update(caps.get(ecodes.EV_KEY, []))
        rels.update(caps.get(ecodes.EV_REL, []))
        for code, info in caps.get(ecodes.EV_ABS, []):
            abs_caps.setdefault(code, info)
    capabilities: dict[int, list] = {
        ecodes.EV_KEY: sorted(keys),
        ecodes.EV_REL: sorted(rels),
    }
    if abs_caps:
        capabilities[ecodes.EV_ABS] = sorted(abs_caps.items())
    return UInput(capabilities, name=name, version=1)


class Mirror:
    """Тонкая обёртка: пересылка события и синхронизация.

    Писать в зеркало могут два потока — основной цикл пересылки и поток
    выполнения действий, — поэтому запись под замком. Замок не удерживается
    на время пауз, иначе пересылка движений вставала бы вместе с ними.
    """

    def __init__(self, ui: UInput):
        self.ui = ui
        self._lock = threading.Lock()

    def emit(self, etype: int, code: int, value: int) -> None:
        with self._lock:
            self.ui.write(etype, code, value)

    def syn(self) -> None:
        with self._lock:
            self.ui.syn()

    def forward(self, event) -> None:
        with self._lock:
            self.ui.write(event.type, event.code, event.value)

    def click(self, code: int, hold_s: float = 0.02) -> None:
        with self._lock:
            self.ui.write(ecodes.EV_KEY, code, 1)
            self.ui.syn()
        time.sleep(hold_s)
        with self._lock:
            self.ui.write(ecodes.EV_KEY, code, 0)
            self.ui.syn()

    def close(self) -> None:
        self.ui.close()


# --- автомат росчерка -------------------------------------------------------
class State(Enum):
    IDLE = "idle"
    HOLD = "hold"          # кнопка нажата, порог длины ещё не пройден
    DRAW = "draw"          # это уже росчерк
    PASSTHRU = "passthru"  # решили отдать кнопку приложению


@dataclass
class StrokeEvent:
    """Что автомат просит сделать внешний код.

    ``begin`` — кнопку нажали, с этого мгновения копится росчерк;
    ``finish`` — отпустили после росчерка, точки готовы к распознаванию;
    ``click`` — отпустили, не нарисовав ничего, это был обычный щелчок;
    ``cancel`` — росчерк прерван (аккорд с другой кнопкой или таймаут);
    ``event`` — особый жест: щелчок другой кнопкой или колесо при удержании.
    """

    kind: str  # begin | cancel | finish | click | event | hint
    points: list[tuple[float, float]] = field(default_factory=list)
    #: для kind == "event" — какое именно: rocker-left, wheel-up и прочие
    event: str = ""


#: колесо: код события → имя особого жеста. Коды 11 и 12 — колесо высокого
#: разрешения, его тоже придётся забирать, иначе страница всё равно прокрутится
WHEEL_EVENTS = {
    ecodes.REL_WHEEL: ("wheel-up", "wheel-down"),
    ecodes.REL_HWHEEL: ("wheel-right", "wheel-left"),
}
HI_RES_WHEEL = {11: ecodes.REL_WHEEL, 12: ecodes.REL_HWHEEL}


class StrokeMachine:
    """Один автомат на устройство: сырые события → события росчерка."""

    def __init__(self, mirror: Mirror, trigger: int, min_stroke_px: float,
                 monitor_only: bool = False, press_passthrough_ms: int = 0,
                 hint_delay_ms: int = 0):
        self.mirror = mirror
        self.trigger = trigger
        self.min_stroke_px = min_stroke_px
        self.monitor_only = monitor_only
        self.press_passthrough_ms = press_passthrough_ms
        self.hint_delay_ms = hint_delay_ms
        self._hint_shown = False
        self.state = State.IDLE
        #: какие особые жесты реально привязаны — только их и забираем себе,
        #: иначе щелчок или колесо должны пройти к приложению как обычно
        self.bound_events: set[str] = set()
        self.pressed_buttons: set[int] = set()
        self._swallowed_buttons: set[int] = set()
        self._swallow_trigger_release = False
        self.consumed = False
        self.points: list[tuple[float, float]] = []
        self.x = 0.0
        self.y = 0.0
        self.length = 0.0
        self.started_at = 0.0
        self._abs_seen = False

    # --- вспомогательное ---
    def _start(self, now: float) -> None:
        self._hint_shown = False
        self.state = State.HOLD
        self.points = [(0.0, 0.0)]
        self.x = self.y = 0.0
        self.length = 0.0
        self.started_at = now

    def _reset(self) -> None:
        self.state = State.IDLE
        self.points = []
        self.length = 0.0
        self.consumed = False
        self._hint_shown = False

    def _release_held_press(self) -> None:
        """Отдать приложению нажатие, которое мы придержали."""
        self.mirror.emit(ecodes.EV_KEY, self.trigger, 1)
        self.mirror.syn()

    def _add_point(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        prev = self.points[-1] if self.points else (0.0, 0.0)
        self.length += abs(self.x - prev[0]) + abs(self.y - prev[1])
        self.points.append((self.x, self.y))

    # --- основной вход ---
    def handle(self, event) -> list[StrokeEvent]:
        out: list[StrokeEvent] = []
        now = time.monotonic()

        if event.type == ecodes.EV_KEY and event.value in (0, 1):
            if event.value:
                self.pressed_buttons.add(event.code)
            else:
                self.pressed_buttons.discard(event.code)

        # щелчок кнопкой, которую мы забрали себе, приложению не показываем
        if event.type == ecodes.EV_KEY and event.code in self._swallowed_buttons:
            if event.value == 0:
                self._swallowed_buttons.discard(event.code)
            return out

        if event.type == ecodes.EV_KEY and event.code == self.trigger:
            if event.value == 1 and not self.monitor_only \
                    and "rocker-right" in self.bound_events \
                    and ecodes.BTN_LEFT in self.pressed_buttons:
                # левая уже нажата и ушла приложению; правую забираем себе
                self._swallow_trigger_release = True
                return [StrokeEvent("event", event="rocker-right")]
            if event.value == 0 and self._swallow_trigger_release:
                self._swallow_trigger_release = False
                return out
            if event.value == 2:  # автоповтор кнопки — игнорируем
                return out
            if event.value == 1:
                if self.monitor_only:
                    self.mirror.forward(event)
                self._start(now)
                # рисование начинается ровно здесь, а не когда набралась длина:
                # так след идёт от точки нажатия, а не от места, где курсор
                # оказался позже
                out.append(StrokeEvent("begin"))
                return out
            # отпускание
            if self.consumed:
                # во время удержания сработал особый жест — щелчок не нужен
                if self.monitor_only:
                    self.mirror.forward(event)
                out.append(StrokeEvent("cancel"))
                self._reset()
                return out
            if self.state == State.HOLD:
                if not self.monitor_only:
                    self.mirror.click(self.trigger)
                else:
                    self.mirror.forward(event)
                out.append(StrokeEvent("click"))
            elif self.state == State.DRAW:
                if self.monitor_only:
                    self.mirror.forward(event)
                out.append(StrokeEvent("finish", list(self.points)))
            elif self.state == State.PASSTHRU:
                self.mirror.forward(event)
            else:
                self.mirror.forward(event)
            self._reset()
            return out

        if event.type == ecodes.EV_KEY and event.value == 1 and \
                self.state in (State.HOLD, State.DRAW) and not self.monitor_only:
            rocker = {ecodes.BTN_LEFT: "rocker-left",
                      ecodes.BTN_MIDDLE: "rocker-middle"}.get(event.code)
            if rocker in self.bound_events:
                self._swallowed_buttons.add(event.code)
                self.consumed = True
                self.points = []
                return [StrokeEvent("event", event=rocker)]

        if event.type == ecodes.EV_KEY and event.value == 1 and \
                self.state in (State.HOLD, State.DRAW):
            # нажали другую кнопку во время удержания — это аккорд, а не жест
            if not self.monitor_only:
                self._release_held_press()
            self.mirror.forward(event)
            out.append(StrokeEvent("cancel"))
            self.state = State.PASSTHRU
            self.points = []
            return out

        if event.type == ecodes.EV_REL and self.state in (State.HOLD, State.DRAW) \
                and not self.monitor_only:
            axis = HI_RES_WHEEL.get(event.code, event.code)
            names = WHEEL_EVENTS.get(axis)
            if names and event.value:
                name = names[0] if event.value > 0 else names[1]
                if name in self.bound_events:
                    self.consumed = True
                    self.points = []
                    # событие колеса забираем себе: страница прокручиваться
                    # не должна. Действие даёт только «щелчок» колеса, а не
                    # промежуточные отсчёты высокого разрешения
                    if event.code in HI_RES_WHEEL:
                        return out
                    return [StrokeEvent("event", event=name)]

        if event.type == ecodes.EV_REL and event.code in (ecodes.REL_X, ecodes.REL_Y):
            self.mirror.forward(event)
            if self.state in (State.HOLD, State.DRAW) and not self._abs_seen:
                dx = event.value if event.code == ecodes.REL_X else 0
                dy = event.value if event.code == ecodes.REL_Y else 0
                self._add_point(dx, dy)
                out.extend(self._after_motion())
            return out

        if event.type == ecodes.EV_ABS and event.code in (ecodes.ABS_X, ecodes.ABS_Y):
            self.mirror.forward(event)
            if self.state in (State.HOLD, State.DRAW):
                self._abs_seen = True
                if event.code == ecodes.ABS_X:
                    self._add_point(event.value - self.x, 0)
                else:
                    self._add_point(0, event.value - self.y)
                out.extend(self._after_motion())
            return out

        self.mirror.forward(event)
        return out

    def _after_motion(self) -> list[StrokeEvent]:
        # порог длины отделяет росчерк от обычного щелчка и ничего больше
        if self.state == State.HOLD and self.length >= self.min_stroke_px:
            self.state = State.DRAW
        return []

    def passthrough_now(self) -> None:
        """Отдать придержанное нажатие приложению и не мешать до отпускания."""
        if self.monitor_only or self.state not in (State.HOLD, State.DRAW):
            return
        self._release_held_press()
        self.state = State.PASSTHRU
        self.points = []

    def tick(self) -> list[StrokeEvent]:
        """Таймауты удержания. Вызывается из простоя основного цикла."""
        now = time.monotonic()
        if (self.hint_delay_ms and self.state == State.HOLD and not self._hint_shown
                and not self.consumed
                and (now - self.started_at) * 1000 >= self.hint_delay_ms
                and self.length < self.min_stroke_px):
            # кнопку держат, но не рисуют — похоже, забыли, какие есть жесты
            self._hint_shown = True
            return [StrokeEvent("hint")]
        if (self.press_passthrough_ms and self.state == State.HOLD
                and not self.monitor_only
                and (time.monotonic() - self.started_at) * 1000 >= self.press_passthrough_ms):
            self._release_held_press()
            self.state = State.PASSTHRU
            self.points = []
            return [StrokeEvent("cancel")]
        return []


# --- тачпад и клавиша --------------------------------------------------------
#: короче этого пути палец росчерка не рисует, в миллиметрах. Разрешение у
#: тачпадов разное: порог в единицах устройства на одном был бы касанием, а на
#: другом — половиной тачпада
TOUCH_MIN_STROKE_MM = 5.0

#: касание двумя пальцами и больше — это прокрутка или жест оболочки
MULTI_FINGER_TOOLS = (ecodes.BTN_TOOL_DOUBLETAP, ecodes.BTN_TOOL_TRIPLETAP,
                      ecodes.BTN_TOOL_QUADTAP, ecodes.BTN_TOOL_QUINTTAP)

#: клавиши, которые редактор предлагает списком; назначить можно любую
TOUCHPAD_KEYS = ("KEY_LEFTMETA", "KEY_LEFTALT", "KEY_LEFTCTRL",
                 "KEY_RIGHTALT", "KEY_RIGHTCTRL", "KEY_COMPOSE")

#: как назвать клавишу человеку; остальные — по имени ядра без приставки
KEY_LABELS = {
    "KEY_LEFTMETA": "Super", "KEY_RIGHTMETA": "Super R",
    "KEY_LEFTALT": "Alt", "KEY_RIGHTALT": "AltGr",
    "KEY_LEFTCTRL": "Ctrl", "KEY_RIGHTCTRL": "Ctrl R",
    "KEY_LEFTSHIFT": "Shift", "KEY_RIGHTSHIFT": "Shift R",
    "KEY_COMPOSE": "Menu",
}


def key_code(name: str) -> int | None:
    """``KEY_LEFTMETA`` → код ядра. ``None`` — пусто или такой клавиши нет."""
    name = (name or "").strip().upper()
    if not name:
        return None
    if not name.startswith("KEY_"):
        name = f"KEY_{name}"
    code = ecodes.ecodes.get(name)
    return code if isinstance(code, int) and code > 0 else None


def key_name(code: int) -> str | None:
    """Код ядра → имя ``KEY_*``. Где имён несколько, последнее самое внятное."""
    if code <= 0:
        return None
    names = ecodes.KEY.get(code)
    if isinstance(names, str):
        names = (names,)
    names = [name for name in names or () if name.startswith("KEY_")]
    return names[-1] if names else None


def key_label(name: str) -> str:
    name = (name or "").strip().upper()
    if name in KEY_LABELS:
        return KEY_LABELS[name]
    return name[4:] if name.startswith("KEY_") else name


def units_per_mm(dev, axis: int = ecodes.ABS_X) -> float:
    """Сколько единиц устройства в миллиметре по оси тачпада.

    Разрешение сообщает драйвер. Если он промолчал, считаем тачпад шириной в
    десять сантиметров: ошибка в полтора раза порогу росчерка не страшна.
    """
    try:
        info = dev.absinfo(axis)
    except (OSError, KeyError, TypeError):
        return 40.0
    if info.resolution:
        return float(info.resolution)
    return max(1.0, (info.max - info.min) / 100.0)


def find_touchpads(exclude: list[str] | None = None,
                   paths: list[str] | None = None) -> list[InputDevice]:
    """Тачпады для рисования с клавишей. Их не захватывают, только читают.

    Сенсорные экраны пропускаем: палец там сам указывает место, и курсор
    прыгал бы под него посреди росчерка.
    """
    found: list[InputDevice] = []
    links = stable_link_map()
    for path in (sorted(paths) if paths is not None else sorted(evdev.list_devices())):
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        try:
            caps = dev.capabilities()
            axes = {code for code, _info in caps.get(ecodes.EV_ABS, [])}
            aliases = device_aliases(dev, links)
            suitable = (
                not (dev.name or "").startswith(VIRTUAL_PREFIX)
                and is_touchpad(dev, caps)
                and ecodes.BTN_TOUCH in caps.get(ecodes.EV_KEY, [])
                and {ecodes.ABS_X, ecodes.ABS_Y} <= axes
                and ecodes.INPUT_PROP_DIRECT not in (dev.input_props() or [])
                and not any(re.search(p, alias, re.IGNORECASE)
                            for p in exclude or [] for alias in aliases))
        except OSError:
            suitable = False
        if suitable:
            found.append(dev)
        else:
            dev.close()
    return found


def find_keyboards(code: int, paths: list[str] | None = None) -> list[InputDevice]:
    """Устройства, на которых есть назначенная клавиша. Их тоже только читают.

    Захватывать клавиатуру незачем: из всего потока нажатий демону важно одно —
    зажата ли назначенная клавиша. Остальное проходит мимо, не запоминаясь и не
    попадая в журнал.
    """
    found: list[InputDevice] = []
    for path in (sorted(paths) if paths is not None else sorted(evdev.list_devices())):
        try:
            dev = InputDevice(path)
        except OSError:
            continue
        try:
            keys = dev.capabilities().get(ecodes.EV_KEY, [])
            suitable = not (dev.name or "").startswith(VIRTUAL_PREFIX) and code in keys
        except OSError:
            suitable = False
        if suitable:
            found.append(dev)
        else:
            dev.close()
    return found


class TouchpadMachine:
    """Росчерк пальцем по тачпаду, пока зажата назначенная клавиша.

    Тачпад не захвачен: курсор идёт за пальцем, как идёт за мышью при обычном
    жесте, а прокрутка, жесты оболочки и отсечение ладони остаются при нём.
    Росчерк начинается касанием при зажатой клавише (или нажатием клавиши,
    когда палец уже лежит) и заканчивается отрывом пальца или отпусканием
    клавиши — что случится раньше. Нажатий мы не придерживаем, поэтому и
    досылать приложению нечего.
    """

    #: общий код демона досылает щелчок только тем, кто его придержал
    monitor_only = True

    def __init__(self, min_stroke: float, units_per_mm: float = 40.0):
        self.min_stroke = min_stroke
        self.units_per_mm = units_per_mm
        self.key_held = False
        self.touching = False
        self.drawing = False
        #: росчерк брошен (второй палец, приложение в исключениях): до отрыва
        #: пальца нового не начинаем
        self.abandoned = False
        self.points: list[tuple[float, float]] = []
        self.length = 0.0
        self.x: float | None = None
        self.y: float | None = None

    @classmethod
    def for_device(cls, dev) -> "TouchpadMachine":
        density = units_per_mm(dev)
        return cls(TOUCH_MIN_STROKE_MM * density, units_per_mm=density)

    def reset(self) -> None:
        """Забыть росчерк. Что делают палец и клавиша, помним по-прежнему."""
        self.drawing = False
        self.points = []
        self.length = 0.0

    def passthrough_now(self) -> None:
        """Росчерк здесь не нужен — приложение в исключениях."""
        if self.drawing:
            self.reset()
            self.abandoned = True

    def _start(self, with_position: bool) -> list[StrokeEvent]:
        self.reset()
        self.drawing = True
        # палец лежал ещё до нажатия клавиши — его место уже известно. При
        # новом касании координаты могут прийти позже, их добавит SYN_REPORT
        if with_position and self.x is not None and self.y is not None:
            self.points.append((self.x, self.y))
        return [StrokeEvent("begin")]

    def _stop(self) -> list[StrokeEvent]:
        points, length = self.points, self.length
        self.reset()
        if length >= self.min_stroke and len(points) >= 2:
            return [StrokeEvent("finish", points)]
        return [StrokeEvent("cancel")]

    def set_key(self, held: bool) -> list[StrokeEvent]:
        if held == self.key_held:
            return []
        self.key_held = held
        if held and self.touching and not self.drawing and not self.abandoned:
            return self._start(with_position=True)
        if not held and self.drawing:
            return self._stop()
        return []

    def observe(self, event) -> None:
        """Только следить за пальцем, ничего не рисуя, — например, пока открыто меню."""
        if event.type == ecodes.EV_KEY and event.code == ecodes.BTN_TOUCH \
                and event.value in (0, 1):
            self.touching = bool(event.value)
            if not self.touching:
                self.abandoned = False
        elif event.type == ecodes.EV_ABS and event.code == ecodes.ABS_X:
            self.x = float(event.value)
        elif event.type == ecodes.EV_ABS and event.code == ecodes.ABS_Y:
            self.y = float(event.value)

    def handle(self, event) -> list[StrokeEvent]:
        if event.type == ecodes.EV_KEY and event.code == ecodes.BTN_TOUCH \
                and event.value in (0, 1):
            self.observe(event)
            if self.touching and self.key_held and not self.drawing:
                return self._start(with_position=False)
            if not self.touching and self.drawing:
                return self._stop()
            return []
        if event.type == ecodes.EV_KEY and event.code in MULTI_FINGER_TOOLS \
                and event.value == 1 and self.drawing:
            self.reset()
            self.abandoned = True
            return [StrokeEvent("cancel")]
        if event.type == ecodes.EV_ABS:
            self.observe(event)
            return []
        if event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT \
                and self.drawing and self.x is not None and self.y is not None:
            point = (self.x, self.y)
            if self.points:
                last = self.points[-1]
                if point == last:
                    return []
                self.length += abs(point[0] - last[0]) + abs(point[1] - last[1])
            self.points.append(point)
        return []
