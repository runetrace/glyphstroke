"""Автомат росчерка и отбор устройств — без обращения к железу."""

from __future__ import annotations

import types

import pytest

evdev = pytest.importorskip("evdev")
from evdev import ecodes  # noqa: E402

from glyphstroke import capture  # noqa: E402
from glyphstroke.capture import State, StrokeMachine  # noqa: E402


class FakeMirror:
    """Запоминает всё, что демон отправил бы системе."""

    def __init__(self):
        self.events: list[tuple[int, int, int]] = []

    def emit(self, etype, code, value):
        self.events.append((etype, code, value))

    def syn(self):
        pass

    def forward(self, event):
        self.events.append((event.type, event.code, event.value))

    def click(self, code, hold_s=0.0):
        self.events.append((ecodes.EV_KEY, code, 1))
        self.events.append((ecodes.EV_KEY, code, 0))

    def buttons(self, code=ecodes.BTN_RIGHT):
        return [v for t, c, v in self.events if t == ecodes.EV_KEY and c == code]


def event(etype, code, value):
    return types.SimpleNamespace(type=etype, code=code, value=value)


def move(machine, dx=0, dy=0):
    out = []
    if dx:
        out += machine.handle(event(ecodes.EV_REL, ecodes.REL_X, dx))
    if dy:
        out += machine.handle(event(ecodes.EV_REL, ecodes.REL_Y, dy))
    return out


@pytest.fixture
def machine():
    return StrokeMachine(FakeMirror(), ecodes.BTN_RIGHT, min_stroke_px=40)


def kinds(events):
    return [e.kind for e in events]


def test_drawing_starts_exactly_at_the_press(machine):
    """Движения до нажатия в росчерк попадать не должны."""
    move(machine, dx=500, dy=-300)          # возили мышью просто так
    assert machine.state is State.IDLE

    assert kinds(machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))) == ["begin"]
    assert machine.points == [(0.0, 0.0)], "росчерк начинается из нуля, а не с чужой точки"

    move(machine, dy=60)
    move(machine, dx=60)
    finish = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0))
    assert kinds(finish) == ["finish"]
    assert finish[0].points[0] == (0.0, 0.0)
    assert finish[0].points[-1] == (60.0, 60.0)


def test_second_stroke_does_not_inherit_the_first(machine):
    for _ in range(2):
        machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
        move(machine, dx=100)
        out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0))
    assert out[0].points[0] == (0.0, 0.0)
    assert out[0].points[-1] == (100.0, 0.0)


def test_short_press_is_a_click(machine):
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    move(machine, dx=5)
    out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0))
    assert kinds(out) == ["click"]
    assert machine.mirror.buttons() == [1, 0], "щелчок должен дойти до приложения"


def test_gesture_does_not_leak_the_click(machine):
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    move(machine, dy=120)
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0))
    assert machine.mirror.buttons() == []


def test_chord_with_another_button_cancels_the_stroke(machine):
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    move(machine, dy=120)
    out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1))
    assert kinds(out) == ["cancel"]
    assert machine.state is State.PASSTHRU
    assert machine.mirror.buttons() == [1], "придержанное нажатие уходит приложению"


def test_hold_without_motion_can_be_released_to_the_application():
    machine = StrokeMachine(FakeMirror(), ecodes.BTN_RIGHT, min_stroke_px=40,
                            press_passthrough_ms=1)
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    machine.started_at -= 1.0            # как будто держат уже секунду
    assert kinds(machine.tick()) == ["cancel"]
    assert machine.state is State.PASSTHRU
    assert machine.mirror.buttons() == [1]


def test_motion_is_forwarded_while_drawing(machine):
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    move(machine, dx=30, dy=30)
    moved = [e for e in machine.mirror.events if e[0] == ecodes.EV_REL]
    assert len(moved) == 2, "курсор во время рисования не должен замирать"


def test_monitor_mode_lets_the_button_through(machine):
    machine.monitor_only = True
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    move(machine, dy=120)
    out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0))
    assert kinds(out) == ["finish"]
    assert machine.mirror.buttons() == [1, 0]


