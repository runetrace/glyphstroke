"""Настройки: клавиша, пока зажата которая палец рисует на тачпаде.

Нужен любой X-дисплей (в CI подойдёт Xvfb) — без него тесты пропускаются.
"""

from __future__ import annotations

import os

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip("нужен X-дисплей (например, Xvfb)", allow_module_level=True)

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from glyphstroke import config  # noqa: E402
from glyphstroke.config import Settings  # noqa: E402

#: X-коды клавиш сдвинуты на 8 от кодов ядра
X_OFFSET = 8
KEY_F13 = 183


def open_editor():
    from glyphstroke.gui import EditorWindow
    return EditorWindow()


def close_editor(window):
    window.destroy()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    config.ensure_default_config()
    window = open_editor()
    yield window
    close_editor(window)


def test_super_is_chosen_by_default(editor):
    assert editor.touchpad_key_combo.get_active_id() == "KEY_LEFTMETA"


def test_chosen_key_is_saved(editor):
    editor.touchpad_key_combo.set_active_id("KEY_LEFTALT")
    editor.save_settings()
    assert Settings.load().touchpad_key == "KEY_LEFTALT"


def test_drawing_on_the_touchpad_can_be_switched_off(editor):
    editor.touchpad_key_combo.set_active_id("")
    editor.save_settings()
    assert Settings.load().touchpad_key == ""


def test_any_key_can_be_assigned_by_pressing_it(editor):
    assert editor.touchpad_key_from_keycode(KEY_F13 + X_OFFSET)
    assert editor.touchpad_key_combo.get_active_id() == "KEY_F13"
    assert "F13" in editor.status.get_text()
    editor.save_settings()
    assert Settings.load().touchpad_key == "KEY_F13"


def test_a_code_without_a_key_is_refused(editor):
    assert not editor.touchpad_key_from_keycode(X_OFFSET)
    assert editor.touchpad_key_combo.get_active_id() == "KEY_LEFTMETA"


def test_assigned_key_is_shown_after_a_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    config.ensure_default_config()
    settings = Settings.load()
    settings.touchpad_key = "KEY_F13"
    settings.save()
    window = open_editor()
    try:
        assert window.touchpad_key_combo.get_active_id() == "KEY_F13"
    finally:
        close_editor(window)
