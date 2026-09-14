"""Наборы жестов: свои каталоги, переключение и то, что без них ничего не меняется."""

from __future__ import annotations

import pytest

from glyphstroke import config
from glyphstroke.config import Action, Gesture, Settings, load_gestures


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    return tmp_path


def make_gesture(name: str, profile: str | None = None) -> Gesture:
    gesture = Gesture(name=name, directions=["D"], actions=[Action("keys", "ctrl+w")])
    gesture.save(config.gestures_dir(profile))
    return gesture


# --- пока наборов не заводили ---
def test_without_profiles_gestures_live_where_they_always_did(tmp_path):
    """Главное обещание: у тех, кто профили не заводил, не меняется ничего."""
    assert config.gestures_dir() == tmp_path / "gestures"
    assert config.available_profiles() == []
    assert config.active_profile() == ""


def test_settings_carry_no_profile_by_default():
    assert Settings().active_profile == ""


# --- заведение и переключение ---
def test_a_new_profile_starts_empty():
    make_gesture("Назад")
    config.create_profile("игры")
    config.use_profile("игры")
    assert load_gestures() == []
    assert config.gestures_dir().name == "игры"


def test_a_copy_takes_the_gestures_along():
    make_gesture("Назад")
    config.create_profile("игры", copy_from="")
    config.use_profile("игры")
    assert [g.name for g in load_gestures()] == ["Назад"]


def test_sets_do_not_mix():
    make_gesture("Назад")
    config.create_profile("игры")
    make_gesture("Огонь", profile="игры")
    assert [g.name for g in load_gestures()] == ["Назад"]
    config.use_profile("игры")
    assert [g.name for g in load_gestures()] == ["Огонь"]
    config.use_profile("")
    assert [g.name for g in load_gestures()] == ["Назад"]


def test_the_choice_is_remembered_in_the_settings():
    config.create_profile("игры")
    config.use_profile("игры")
    assert Settings.load().active_profile == "игры"


def test_switching_to_an_unknown_set_is_refused():
    with pytest.raises(ValueError):
        config.use_profile("нетакого")


def test_a_name_cannot_escape_the_directory():
    """Иначе «../../» увело бы жесты куда угодно."""
    config.create_profile("../злой")
    assert config.available_profiles() == ["-злой"]


def test_two_sets_cannot_share_a_name():
    config.create_profile("игры")
    with pytest.raises(ValueError):
        config.create_profile("игры")


def test_a_set_needs_a_name():
    with pytest.raises(ValueError):
        config.create_profile("   ")


# --- удаление ---
def test_removing_the_current_set_returns_to_the_base_one():
    make_gesture("Назад")
    config.create_profile("игры")
    config.use_profile("игры")
    config.remove_profile("игры")
    assert config.active_profile() == ""
    assert [g.name for g in load_gestures()] == ["Назад"]


def test_the_base_set_cannot_be_removed():
    with pytest.raises(ValueError):
        config.remove_profile("")


def test_removing_an_unknown_set_is_refused():
    with pytest.raises(ValueError):
        config.remove_profile("нетакого")


def test_a_vanished_set_falls_back_to_the_base_one(tmp_path):
    """Остаться вовсе без жестов хуже, чем откатиться к тому, что точно есть."""
    make_gesture("Назад")
    config.create_profile("игры")
    config.use_profile("игры")
    import shutil
    shutil.rmtree(tmp_path / "profiles" / "игры")
    assert config.active_profile() == ""
    assert [g.name for g in load_gestures()] == ["Назад"]


def test_size_is_counted_without_reading_the_gestures():
    make_gesture("Назад")
    make_gesture("Вперёд")
    assert config.profile_size("") == 2
    config.create_profile("игры")
    assert config.profile_size("игры") == 0


# --- командная строка ---
def run(argv) -> int:
    from glyphstroke.cli import main
    return main(argv)


def test_the_command_line_switches_sets(capsys):
    make_gesture("Назад")
    assert run(["profile", "new", "игры", "--copy", "--use"]) == 0
    assert config.active_profile() == "игры"
    assert [g.name for g in load_gestures()] == ["Назад"]
    capsys.readouterr()
    assert run(["profile", "use", "-"]) == 0
    assert config.active_profile() == ""


def test_the_base_set_answers_to_its_name(capsys):
    config.create_profile("игры")
    config.use_profile("игры")
    assert run(["profile", "use", "основной"]) == 0
    assert config.active_profile() == ""


def test_the_listing_marks_the_current_set(capsys):
    config.create_profile("игры")
    config.use_profile("игры")
    run(["profile"])
    out = capsys.readouterr().out
    assert "* игры" in out
    assert "  основной" in out


def test_a_bad_name_ends_with_an_error(capsys):
    assert run(["profile", "use", "нетакого"]) == 1
    assert "нетакого" in capsys.readouterr().err


def test_the_gesture_listing_names_the_set(capsys):
    """Пока наборов нет, про них молчим — вывод не должен меняться у всех."""
    make_gesture("Назад")
    run(["list"])
    assert "набор:" not in capsys.readouterr().out
    config.create_profile("игры")
    run(["list"])
    assert "набор: основной" in capsys.readouterr().out


# --- демон ---
def test_the_daemon_takes_the_gestures_of_the_current_set():
    """Ради этого всё и затевалось: переключение меняет то, что ловит демон."""
    pytest.importorskip("evdev")
    from glyphstroke.daemon import Daemon

    make_gesture("Назад")
    config.create_profile("игры")
    make_gesture("Огонь", profile="игры")

    daemon = Daemon(Settings())
    assert [g.name for g in daemon.gestures] == ["Назад"]
    config.use_profile("игры")
    daemon.reload()
    assert [g.name for g in daemon.gestures] == ["Огонь"]
    config.use_profile("")
    daemon.reload()
    assert [g.name for g in daemon.gestures] == ["Назад"]
