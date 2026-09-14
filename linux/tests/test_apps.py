"""База приложений, мишень и точное сравнение по классу окна."""

from __future__ import annotations

import os
import shutil
import socket
import tempfile
import threading
import time
from urllib.parse import quote

import pytest

from glyphstroke import config
from glyphstroke.config import (Gesture, KnownApp, Settings, add_app, app_matches,
                             apps_usage, class_pattern, describe_patterns,
                             load_apps, load_gestures, remove_app)


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path / "config"))
    # путь к сокету ограничен сотней байт, каталог теста для него длинноват
    runtime = tempfile.mkdtemp(prefix="rc-")
    monkeypatch.setenv("XDG_RUNTIME_DIR", runtime)
    yield tmp_path
    shutil.rmtree(runtime, ignore_errors=True)


# --- сравнение с окном ------------------------------------------------------
def test_class_pattern_matches_the_window_class_only():
    pattern = class_pattern("code")
    assert app_matches(pattern, "code | main.py — проект")
    assert app_matches(pattern, "Code | main.py"), "регистр класса неважен"
    assert not app_matches(pattern, "firefox | Claude Code docs"), \
        "слово в заголовке чужого окна не должно давать совпадения"
    assert not app_matches(pattern, "code-oss | main.py")
    assert not app_matches(pattern, None)


def test_expressions_keep_working_as_before():
    assert app_matches("firefox", "Navigator | Firefox")
    assert app_matches("chrom", "google-chrome | Новая вкладка")
    assert not app_matches("firefox", "gedit | текст")


def test_broken_expression_does_not_raise():
    assert not app_matches("firefox(", "firefox | сайт")


def test_gesture_filter_understands_classes():
    gesture = Gesture(name="только код", apps=[class_pattern("code")])
    assert gesture.matches_app("code | a.py")
    assert not gesture.matches_app("firefox | code")


# --- база -------------------------------------------------------------------
def test_added_app_survives_a_reload():
    app, created = add_app("org.gnome.Nautilus", "Файлы")
    assert created and app.pattern == "class:org.gnome.Nautilus"
    assert load_apps() == [KnownApp("org.gnome.Nautilus", "Файлы")]


def test_the_same_class_is_not_added_twice():
    add_app("firefox", "Firefox")
    again, created = add_app("Firefox", "Другое имя")
    assert not created and again.name == "Firefox"
    assert len(load_apps()) == 1


def test_missing_name_is_filled_in_later():
    add_app("krita")
    add_app("krita", "Krita")
    assert load_apps()[0].title == "Krita"


def test_window_without_class_is_refused():
    with pytest.raises(ValueError):
        add_app("  ")


def test_apps_are_listed_by_title():
    add_app("zed", "Zed")
    add_app("alacritty", "Alacritty")
    add_app("btop")
    assert [app.title for app in load_apps()] == ["Alacritty", "btop", "Zed"]


def test_broken_base_file_gives_an_empty_list():
    config.apps_path().parent.mkdir(parents=True, exist_ok=True)
    config.apps_path().write_text("apps: [unclosed", encoding="utf-8")
    assert load_apps() == []


def test_titles_for_the_gesture_list():
    apps = [KnownApp("firefox", "Firefox")]
    patterns = [class_pattern("FIREFOX"), class_pattern("gimp"), "chrom"]
    assert describe_patterns(patterns, apps) == "Firefox, gimp, chrom"


def test_usage_counts_gestures_and_exclusions():
    Gesture(name="Раз", directions=["U"], apps=[class_pattern("firefox")]).save()
    Gesture(name="Два", directions=["D"], apps=["firefox"]).save()  # выражение
    settings = Settings()
    settings.excluded_apps = [class_pattern("Gimp")]
    settings.save()
    usage = apps_usage()
    assert usage["firefox"].gestures == ["Раз"] and not usage["firefox"].excluded
    assert usage["gimp"].excluded and usage["gimp"].gestures == []


# --- удаление ---------------------------------------------------------------
def test_removing_an_app_unbinds_it_in_every_set():
    add_app("firefox", "Firefox")
    add_app("code", "Code")
    firefox = class_pattern("firefox")
    Gesture(name="Только Firefox", directions=["U"], apps=[firefox]).save()
    Gesture(name="Firefox и код", directions=["D"],
            apps=[firefox, class_pattern("code")]).save()
    Gesture(name="Везде", directions=["L"]).save()
    config.create_profile("работа")
    Gesture(name="В наборе", directions=["R"], apps=[firefox]).save(
        config.gestures_dir("работа"))
    settings = Settings()
    settings.excluded_apps = [firefox, "gimp"]
    settings.save()

    result = remove_app("firefox")

    assert [app.wm_class for app in load_apps()] == ["code"]
    assert sorted(result.unbound) == sorted(
        ["Только Firefox", "Firefox и код", "работа: В наборе"])
    assert sorted(result.disabled) == sorted(["Только Firefox", "работа: В наборе"])
    base = {g.name: g for g in load_gestures(config.gestures_dir(""))}
    assert base["Только Firefox"].apps == []
    assert not base["Только Firefox"].enabled, \
        "жест без приложений выключается, иначе он заработал бы везде"
    assert base["Firefox и код"].apps == [class_pattern("code")]
    assert base["Firefox и код"].enabled
    assert base["Везде"].enabled
    assert result.excluded and Settings.load().excluded_apps == ["gimp"]


