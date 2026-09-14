"""Поведение цикла демона: горячее подключение, след, привязка к мыши."""

from __future__ import annotations

import types

import pytest

pytest.importorskip("evdev")

from glyphstroke import capture, cli  # noqa: E402
from glyphstroke.config import Settings  # noqa: E402
from glyphstroke.daemon import Daemon  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def daemon():
    return Daemon(Settings())


def test_rescan_does_not_open_devices_when_nothing_changed(daemon, monkeypatch):
    """Раньше полный обход /dev/input каждые две секунды дёргал курсор."""
    opened = []
    monkeypatch.setattr(capture, "event_paths",
                        lambda: ["/dev/input/event0", "/dev/input/event1"])
    monkeypatch.setattr(capture, "find_pointers",
                        lambda **kw: opened.append(kw) or [])
    daemon._known_paths = {"/dev/input/event0", "/dev/input/event1"}
    daemon.rescan_devices()
    daemon.rescan_devices()
    assert opened == [], "устройства открывались, хотя ничего не появилось"


def test_rescan_opens_only_the_new_path(daemon, monkeypatch):
    seen = {}
    monkeypatch.setattr(capture, "event_paths",
                        lambda: ["/dev/input/event0", "/dev/input/event9"])
    monkeypatch.setattr(capture, "find_pointers",
                        lambda **kw: seen.update(kw) or [])
    daemon._known_paths = {"/dev/input/event0"}
    daemon.rescan_devices()
    assert seen["paths"] == ["/dev/input/event9"]


def test_overlay_is_skipped_in_a_wayland_session(daemon, monkeypatch):
    """В Wayland окно подцепилось бы к Xwayland и рисовало чушь."""
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: pytest.fail("след не должен запускаться"))
    daemon.settings.overlay.enabled = True
    daemon.start_overlay()
    assert daemon.overlay is None


def test_overlay_is_skipped_without_a_display(daemon, monkeypatch):
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setenv("XDG_SESSION_TYPE", "tty")
    monkeypatch.setattr("subprocess.Popen",
                        lambda *a, **k: pytest.fail("след не должен запускаться"))
    daemon.settings.overlay.enabled = True
    daemon.start_overlay()
    assert daemon.overlay is None


# --- привязка к одной мыши ---
def fake_device(name, path, links=()):
    dev = types.SimpleNamespace(name=name, path=path, close=lambda: None)
    return dev, {path: list(links)}


def test_name_pattern_matches_only_that_device():
    import re
    pattern = cli.name_pattern("Razer Razer DeathAdder Essential")
    assert re.search(pattern, "Razer Razer DeathAdder Essential")
    assert not re.search(pattern, "Razer Razer DeathAdder Essential 2")


def test_name_pattern_survives_special_characters():
    import re
    tricky = "Logitech USB Receiver (2.4+) [mouse]"
    assert re.search(cli.name_pattern(tricky), tricky)


def test_stable_id_prefers_by_id(monkeypatch):
    dev, links = fake_device("Мышь", "/dev/input/event5",
                             ["/dev/input/by-path/pci-0000-usb-event-mouse",
                              "/dev/input/by-id/usb-Razer-event-mouse"])
    monkeypatch.setattr(capture, "stable_link_map", lambda: links)
    assert cli.stable_id(dev) == "/dev/input/by-id/usb-Razer-event-mouse"


def test_stable_id_falls_back_to_by_path(monkeypatch):
    dev, links = fake_device("Мышь", "/dev/input/event5",
                             ["/dev/input/by-path/platform-i8042-event-mouse"])
    monkeypatch.setattr(capture, "stable_link_map", lambda: links)
    assert cli.stable_id(dev) == "/dev/input/by-path/platform-i8042-event-mouse"


def test_stable_id_falls_back_to_the_name(monkeypatch):
    dev, links = fake_device("VirtualPS/2 VMware VMMouse", "/dev/input/event5")
    monkeypatch.setattr(capture, "stable_link_map", lambda: links)
    assert cli.stable_id(dev) == "VirtualPS/2 VMware VMMouse"


