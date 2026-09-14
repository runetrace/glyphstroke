"""Стандартные действия системы: разворот имени в клавиши и в действие окна."""

from __future__ import annotations

import pytest

from glyphstroke import standard
from glyphstroke.config import Action

evdev = pytest.importorskip("evdev")
from glyphstroke.actions import ActionRunner  # noqa: E402
from glyphstroke import keysyms  # noqa: E402


def test_every_action_resolves():
    for key in standard.STANDARD_ACTIONS:
        assert standard.resolve(key) is not None, key


def test_every_combination_parses():
    """Опечатка в таблице всплыла бы только при выполнении жеста у человека."""
    broken = []
    for key, (_label, kind, value) in standard.STANDARD_ACTIONS.items():
        if kind != "keys":
            continue
        try:
            keysyms.parse_sequence(value)
        except keysyms.KeyParseError as exc:
            broken.append((key, value, str(exc)))
    assert broken == []


def test_window_actions_use_the_window_type():
    """Свернуть и развернуть окно клавишами нельзя: у каждого рабочего стола
    сочетания свои, поэтому они уходят в действие «окно»."""
    for key in ("minimize", "maximize", "unmaximize", "fullscreen", "close-window"):
        kind, _value = standard.resolve(key)
        assert kind == "window", key


def test_unknown_name_resolves_to_nothing():
    assert standard.resolve("не-такое") is None
    assert standard.resolve("") is None


def test_name_is_case_insensitive():
    assert standard.resolve("Copy") == standard.resolve("copy")


def test_labels_are_translated():
    from glyphstroke import i18n

    i18n.setup("en")
    try:
        assert standard.label("copy") == "Copy"
        assert standard.label("minimize") == "Minimise the window"
    finally:
        i18n.setup("ru")


def test_description_shows_the_combination():
    """В списке видно, что именно нажмётся: иначе выбор из тридцати строк —
    гадание."""
    assert standard.describe("paste") == "Вставить — ctrl+v"
    assert standard.describe("copy") == "Копировать — ctrl+c"


def test_window_actions_have_no_combination_to_show():
    assert standard.describe("minimize") == "Свернуть окно"


def test_unknown_name_is_shown_as_is():
    assert standard.describe("не-такое") == "не-такое"


def test_choices_keep_the_order_of_the_table():
    assert [key for key, _title in standard.choices()] == list(standard.STANDARD_ACTIONS)
    assert dict(standard.choices())["paste"] == "Вставить — ctrl+v"


# --- выполнение ---
def test_copy_sends_the_system_combination():
    sent = []
    runner = ActionRunner(keys_sender=lambda combo: sent.append(combo) or True)
    runner.run_one(Action("standard", "copy"))
    assert sent == ["ctrl+c"]


def test_minimize_goes_to_the_window_handler():
    commands = []
    runner = ActionRunner(keys_sender=lambda combo: True,
                          window_sender=lambda command: commands.append(command) or True)
    runner.run_one(Action("standard", "minimize"))
    assert commands == ["minimize"]


def test_unknown_standard_action_is_reported():
    sent = []
    runner = ActionRunner(keys_sender=lambda combo: sent.append(combo) or True)
    with pytest.raises(ValueError):
        runner.run_one(Action("standard", "потанцевать"))
    assert sent == [], "непонятое имя отправлять нечем"


def test_the_gesture_survives_a_broken_standard_action(tmp_path):
    """Ошибка в одном действии не должна отменять остальные."""
    marker = tmp_path / "done"
    runner = ActionRunner(keys_sender=lambda combo: True)
    runner.run([Action("standard", "потанцевать"), Action("command", f"touch {marker}")])
    import time

    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists()
