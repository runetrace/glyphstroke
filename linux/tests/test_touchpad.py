"""Рисование пальцем по тачпаду, пока зажата назначенная клавиша."""

from __future__ import annotations

import types

import pytest

pytest.importorskip("evdev")
from evdev import AbsInfo, ecodes  # noqa: E402

from glyphstroke import capture  # noqa: E402
from glyphstroke.capture import TouchpadMachine  # noqa: E402
from glyphstroke.config import Action, MenuItem, Settings  # noqa: E402
from glyphstroke.menu import MenuSession  # noqa: E402
from glyphstroke.recognizer import direction_code  # noqa: E402


def ev(etype, code, value):
    return types.SimpleNamespace(type=etype, code=code, value=value)


def touch(value):
    return ev(ecodes.EV_KEY, ecodes.BTN_TOUCH, value)


def syn():
    return ev(ecodes.EV_SYN, ecodes.SYN_REPORT, 0)


def position(x, y):
    return [ev(ecodes.EV_ABS, ecodes.ABS_X, x), ev(ecodes.EV_ABS, ecodes.ABS_Y, y), syn()]


def kinds(events):
    return [event.kind for event in events]


#: «уголок вниз-вправо» в единицах тачпада с разрешением 40 на миллиметр
CORNER = [(1000, 500 + i * 50) for i in range(20)] + \
         [(1000 + i * 75, 1450) for i in range(20)]


def feed(machine, events):
    out = []
    for event in events:
        out += machine.handle(event)
    return out


def stroke_events(points, lift=True):
    events = [touch(1)]
    for x, y in points:
        events += position(x, y)
    if lift:
        events += [touch(0), syn()]
    return events


@pytest.fixture
def machine():
    return TouchpadMachine(min_stroke=200, units_per_mm=40)   # 5 мм


# --- автомат росчерка --------------------------------------------------------
def test_stroke_with_the_key_held(machine):
    machine.set_key(True)
    events = feed(machine, stroke_events(CORNER))
    assert kinds(events) == ["begin", "finish"]
    points = events[-1].points
    assert points[0] == (1000.0, 500.0) and points[-1] == (2425.0, 1450.0)
    assert direction_code(points) == "D-R"


def test_without_the_key_the_finger_only_moves_the_cursor(machine):
    assert feed(machine, stroke_events(CORNER)) == []


def test_a_short_touch_is_not_a_stroke(machine):
    machine.set_key(True)
    events = feed(machine, stroke_events([(1000, 1000), (1010, 1005), (1020, 1000)]))
    assert kinds(events) == ["begin", "cancel"]


def test_releasing_the_key_ends_the_stroke(machine):
    machine.set_key(True)
    events = feed(machine, stroke_events(CORNER, lift=False))
    events += machine.set_key(False)
    assert kinds(events) == ["begin", "finish"]
    assert feed(machine, [touch(0), syn()]) == [], "отрыв пальца потом ничего не добавляет"


def test_pressing_the_key_with_the_finger_already_down(machine):
    feed(machine, [touch(1)] + position(1000, 500))
    events = machine.set_key(True)
    for x, y in CORNER[1:]:
        events += feed(machine, position(x, y))
    events += feed(machine, [touch(0)])
    assert kinds(events) == ["begin", "finish"]
    assert events[-1].points[0] == (1000.0, 500.0)


def test_a_second_finger_cancels_the_stroke(machine):
    machine.set_key(True)
    events = feed(machine, stroke_events(CORNER[:10], lift=False))
    events += machine.handle(ev(ecodes.EV_KEY, ecodes.BTN_TOOL_DOUBLETAP, 1))
    for x, y in CORNER[10:]:
        events += feed(machine, position(x, y))
    events += feed(machine, [touch(0), syn()])
    assert kinds(events) == ["begin", "cancel"]


def test_the_next_touch_after_a_cancel_draws_again(machine):
    machine.set_key(True)
    feed(machine, [touch(1), ev(ecodes.EV_KEY, ecodes.BTN_TOOL_DOUBLETAP, 1), touch(0)])
    assert kinds(feed(machine, stroke_events(CORNER))) == ["begin", "finish"]


def test_each_touch_while_holding_is_its_own_gesture(machine):
    machine.set_key(True)
    assert kinds(feed(machine, stroke_events(CORNER))) == ["begin", "finish"]
    assert kinds(feed(machine, stroke_events(CORNER))) == ["begin", "finish"]


def test_an_excluded_application_abandons_the_stroke(machine):
    machine.set_key(True)
    events = machine.handle(touch(1))
    machine.passthrough_now()
    for x, y in CORNER:
        events += feed(machine, position(x, y))
    events += feed(machine, [touch(0), syn()])
    assert kinds(events) == ["begin"]


def test_the_touchpad_holds_back_no_clicks():
    assert TouchpadMachine.monitor_only, "демон не должен досылать щелчок за тачпад"


# --- устройство и клавиша ----------------------------------------------------
class FakeDevice:
    def __init__(self, resolution, maximum=4000):
        self.info = AbsInfo(value=0, min=0, max=maximum, fuzz=0, flat=0,
                            resolution=resolution)

    def absinfo(self, axis):
        return self.info


def test_threshold_follows_the_touchpad_resolution():
    assert capture.units_per_mm(FakeDevice(40)) == 40
    assert capture.units_per_mm(FakeDevice(0, maximum=3000)) == 30, \
        "без разрешения тачпад считается шириной в десять сантиметров"
    machine = TouchpadMachine.for_device(FakeDevice(40))
    assert machine.min_stroke == pytest.approx(capture.TOUCH_MIN_STROKE_MM * 40)
    assert machine.units_per_mm == 40


