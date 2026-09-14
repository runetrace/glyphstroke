"""Чтение, запись и фильтры конфигурации."""

from __future__ import annotations

import pytest

from glyphstroke import config
from glyphstroke.config import Action, Gesture, Settings, load_gestures


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_gesture_round_trip(tmp_path):
    gesture = Gesture(
        name="Закрыть вкладку",
        directions=["D"],
        templates=[[(0.0, 0.0), (10.5, 20.25)]],
        actions=[Action("keys", "ctrl+w")],
        apps=["firefox"],
    )
    gesture.save()
    loaded = load_gestures()
    assert len(loaded) == 1
    got = loaded[0]
    assert got.name == "Закрыть вкладку"
    assert got.directions == ["D"]
    assert got.templates[0][1] == (10.5, 20.2)  # точки пишутся с одним знаком
    assert got.actions[0].type == "keys" and got.actions[0].value == "ctrl+w"
    assert got.apps == ["firefox"]


def test_filename_is_transliteration_safe():
    path = Gesture(name="Закрыть окно!").save()
    assert path.name.endswith(".yaml") and " " not in path.name


def test_saving_twice_does_not_multiply_files():
    gesture = Gesture(name="Один")
    gesture.save()
    gesture.name = "Один"
    gesture.save()
    assert len(list(config.gestures_dir().glob("*.yaml"))) == 1


def test_app_filter():
    everywhere = Gesture(name="везде")
    only_firefox = Gesture(name="только firefox", apps=["firefox"])
    assert everywhere.matches_app(None) and everywhere.matches_app("gedit | текст")
    assert only_firefox.matches_app("Navigator | Firefox")
    assert not only_firefox.matches_app("gedit | текст")
    assert not only_firefox.matches_app(None), \
        "жест с фильтром не должен срабатывать, когда окно неизвестно"


def test_settings_round_trip():
    settings = Settings(trigger_button="BTN_MIDDLE", min_stroke_px=99)
    settings.overlay.color = "#ff0000"
    settings.save()
    loaded = Settings.load()
    assert loaded.trigger_button == "BTN_MIDDLE"
    assert loaded.min_stroke_px == 99
    assert loaded.overlay.color == "#ff0000"


def test_unknown_settings_keys_are_ignored(tmp_path):
    (tmp_path / "settings.yaml").write_text(
        "trigger_button: BTN_RIGHT\nиз_будущей_версии: 1\n", encoding="utf-8")
    assert Settings.load().trigger_button == "BTN_RIGHT"


def test_broken_gesture_file_does_not_break_the_rest(tmp_path):
    config.gestures_dir().mkdir(parents=True, exist_ok=True)
    (config.gestures_dir() / "bad.yaml").write_text("{[не yaml", encoding="utf-8")
    Gesture(name="Хороший", directions=["R"]).save()
    assert [g.name for g in load_gestures()] == ["Хороший"]


def test_default_set_is_installed():
    config.ensure_default_config()
    gestures = load_gestures()
    assert len(gestures) >= 6
    codes = {tuple(g.directions) for g in gestures if g.directions}
    assert ("D-R",) in codes and ("L",) in codes
    from glyphstroke.config import find_conflicts
    assert find_conflicts(gestures) == {}, "жесты набора не должны спорить друг с другом"
    assert {g.event for g in gestures if g.event} >= {"rocker-left", "wheel-up"}, \
        "в наборе должны быть примеры особых жестов"


# --- диагностика окружения --------------------------------------------------
class _FakeGroup:
    def __init__(self, gid, members):
        self.gr_gid = gid
        self.gr_mem = members


class _FakeUser:
    def __init__(self, name):
        self.pw_name = name


@pytest.fixture
def as_regular_user(monkeypatch):
    """Притворяемся обычным пользователем, а не root."""
    import grp
    import os
    import pwd
    monkeypatch.setattr(os, "getuid", lambda: 1000)
    monkeypatch.setattr(pwd, "getpwuid", lambda uid: _FakeUser("tester"))
    return monkeypatch, grp, os


