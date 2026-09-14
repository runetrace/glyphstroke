"""Окно следа: команды из канала и меню, которое оно рисует в X11.

Нужен любой X-дисплей (в CI подойдёт Xvfb) — без него тесты пропускаются.
"""

from __future__ import annotations

import io
import os
import sys

import pytest

if not os.environ.get("DISPLAY"):
    pytest.skip("нужен X-дисплей (например, Xvfb)", allow_module_level=True)

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from glyphstroke.overlay import Overlay  # noqa: E402


class ImmediateGLib:
    """Вместо очереди главного цикла — вызов на месте: цикла в тестах нет."""

    @staticmethod
    def idle_add(func, *args):
        func(*args)
        return 0

    @staticmethod
    def timeout_add(_interval, func, *args):
        return 0

    @staticmethod
    def source_remove(_source):
        return None


@pytest.fixture
def overlay():
    window = Overlay(Gtk, Gdk, ImmediateGLib, (0.3, 0.64, 1.0), 4, 220)
    yield window
    window.window.destroy()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def feed(overlay, *lines):
    """Прогнать строки канала через разбор команд."""
    stdin = sys.stdin
    sys.stdin = io.StringIO("".join(line + "\n" for line in lines))
    try:
        overlay.read_commands()
    finally:
        sys.stdin = stdin


def test_menu_command_opens_the_list(overlay):
    feed(overlay, "menu\tПравка\tКопировать\tВставить")
    assert overlay.menu_title == "Правка"
    assert overlay.menu_items == ["Копировать", "Вставить"]
    assert overlay.menu_index == -1
    assert overlay.window.get_visible()


def test_selection_is_remembered(overlay):
    feed(overlay, "menu\tПравка\tКопировать\tВставить", "menu-select\t1")
    assert overlay.menu_index == 1


def test_a_broken_index_selects_nothing(overlay):
    feed(overlay, "menu\tПравка\tКопировать", "menu-select\tчепуха")
    assert overlay.menu_index == -1


def test_hiding_the_menu_hides_the_window(overlay):
    feed(overlay, "menu\tПравка\tКопировать", "menu-hide")
    assert overlay.menu_items == []
    assert not overlay.window.get_visible()


def test_the_window_stays_while_a_hint_is_shown(overlay):
    feed(overlay, "hint\tНазад|L", "menu\tПравка\tКопировать", "menu-hide")
    assert overlay.hint_items, "шпаргалка не должна пропадать вместе с меню"
    assert overlay.window.get_visible()


def test_the_anchor_is_taken_once_when_the_menu_opens(overlay, monkeypatch):
    monkeypatch.setattr(overlay, "pointer_position", lambda: (640.0, 400.0))
    feed(overlay, "menu\tПравка\tКопировать")
    monkeypatch.setattr(overlay, "pointer_position", lambda: (0.0, 0.0))
    feed(overlay, "menu-select\t0")
    assert overlay.menu_anchor == (640.0, 400.0)