# --- отбор устройств ---
def test_event_paths_are_cheap_and_sorted():
    paths = capture.event_paths()
    assert paths == sorted(paths)
    assert all(p.startswith("/dev/input/event") for p in paths)


def test_device_aliases_include_name_and_path():
    dev = types.SimpleNamespace(name="Razer DeathAdder", path="/dev/input/event7")
    links = {"/dev/input/event7": ["/dev/input/by-id/usb-Razer-event-mouse"]}
    aliases = capture.device_aliases(dev, links)
    assert "Razer DeathAdder" in aliases
    assert "/dev/input/event7" in aliases
    assert "/dev/input/by-id/usb-Razer-event-mouse" in aliases


# --- особые жесты: rocker и колесо ---
def test_rocker_fires_only_when_bound(machine):
    """Непривязанный щелчок должен проходить к приложению как обычно."""
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1))
    assert kinds(out) == ["cancel"], "без привязки это обычный аккорд"
    assert machine.mirror.buttons(ecodes.BTN_LEFT) == [1]


def test_rocker_left_fires_and_swallows_the_click(machine):
    machine.bound_events = {"rocker-left"}
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1))
    assert [e.event for e in out] == ["rocker-left"]
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_LEFT, 0))
    assert machine.mirror.buttons(ecodes.BTN_LEFT) == [], \
        "щелчок, ставший жестом, приложению не нужен"


def test_after_rocker_the_trigger_release_is_silent(machine):
    machine.bound_events = {"rocker-left"}
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1))
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_LEFT, 0))
    out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0))
    assert kinds(out) == ["cancel"]
    assert machine.mirror.buttons() == [], "контекстное меню открываться не должно"


def test_rocker_right_when_left_is_held(machine):
    """Обратный rocker: левая уже нажата, щёлкаем правой."""
    machine.bound_events = {"rocker-right"}
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_LEFT, 1))
    out = machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    assert [e.event for e in out] == ["rocker-right"]
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 0))
    assert machine.mirror.buttons() == [], "правая кнопка ушла в жест"


def test_wheel_gesture_swallows_scrolling(machine):
    machine.bound_events = {"wheel-down"}
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    out = machine.handle(event(ecodes.EV_REL, ecodes.REL_WHEEL, -1))
    assert [e.event for e in out] == ["wheel-down"]
    wheel = [e for e in machine.mirror.events if e[1] == ecodes.REL_WHEEL]
    assert wheel == [], "страница прокручиваться не должна"


def test_high_resolution_wheel_is_swallowed_too(machine):
    """Иначе плавная прокрутка сработает в обход жеста."""
    machine.bound_events = {"wheel-down"}
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    machine.handle(event(ecodes.EV_REL, 11, -120))
    assert [e for e in machine.mirror.events if e[1] == 11] == []


def test_wheel_without_binding_scrolls_normally(machine):
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    machine.handle(event(ecodes.EV_REL, ecodes.REL_WHEEL, -1))
    assert [e for e in machine.mirror.events if e[1] == ecodes.REL_WHEEL] == [
        (ecodes.EV_REL, ecodes.REL_WHEEL, -1)]


# --- шпаргалка ---
def test_hint_appears_after_holding_still():
    machine = StrokeMachine(FakeMirror(), ecodes.BTN_RIGHT, min_stroke_px=40,
                            hint_delay_ms=1)
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    machine.started_at -= 1.0
    assert kinds(machine.tick()) == ["hint"]
    assert kinds(machine.tick()) == [], "показываем один раз за удержание"


def test_hint_does_not_appear_while_drawing():
    machine = StrokeMachine(FakeMirror(), ecodes.BTN_RIGHT, min_stroke_px=40,
                            hint_delay_ms=1)
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    move(machine, dx=100)
    machine.started_at -= 1.0
    assert kinds(machine.tick()) == []


def test_passthrough_now_releases_the_button(machine):
    """Так работает список приложений-исключений."""
    machine.handle(event(ecodes.EV_KEY, ecodes.BTN_RIGHT, 1))
    machine.passthrough_now()
    assert machine.state is State.PASSTHRU
    assert machine.mirror.buttons() == [1]