def test_key_names():
    assert capture.key_code("KEY_LEFTMETA") == ecodes.KEY_LEFTMETA
    assert capture.key_code("leftmeta") == ecodes.KEY_LEFTMETA
    assert capture.key_code("") is None
    assert capture.key_code("KEY_NO_SUCH_KEY") is None
    assert capture.key_name(ecodes.KEY_LEFTMETA) == "KEY_LEFTMETA"
    assert capture.key_name(113) == "KEY_MUTE", "из нескольких имён берётся внятное"
    assert capture.key_name(0) is None
    assert capture.key_label("KEY_LEFTMETA") == "Super"
    assert capture.key_label("KEY_F13") == "F13"


def test_super_is_the_default_key():
    assert Settings().touchpad_key == "KEY_LEFTMETA"


# --- меню пальцем ------------------------------------------------------------
def menu():
    return MenuSession("Жест", [MenuItem("Первый"), MenuItem("Второй"),
                                MenuItem("Третий")], step_px=36)


def slide(session, start, end, step=10, units=40):
    outcomes = [session.handle_touch(touch(1), units)]
    for y in range(start, end + 1, step):
        outcomes.append(session.handle_touch(ev(ecodes.EV_ABS, ecodes.ABS_Y, y), units))
    return outcomes


def test_the_finger_moves_the_highlight_and_lifting_it_chooses():
    session = menu()
    # 12 мм вниз — это 72 точки пути: полшага мёртвой зоны и полтора пункта
    slide(session, 1000, 1480)
    assert session.index == 1
    assert session.handle_touch(touch(0), 40) == "choose"
    assert session.chosen.name == "Второй"


def test_lifting_without_a_highlight_keeps_the_menu_open():
    session = menu()
    session.handle_touch(touch(1), 40)
    assert session.handle_touch(touch(0), 40) is None
    assert not session.finished


def test_the_first_position_of_a_touch_is_only_a_baseline():
    session = menu()
    assert session.handle_touch(ev(ecodes.EV_ABS, ecodes.ABS_Y, 3000), 40) is None
    assert session.dy == 0 and session.index == -1


# --- демон -------------------------------------------------------------------
class FakeChannel:
    def __init__(self):
        self.sent: list[str] = []

    def has(self, capability):
        return False

    def broadcast(self, line):
        self.sent.append(line)
        return 1


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("DISPLAY", raising=False)
    from glyphstroke.daemon import Daemon
    daemon = Daemon(Settings())
    daemon.overlay_server = FakeChannel()
    daemon.touch_key = ecodes.KEY_LEFTMETA
    return daemon


def attach(daemon):
    machine = TouchpadMachine(min_stroke=200, units_per_mm=40)
    daemon.touch_machines = {7: machine}
    return machine


def key(daemon, value, code=ecodes.KEY_LEFTMETA, fd=3):
    daemon.handle_key_event(fd, ev(ecodes.EV_KEY, code, value))


def draw(daemon, machine, points=CORNER):
    for event in stroke_events(points):
        daemon.handle_touch_event(machine, event)


def test_key_and_finger_give_the_worker_a_stroke(daemon):
    machine = attach(daemon)
    key(daemon, 1)
    draw(daemon, machine)
    key(daemon, 0)
    worker_machine, points = daemon._work.get_nowait()
    assert worker_machine is machine and direction_code(points) == "D-R"
    sent = daemon.overlay_server.sent
    assert sent[0].startswith("begin ")
    assert "end" in sent
    assert sent.index("overlay-key-hold") < sent.index("overlay-key-free")


def test_other_keys_are_ignored(daemon):
    machine = attach(daemon)
    key(daemon, 1, code=ecodes.KEY_A)
    draw(daemon, machine)
    assert not machine.key_held
    assert daemon._work.empty() and daemon.overlay_server.sent == []


def test_holding_alt_leaves_the_overview_alone(daemon):
    machine = attach(daemon)
    daemon.touch_key = ecodes.KEY_LEFTALT
    key(daemon, 1, code=ecodes.KEY_LEFTALT)
    draw(daemon, machine)
    key(daemon, 0, code=ecodes.KEY_LEFTALT)
    assert not daemon._work.empty()
    assert not any(line.startswith("overlay-key") for line in daemon.overlay_server.sent)


def test_the_key_counts_as_held_while_any_keyboard_holds_it(daemon):
    machine = attach(daemon)
    key(daemon, 1, fd=3)
    key(daemon, 1, fd=4)
    key(daemon, 0, fd=3)
    assert machine.key_held
    key(daemon, 0, fd=4)
    assert not machine.key_held


def test_a_paused_daemon_draws_nothing_but_remembers_the_key(daemon):
    machine = attach(daemon)
    daemon.paused = True
    key(daemon, 1)
    draw(daemon, machine)
    assert daemon._work.empty()
    assert machine.key_held, "после паузы клавиша должна считаться зажатой"


def test_the_menu_is_driven_by_the_finger(daemon):
    machine = attach(daemon)
    session = MenuSession("Жест", [MenuItem("Первый", [Action("none")]),
                                   MenuItem("Второй", [Action("none")])], step_px=36)
    daemon.menu = session
    daemon.handle_touch_event(machine, touch(1))
    for y in range(1000, 1481, 10):
        daemon.handle_touch_event(machine, ev(ecodes.EV_ABS, ecodes.ABS_Y, y))
    daemon.handle_touch_event(machine, touch(0))
    assert daemon.menu is None
    _machine, choice = daemon._work.get_nowait()
    assert choice.item.name == "Второй"
    assert not machine.touching, "за пальцем следим и при открытом меню"
