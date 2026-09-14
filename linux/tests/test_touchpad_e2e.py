"""Сквозная проверка рисования на тачпаде: виртуальные тачпад и клавиатура.

Демон запускается без единой мыши — так выглядит ноутбук, где жесты рисуют
пальцем. Нужны права на /dev/uinput и /dev/input — без них тесты пропускаются.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")
from evdev import AbsInfo, InputDevice, UInput, ecodes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FAKE_PAD = "e2e-test-touchpad"
FAKE_KEYBOARD = "e2e-test-keyboard"
MIRROR = "glyphstroke-virtual-pointer"

pytestmark = pytest.mark.skipif(
    not os.access("/dev/uinput", os.W_OK),
    reason="нужен доступ на запись к /dev/uinput",
)


def wait_for_device(name: str, exclude: set[str], timeout: float = 5.0) -> InputDevice:
    """Устройство с таким именем среди появившихся после запуска демона."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for path in evdev.list_devices():
            if path in exclude:
                continue
            try:
                dev = InputDevice(path)
            except OSError:
                continue
            if dev.name == name:
                return dev
            dev.close()
        time.sleep(0.05)
    raise AssertionError(f"устройство {name} не появилось за {timeout} с")


def wait_for_file(path: Path, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


@pytest.fixture
def fake_touchpad():
    axis_x = AbsInfo(value=0, min=0, max=4000, fuzz=0, flat=0, resolution=40)
    axis_y = AbsInfo(value=0, min=0, max=2500, fuzz=0, flat=0, resolution=40)
    ui = UInput({
        ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_TOUCH, ecodes.BTN_TOOL_FINGER,
                        ecodes.BTN_TOOL_DOUBLETAP],
        ecodes.EV_ABS: [(ecodes.ABS_X, axis_x), (ecodes.ABS_Y, axis_y),
                        (ecodes.ABS_MT_POSITION_X, axis_x),
                        (ecodes.ABS_MT_POSITION_Y, axis_y)],
    }, name=FAKE_PAD, version=1)
    time.sleep(0.3)
    yield ui
    ui.close()


@pytest.fixture
def fake_keyboard():
    ui = UInput({ecodes.EV_KEY: [ecodes.KEY_LEFTMETA, ecodes.KEY_A]},
                name=FAKE_KEYBOARD, version=1)
    time.sleep(0.3)
    yield ui
    ui.close()


@pytest.fixture
def daemon(tmp_path, fake_touchpad, fake_keyboard):
    marker = tmp_path / "fired"
    gestures = tmp_path / "gestures"
    gestures.mkdir()
    (tmp_path / "settings.yaml").write_text(
        "trigger_button: BTN_RIGHT\n"
        "capture_mode: grab\n"
        # мышей нет вовсе: демону должно хватить тачпада с клавишей
        "device_include: ['no-such-mouse-in-this-test']\n"
        "touchpad_key: KEY_LEFTMETA\n"
        "unrecognized: passthrough\n"
        "log_level: debug\n"
        "overlay:\n  enabled: false\n",
        encoding="utf-8")
    (gestures / "corner.yaml").write_text(
        "name: Уголок\n"
        "enabled: true\n"
        "directions: [D-R]\n"
        "actions:\n"
        f"  - {{type: command, value: 'touch {marker}'}}\n",
        encoding="utf-8")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    env = dict(os.environ, GLYPHSTROKE_CONFIG_DIR=str(tmp_path),
               # демон при запуске кладёт расширение оболочки в XDG_DATA_HOME —
               # уводим его в каталог теста, чтобы не трогать настоящий дом
               XDG_DATA_HOME=str(tmp_path / "share"),
               XDG_RUNTIME_DIR=str(runtime),
               PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    known = set(evdev.list_devices())
    proc = subprocess.Popen([sys.executable, "-m", "glyphstroke.daemon"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        mirror = wait_for_device(MIRROR, exclude=known)
    except AssertionError:
        proc.kill()
        output = proc.communicate(timeout=5)[0]
        raise AssertionError(f"демон не поднялся без мыши:\n{output}")
    time.sleep(0.6)  # даём демону открыть тачпад и клавиатуру
    yield proc, marker, runtime / "glyphstroke" / "overlay.sock"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    mirror.close()


def press_super(keyboard: UInput, value: int) -> None:
    keyboard.write(ecodes.EV_KEY, ecodes.KEY_LEFTMETA, value)
    keyboard.syn()
    time.sleep(0.05)


def draw_corner(pad: UInput) -> None:
    """Палец вниз, потом вправо, и отрыв — в единицах тачпада 40 на миллиметр."""
    points = [(1000, 500 + i * 50) for i in range(20)] + \
             [(1000 + i * 75, 1450) for i in range(20)]
    pad.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1)
    pad.write(ecodes.EV_KEY, ecodes.BTN_TOOL_FINGER, 1)
    for x, y in points:
        pad.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        pad.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
        pad.syn()
        time.sleep(0.004)
    pad.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 0)
    pad.write(ecodes.EV_KEY, ecodes.BTN_TOOL_FINGER, 0)
    pad.syn()


def test_touchpad_stroke_with_super_runs_the_action(daemon, fake_touchpad, fake_keyboard):
    _proc, marker, _sock = daemon
    press_super(fake_keyboard, 1)
    draw_corner(fake_touchpad)
    press_super(fake_keyboard, 0)
    assert wait_for_file(marker), "росчерк пальцем при зажатом Super должен сработать"


def test_touchpad_stroke_without_the_key_does_nothing(daemon, fake_touchpad):
    _proc, marker, _sock = daemon
    draw_corner(fake_touchpad)
    time.sleep(1.0)
    assert not marker.exists(), "без клавиши палец просто водит курсор"


def test_the_shell_hears_that_super_is_busy(daemon, fake_touchpad, fake_keyboard):
    _proc, marker, sock_path = daemon
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(sock_path))
    client.settimeout(0.1)
    try:
        press_super(fake_keyboard, 1)
        draw_corner(fake_touchpad)
        press_super(fake_keyboard, 0)
        buffer = b""
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and b"overlay-key-free" not in buffer:
            try:
                buffer += client.recv(4096)
            except socket.timeout:
                continue
    finally:
        client.close()
    lines = buffer.decode("utf-8", "replace").splitlines()
    assert "overlay-key-hold" in lines and "overlay-key-free" in lines
    assert lines.index("overlay-key-hold") < lines.index("overlay-key-free")
    assert wait_for_file(marker)
