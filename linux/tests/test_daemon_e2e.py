"""Сквозная проверка демона на виртуальной мыши.

Тест поднимает настоящий ``glyphstroke.daemon`` отдельным процессом, создаёт
через uinput поддельную мышь и шлёт в неё события. Проверяется то, ради чего
всё затевалось: жест выполняет действие и не даёт правому клику дойти до
приложения, а обычный клик доходит.

Нужны права на /dev/uinput и /dev/input — без них тесты пропускаются.
"""

from __future__ import annotations

import os
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")
from evdev import InputDevice, UInput, ecodes  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FAKE_MOUSE = "e2e-test-mouse"
MIRROR = "glyphstroke-virtual-pointer"

pytestmark = pytest.mark.skipif(
    not os.access("/dev/uinput", os.W_OK),
    reason="нужен доступ на запись к /dev/uinput",
)


def wait_for_device(name: str, timeout: float = 5.0,
                    exclude: set[str] | None = None) -> InputDevice:
    """Дождаться устройства с таким именем, пропуская уже известные пути.

    Имена виртуальных устройств одинаковы у всех запусков, поэтому без
    ``exclude`` легко подхватить клавиатуру прошлого демона и ждать от неё
    событий, которых там никогда не будет.
    """
    exclude = exclude or set()
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


@pytest.fixture
def fake_mouse():
    ui = UInput(
        {ecodes.EV_KEY: [ecodes.BTN_LEFT, ecodes.BTN_RIGHT, ecodes.BTN_MIDDLE],
         ecodes.EV_REL: [ecodes.REL_X, ecodes.REL_Y, ecodes.REL_WHEEL]},
        name=FAKE_MOUSE, version=1)
    time.sleep(0.3)
    yield ui
    ui.close()


@pytest.fixture
def workspace(tmp_path):
    """Каталог настроек с одним жестом «уголок вниз-вправо»."""
    marker = tmp_path / "fired"
    gestures = tmp_path / "gestures"
    gestures.mkdir()
    (tmp_path / "settings.yaml").write_text(
        "trigger_button: BTN_RIGHT\n"
        "capture_mode: grab\n"
        "min_stroke_px: 40\n"
        "unrecognized: passthrough\n"
        f"device_include: ['{FAKE_MOUSE}']\n"
        "log_level: debug\n"
        "overlay:\n  enabled: false\n",
        encoding="utf-8")
    rocker_marker = tmp_path / "rocker-fired"
    (gestures / "rocker.yaml").write_text(
        "name: Rocker назад\n"
        "enabled: true\n"
        "event: rocker-left\n"
        "actions:\n"
        f"  - {{type: command, value: 'touch {rocker_marker}'}}\n",
        encoding="utf-8")
    (gestures / "corner.yaml").write_text(
        "name: Уголок\n"
        "enabled: true\n"
        "directions: [D-R]\n"
        "actions:\n"
        f"  - {{type: command, value: 'touch {marker}'}}\n",
        encoding="utf-8")
    return tmp_path, marker


@pytest.fixture
def daemon(workspace, fake_mouse):
    tmp_path, marker = workspace
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
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
    mirror = wait_for_device(MIRROR, exclude=known)
    time.sleep(0.5)  # даём демону дочитать очередь и захватить мышь
    yield proc, mirror, marker, runtime / "glyphstroke" / "overlay.sock"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    mirror.close()


# --- работа с событиями ---
def _read_available(dev: InputDevice, timeout: float) -> list:
    ready, _, _ = select.select([dev.fd], [], [], timeout)
    if not ready:
        return []
    try:
        return list(dev.read())
    except BlockingIOError:
        return []


def drain(dev: InputDevice) -> None:
    while _read_available(dev, 0.02):
        pass


def collect(dev: InputDevice, duration: float = 0.6) -> list:
    events: list = []
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        events.extend(_read_available(dev, 0.05))
    return events


def buttons(events, code=ecodes.BTN_RIGHT) -> list[int]:
    return [e.value for e in events if e.type == ecodes.EV_KEY and e.code == code]


