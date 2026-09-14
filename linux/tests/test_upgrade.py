"""Обновление поверх прежней версии: номер версии, пакет и glyphstroke doctor."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILDER = ROOT / "packaging" / "build-deb.sh"


# --- номер версии ------------------------------------------------------------
def test_the_version_is_the_same_everywhere():
    """Разойдись номера — apt не обновит пакет, а glyphstroke doctor не заметит старый демон."""
    from glyphstroke.version import __version__
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version = "(.+)"', pyproject, re.M).group(1) == __version__
    for name in ("README.md", "README.ru.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert f"glyphstroke_{__version__}_all.deb" in text, \
            f"{name}: команда установки называет другую версию"
    head = (ROOT / "glyphstroke" / "locale" / "en.po").read_text(encoding="utf-8")[:400]
    assert f"glyphstroke {__version__}" in head


# --- сценарий установки пакета ----------------------------------------------
def postinst_body() -> str:
    text = BUILDER.read_text(encoding="utf-8")
    return re.search(r"DEBIAN/postinst\" <<'POST'\n(.*?)\nPOST\n", text, re.S).group(1)


@pytest.fixture
def quiet_system(tmp_path):
    """Заглушки команд, которые postinst зовёт на настоящей системе."""
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for name in ("python3", "udevadm", "modprobe", "gtk-update-icon-cache",
                 "update-desktop-database", "usermod", "runuser", "systemctl"):
        stub = stubs / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    return {**os.environ, "PATH": f"{stubs}:/usr/bin:/bin", "SUDO_USER": "tester"}


def run_postinst(env, *args) -> str:
    return subprocess.run(["sh", "-s", "--", *args], input=postinst_body(), env=env,
                          capture_output=True, text=True, check=True).stdout


def test_first_install_does_the_setup_itself(quiet_system):
    """Человеку остаётся только перезайти: всё остальное делает установщик."""
    out = run_postinst(quiet_system, "configure")
    assert "Glyphstroke установлен" in out
    assert "выйдите из системы и войдите снова" in out.lower()
    assert "sudo usermod" not in out, "группа выдаётся сама"
    # Автозапуск включается сам, но только при живом сеансе пользователя: при
    # установке по ssh его нет, и тогда в тексте должна быть причина, а не
    # молчание. В тесте сеанса нет, поэтому годится любой из двух ответов.
    assert ("Автозапуск включён" in out) or ("не видно вашего сеанса" in out)
    assert "обновлён" not in out


def test_upgrade_tells_about_the_relogin(quiet_system):
    """Службу и расширение пакет обновляет сам, от человека нужен только перезаход."""
    out = run_postinst(quiet_system, "configure", "0.5.0")
    assert "обновлён с версии 0.5.0" in out
    assert "перезайдите в систему" in out
    assert "glyphstroke doctor" in out
    assert "usermod" not in out, "группа у обновляющегося уже есть"


# --- glyphstroke doctor и версия расширения ----------------------------------------
pytest.importorskip("evdev")


@pytest.fixture
def home_extension(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path / "config"))
    from glyphstroke import cli
    target = cli.extension_dir()
    target.mkdir(parents=True)
    return target


def write_version(directory: pathlib.Path, version) -> None:
    (directory / "metadata.json").write_text(
        json.dumps({"uuid": "glyphstroke@glyphstroke.local", "version": version}),
        encoding="utf-8")


def packaged_version() -> int:
    from glyphstroke import cli
    return cli.extension_version(cli.DATA_DIR / "gnome-extension" / cli.EXTENSION_UUID)


def test_installed_and_packaged_versions_are_read(home_extension):
    from glyphstroke import cli
    write_version(home_extension, 0)
    assert packaged_version() >= 1
    assert cli.extension_versions() == (0, packaged_version())


def test_missing_or_broken_metadata_gives_no_version(tmp_path):
    from glyphstroke import cli
    assert cli.extension_version(tmp_path) is None
    (tmp_path / "metadata.json").write_text("{", encoding="utf-8")
    assert cli.extension_version(tmp_path) is None
    (tmp_path / "metadata.json").write_text("[]", encoding="utf-8")
    assert cli.extension_version(tmp_path) is None


def doctor_output(capsys) -> str:
    from glyphstroke import cli
    cli.cmd_doctor(argparse.Namespace())
    return capsys.readouterr().out


def test_doctor_flags_an_outdated_extension(home_extension, capsys):
    write_version(home_extension, 0)
    out = doctor_output(capsys)
    assert "[✗] расширение оболочки совпадает с программой (версия 0)" in out
    assert "glyphstroke shell-extension install" in out


def test_doctor_accepts_a_fresh_extension(home_extension, capsys):
    write_version(home_extension, packaged_version())
    out = doctor_output(capsys)
    assert f"[✓] расширение оболочки совпадает с программой (версия {packaged_version()})" in out