def test_group_effective_when_session_has_it(as_regular_user):
    monkeypatch, grp, os = as_regular_user
    monkeypatch.setattr(grp, "getgrnam", lambda name: _FakeGroup(107, ["tester"]))
    monkeypatch.setattr(os, "getgroups", lambda: [1000, 107])
    from glyphstroke.cli import group_state
    assert group_state("input") == "effective"


def test_group_pending_until_relogin(as_regular_user):
    """Записан в /etc/group, но сеанс начался раньше — самый частый случай."""
    monkeypatch, grp, os = as_regular_user
    monkeypatch.setattr(grp, "getgrnam", lambda name: _FakeGroup(107, ["tester"]))
    monkeypatch.setattr(os, "getgroups", lambda: [1000])
    from glyphstroke.cli import group_state
    assert group_state("input") == "pending"


def test_group_absent_when_not_a_member(as_regular_user):
    monkeypatch, grp, os = as_regular_user
    monkeypatch.setattr(grp, "getgrnam", lambda name: _FakeGroup(107, ["someone"]))
    monkeypatch.setattr(os, "getgroups", lambda: [1000])
    from glyphstroke.cli import group_state
    assert group_state("input") == "absent"


def test_group_absent_when_group_does_not_exist(as_regular_user):
    monkeypatch, grp, os = as_regular_user
    def boom(name):
        raise KeyError(name)
    monkeypatch.setattr(grp, "getgrnam", boom)
    from glyphstroke.cli import group_state
    assert group_state("input") == "absent"


def test_root_always_effective():
    from glyphstroke.cli import group_state
    import os
    if os.getuid() != 0:
        pytest.skip("проверка для root")
    assert group_state("input") == "effective"


def test_device_node_info_shows_owner_and_mode(tmp_path):
    import re
    from glyphstroke.cli import device_node_info
    node = tmp_path / "fake-uinput"
    node.write_bytes(b"")
    node.chmod(0o660)
    assert re.fullmatch(r"\S+:\S+ 660", device_node_info(str(node)))


def test_device_node_info_when_missing():
    from glyphstroke.cli import device_node_info
    assert device_node_info("/dev/точно-нет-такого") == "нет устройства"


# --- жесты, описанные одинаково ---
def test_two_gestures_with_the_same_code_are_reported():
    from glyphstroke.config import find_conflicts
    gestures = [Gesture(name="Новая вкладка", directions=["U"]),
                Gesture(name="Копировать", directions=["U"])]
    assert find_conflicts(gestures) == {"U": ["Новая вкладка", "Копировать"]}


def test_disabled_gesture_does_not_conflict():
    from glyphstroke.config import find_conflicts
    gestures = [Gesture(name="Новая вкладка", directions=["U"]),
                Gesture(name="Копировать", directions=["U"], enabled=False)]
    assert find_conflicts(gestures) == {}


def test_different_codes_do_not_conflict():
    from glyphstroke.config import find_conflicts
    assert find_conflicts([Gesture(name="а", directions=["U"]),
                           Gesture(name="б", directions=["D"])]) == {}


def test_conflict_check_ignores_case_and_spaces():
    from glyphstroke.config import find_conflicts
    assert find_conflicts([Gesture(name="а", directions=["d-r"]),
                           Gesture(name="б", directions=[" D-R "])]) == {
        "D-R": ["а", "б"]}


def test_gestures_with_samples_only_never_conflict():
    from glyphstroke.config import find_conflicts
    assert find_conflicts([Gesture(name="а", templates=[[(0, 0), (1, 1)]]),
                           Gesture(name="б", templates=[[(0, 0), (2, 2)]])]) == {}