def test_known_apps_travel_with_exported_gestures(tmp_path, monkeypatch):
    add_app("firefox", "Firefox")
    Gesture(name="Жест", directions=["U"], apps=[class_pattern("firefox")]).save()
    bundle = tmp_path / "bundle.yaml"
    config.export_bundle(bundle)

    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path / "other"))
    result = config.import_bundle(bundle)
    assert load_apps() == [KnownApp("firefox", "Firefox")]
    assert result.apps_added == 1
    assert "1" in result.summary()


# --- демон ------------------------------------------------------------------
class FakeChannel:
    def __init__(self, capabilities=("pick",)):
        self.capabilities = set(capabilities)
        self.sent: list[str] = []

    def has(self, capability):
        return capability in self.capabilities

    def broadcast(self, line):
        self.sent.append(line)
        return 1


@pytest.fixture
def daemon():
    pytest.importorskip("evdev")
    from glyphstroke.daemon import Daemon
    daemon = Daemon(Settings())
    daemon.overlay_server = FakeChannel()
    return daemon


def test_exclusion_by_class(daemon):
    daemon.settings.excluded_apps = [class_pattern("gimp")]
    assert daemon.is_excluded("Gimp | Безымянный")
    assert not daemon.is_excluded("firefox | gimp — уроки")


def test_pick_is_asked_from_the_shell(daemon):
    daemon.handle_command(["pick"])
    assert daemon.overlay_server.sent == ["dopick"]


def test_pick_without_the_shell_is_answered_at_once(daemon):
    daemon.overlay_server = FakeChannel(capabilities=())
    daemon.handle_command(["pick"])
    assert daemon.overlay_server.sent == ["picked\t-\tnoshell"]


def test_shell_answer_is_decoded_and_relayed(daemon):
    daemon.handle_command(["picked", quote("org.gnome.TextEditor"),
                           quote("Текстовый редактор")])
    assert daemon.overlay_server.sent == [
        "picked\torg.gnome.TextEditor\tТекстовый редактор"]


def test_shell_reports_an_empty_spot(daemon):
    daemon.handle_command(["picked", "-", "nowindow"])
    assert daemon.overlay_server.sent == ["picked\t-\tnowindow"]


# --- канал целиком: редактор → демон → оболочка → редактор -------------------
class FakeShell:
    """Клиент канала, который притворяется расширением оболочки."""

    def __init__(self, answer: str | None):
        from glyphstroke.ipc import socket_path
        self.answer = answer
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(str(socket_path()))
        self.sock.sendall(b"iam shell pick\n")
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        buffer = b""
        while True:
            try:
                chunk = self.sock.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buffer += chunk
            while b"\n" in buffer:
                line, _sep, buffer = buffer.partition(b"\n")
                if line == b"dopick" and self.answer is not None:
                    self.sock.sendall(self.answer.encode("utf-8") + b"\n")

    def close(self):
        self.sock.close()


@pytest.fixture
def channel(daemon):
    from glyphstroke.ipc import OverlayServer
    server = OverlayServer(greeting="hello\ttest\t1\tactive",
                           on_command=daemon.handle_command)
    server.start()
    daemon.overlay_server = server
    yield server
    server.stop()


def wait_for(condition, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_editor_learns_the_window_through_the_channel(channel):
    from glyphstroke import cli
    shell = FakeShell(f"picked {quote('firefox')} {quote('Firefox Web Browser')}")
    try:
        assert wait_for(lambda: channel.has("pick"))
        assert cli.pick_window(timeout=2.0) == ("firefox", "Firefox Web Browser")
    finally:
        shell.close()


def test_editor_is_told_there_is_no_shell(channel):
    from glyphstroke import cli
    assert cli.pick_window(timeout=2.0) == "noshell"


def test_editor_is_told_there_is_no_daemon():
    pytest.importorskip("evdev")
    from glyphstroke import cli
    assert cli.pick_window(timeout=0.5) == "nodaemon"


def test_silent_shell_ends_in_a_timeout(channel):
    from glyphstroke import cli
    shell = FakeShell(None)
    try:
        assert wait_for(lambda: channel.has("pick"))
        assert cli.pick_window(timeout=0.5) == "timeout"
    finally:
        shell.close()


# --- X11 без оболочки --------------------------------------------------------
def test_x11_window_under_the_pointer():
    if not os.environ.get("DISPLAY"):
        pytest.skip("нужен X-дисплей (например, Xvfb)")
    gi = pytest.importorskip("gi")
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, Gtk

    from glyphstroke.context import window_at_pointer

    def pump(seconds=0.3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.01)

    window = Gtk.Window(title="мишень")
    window.set_wmclass("glyphstroke-probe", "GlyphstrokeProbe")
    window.set_default_size(300, 200)
    window.move(40, 40)
    window.show_all()
    pointer = Gdk.Display.get_default().get_default_seat().get_pointer()
    try:
        pump()
        pointer.warp(window.get_screen(), 120, 120)
        pump(0.1)
        assert window_at_pointer() == ("GlyphstrokeProbe", "GlyphstrokeProbe")
        screen = window.get_screen()
        pointer.warp(screen, screen.get_width() - 2, screen.get_height() - 2)
        pump(0.1)
        assert window_at_pointer() is None, "над пустым столом окна нет"
    finally:
        window.destroy()
        pump(0.1)
