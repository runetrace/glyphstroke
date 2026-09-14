"""Отключение перехвата, пока активное окно во весь экран."""

from __future__ import annotations

import json
import types

import pytest

pytest.importorskip("evdev")

from glyphstroke.config import Settings  # noqa: E402
from glyphstroke.context import WindowContext  # noqa: E402
from glyphstroke.daemon import Daemon  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    return tmp_path


class FakeChannel:
    def __init__(self, capabilities=("fullscreen",)):
        self.capabilities = set(capabilities)
        self.listeners = 1
        self.sent: list[str] = []

    def has(self, capability):
        return capability in self.capabilities

    def broadcast(self, line):
        self.sent.append(line)
        return self.listeners


@pytest.fixture
def daemon():
    settings = Settings()
    settings.pause_in_fullscreen = True
    daemon = Daemon(settings)
    daemon.overlay_server = FakeChannel()
    return daemon


# --- сам механизм ---
def test_a_fullscreen_window_asks_for_a_pause(daemon):
    daemon.handle_command(["fullscreen", "1"])
    assert daemon._pause_request is True
    assert daemon._auto_paused


def test_leaving_fullscreen_gives_the_mouse_back(daemon):
    daemon.handle_command(["fullscreen", "1"])
    daemon._pause_request = None
    daemon.paused = True
    daemon.handle_command(["fullscreen", "0"])
    assert daemon._pause_request is False
    assert not daemon._auto_paused


def test_nothing_happens_while_the_option_is_off(daemon):
    daemon.settings.pause_in_fullscreen = False
    daemon.handle_command(["fullscreen", "1"])
    assert daemon._pause_request is None
    assert not daemon._auto_paused


def test_switching_the_option_off_returns_the_capture(daemon):
    daemon.handle_command(["fullscreen", "1"])
    daemon.paused = True
    daemon._pause_request = None
    daemon.settings.pause_in_fullscreen = False
    daemon.apply_auto_pause()
    assert daemon._pause_request is False
    assert not daemon._auto_paused


def test_a_hand_made_pause_is_not_undone_by_us(daemon):
    """Человек нажал паузу сам — выход из игры не должен её снимать."""
    daemon.paused = True
    daemon.handle_command(["fullscreen", "1"])
    assert not daemon._auto_paused
    daemon._pause_request = None
    daemon.handle_command(["fullscreen", "0"])
    assert daemon._pause_request is None, "мы этого не снимали, значит не возвращаем"


def test_a_hand_made_resume_wins_over_the_game(daemon):
    """Вернули перехват руками прямо в игре — больше не отбираем."""
    daemon.handle_command(["fullscreen", "1"])
    daemon.paused = True
    daemon.handle_command(["resume"])
    assert not daemon._auto_paused
    assert daemon._pause_request is False


def test_without_anyone_to_ask_we_keep_our_hands_off(daemon, monkeypatch):
    daemon.overlay_server = FakeChannel(capabilities=[])
    monkeypatch.setattr(daemon.context, "fullscreen", lambda: None)
    daemon.apply_auto_pause()
    assert daemon._pause_request is None


def test_the_shell_is_trusted_when_it_reports(daemon, monkeypatch):
    """Оболочка знает про окна больше нас — в GNOME только она и знает."""
    monkeypatch.setattr(daemon.context, "fullscreen", lambda: False)
    daemon.handle_command(["fullscreen", "1"])
    assert daemon.fullscreen_now() is True


def test_the_session_is_asked_when_the_shell_is_silent(daemon, monkeypatch):
    daemon.overlay_server = FakeChannel(capabilities=[])
    monkeypatch.setattr(daemon.context, "fullscreen", lambda: True)
    assert daemon.fullscreen_now() is True


# --- откуда берётся признак ---
def sway_tree(fullscreen_mode: int) -> str:
    return json.dumps({"nodes": [{"focused": True, "app_id": "steam_app",
                                  "name": "Игра", "fullscreen_mode": fullscreen_mode}]})


def fake_run(output: str):
    return lambda *a, **kw: types.SimpleNamespace(stdout=output, returncode=0)


def test_sway_reports_fullscreen(monkeypatch):
    context = WindowContext()
    context._backend = "sway"
    monkeypatch.setattr("subprocess.run", fake_run(sway_tree(1)))
    assert context.fullscreen() is True
    assert context.active_app() == "steam_app | Игра"


def test_sway_reports_a_window_as_usual(monkeypatch):
    context = WindowContext()
    context._backend = "sway"
    monkeypatch.setattr("subprocess.run", fake_run(sway_tree(0)))
    assert context.fullscreen() is False


def test_hyprland_reports_fullscreen(monkeypatch):
    context = WindowContext()
    context._backend = "hyprland"
    monkeypatch.setattr("subprocess.run", fake_run(
        json.dumps({"class": "steam_app", "title": "Игра", "fullscreen": True})))
    assert context.fullscreen() is True


def test_xprop_reads_the_window_state(monkeypatch):
    context = WindowContext()
    context._backend = "xprop"
    answers = iter([
        "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3400007",
        'WM_CLASS(STRING) = "steam", "Steam"\n'
        '_NET_WM_NAME(UTF8_STRING) = "Игра"\n'
        "_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN, _NET_WM_STATE_FOCUSED",
    ])
    monkeypatch.setattr("subprocess.run",
                        lambda *a, **kw: types.SimpleNamespace(stdout=next(answers)))
    assert context.fullscreen() is True


def test_xprop_without_fullscreen(monkeypatch):
    context = WindowContext()
    context._backend = "xprop"
    answers = iter([
        "_NET_ACTIVE_WINDOW(WINDOW): window id # 0x3400007",
        'WM_CLASS(STRING) = "firefox", "Firefox"\n'
        '_NET_WM_NAME(UTF8_STRING) = "Сайт"\n'
        "_NET_WM_STATE(ATOM) = _NET_WM_STATE_FOCUSED",
    ])
    monkeypatch.setattr("subprocess.run",
                        lambda *a, **kw: types.SimpleNamespace(stdout=next(answers)))
    assert context.fullscreen() is False
    assert context.active_app() == "Firefox | Сайт"


def test_without_a_backend_the_answer_is_unknown():
    context = WindowContext()
    context._backend = None
    context._cached_at = 0.0
    assert context.fullscreen() is None


def test_the_extension_reports_fullscreen():
    import pathlib
    text = (pathlib.Path(__file__).resolve().parent.parent / "glyphstroke" / "data"
            / "gnome-extension" / "glyphstroke@glyphstroke.local"
            / "extension.js").read_text(encoding="utf-8")
    assert "in-fullscreen-changed" in text
    assert "fullscreen\\t" in text
    assert "iam shell keys window focus menu fullscreen" in text
