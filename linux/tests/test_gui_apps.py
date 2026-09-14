"""Редактор: мишень, выбор приложений и список известных приложений.

Нужен любой X-дисплей (в CI подойдёт Xvfb) — без него тесты пропускаются.
"""

from __future__ import annotations

import os
import time

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip("нужен X-дисплей (например, Xvfb)", allow_module_level=True)

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from glyphstroke import config  # noqa: E402
from glyphstroke.config import (Gesture, KnownApp, Settings, add_app,  # noqa: E402
                             load_apps, load_gestures)


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    config.ensure_default_config()
    from glyphstroke.gui import EditorWindow
    window = EditorWindow()
    yield window
    window.destroy()
    pump(0.05)


class FakeEvent:
    def __init__(self, x, y, button=1):
        self.x, self.y, self.button = x, y, button


def pump(seconds=0.0, until=None, timeout=2.0):
    """Прокрутить цикл GTK: заданное время или пока не выполнится условие."""
    deadline = time.monotonic() + (timeout if until else seconds)
    while time.monotonic() < deadline:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until() if until else True


def saved(name):
    return {g.name: g for g in load_gestures()}[name]


def new_gesture(editor, name):
    editor.on_add(None)
    editor.name_entry.set_text(name)
    editor.directions_entry.set_text("U-R-D")


def checks(popover):
    return [child for child in popover.get_child().get_children()
            if isinstance(child, Gtk.CheckButton)]


def expressions_gesture(editor):
    """Стартовый «Обновить страницу» записан прежними выражениями."""
    return next(g for g in editor.gestures if g.apps == ["firefox", "chrom", "yandex"])


# --- мишень -----------------------------------------------------------------
def test_caught_window_is_remembered_and_ticked(editor):
    new_gesture(editor, "Для Firefox")
    editor.apps_chooser.picker.finish(("firefox", "Firefox"))
    assert load_apps() == [KnownApp("firefox", "Firefox")]
    assert editor.apps_chooser.get_patterns() == ["class:firefox"]
    assert editor.apps_chooser.summary.get_text() == "Firefox"
    assert "Сохранить жест" in editor.status.get_text()
    editor.on_save(None)
    assert saved("Для Firefox").apps == ["class:firefox"]


def test_own_window_is_not_caught(editor):
    editor.apps_chooser.picker.finish(("glyphstroke", "Glyphstroke"))
    assert load_apps() == []
    assert "Glyphstroke" in editor.status.get_text()


def test_failure_is_explained(editor):
    editor.apps_chooser.picker.finish("noshell")
    assert "glyphstroke shell-extension install" in editor.status.get_text()
    assert load_apps() == []


def test_target_released_over_the_editor_asks_nothing(editor):
    editor.show_all()
    pump(0.3)
    picker = editor.apps_chooser.picker
    asked = []
    picker.locate = lambda: asked.append(True) or ("gimp", "GIMP")
    picker._press(picker, FakeEvent(3, 3))
    assert picker.dragging
    picker._release(picker, FakeEvent(3, 3))
    pump(0.2)
    assert not picker.dragging
    assert asked == [] and load_apps() == []


def test_target_released_elsewhere_catches_the_window(editor):
    editor.show_all()
    pump(0.3)
    picker = editor.apps_chooser.picker
    picker.locate = lambda: ("gimp", "GIMP")
    picker._press(picker, FakeEvent(3, 3))
    picker._release(picker, FakeEvent(-4000, -4000))
    assert pump(until=lambda: bool(load_apps()))
    assert [app.wm_class for app in load_apps()] == ["gimp"]
    assert editor.apps_chooser.has("class:gimp")


# --- выбор из списка --------------------------------------------------------
def test_list_offers_known_apps_and_old_expressions(editor):
    add_app("firefox", "Firefox")
    editor.load_gesture(expressions_gesture(editor))
    items = dict(editor.apps_chooser.choices())
    assert items["class:firefox"] == "Firefox"
    assert items["firefox"] == "выражение «firefox»"
    popover = editor.apps_chooser.open_list()
    ticked = [check.get_label() for check in checks(popover) if check.get_active()]
    assert ticked == ["выражение «firefox»", "выражение «chrom»", "выражение «yandex»"]
    popover.popdown()


def test_old_expressions_survive_an_untouched_save(editor):
    gesture = expressions_gesture(editor)
    editor.load_gesture(gesture)
    editor.on_save(None)
    assert saved(gesture.name).apps == ["firefox", "chrom", "yandex"]


def test_empty_list_tells_how_to_fill_it(editor):
    new_gesture(editor, "Пустой список")
    popover = editor.apps_chooser.open_list()
    labels = [child.get_text() for child in popover.get_child().get_children()
              if isinstance(child, Gtk.Label)]
    assert any("мишень" in text for text in labels)
    popover.popdown()


def test_ticking_an_app_in_the_list(editor):
    add_app("code", "Code")
    new_gesture(editor, "Для кода")
    popover = editor.apps_chooser.open_list()
    check = next(check for check in checks(popover) if check.get_label() == "Code")
    check.set_active(True)
    assert editor.apps_chooser.get_patterns() == ["class:code"]
    check.set_active(False)
    assert editor.apps_chooser.get_patterns() == []
    assert editor.apps_chooser.summary.get_text() == "везде"
    popover.popdown()


def test_exclusions_are_chosen_and_applied(editor):
    add_app("gimp", "GIMP")
    editor.excluded_chooser.set_active("class:gimp", True)
    editor.save_settings()
    assert Settings.load().excluded_apps == ["class:gimp"]


# --- список известных приложений --------------------------------------------
def test_known_apps_list_shows_where_they_are_used(editor):
    add_app("firefox", "Firefox")
    add_app("krita", "Krita")
    Gesture(name="Жест Firefox", directions=["U-L-D"], apps=["class:firefox"]).save()
    settings = Settings.load()
    settings.excluded_apps = ["class:firefox"]
    settings.save()
    editor.refresh_apps()
    rows = [tuple(row) for row in editor.apps_store]
    assert rows == [("Firefox", "firefox", "жестов: 1, без перехвата"),
                    ("Krita", "krita", "—")]


def test_removing_an_app_switches_off_its_lonely_gesture(editor):
    add_app("firefox", "Firefox")
    new_gesture(editor, "Только Firefox")
    editor.apps_chooser.set_active("class:firefox", True)
    editor.on_save(None)
    editor.refresh_apps()
    editor.apps_tree.get_selection().select_path(Gtk.TreePath(0))

    assert editor.remove_selected_app(confirmed=True)

    assert load_apps() == []
    assert saved("Только Firefox").apps == []
    assert not saved("Только Firefox").enabled
    assert editor.current.name == "Только Firefox" and not editor.current.enabled
    assert editor.apps_chooser.get_patterns() == []
    assert "выключены" in editor.status.get_text()
    editor.on_save(None)
    assert not saved("Только Firefox").enabled, \
        "пересохранение не должно включить жест, оставшийся без приложений"


def test_removing_needs_a_selection(editor):
    assert not editor.remove_selected_app(confirmed=True)
    assert "Выберите" in editor.status.get_text()


def test_gesture_list_shows_app_names(editor):
    add_app("firefox", "Firefox")
    new_gesture(editor, "Для Firefox")
    editor.apps_chooser.set_active("class:firefox", True)
    editor.on_save(None)
    row = next(row for row in editor.store if row[1] == "Для Firefox")
    assert row[3] == "Firefox"
