"""Разбор команд и передача управления подкомандам."""

from __future__ import annotations

import pytest

from glyphstroke import config
from glyphstroke.cli import build_parser, main


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    return tmp_path


ALL_COMMANDS = [
    ["init"], ["list"], ["devices"], ["doctor"], ["gui"], ["test"],
    ["daemon"], ["daemon", "--dry-run"], ["daemon", "--monitor"],
    ["record", "Имя"], ["record", "Имя", "-n", "5", "--keys", "ctrl+w"],
    ["install"], ["service", "enable"], ["service", "status"],
]


@pytest.mark.parametrize("argv", ALL_COMMANDS)
def test_every_subcommand_parses_and_has_handler(argv):
    args = build_parser().parse_args(argv)
    assert callable(args.func), f"у команды {argv} нет обработчика"


def test_gui_does_not_receive_the_subcommand_name(monkeypatch):
    """«glyphstroke gui» не должен передавать редактору слово gui как аргумент."""
    gui_module = pytest.importorskip("glyphstroke.gui")
    seen: list = []

    def fake_main(argv=None):
        seen.append(argv)
        return 0

    monkeypatch.setattr(gui_module, "main", fake_main)
    assert main(["gui"]) == 0
    assert seen == [[]], f"редактору ушло: {seen}"


def test_init_creates_settings_and_gestures(tmp_path, capsys):
    assert main(["init"]) == 0
    assert (tmp_path / "settings.yaml").exists()
    assert list((tmp_path / "gestures").glob("*.yaml"))
    assert "жестов в наборе" in capsys.readouterr().out


def test_list_shows_gestures(capsys):
    config.ensure_default_config()
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "Закрыть окно" in out and "alt+F4" in out


def test_list_without_config_is_an_error(capsys):
    assert main(["list"]) == 1
    assert "glyphstroke init" in capsys.readouterr().out