# --- перенос жестов между машинами ---
def test_export_then_import_restores_everything(tmp_path):
    from glyphstroke.config import export_bundle, import_bundle
    Gesture(name="Копировать", directions=["U"],
            actions=[Action("keys", "ctrl+c")]).save()
    Gesture(name="Свернуть", templates=[[(0.0, 0.0), (10.0, 20.0)]],
            actions=[Action("window", "minimize")]).save()
    bundle = tmp_path / "жесты.yaml"
    assert export_bundle(bundle) == 2

    for gesture in load_gestures():
        gesture.delete()
    assert load_gestures() == []

    result = import_bundle(bundle)
    assert sorted(result.added) == ["Копировать", "Свернуть"]
    restored = {g.name: g for g in load_gestures()}
    assert restored["Копировать"].actions[0].value == "ctrl+c"
    assert restored["Свернуть"].templates[0][1] == (10.0, 20.0)


def test_import_replaces_gestures_with_the_same_name(tmp_path):
    from glyphstroke.config import export_bundle, import_bundle
    Gesture(name="Назад", directions=["L"], actions=[Action("keys", "alt+Left")]).save()
    bundle = tmp_path / "b.yaml"
    export_bundle(bundle)
    # меняем жест у себя, потом загружаем файл поверх
    saved = load_gestures()[0]
    saved.actions = [Action("keys", "ctrl+z")]
    saved.save()

    result = import_bundle(bundle)
    assert result.replaced == ["Назад"] and result.added == []
    assert load_gestures()[0].actions[0].value == "alt+Left"
    assert len(list(config.gestures_dir().glob("*.yaml"))) == 1, "дубли файлов не нужны"


def test_import_with_replace_wipes_previous(tmp_path):
    from glyphstroke.config import export_bundle, import_bundle
    Gesture(name="Чужой", directions=["R"]).save()
    bundle = tmp_path / "b.yaml"
    export_bundle(bundle, gestures=[Gesture(name="Новый", directions=["L"])])

    result = import_bundle(bundle, replace=True)
    assert result.removed == 1
    assert [g.name for g in load_gestures()] == ["Новый"]


def test_import_can_bring_settings(tmp_path):
    from glyphstroke.config import export_bundle, import_bundle
    export_bundle(tmp_path / "b.yaml", gestures=[],
                  settings=Settings(trigger_button="BTN_MIDDLE", min_stroke_px=77))
    result = import_bundle(tmp_path / "b.yaml", with_settings=True)
    assert result.settings_applied
    assert Settings.load().trigger_button == "BTN_MIDDLE"
    assert Settings.load().min_stroke_px == 77


def test_import_leaves_settings_alone_by_default(tmp_path):
    from glyphstroke.config import export_bundle, import_bundle
    export_bundle(tmp_path / "b.yaml", gestures=[],
                  settings=Settings(trigger_button="BTN_MIDDLE"))
    import_bundle(tmp_path / "b.yaml")
    assert Settings.load().trigger_button == "BTN_RIGHT"


def test_import_refuses_a_foreign_file(tmp_path):
    from glyphstroke.config import import_bundle
    (tmp_path / "чужой.yaml").write_text("привет: мир\n", encoding="utf-8")
    with pytest.raises(ValueError):
        import_bundle(tmp_path / "чужой.yaml")


def test_import_refuses_a_newer_format(tmp_path):
    from glyphstroke.config import import_bundle
    (tmp_path / "b.yaml").write_text("glyphstroke: 99\ngestures: []\n", encoding="utf-8")
    with pytest.raises(ValueError):
        import_bundle(tmp_path / "b.yaml")


