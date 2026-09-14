"""Расширение оболочки ставится само: демон следит за версией в домашнем каталоге."""

from __future__ import annotations

import json
import logging
import pathlib

import pytest

from glyphstroke import shellext


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(shellext, "is_gnome", lambda: True)
    # включение идёт через gnome-extensions и gsettings — их на сборочной
    # машине нет, и проверяем мы не их, а копирование
    monkeypatch.setattr(shellext, "enable", lambda: True)
    return tmp_path


def write_version(directory: pathlib.Path, version) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "metadata.json").write_text(
        json.dumps({"uuid": shellext.EXTENSION_UUID, "version": version}), encoding="utf-8")


def packaged_version() -> int:
    return shellext.extension_version(shellext.packaged_dir())


def test_missing_extension_is_installed(home):
    assert shellext.ensure_current() == "installed"
    assert shellext.extension_version(shellext.extension_dir()) == packaged_version()
    assert (shellext.extension_dir() / "extension.js").is_file()


def test_outdated_extension_is_replaced(home):
    target = shellext.extension_dir()
    write_version(target, 0)
    (target / "мусор-из-прошлой-версии.js").write_text("", encoding="utf-8")

    assert shellext.ensure_current() == "updated"
    assert shellext.extension_version(target) == packaged_version()
    assert not (target / "мусор-из-прошлой-версии.js").exists(), \
        "старые файлы должны уйти, иначе оболочка загрузит их вперемешку с новыми"


def test_current_extension_is_left_alone(home):
    target = shellext.extension_dir()
    write_version(target, packaged_version())
    marker = target / "не-трогать"
    marker.write_text("", encoding="utf-8")

    assert shellext.ensure_current() == "ok"
    assert marker.exists(), "лишняя перезапись стоила бы перезахода в систему на ровном месте"


def test_newer_extension_is_left_alone(home):
    """Свежее расширение из другого источника откатывать назад нельзя."""
    write_version(shellext.extension_dir(), packaged_version() + 1)
    assert shellext.ensure_current() == "ok"


def test_nothing_happens_outside_gnome(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setattr(shellext, "is_gnome", lambda: False)
    assert shellext.ensure_current() == "skipped"
    assert not shellext.extension_dir().exists()


def test_current_extension_is_enabled_even_when_installed(home, monkeypatch):
    """Уже установленное, но выключенное расширение демон обязан включить.

    Раньше при совпадении версий возвращалось «ok» без включения — из-за этого
    после переустановки расширение оставалось выключенным, и не было ни иконки,
    ни следа.
    """
    calls = []
    monkeypatch.setattr(shellext, "enable", lambda: calls.append(True) or True)
    write_version(shellext.extension_dir(), packaged_version())
    assert shellext.ensure_current() == "ok"
    assert calls, "включение должно вызываться и для уже установленной копии"


def test_system_copy_is_enabled_not_recopied(home, monkeypatch):
    """Есть системная копия (из .deb) — своя в ~/.local не создаётся."""
    system = home / "system-ext"
    write_version(system, packaged_version())
    monkeypatch.setattr(shellext, "system_extension_dir", lambda: system)
    calls = []
    monkeypatch.setattr(shellext, "enable", lambda: calls.append(True) or True)

    assert shellext.ensure_current() == "ok"
    assert calls, "системную копию нужно включить"
    assert not shellext.extension_dir().exists(), \
        "при свежей системной копии дублировать её в дом не нужно"


def test_stale_user_copy_removed_when_system_is_current(home, monkeypatch):
    """Устаревшая копия в ~/.local не должна затенять свежую системную."""
    system = home / "system-ext"
    write_version(system, packaged_version())
    monkeypatch.setattr(shellext, "system_extension_dir", lambda: system)
    monkeypatch.setattr(shellext, "enable", lambda: True)
    write_version(shellext.extension_dir(), 0)

    assert shellext.ensure_current() == "ok"
    assert not shellext.extension_dir().exists(), \
        "старую пользовательскую копию нужно убрать, чтобы грузилась системная"


# --- как это видит демон ----------------------------------------------------
pytest.importorskip("evdev")


def make_daemon():
    from glyphstroke.config import Settings
    from glyphstroke.daemon import Daemon
    return Daemon(Settings())


def test_daemon_reports_the_relogin(home, caplog):
    from glyphstroke import daemon as daemon_mod
    with caplog.at_level(logging.INFO, logger=daemon_mod.log.name):
        make_daemon().ensure_shell_extension()
    assert any("перезайдите" in record.getMessage() for record in caplog.records)


def test_daemon_survives_a_broken_extension(home, caplog, monkeypatch):
    """Расширение — не повод не ловить жесты: демон должен подняться в любом случае."""
    from glyphstroke import daemon as daemon_mod

    def boom():
        raise OSError("нет прав на каталог")

    monkeypatch.setattr(daemon_mod.shellext, "ensure_current", boom)
    with caplog.at_level(logging.WARNING, logger=daemon_mod.log.name):
        make_daemon().ensure_shell_extension()
    assert any("расширение" in record.getMessage() for record in caplog.records)


def test_daemon_sets_up_the_extension_before_it_starts_listening():
    """Порядок важен: копия должна лечь до того, как демон уйдёт в цикл событий."""
    import inspect
    from glyphstroke.daemon import Daemon
    body = inspect.getsource(Daemon.run)
    assert "self.ensure_shell_extension()" in body