def move(ui: UInput, dx: int, dy: int, steps: int = 12) -> None:
    for _ in range(steps):
        if dx:
            ui.write(ecodes.EV_REL, ecodes.REL_X, dx // steps)
        if dy:
            ui.write(ecodes.EV_REL, ecodes.REL_Y, dy // steps)
        ui.syn()
        time.sleep(0.004)


def press(ui: UInput, value: int, code=ecodes.BTN_RIGHT) -> None:
    ui.write(ecodes.EV_KEY, code, value)
    ui.syn()
    time.sleep(0.02)


# --- сами проверки ---
def test_gesture_runs_action_and_swallows_right_click(daemon, fake_mouse):
    proc, mirror, marker, _ = daemon
    drain(mirror)
    press(fake_mouse, 1)
    move(fake_mouse, 0, 180)   # вниз
    move(fake_mouse, 180, 0)   # вправо
    press(fake_mouse, 0)
    events = collect(mirror, 1.0)

    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "действие жеста не выполнилось"
    assert buttons(events) == [], "правый клик просочился в приложение"


def test_plain_click_reaches_application(daemon, fake_mouse):
    proc, mirror, marker, _ = daemon
    drain(mirror)
    press(fake_mouse, 1)
    press(fake_mouse, 0)
    events = collect(mirror, 0.8)
    assert buttons(events) == [1, 0], "обычный правый клик не дошёл до приложения"
    assert not marker.exists()


def test_unrecognized_stroke_passes_click_through(daemon, fake_mouse):
    proc, mirror, marker, _ = daemon
    drain(mirror)
    press(fake_mouse, 1)
    move(fake_mouse, -180, 0)  # влево — такого жеста в наборе нет
    press(fake_mouse, 0)
    events = collect(mirror, 1.0)
    assert buttons(events) == [1, 0], "нераспознанный росчерк должен вернуть клик"
    assert not marker.exists()


def test_motion_still_reaches_system_while_drawing(daemon, fake_mouse):
    """Курсор во время рисования не должен замирать."""
    proc, mirror, marker, _ = daemon
    drain(mirror)
    press(fake_mouse, 1)
    move(fake_mouse, 0, 180)
    move(fake_mouse, 180, 0)
    press(fake_mouse, 0)
    events = collect(mirror, 1.0)
    moved = sum(1 for e in events if e.type == ecodes.EV_REL)
    assert moved >= 20, f"движение мыши потерялось (дошло событий: {moved})"


def test_click_of_an_unbound_button_during_hold_is_a_chord(daemon, fake_mouse):
    """Кнопка без привязки при удержании — аккорд: правую отдаём приложению.

    Левая тут не годится: в наборе этого теста на неё повешен rocker-жест.
    """
    proc, mirror, marker, _ = daemon
    drain(mirror)
    press(fake_mouse, 1)
    move(fake_mouse, 0, 180)
    press(fake_mouse, 1, ecodes.BTN_MIDDLE)
    press(fake_mouse, 0, ecodes.BTN_MIDDLE)
    press(fake_mouse, 0)
    events = collect(mirror, 0.8)
    assert buttons(events) == [1, 0], "правая кнопка должна дойти до приложения"
    assert buttons(events, ecodes.BTN_MIDDLE) == [1, 0]
    assert not marker.exists(), "аккорд не должен считаться жестом"


# --- стартовый набор жестов ------------------------------------------------
@pytest.fixture
def default_setup(tmp_path, fake_mouse):
    """Демон с тем набором жестов, который ставится по умолчанию."""
    import shutil
    from glyphstroke import config as glyphstroke_config

    (tmp_path / "settings.yaml").write_text(
        f"device_include: ['{FAKE_MOUSE}']\nlog_level: debug\n"
        "overlay:\n  enabled: false\n", encoding="utf-8")
    gestures = tmp_path / "gestures"
    gestures.mkdir()
    for path in (ROOT / "glyphstroke" / "data" / "gestures").glob("*.yaml"):
        shutil.copy(path, gestures / path.name)

    env = dict(os.environ, GLYPHSTROKE_CONFIG_DIR=str(tmp_path),
               # демон при запуске кладёт расширение оболочки в XDG_DATA_HOME —
               # уводим его в каталог теста, чтобы не трогать настоящий дом
               XDG_DATA_HOME=str(tmp_path / "share"),
               PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    known = set(evdev.list_devices())
    proc = subprocess.Popen([sys.executable, "-m", "glyphstroke.daemon"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    wait_for_device(MIRROR, exclude=known)
    keyboard = wait_for_device("glyphstroke-virtual-keyboard", exclude=known)
    time.sleep(0.5)
    yield keyboard
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    keyboard.close()


def test_default_gesture_sends_real_keystrokes(default_setup, fake_mouse):
    """Росчерк влево из набора по умолчанию должен дать alt+Left."""
    keyboard = default_setup
    drain(keyboard)
    press(fake_mouse, 1)
    move(fake_mouse, -240, 0)
    press(fake_mouse, 0)
    events = collect(keyboard, 1.5)
    pressed = [(e.code, e.value) for e in events if e.type == ecodes.EV_KEY]
    assert pressed == [
        (ecodes.KEY_LEFTALT, 1),
        (ecodes.KEY_LEFT, 1),
        (ecodes.KEY_LEFT, 0),
        (ecodes.KEY_LEFTALT, 0),
    ], f"пришло: {pressed}"


# --- канал к рисовальщику следа --------------------------------------------
@pytest.fixture
def daemon_with_trail(tmp_path, fake_mouse):
    """Демон с включённым следом: слушаем его команды как расширение оболочки."""
    import shutil
    import socket as socket_module

    (tmp_path / "settings.yaml").write_text(
        f"device_include: ['{FAKE_MOUSE}']\nlog_level: debug\n"
        "overlay:\n  enabled: true\n  color: '#ff8800'\n  width: 6\n"
        "  opacity: 0.5\n",
        encoding="utf-8")
    gestures = tmp_path / "gestures"
    gestures.mkdir()
    shutil.copy(ROOT / "glyphstroke" / "data" / "gestures" / "nazad.yaml",
                gestures / "nazad.yaml")

    runtime = tmp_path / "runtime"
    runtime.mkdir()
    env = dict(os.environ, GLYPHSTROKE_CONFIG_DIR=str(tmp_path),
               # демон при запуске кладёт расширение оболочки в XDG_DATA_HOME —
               # уводим его в каталог теста, чтобы не трогать настоящий дом
               XDG_DATA_HOME=str(tmp_path / "share"),
               XDG_RUNTIME_DIR=str(runtime), PYTHONPATH=str(ROOT),
               PYTHONUNBUFFERED="1")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    known = set(evdev.list_devices())
    proc = subprocess.Popen([sys.executable, "-m", "glyphstroke.daemon"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    sock_path = runtime / "glyphstroke" / "overlay.sock"
    deadline = time.monotonic() + 5
    while not sock_path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sock_path.exists(), "демон не открыл канал следа"
    client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    client.connect(str(sock_path))
    time.sleep(0.5)
    yield client, known
    try:
        client.close()
    except OSError:
        pass
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def trail_lines(client, duration: float = 1.0) -> list[str]:
    """Только команды следа: приветствие, разбор и подсказки тут не нужны."""
    return [l for l in read_lines(client, duration)
            if l in ("begin", "end") or l.startswith("begin ")]


def read_lines(client, duration: float = 1.0) -> list[str]:
    lines: list[str] = []
    buffer = b""
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        ready, _, _ = select.select([client], [], [], 0.05)
        if not ready:
            continue
        chunk = client.recv(256)
        if not chunk:
            break
        buffer += chunk
        while b"\n" in buffer:
            line, _, buffer = buffer.partition(b"\n")
            lines.append(line.decode().strip())
    return lines


def test_trail_starts_at_the_press_and_ends_at_the_release(daemon_with_trail, fake_mouse):
    client, _ = daemon_with_trail
    trail_lines(client, 0.3)          # пропускаем приветствие
    press(fake_mouse, 1)
    time.sleep(0.2)
    started = trail_lines(client, 0.4)
    assert started == ["begin #ff8800 6 0.50"], \
        f"след должен начинаться сразу по нажатию, пришло: {started}"

    move(fake_mouse, -240, 0)
    press(fake_mouse, 0)
    assert "end" in trail_lines(client, 1.0)


def test_plain_click_closes_the_trail_too(daemon_with_trail, fake_mouse):
    """Иначе рисовальщик остался бы опрашивать курсор навсегда."""
    client, _ = daemon_with_trail
    trail_lines(client, 0.3)          # пропускаем приветствие
    press(fake_mouse, 1)
    press(fake_mouse, 0)
    lines = trail_lines(client, 1.0)
    assert lines[0].startswith("begin") and lines[-1] == "end"


def test_channel_reports_what_was_recognized(daemon_with_trail, fake_mouse):
    """«glyphstroke watch» читает именно эти строки."""
    client, _ = daemon_with_trail
    press(fake_mouse, 1)
    move(fake_mouse, -240, 0)
    press(fake_mouse, 0)
    lines = read_lines(client, 1.5)
    reports = [l for l in lines if l.startswith("stroke\t")]
    assert reports, f"демон не объявил результат разбора: {lines}"
    fields = reports[0].split("\t")
    assert fields[1] == "L", f"код направлений вышел неожиданным: {fields}"
    assert fields[2] == "Назад"


def test_channel_reports_an_unrecognized_stroke(daemon_with_trail, fake_mouse):
    client, _ = daemon_with_trail
    press(fake_mouse, 1)
    move(fake_mouse, 200, 200)          # ровная диагональ — такого жеста нет
    press(fake_mouse, 0)
    reports = [l for l in read_lines(client, 1.5) if l.startswith("stroke\t")]
    assert reports
    fields = reports[0].split("\t")
    assert fields[2] == "-", f"диагональ не должна ни во что попадать: {fields}"


def test_channel_greets_with_the_daemon_version(daemon_with_trail):
    """По этой строке видно, что работает свежий демон, а не старый из /opt."""
    from glyphstroke.version import __version__
    client, _ = daemon_with_trail
    # приветствие приходит первым, до всяких росчерков
    greeting = read_lines(client, 0.3)
    assert greeting and greeting[0].startswith("hello\t"), f"пришло: {greeting}"
    assert greeting[0].split("\t")[1] == __version__


def test_channel_carries_the_stroke_itself(daemon_with_trail, fake_mouse):
    client, _ = daemon_with_trail
    read_lines(client, 0.2)
    press(fake_mouse, 1)
    move(fake_mouse, -240, 0)
    press(fake_mouse, 0)
    points = [l for l in read_lines(client, 1.5) if l.startswith("points\t")]
    assert points, "росчерк должен приходить в канал целиком"
    coordinates = points[0].split("\t")[1].split()
    assert len(coordinates) == 64, "росчерк приводится к 64 точкам"


def test_channel_reports_the_executed_action(daemon_with_trail, fake_mouse):
    client, _ = daemon_with_trail
    read_lines(client, 0.2)
    press(fake_mouse, 1)
    move(fake_mouse, -240, 0)
    press(fake_mouse, 0)
    actions = [l for l in read_lines(client, 1.5) if l.startswith("action\t")]
    assert actions, "демон должен сообщать, что именно выполнил"
    fields = actions[0].split("\t")
    assert fields[1] == "Назад"
    assert fields[2] == "keys alt+Left"


def test_keys_are_handed_to_the_shell_when_it_is_connected(daemon_with_trail, fake_mouse):
    """Раскладка не должна решать, дойдёт ли ctrl+c: пусть шлёт оболочка."""
    client, known = daemon_with_trail
    keyboard = wait_for_device("glyphstroke-virtual-keyboard", exclude=known)
    try:
        client.sendall(b"iam shell keys\n")
        time.sleep(0.5)
        drain(keyboard)
        read_lines(client, 0.2)

        press(fake_mouse, 1)
        move(fake_mouse, -240, 0)
        press(fake_mouse, 0)

        lines = read_lines(client, 1.5)
        assert "dokeys\talt+Left" in lines, f"сочетание не ушло в оболочку: {lines}"
        assert not [e for e in collect(keyboard, 0.4) if e.type == ecodes.EV_KEY], \
            "клавиши не должны дублироваться через uinput"
        action = [l for l in lines if l.startswith("action\t")]
        assert action and action[0].split("\t")[4] == "shell"
    finally:
        keyboard.close()


def test_keys_return_to_uinput_when_the_shell_goes_away(daemon_with_trail, fake_mouse):
    client, known = daemon_with_trail
    keyboard = wait_for_device("glyphstroke-virtual-keyboard", exclude=known)
    try:
        client.sendall(b"iam shell keys\n")
        time.sleep(0.4)
        client.close()                     # расширение выключили
        time.sleep(0.6)
        drain(keyboard)
        press(fake_mouse, 1)
        move(fake_mouse, -240, 0)
        press(fake_mouse, 0)
        pressed = [(e.code, e.value) for e in collect(keyboard, 1.5)
                   if e.type == ecodes.EV_KEY]
        assert (ecodes.KEY_LEFT, 1) in pressed, \
            f"без оболочки клавиши обязаны идти через uinput: {pressed}"
    finally:
        keyboard.close()


# --- пауза перехвата ---
def send_to_daemon(sock_path, command: str) -> str | None:
    """Послать демону команду и дождаться нового состояния."""
    import socket as socket_module

    client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    client.settimeout(2)
    try:
        client.connect(str(sock_path))
        client.recv(256)
        client.sendall((command + "\n").encode())
        buffer = ""
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            buffer += client.recv(256).decode("utf-8", "replace")
            for line in buffer.splitlines():
                if line.startswith("state\t"):
                    return line.split("\t")[1]
        return None
    finally:
        client.close()


def test_pause_lets_the_right_button_through_untouched(daemon, fake_mouse):
    """На паузе мышь отпущена: события идут мимо нас прямо в систему."""
    proc, mirror, marker, sock = daemon
    deadline = time.monotonic() + 5
    while not sock.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sock.exists(), "канал управления не открылся"

    assert send_to_daemon(sock, "pause") == "paused"
    drain(mirror)
    press(fake_mouse, 1)
    move(fake_mouse, 0, 180)
    move(fake_mouse, 180, 0)
    press(fake_mouse, 0)
    assert collect(mirror, 0.8) == [], "на паузе мы не должны ничего пересылать"
    assert not marker.exists(), "жест на паузе выполняться не должен"


def test_capture_returns_after_resume(daemon, fake_mouse):
    proc, mirror, marker, sock = daemon
    deadline = time.monotonic() + 5
    while not sock.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert send_to_daemon(sock, "pause") == "paused"
    assert send_to_daemon(sock, "resume") == "active"
    time.sleep(0.3)

    press(fake_mouse, 1)
    move(fake_mouse, 0, 180)
    move(fake_mouse, 180, 0)
    press(fake_mouse, 0)
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "после возврата жест обязан работать"


# --- особые жесты через настоящий демон ---
def test_rocker_runs_its_action_and_eats_both_clicks(daemon, fake_mouse):
    proc, mirror, marker, sock = daemon
    rocker_marker = marker.parent / "rocker-fired"
    drain(mirror)

    press(fake_mouse, 1)                                   # держим правую
    press(fake_mouse, 1, ecodes.BTN_LEFT)                  # щёлкаем левой
    press(fake_mouse, 0, ecodes.BTN_LEFT)
    press(fake_mouse, 0)

    deadline = time.monotonic() + 3
    while not rocker_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert rocker_marker.exists(), "действие rocker-жеста не выполнилось"

    events = collect(mirror, 0.5)
    assert buttons(events) == [], "правая кнопка не должна дойти до приложения"
    assert buttons(events, ecodes.BTN_LEFT) == [], "левая — тоже"
    assert not marker.exists(), "росчерк тут ни при чём"


def test_ordinary_gesture_still_works_next_to_rocker(daemon, fake_mouse):
    proc, mirror, marker, sock = daemon
    drain(mirror)
    press(fake_mouse, 1)
    move(fake_mouse, 0, 180)
    move(fake_mouse, 180, 0)
    press(fake_mouse, 0)
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists()


# --- меню под жестом --------------------------------------------------------
@pytest.fixture
def menu_workspace(tmp_path):
    """Жест «Правка»: своё действие плюс два пункта меню."""
    plain = tmp_path / "plain"
    first = tmp_path / "first"
    second = tmp_path / "second"
    (tmp_path / "settings.yaml").write_text(
        f"device_include: ['{FAKE_MOUSE}']\n"
        "log_level: debug\n"
        "menu_step_px: 36\n"
        "menu_timeout_ms: 5000\n"
        "overlay:\n  enabled: false\n",
        encoding="utf-8")
    gestures = tmp_path / "gestures"
    gestures.mkdir()
    (gestures / "pravka.yaml").write_text(
        "name: Правка\n"
        "enabled: true\n"
        "directions: [D]\n"
        "actions:\n"
        f"  - {{type: command, value: 'touch {plain}'}}\n"
        "menu:\n"
        "  - name: Первый\n"
        "    actions:\n"
        f"      - {{type: command, value: 'touch {first}'}}\n"
        "  - name: Второй\n"
        "    actions:\n"
        f"      - {{type: command, value: 'touch {second}'}}\n",
        encoding="utf-8")
    return tmp_path, plain, first, second


@pytest.fixture
def menu_daemon(menu_workspace, fake_mouse):
    """Демон и клиент канала: он же изображает того, кто рисует меню."""
    import socket as socket_module

    tmp_path = menu_workspace[0]
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    env = dict(os.environ, GLYPHSTROKE_CONFIG_DIR=str(tmp_path),
               # демон при запуске кладёт расширение оболочки в XDG_DATA_HOME —
               # уводим его в каталог теста, чтобы не трогать настоящий дом
               XDG_DATA_HOME=str(tmp_path / "share"),
               XDG_RUNTIME_DIR=str(runtime), PYTHONPATH=str(ROOT),
               PYTHONUNBUFFERED="1")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)
    opened: dict = {}

    def start(iam: str = "iam shell menu"):
        known = set(evdev.list_devices())
        proc = subprocess.Popen([sys.executable, "-m", "glyphstroke.daemon"], env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True)
        opened["proc"] = proc
        opened["mirror"] = wait_for_device(MIRROR, exclude=known)
        sock_path = runtime / "glyphstroke" / "overlay.sock"
        deadline = time.monotonic() + 5
        while not sock_path.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sock_path.exists(), "демон не открыл канал"
        client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
        client.connect(str(sock_path))
        opened["client"] = client
        client.sendall((iam + "\n").encode("utf-8"))
        time.sleep(0.6)      # даём демону захватить мышь и запомнить умения
        return client, opened["mirror"]

    yield start

    if "client" in opened:
        try:
            opened["client"].close()
        except OSError:
            pass
    if "proc" in opened:
        opened["proc"].terminate()
        try:
            opened["proc"].wait(timeout=5)
        except subprocess.TimeoutExpired:
            opened["proc"].kill()
    if "mirror" in opened:
        opened["mirror"].close()


def draw_down(ui: UInput) -> None:
    """Росчерк вниз — им открывается меню жеста «Правка»."""
    press(ui, 1)
    move(ui, 0, 180)
    press(ui, 0)
    time.sleep(0.4)          # разбор и запуск меню идут отдельным потоком


def wait_for_file(path, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return True
        time.sleep(0.05)
    return False


def test_the_menu_opens_and_runs_the_item_it_shows(menu_daemon, menu_workspace,
                                                   fake_mouse):
    _tmp, plain, first, second = menu_workspace
    client, _mirror = menu_daemon()
    draw_down(fake_mouse)
    opened = [l for l in read_lines(client, 1.0) if l.startswith("menu\t")]
    assert opened == ["menu\tПравка\tПервый\tВторой"], f"пришло: {opened}"
    assert wait_for_file(plain), "своё действие жеста должно выполниться"

    move(fake_mouse, 0, 36)          # один шаг вниз — первый пункт
    assert "menu-select\t0" in read_lines(client, 0.8)
    press(fake_mouse, 1, ecodes.BTN_LEFT)
    press(fake_mouse, 0, ecodes.BTN_LEFT)
    lines = read_lines(client, 1.0)
    assert "menu-choice\tПравка\tПервый" in lines
    assert "menu-hide" in lines
    assert wait_for_file(first), "действие выбранного пункта не выполнилось"
    assert not second.exists(), "выполнился не тот пункт"


def test_the_mouse_stands_still_while_the_menu_is_open(menu_daemon, fake_mouse):
    """Курсор замирает: иначе он уехал бы, а меню осталось на месте."""
    client, mirror = menu_daemon()
    draw_down(fake_mouse)
    read_lines(client, 0.8)
    drain(mirror)
    move(fake_mouse, 0, 72)
    events = collect(mirror, 0.5)
    assert [e for e in events if e.type == ecodes.EV_REL] == [], \
        "движение мыши дошло до системы, хотя меню открыто"


def test_the_right_button_closes_the_menu_and_runs_nothing(menu_daemon,
                                                           menu_workspace, fake_mouse):
    _tmp, _plain, first, second = menu_workspace
    client, mirror = menu_daemon()
    draw_down(fake_mouse)
    read_lines(client, 0.8)
    move(fake_mouse, 0, 36)
    drain(mirror)
    press(fake_mouse, 1)
    press(fake_mouse, 0)
    assert "menu-choice\tПравка\t-" in read_lines(client, 1.0)
    assert buttons(collect(mirror, 0.4)) == [], \
        "щелчок закрытия меню не должен уходить в приложение"
    assert not first.exists() and not second.exists()


def test_without_anyone_to_draw_it_the_gesture_just_acts(menu_daemon, menu_workspace,
                                                         fake_mouse):
    """Невидимое меню не открывается — мышь осталась бы захваченной впустую."""
    _tmp, plain, first, second = menu_workspace
    client, mirror = menu_daemon("iam watcher")
    draw_down(fake_mouse)
    lines = read_lines(client, 1.0)
    assert not [l for l in lines if l.startswith("menu\t")], f"пришло: {lines}"
    assert wait_for_file(plain), "жест должен выполнить свои действия как обычно"

    drain(mirror)
    move(fake_mouse, 0, 72)
    assert [e for e in collect(mirror, 0.4) if e.type == ecodes.EV_REL], \
        "мышь должна работать как обычно"
    assert not first.exists() and not second.exists()