# --- переезд со старого имени ---
@pytest.fixture
def legacy_home(tmp_path, monkeypatch):
    """Каталог настроек прежнего имени со своими жестами."""
    monkeypatch.delenv("GLYPHSTROKE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(config, "_migrated", False)
    old = tmp_path / "strokeit"
    (old / "gestures").mkdir(parents=True)
    (old / "settings.yaml").write_text("trigger_button: BTN_MIDDLE\n", encoding="utf-8")
    (old / "gestures" / "moy.yaml").write_text(
        "name: Мой жест\ndirections: [U-L]\nactions:\n  - {type: keys, value: ctrl+c}\n",
        encoding="utf-8")
    return old


def test_settings_move_from_the_previous_name(legacy_home):
    """До версии 0.3 программа звалась strokeit — жесты не должны потеряться."""
    assert config.migrate_legacy_config() == legacy_home
    assert [g.name for g in load_gestures()] == ["Мой жест"]
    assert Settings.load().trigger_button == "BTN_MIDDLE"


def test_previous_directory_is_left_alone(legacy_home):
    config.migrate_legacy_config()
    assert (legacy_home / "settings.yaml").exists(), \
        "прежняя установка должна остаться рабочей"


def test_migration_does_not_overwrite_existing_settings(legacy_home):
    config.config_dir().mkdir(parents=True)
    Settings(trigger_button="BTN_SIDE").save()
    assert config.migrate_legacy_config() is None
    assert Settings.load().trigger_button == "BTN_SIDE"


def test_migration_happens_once(legacy_home):
    assert config.migrate_legacy_config() == legacy_home
    assert config.migrate_legacy_config() is None


def test_nothing_to_migrate(tmp_path, monkeypatch):
    monkeypatch.delenv("GLYPHSTROKE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(config, "_migrated", False)
    assert config.migrate_legacy_config() is None


def test_explicit_config_dir_disables_migration(tmp_path, monkeypatch):
    """Когда каталог задан явно (в том числе в тестах), переезд не нужен."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "strokeit").mkdir()
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path / "явный"))
    monkeypatch.setattr(config, "_migrated", False)
    assert config.migrate_legacy_config() is None


# --- особые жесты и области видимости ---
def test_event_gesture_round_trip():
    Gesture(name="Назад (rocker)", event="rocker-left",
            actions=[Action("keys", "alt+Left")]).save()
    loaded = load_gestures()[0]
    assert loaded.event == "rocker-left"
    assert not loaded.directions


def test_bound_events_takes_only_enabled():
    from glyphstroke.config import bound_events
    active = Gesture(name="Колесо", event="wheel-up")
    off = Gesture(name="Выключенный", event="wheel-down", enabled=False)
    assert set(bound_events([active, off])) == {"wheel-up"}


def test_app_gesture_does_not_conflict_with_a_global_one():
    """Один росчерк, разное действие в разных приложениях — это норма."""
    from glyphstroke.config import find_conflicts
    assert find_conflicts([
        Gesture(name="Закрыть вкладку", directions=["D"]),
        Gesture(name="Удалить строку", directions=["D"], apps=["code"]),
    ]) == {}


def test_two_gestures_for_the_same_app_do_conflict():
    from glyphstroke.config import find_conflicts
    conflicts = find_conflicts([
        Gesture(name="Первый", directions=["D"], apps=["code"]),
        Gesture(name="Второй", directions=["D"], apps=["code", "gedit"]),
    ])
    assert conflicts == {"D": ["Первый", "Второй"]}


def test_gestures_for_different_apps_live_together():
    from glyphstroke.config import find_conflicts
    assert find_conflicts([
        Gesture(name="В редакторе", directions=["D"], apps=["code"]),
        Gesture(name="В браузере", directions=["D"], apps=["firefox"]),
    ]) == {}


def test_two_global_gestures_still_conflict():
    from glyphstroke.config import find_conflicts
    assert "D" in find_conflicts([Gesture(name="а", directions=["D"]),
                                  Gesture(name="б", directions=["D"])])


def test_events_conflict_too():
    from glyphstroke.config import find_conflicts
    assert "rocker-left" in find_conflicts([
        Gesture(name="а", event="rocker-left"),
        Gesture(name="б", event="rocker-left"),
    ])


# --- вид следа ---
def test_trail_style_round_trip():
    settings = Settings()
    settings.overlay.color = "#ff8800"
    settings.overlay.width = 7
    settings.overlay.opacity = 0.35
    settings.save()
    loaded = Settings.load().overlay
    assert (loaded.color, loaded.width, loaded.opacity) == ("#ff8800", 7, 0.35)


def test_trail_has_sensible_defaults():
    overlay = Settings().overlay
    assert overlay.color.startswith("#") and len(overlay.color) == 7
    assert 1 <= overlay.width <= 24
    assert 0 < overlay.opacity <= 1