# --- расширение GNOME Shell ---
@pytest.fixture
def fake_share(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    return tmp_path / "share"


def test_extension_install_copies_the_files(fake_share, capsys):
    from glyphstroke.cli import extension_dir
    assert main(["shell-extension", "install"]) == 0
    target = extension_dir()
    assert (target / "metadata.json").exists()
    assert (target / "extension.js").exists()
    assert "установлено" in capsys.readouterr().out


def test_extension_metadata_declares_this_gnome(fake_share):
    import json
    from glyphstroke.cli import extension_dir
    main(["shell-extension", "install"])
    meta = json.loads((extension_dir() / "metadata.json").read_text(encoding="utf-8"))
    assert meta["uuid"] == "glyphstroke@glyphstroke.local"
    assert "47" in meta["shell-version"], "Ubuntu 24.10 и 25.04 несут GNOME 47–48"


def test_extension_status_without_installation(fake_share, capsys):
    assert main(["shell-extension", "status"]) == 0
    assert "не установлено" in capsys.readouterr().out


def test_extension_remove_is_idempotent(fake_share, capsys):
    main(["shell-extension", "install"])
    assert main(["shell-extension", "remove"]) == 0
    assert main(["shell-extension", "remove"]) == 0
    from glyphstroke.cli import extension_dir
    assert not extension_dir().exists()


def test_reinstall_over_existing_copy(fake_share):
    from glyphstroke.cli import extension_dir
    main(["shell-extension", "install"])
    (extension_dir() / "мусор.txt").write_text("старое", encoding="utf-8")
    main(["shell-extension", "install"])
    assert not (extension_dir() / "мусор.txt").exists(), \
        "переустановка должна класть чистую копию"


def test_enable_via_gsettings_appends_without_losing_others(monkeypatch):
    """Список включённых расширений нельзя затирать чужими значениями."""
    from glyphstroke import cli
    calls = []

    class Result:
        def __init__(self, out="", code=0):
            self.stdout, self.returncode = out, code

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["gsettings", "get"]:
            return Result("['ubuntu-dock@ubuntu.com', 'ding@rastersoft.com']\n")
        return Result()

    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.enable_via_gsettings() is True
    written = [c for c in calls if c[:2] == ["gsettings", "set"]][0][-1]
    assert "ubuntu-dock@ubuntu.com" in written and "ding@rastersoft.com" in written
    assert cli.EXTENSION_UUID in written


def test_enable_via_gsettings_is_idempotent(monkeypatch):
    from glyphstroke import cli
    calls = []

    class Result:
        def __init__(self, out="", code=0):
            self.stdout, self.returncode = out, code

    def fake_run(argv, **kwargs):
        calls.append(argv)
        if argv[:2] == ["gsettings", "get"]:
            return Result(f"['{cli.EXTENSION_UUID}']\n")
        return Result()

    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.enable_via_gsettings() is True
    assert not [c for c in calls if c[:2] == ["gsettings", "set"]], \
        "повторно дописывать не нужно"


def test_enable_via_gsettings_without_gnome(monkeypatch):
    from glyphstroke import cli
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    assert cli.enable_via_gsettings() is False


# --- наблюдение за распознаванием ---
def test_stroke_line_for_a_recognized_gesture():
    from glyphstroke.cli import format_stroke_line
    text = format_stroke_line("stroke\tD-R\tЗакрыть окно\t1.00\tВперёд\t0.20")
    assert "D-R" in text and "Закрыть окно" in text and "1.00" in text


def test_stroke_line_for_an_unrecognized_one():
    from glyphstroke.cli import format_stroke_line
    text = format_stroke_line("stroke\tDR\t-\t0.75\tВперёд\t0.75")
    assert "не распознано" in text and "Вперёд" in text


def test_other_channel_lines_are_ignored():
    from glyphstroke.cli import format_stroke_line
    assert format_stroke_line("begin #4da3ff 4") is None
    assert format_stroke_line("end") is None


def test_watch_without_a_running_daemon(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert main(["watch"]) == 1
    assert "демон не запущен" in capsys.readouterr().err


def test_record_pauses_the_running_service(monkeypatch):
    """Демон держит мышь эксклюзивно — записать жест поверх него нельзя."""
    from glyphstroke import cli
    calls = []
    monkeypatch.setattr(cli, "service_is_active", lambda: True)
    monkeypatch.setattr(cli.subprocess, "run",
                        lambda argv, **kw: calls.append(argv) or type("R", (), {"returncode": 0})())
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    with cli.ServicePause(announce=False):
        pass
    assert ["systemctl", "--user", "stop", "glyphstroke"] in calls
    assert ["systemctl", "--user", "start", "glyphstroke"] in calls


def test_service_pause_does_nothing_when_service_is_off(monkeypatch):
    from glyphstroke import cli
    calls = []
    monkeypatch.setattr(cli, "service_is_active", lambda: False)
    monkeypatch.setattr(cli.subprocess, "run", lambda argv, **kw: calls.append(argv))
    with cli.ServicePause(announce=False):
        pass
    assert calls == []


# --- версия работающего демона ---
def test_hello_line_of_a_matching_version():
    from glyphstroke.cli import format_hello
    from glyphstroke.version import __version__
    text = format_hello(f"hello\t{__version__}\t4242")
    assert __version__ in text and "4242" in text
    assert "ВНИМАНИЕ" not in text


def test_hello_line_warns_about_an_old_daemon():
    """Самая частая причина «поправил, а не работает» — старый код в /opt."""
    from glyphstroke.cli import format_hello
    text = format_hello("hello\t0.0.1\t7")
    assert "ВНИМАНИЕ" in text and "restart" in text


def test_daemon_info_without_a_running_daemon(monkeypatch, tmp_path):
    from glyphstroke.cli import daemon_info
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert daemon_info() is None


def test_daemon_info_reads_the_greeting(monkeypatch, tmp_path):
    from glyphstroke.cli import daemon_info
    from glyphstroke.ipc import OverlayServer
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    (tmp_path / "glyphstroke").mkdir()
    server = OverlayServer(greeting="hello\t9.9.9\t555\tpaused")
    server.start()
    try:
        assert daemon_info() == ("9.9.9", "555", "paused")
    finally:
        server.stop()


def test_daemon_info_defaults_to_active_for_an_old_daemon(monkeypatch, tmp_path):
    """Демон прошлой версии не сообщает состояние — считаем, что работает."""
    from glyphstroke.cli import daemon_info
    from glyphstroke.ipc import OverlayServer
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    (tmp_path / "glyphstroke").mkdir()
    server = OverlayServer(greeting="hello\t0.1.0\t7")
    server.start()
    try:
        assert daemon_info() == ("0.1.0", "7", "active")
    finally:
        server.stop()


def test_saved_stroke_keeps_code_and_points(tmp_path):
    from glyphstroke.cli import save_stroke
    path = save_stroke(tmp_path, "points\t0,0 10,5 20,10", "stroke\tD-R\tЗакрыть окно\t1.00\t-\t0.00")
    text = path.read_text(encoding="utf-8")
    assert "code: D-R" in text
    assert "recognized: Закрыть окно" in text
    assert "0,0 10,5 20,10" in text


def test_saved_stroke_survives_an_unrecognized_one(tmp_path):
    from glyphstroke.cli import save_stroke
    path = save_stroke(tmp_path, "points\t0,0 5,5", "")
    assert "code: -" in path.read_text(encoding="utf-8")


def test_watch_shows_what_was_actually_executed():
    """Иначе не отличить «жест не сработал» от «приложение не знает сочетания»."""
    from glyphstroke.cli import format_stroke_line
    text = format_stroke_line("action\tЗакрыть вкладку\tkeys ctrl+w\t-")
    assert "выполнено" in text and "ctrl+w" in text


def test_watch_shows_the_window_when_it_is_known():
    from glyphstroke.cli import format_stroke_line
    text = format_stroke_line("action\tНазад\tkeys alt+Left\tNavigator | Firefox")
    assert "Firefox" in text


# --- о программе ---
def test_about_shows_version_author_and_contact(capsys):
    from glyphstroke import version as about
    assert main(["about"]) == 0
    out = capsys.readouterr().out
    assert about.__version__ in out
    assert about.RELEASE_DATE in out
    assert about.AUTHOR in out
    assert about.EMAIL in out
    assert about.YEARS in out


def test_about_includes_environment_for_bug_reports(capsys):
    """Вывод прикладывают к письму, поэтому окружение обязано быть в нём."""
    main(["about"])
    out = capsys.readouterr().out
    assert "Сеанс:" in out and "Демон:" in out and "Настройки:" in out


def test_about_metadata_is_consistent_with_the_package():
    import tomllib
    from pathlib import Path

    from glyphstroke import version as about
    meta = tomllib.load(open(Path(__file__).resolve().parent.parent / "pyproject.toml", "rb"))
    assert meta["project"]["version"] == about.__version__, \
        "версия в pyproject.toml разошлась с version.py"


def test_release_date_is_a_valid_date():
    import datetime

    from glyphstroke import version as about
    datetime.date.fromisoformat(about.RELEASE_DATE)