def test_bind_writes_the_single_mouse_into_settings(monkeypatch, tmp_path):
    dev, links = fake_device("Razer DeathAdder", "/dev/input/event5",
                             ["/dev/input/by-id/usb-Razer-event-mouse"])
    monkeypatch.setattr(capture, "stable_link_map", lambda: links)
    monkeypatch.setattr(capture, "find_pointers", lambda *a, **k: [dev])
    monkeypatch.setattr(cli, "_restart_daemon", lambda: None)
    assert cli.main(["bind"]) == 0
    assert Settings.load().device_include == [
        cli.name_pattern("/dev/input/by-id/usb-Razer-event-mouse")]


def test_bind_clear_returns_to_all_mice(monkeypatch):
    monkeypatch.setattr(cli, "_restart_daemon", lambda: None)
    settings = Settings(device_include=["^что-то$"])
    settings.save()
    assert cli.main(["bind", "--clear"]) == 0
    assert Settings.load().device_include == []


def test_bound_device_is_readable():
    settings = Settings(device_include=[cli.name_pattern("Razer DeathAdder")])
    assert cli.bound_device(settings) == "Razer DeathAdder"
    assert cli.bound_device(Settings()) == "все найденные мыши"


# --- чем нажимать клавиши ---
class FakeChannel:
    def __init__(self, capabilities=(), listeners=1):
        self.capabilities = set(capabilities)
        self.listeners = listeners
        self.sent: list[str] = []

    def has(self, capability):
        return capability in self.capabilities

    def broadcast(self, line):
        self.sent.append(line)
        return self.listeners


def test_keys_go_through_the_shell_when_it_can(daemon):
    """Расширение шлёт символ, а не код клавиши, — раскладка не мешает."""
    daemon.overlay_server = FakeChannel(capabilities=["keys"])
    assert daemon._send_keys_via_shell("ctrl+c") is True
    assert daemon.overlay_server.sent == ["dokeys\tctrl+c"]


def test_keys_go_through_uinput_when_the_shell_is_absent(daemon):
    daemon.overlay_server = FakeChannel(capabilities=[])
    assert daemon._send_keys_via_shell("ctrl+c") is False
    assert daemon.overlay_server.sent == []


def test_uinput_can_be_forced(daemon):
    daemon.settings.keys_via = "uinput"
    daemon.overlay_server = FakeChannel(capabilities=["keys"])
    assert daemon._send_keys_via_shell("ctrl+c") is False


def test_shell_can_be_forced_before_it_announces_itself(daemon):
    daemon.settings.keys_via = "shell"
    daemon.overlay_server = FakeChannel(capabilities=[])
    assert daemon._send_keys_via_shell("ctrl+c") is True


def test_without_a_channel_keys_stay_on_uinput(daemon):
    daemon.overlay_server = None
    assert daemon._send_keys_via_shell("ctrl+c") is False


def test_nobody_listening_means_uinput(daemon):
    daemon.overlay_server = FakeChannel(capabilities=["keys"], listeners=0)
    assert daemon._send_keys_via_shell("ctrl+c") is False


# --- действия над окнами и фокус ---
def test_window_action_goes_to_the_shell(daemon):
    daemon.overlay_server = FakeChannel(capabilities=["window"])
    assert daemon._send_window_via_shell("minimize") is True
    assert daemon.overlay_server.sent == ["dowindow\tminimize"]


def test_window_action_without_the_shell(daemon):
    daemon.overlay_server = FakeChannel(capabilities=["keys"])
    assert daemon._send_window_via_shell("minimize") is False


def test_focus_is_requested_before_acting(daemon):
    """Иначе на двух экранах действие уходит в окно на другом экране."""
    daemon.overlay_server = FakeChannel(capabilities=["window"])
    daemon.settings.focus_under_cursor = True
    daemon.focus_target_window()
    assert daemon.overlay_server.sent == ["dofocus"]


def test_focus_can_be_switched_off(daemon):
    daemon.overlay_server = FakeChannel(capabilities=["window"])
    daemon.settings.focus_under_cursor = False
    daemon.focus_target_window()
    assert daemon.overlay_server.sent == []


def test_focus_is_skipped_without_the_shell(daemon):
    daemon.overlay_server = FakeChannel(capabilities=[])
    daemon.settings.focus_under_cursor = True
    daemon.focus_target_window()
    assert daemon.overlay_server.sent == []


