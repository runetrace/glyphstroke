"""Логика редактора: рисование образца, сохранение, распознавание.

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
from glyphstroke.config import Action, load_gestures  # noqa: E402


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    config.ensure_default_config()
    from glyphstroke.gui import EditorWindow
    window = EditorWindow()
    yield window
    window.destroy()
    while Gtk.events_pending():
        Gtk.main_iteration_do(False)


def corner_stroke():
    return [(20.0, 20.0 + i * 4) for i in range(40)] + \
           [(20.0 + i * 4, 180.0) for i in range(40)]


def test_editor_lists_default_gestures(editor):
    assert len(editor.gestures) >= 6
    assert editor.current is not None, "первый жест должен быть выбран сразу"


def test_drawing_gives_direction_code(editor):
    editor.on_canvas_stroke(corner_stroke())
    editor.code_from_stroke()
    assert editor.directions_entry.get_text() == "D-R"


def test_sample_is_saved_to_yaml(editor, tmp_path):
    """Нарисованное становится образцом сразу, без отдельной кнопки."""
    editor.on_add(None)
    editor.name_entry.set_text("Мой жест")
    editor.on_canvas_stroke(corner_stroke())
    editor.on_save(None)
    saved = {g.name: g for g in load_gestures()}
    assert "Мой жест" in saved
    assert len(saved["Мой жест"].templates[0]) == 64, "образец пишется как 64 точки"


def test_save_requires_a_stroke_or_a_code(editor):
    editor.on_add(None)
    editor.name_entry.set_text("Пустой")
    editor.on_save(None)
    assert "нарисуйте" in editor.status.get_text().lower(), \
        "подсказка должна звать нарисовать росчерк"
    assert "Пустой" not in {g.name for g in load_gestures()}


def test_actions_survive_a_round_trip(editor):
    editor.on_add(None)
    editor.name_entry.set_text("С действиями")
    editor.directions_entry.set_text("U-L")
    for child in editor.actions_box.get_children():
        editor.actions_box.remove(child)
    editor.add_action_row(Action("command", "gnome-terminal"))
    editor.add_action_row(Action("delay", "100"))
    editor.on_save(None)
    saved = {g.name: g for g in load_gestures()}["С действиями"]
    assert [(a.type, a.value) for a in saved.actions] == [
        ("command", "gnome-terminal"), ("delay", "100")]


def test_check_stroke_reports_recognized_gesture(editor):
    editor.on_canvas_stroke(corner_stroke())
    editor.check_stroke()
    assert "Закрыть окно" in editor.status.get_text()


def test_toggle_switches_gesture_off(editor):
    editor.tree.get_selection().select_path(Gtk.TreePath(0))
    name = editor.gestures[0].name
    editor.on_toggle_enabled(None, "0")
    assert not {g.name: g for g in load_gestures()}[name].enabled


# --- настройки следа ---
def test_trail_style_is_read_from_the_controls(editor):
    from gi.repository import Gdk
    colour = Gdk.RGBA()
    colour.parse("#ff8800")
    editor.color_button.set_rgba(colour)
    editor.trail_width.set_value(9)
    editor.trail_opacity.set_value(40)
    rgb, width, opacity = editor.trail_style()
    assert width == 9
    assert opacity == pytest.approx(0.4)
    assert rgb[0] == pytest.approx(1.0) and rgb[2] == pytest.approx(0.0)


def test_saving_settings_stores_the_trail(editor):
    from gi.repository import Gdk
    colour = Gdk.RGBA()
    colour.parse("#20c040")
    editor.color_button.set_rgba(colour)
    editor.trail_width.set_value(6)
    editor.trail_opacity.set_value(55)
    editor.save_settings()
    from glyphstroke.config import Settings
    overlay = Settings.load().overlay
    assert overlay.color == "#20c040"
    assert overlay.width == 6
    assert overlay.opacity == pytest.approx(0.55)


def test_preview_follows_the_controls(editor):
    editor.trail_width.set_value(11)
    editor.refresh_trail_preview()
    assert editor.trail_preview.line_width == 11


# --- меню под жестом ---
def test_menu_items_survive_a_round_trip(editor):
    from glyphstroke.config import MenuItem

    editor.on_add(None)
    editor.name_entry.set_text("С меню")
    editor.directions_entry.set_text("U-R")
    editor.add_menu_row(MenuItem("Копировать", [Action("keys", "ctrl+c")]))
    editor.add_menu_row(MenuItem("Вставить", [Action("keys", "ctrl+v")]))
    editor.on_save(None)
    saved = {g.name: g for g in load_gestures()}["С меню"]
    assert [(i.name, i.actions[0].value) for i in saved.menu] == [
        ("Копировать", "ctrl+c"), ("Вставить", "ctrl+v")]


def test_a_gesture_without_a_menu_gets_no_rows(editor):
    """Пустая вкладка — обычный жест: пункта «на всякий случай» тут не заводим."""
    editor.on_add(None)
    assert editor.menu_box.get_children() == []


def test_an_unnamed_item_is_not_saved(editor):
    from glyphstroke.config import MenuItem

    editor.on_add(None)
    editor.name_entry.set_text("Без названий")
    editor.directions_entry.set_text("R-D")
    editor.add_menu_row(MenuItem("", [Action("keys", "ctrl+c")]))
    editor.on_save(None)
    assert {g.name: g for g in load_gestures()}["Без названий"].menu == []


# --- автозапуск ---
def autostart_probe(editor, monkeypatch, state: dict):
    """Кнопка спрашивает systemd, а её нажатие туда же и пишет."""
    from glyphstroke import cli

    monkeypatch.setattr(cli, "service_is_enabled", lambda: state["enabled"])
    done: list[bool] = []

    def set_autostart(enabled):
        done.append(enabled)
        state["enabled"] = enabled

    monkeypatch.setattr(editor, "set_autostart", set_autostart)
    editor.refresh_autostart()
    return done


def test_autostart_button_is_pressed_when_it_was_set_before(editor, monkeypatch):
    """Включённый автозапуск должен быть виден сразу при открытии настроек."""
    autostart_probe(editor, monkeypatch, {"enabled": True})
    assert editor.autostart_button.get_active()
    assert editor.autostart_button.get_style_context().has_class("suggested-action"), \
        "включённый автозапуск должен быть подсвечен"


def test_autostart_button_is_released_when_it_is_off(editor, monkeypatch):
    autostart_probe(editor, monkeypatch, {"enabled": False})
    assert not editor.autostart_button.get_active()
    assert not editor.autostart_button.get_style_context().has_class("suggested-action")
    assert editor.autostart_button.get_sensitive()


def test_without_systemd_the_button_does_nothing(editor, monkeypatch):
    done = autostart_probe(editor, monkeypatch, {"enabled": None})
    assert not editor.autostart_button.get_sensitive()
    assert not editor.autostart_button.get_active()
    assert done == []


def test_refreshing_runs_no_commands(editor, monkeypatch):
    """Иначе открытие настроек само включало бы автозапуск."""
    done = autostart_probe(editor, monkeypatch, {"enabled": True})
    editor.refresh_autostart()
    assert done == []


def test_pressing_the_button_turns_autostart_on(editor, monkeypatch):
    done = autostart_probe(editor, monkeypatch, {"enabled": False})
    editor.autostart_button.set_active(True)
    assert done == [True]
    assert editor.autostart_button.get_style_context().has_class("suggested-action")


def test_releasing_the_button_puts_it_back(editor, monkeypatch):
    """Отжатие возвращает к начальному состоянию — служба больше не стартует."""
    done = autostart_probe(editor, monkeypatch, {"enabled": True})
    editor.autostart_button.set_active(False)
    assert done == [False]
    assert not editor.autostart_button.get_style_context().has_class("suggested-action")


def test_the_button_returns_to_the_truth_when_the_command_fails(editor, monkeypatch):
    """Не вышло включить — кнопка не должна остаться нажатой."""
    from glyphstroke import cli

    monkeypatch.setattr(cli, "service_is_enabled", lambda: False)
    monkeypatch.setattr(editor, "set_autostart", lambda enabled: None)
    editor.refresh_autostart()
    editor.autostart_button.set_active(True)
    assert not editor.autostart_button.get_active()


# --- где что лежит ---
def test_tabs_are_only_about_the_gesture(editor):
    """Настройки всей программы среди вкладок жеста сбивали с толку."""
    titles = [editor.notebook.get_tab_label_text(editor.notebook.get_nth_page(i))
              for i in range(editor.notebook.get_n_pages())]
    assert titles == ["Росчерк", "Действия", "Меню"]


def test_the_header_button_says_it_saves_the_gesture(editor):
    assert editor.save_button.get_label() == "Сохранить жест"


def test_settings_live_in_their_own_window(editor):
    assert not editor.settings_window.get_visible()
    editor.show_settings()
    assert editor.settings_window.get_visible()
    assert editor.settings_window.get_transient_for() is editor
    editor.hide_settings()
    assert not editor.settings_window.get_visible()


def test_opening_settings_refreshes_the_service_state(editor, monkeypatch):
    """Пока окно было закрыто, службу могли включить или остановить снаружи."""
    from glyphstroke import cli

    monkeypatch.setattr(cli, "service_is_enabled", lambda: True)
    monkeypatch.setattr(editor, "set_autostart", lambda enabled: None)
    editor.show_settings()
    assert editor.autostart_button.get_active()
    editor.hide_settings()


def test_window_icon_does_not_fail_without_the_installed_theme(editor):
    """Из исходников значок берётся прямо из комплекта, а не из темы."""
    from pathlib import Path

    from glyphstroke import gui

    gui.apply_window_icon()
    assert (Path(gui.__file__).parent / "data" / "icons" / "128"
            / "glyphstroke.png").exists()


# --- наборы жестов ---
def test_the_base_set_is_chosen_and_cannot_be_deleted(editor):
    assert editor.profile_combo.get_active_id() == ""
    assert not editor.remove_profile_button.get_sensitive()
    assert editor.delete_profile(confirmed=True) is False


def test_creating_a_copy_switches_to_it(editor):
    before = len(editor.gestures)
    assert editor.create_profile("игры", copy_current=True)
    assert editor.profile_combo.get_active_id() == "игры"
    assert len(editor.gestures) == before
    assert editor.remove_profile_button.get_sensitive()


def test_an_empty_set_leaves_no_gesture_selected(editor):
    """Иначе «Сохранить жест» записал бы в новый набор жест из прежнего."""
    assert editor.create_profile("пустой", copy_current=False)
    assert editor.gestures == []
    assert editor.current is None


def test_deleting_the_set_returns_to_the_base_one(editor):
    editor.create_profile("игры", copy_current=False)
    assert editor.delete_profile(confirmed=True)
    assert editor.profile_combo.get_active_id() == ""
    assert len(editor.gestures) >= 6


def test_switching_in_the_box_reloads_the_list(editor):
    editor.create_profile("пустой", copy_current=False)
    assert editor.gestures == []
    editor.profile_combo.set_active_id("")
    assert editor.profile_combo.get_active_id() == ""
    assert len(editor.gestures) >= 6


def test_a_name_taken_twice_is_refused(editor):
    editor.create_profile("игры", copy_current=False)
    assert editor.create_profile("игры", copy_current=False) is False


def test_the_fullscreen_switch_is_saved(editor):
    """Отключение в полноэкранных — настройка, а не разовое действие."""
    from glyphstroke.config import Settings

    assert not editor.fullscreen_switch.get_active()
    editor.fullscreen_switch.set_active(True)
    editor.save_settings()
    assert Settings.load().pause_in_fullscreen


# --- где кнопка сохранения и когда появляется образец ---
def test_the_save_button_sits_in_the_tab_row(editor):
    """Она про жест, как и вкладки рядом, — в шапке ей было не место."""
    from gi.repository import Gtk as _Gtk

    assert editor.notebook.get_action_widget(_Gtk.PackType.END) is editor.save_button


def test_drawing_adds_a_sample_at_once(editor):
    editor.on_add(None)
    assert editor.current.templates == []
    editor.on_canvas_stroke(corner_stroke())
    assert len(editor.current.templates) == 1
    assert len(editor.current.templates[0]) == 64
    assert "образцов: 1" in editor.canvas_hint.get_text()


def test_a_second_stroke_adds_a_second_sample(editor):
    editor.on_add(None)
    editor.on_canvas_stroke(corner_stroke())
    editor.on_canvas_stroke(corner_stroke())
    assert len(editor.current.templates) == 2


def test_clearing_removes_the_drawn_samples(editor):
    editor.on_add(None)
    editor.on_canvas_stroke(corner_stroke())
    editor.clear_samples()
    assert editor.current.templates == []
