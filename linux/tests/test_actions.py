"""Проверка исполнителя действий, включая настоящую отправку клавиш."""

from __future__ import annotations

import os
import select
import time
from pathlib import Path

import pytest

evdev = pytest.importorskip("evdev")
from evdev import InputDevice, ecodes  # noqa: E402

from glyphstroke.actions import ActionRunner, VirtualKeyboard  # noqa: E402
from glyphstroke.config import Action  # noqa: E402
from glyphstroke import keysyms  # noqa: E402


def test_parse_combo_understands_aliases():
    mods, keys = keysyms.parse_combo("ctrl+alt+t")
    assert mods == [ecodes.KEY_LEFTCTRL, ecodes.KEY_LEFTALT]
    assert keys == [ecodes.KEY_T]


def test_parse_combo_accepts_dash_and_case():
    assert keysyms.parse_combo("Alt-Left") == ([ecodes.KEY_LEFTALT], [ecodes.KEY_LEFT])


def test_unknown_key_is_reported():
    with pytest.raises(keysyms.KeyParseError):
        keysyms.parse_combo("ctrl+нетакой")


def test_sequence_of_combos():
    assert len(keysyms.parse_sequence("ctrl+c ctrl+v")) == 2


def test_command_action_runs(tmp_path):
    marker = tmp_path / "done"
    runner = ActionRunner(keyboard=VirtualKeyboard())
    runner.run_one(Action("command", f"touch {marker}"))
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists()


def test_button_and_scroll_go_to_pointer():
    emitted: list[tuple[int, int, int]] = []
    runner = ActionRunner(pointer_emit=lambda t, c, v: emitted.append((t, c, v)))
    runner.run_one(Action("button", "middle"))
    assert (ecodes.EV_KEY, ecodes.BTN_MIDDLE, 1) in emitted
    assert (ecodes.EV_KEY, ecodes.BTN_MIDDLE, 0) in emitted
    emitted.clear()
    runner.run_one(Action("scroll", "up 2"))
    wheel = [e for e in emitted if e[1] == ecodes.REL_WHEEL]
    assert wheel == [(ecodes.EV_REL, ecodes.REL_WHEEL, 1)] * 2


def test_unknown_action_type_does_not_crash():
    ActionRunner(pointer_emit=lambda *a: None).run([Action("нетакого", "x")])


def test_broken_action_does_not_stop_the_rest(tmp_path):
    marker = tmp_path / "second"
    runner = ActionRunner()
    runner.run([Action("keys", "ctrl+несуществующая"),
                Action("command", f"touch {marker}")])
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists(), "ошибка в первом действии не должна отменять второе"


@pytest.mark.skipif(not os.access("/dev/uinput", os.W_OK),
                    reason="нужен доступ на запись к /dev/uinput")
def test_keys_really_reach_the_kernel():
    """Комбинация уходит в ядро как настоящее нажатие — это и есть способ
    работать в Wayland, где синтетика X-сервера бессильна."""
    keyboard = VirtualKeyboard(name="glyphstroke-test-keyboard")
    keyboard.ui  # создаём устройство
    time.sleep(0.3)
    reader = None
    for path in evdev.list_devices():
        dev = InputDevice(path)
        if dev.name == "glyphstroke-test-keyboard":
            reader = dev
            break
        dev.close()
    assert reader is not None, "виртуальная клавиатура не появилась в системе"
    try:
        ActionRunner(keyboard=keyboard).run_one(Action("keys", "ctrl+w"))
        events = []
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            ready, _, _ = select.select([reader.fd], [], [], 0.05)
            if ready:
                events.extend(e for e in reader.read() if e.type == ecodes.EV_KEY)
        assert [(e.code, e.value) for e in events] == [
            (ecodes.KEY_LEFTCTRL, 1),
            (ecodes.KEY_W, 1),
            (ecodes.KEY_W, 0),
            (ecodes.KEY_LEFTCTRL, 0),
        ]
    finally:
        reader.close()
        keyboard.close()


def test_keys_sender_takes_over_when_it_can():
    sent = []
    runner = ActionRunner(keys_sender=lambda combo: sent.append(combo) or True)
    runner.run_one(Action("keys", "ctrl+c"))
    assert sent == ["ctrl+c"]
    assert runner.last_keys_transport == "shell", "способ отправки — признак, не текст"


@pytest.mark.skipif(not os.access("/dev/uinput", os.W_OK),
                    reason="нужен доступ на запись к /dev/uinput")
def test_keys_fall_back_to_uinput_when_the_sender_declines():
    runner = ActionRunner(keys_sender=lambda combo: False)
    try:
        runner.run_one(Action("keys", "ctrl+c"))
        assert runner.last_keys_transport == "uinput"
    finally:
        runner.close()   # иначе устройство переживёт тест и запутает соседей


def test_typo_is_caught_before_anything_is_sent():
    sent = []
    runner = ActionRunner(keys_sender=lambda combo: sent.append(combo) or True)
    with pytest.raises(keysyms.KeyParseError):
        runner.run_one(Action("keys", "ctrl+такойнет"))
    assert sent == [], "неразобранное сочетание отправлять нельзя"


def test_window_action_is_handed_to_the_shell():
    sent = []
    runner = ActionRunner(window_sender=lambda command: sent.append(command) or True)
    runner.run_one(Action("window", "minimize"))
    assert sent == ["minimize"]


def test_window_action_checks_the_value():
    runner = ActionRunner(window_sender=lambda command: True)
    with pytest.raises(ValueError):
        runner.run_one(Action("window", "свернуть-как-нибудь"))


def test_window_action_without_a_shell_does_not_crash():
    ActionRunner(window_sender=None).run([Action("window", "minimize")])


# --- запуск приложений ---
def test_desktop_exec_drops_placeholders(tmp_path):
    entry = tmp_path / "проба.desktop"
    entry.write_text("[Desktop Entry]\nType=Application\n"
                     "Exec=gedit %U --new-window\nName=Проба\n", encoding="utf-8")
    assert ActionRunner.desktop_exec(entry) == "gedit --new-window"


def test_desktop_exec_ignores_other_sections(tmp_path):
    entry = tmp_path / "проба.desktop"
    entry.write_text("[Desktop Entry]\nExec=правильный\n"
                     "[Desktop Action new]\nExec=неправильный\n", encoding="utf-8")
    assert ActionRunner.desktop_exec(entry) == "правильный"


def test_app_resolves_a_program_by_name():
    assert str(ActionRunner().resolve_app("sh")).endswith("/sh")


def test_app_reports_a_missing_program():
    assert ActionRunner().resolve_app("такой-программы-нет-12345") is None


def test_app_action_runs_an_executable(tmp_path):
    marker = tmp_path / "запущено"
    script = tmp_path / "программа.sh"
    script.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    script.chmod(0o755)
    ActionRunner().run_one(Action("app", str(script)))
    deadline = time.monotonic() + 3
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.exists()


def test_missing_app_does_not_crash():
    ActionRunner().run([Action("app", "такой-программы-нет-12345")])