# --- пауза перехвата ---
def test_pause_command_is_queued_for_the_main_loop(daemon):
    """Захват снимается в цикле чтения, а не из чужого потока."""
    daemon.handle_command(["pause"])
    assert daemon._pause_request is True
    daemon.handle_command(["resume"])
    assert daemon._pause_request is False


def test_toggle_flips_the_current_state(daemon):
    daemon.paused = True
    daemon.handle_command(["toggle"])
    assert daemon._pause_request is False


def test_state_question_is_answered(daemon):
    daemon.overlay_server = FakeChannel()
    daemon.handle_command(["state?"])
    assert daemon.overlay_server.sent == ["state\tactive"]


def test_greeting_carries_the_state(daemon):
    assert daemon._greeting().endswith("\tactive")
    daemon.paused = True
    assert daemon._greeting().endswith("\tpaused")


def test_unknown_command_is_ignored(daemon):
    daemon.handle_command(["станцуй"])
    assert daemon._pause_request is None


# --- жесты приложения и исключения ---
def line_down():
    return [(0.0, float(i)) for i in range(0, 200, 5)]


@pytest.fixture
def daemon_with_apps(daemon):
    from glyphstroke.config import Action, Gesture
    daemon.gestures = [
        Gesture(name="Закрыть вкладку", directions=["D"],
                actions=[Action("keys", "ctrl+w")]),
        Gesture(name="Удалить строку", directions=["D"], apps=["code"],
                actions=[Action("keys", "ctrl+shift+k")]),
    ]
    daemon._recognizers = {}
    return daemon


def test_app_gesture_wins_in_its_application(daemon_with_apps):
    match = daemon_with_apps.recognizer_for("code | main.py", specific=True)
    assert match.recognize(line_down()).name == "Удалить строку"


def test_global_gesture_works_everywhere_else(daemon_with_apps):
    assert daemon_with_apps.recognizer_for("gedit | текст",
                                           specific=True).recognize(line_down()).name is None
    assert daemon_with_apps.recognizer_for("gedit | текст",
                                           specific=False).recognize(line_down()).name \
        == "Закрыть вкладку"


def test_unknown_window_falls_back_to_global(daemon_with_apps):
    assert daemon_with_apps.recognizer_for(None, specific=False).recognize(
        line_down()).name == "Закрыть вкладку"


def test_recognizers_are_cached_per_application(daemon_with_apps):
    first = daemon_with_apps.recognizer_for("code | a", specific=True)
    assert daemon_with_apps.recognizer_for("code | a", specific=True) is first


def test_excluded_application(daemon):
    daemon.settings.excluded_apps = ["gimp", "krita"]
    assert daemon.is_excluded("gimp | Безымянный")
    assert not daemon.is_excluded("firefox | сайт")
    assert not daemon.is_excluded(None)


def test_no_exclusions_by_default(daemon):
    assert not daemon.is_excluded("gimp | Безымянный")


def test_window_from_the_shell_becomes_the_context(daemon):
    daemon.handle_command(["window", "firefox", "Поиск", "—", "Mozilla"])
    assert daemon.context.active_app() == "firefox | Поиск — Mozilla"


def test_hint_lists_gestures_with_how_to_make_them(daemon):
    from glyphstroke.config import Gesture
    daemon.gestures = [Gesture(name="Назад", directions=["L"]),
                       Gesture(name="Rocker", event="rocker-left"),
                       Gesture(name="Без ничего")]
    text = daemon.hint_text()
    assert "Назад|L" in text
    assert "Rocker|щёлкнуть левой" in text
    assert "Без ничего" not in text, "жесту без росчерка в шпаргалке не место"


# --- вид следа уходит в канал ---
def test_begin_carries_colour_width_and_opacity(daemon):
    daemon.overlay_server = FakeChannel()
    daemon.settings.overlay.color = "#112233"
    daemon.settings.overlay.width = 9
    daemon.settings.overlay.opacity = 0.4
    daemon.overlay_send("begin")
    assert daemon.overlay_server.sent == ["begin #112233 9 0.40"]


def test_other_commands_go_as_they_are(daemon):
    daemon.overlay_server = FakeChannel()
    daemon.overlay_send("end")
    assert daemon.overlay_server.sent == ["end"]
