"""Сборка .deb: пакет действительно собирается и содержит всё нужное."""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILDER = ROOT / "packaging" / "build-deb.sh"
SIZES = (16, 24, 32, 48, 64, 128, 256)

needs_dpkg = pytest.mark.skipif(shutil.which("dpkg-deb") is None,
                                reason="нужен dpkg-deb")


def test_the_builder_is_runnable():
    assert BUILDER.exists()
    assert BUILDER.stat().st_mode & 0o111, "сборщик должен быть исполняемым"


@pytest.mark.parametrize("name", ["postinst", "postrm", "prerm"])
def test_the_hooks_are_valid_shell(name):
    """Ошибка в сценарии пакета всплыла бы только при установке."""
    marker = {"postinst": "POST", "postrm": "POSTRM", "prerm": "PRERM"}[name]
    text = BUILDER.read_text(encoding="utf-8")
    body = re.search(rf"DEBIAN/{name}\" <<'{marker}'\n(.*?)\n{marker}\n",
                     text, re.S).group(1)
    assert body.startswith("#!/bin/sh")
    subprocess.run(["sh", "-n"], input=body, text=True, check=True)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    if shutil.which("dpkg-deb") is None:
        pytest.skip("нужен dpkg-deb")
    out = tmp_path_factory.mktemp("deb")
    result = subprocess.run([str(BUILDER), str(out)], capture_output=True,
                            text=True, cwd=ROOT)
    assert result.returncode == 0, result.stderr
    return pathlib.Path(result.stdout.strip())


@needs_dpkg
def test_the_name_carries_the_version(built):
    from glyphstroke.version import __version__
    assert built.name == f"glyphstroke_{__version__}_all.deb"


@needs_dpkg
def test_the_control_file_asks_for_what_is_needed(built):
    info = subprocess.run(["dpkg-deb", "-I", str(built)], capture_output=True,
                          text=True).stdout
    from glyphstroke.version import __version__
    assert f"Version: {__version__}" in info
    assert "Architecture: all" in info
    depends = re.search(r"Depends: (.+)", info).group(1)
    assert "python3-evdev" in depends and "python3-yaml" in depends
    assert "python3-gi" in re.search(r"Recommends: (.+)", info).group(1)


@needs_dpkg
def test_the_package_carries_the_program(built):
    files = subprocess.run(["dpkg-deb", "-c", str(built)], capture_output=True,
                           text=True).stdout
    for path in ("./usr/bin/glyphstroke", "./usr/bin/glyphstroked",
                 "./usr/lib/glyphstroke/glyphstroke/daemon.py",
                 "./usr/lib/glyphstroke/glyphstroke/locale/en.po",
                 "./usr/lib/glyphstroke/glyphstroke/data/gestures/nazad.yaml",
                 "./usr/share/applications/glyphstroke.desktop",
                 "./usr/lib/udev/rules.d/99-glyphstroke.rules",
                 "./usr/lib/modules-load.d/glyphstroke.conf",
                 "./usr/lib/systemd/user/glyphstroke.service",
                 "./usr/share/gnome-shell/extensions/glyphstroke@glyphstroke.local/metadata.json",
                 "./usr/share/doc/glyphstroke/copyright"):
        assert path in files, f"в пакете нет {path}"


@needs_dpkg
def test_every_icon_size_is_packed(built):
    files = subprocess.run(["dpkg-deb", "-c", str(built)], capture_output=True,
                           text=True).stdout
    for size in SIZES:
        assert f"./usr/share/icons/hicolor/{size}x{size}/apps/glyphstroke.png" in files
    assert "./usr/share/icons/hicolor/scalable/apps/glyphstroke.svg" in files
    assert "./usr/share/icons/hicolor/symbolic/apps/glyphstroke-symbolic.svg" in files


@needs_dpkg
def test_the_commands_are_executable(built):
    files = subprocess.run(["dpkg-deb", "-c", str(built)], capture_output=True,
                           text=True).stdout
    for line in files.splitlines():
        if line.endswith("./usr/bin/glyphstroke") or line.endswith("./usr/bin/glyphstroked"):
            assert line.startswith("-rwxr-xr-x"), line


@needs_dpkg
def test_no_byte_code_sneaks_into_the_package(built):
    """__pycache__ из рабочего дерева в пакете не место."""
    files = subprocess.run(["dpkg-deb", "-c", str(built)], capture_output=True,
                           text=True).stdout
    assert "__pycache__" not in files
    assert ".pyc" not in files


# --- документация ---
def test_the_english_readme_is_the_main_one():
    """Программа говорит по-английски — документация не должна отставать."""
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    # Сверху строка-переключатель языков, затем заголовок — он должен быть у начала.
    assert "# Glyphstroke" in english.splitlines()[:5]
    assert "[Русский](README.ru.md)" in english
    assert "Mouse gestures for Linux" in english


def test_the_russian_readme_points_back():
    russian = (ROOT / "README.ru.md").read_text(encoding="utf-8")
    assert "[English](README.md)" in russian


def test_both_readmes_keep_the_same_shape():
    """Перевод не должен отставать от исходника по составу разделов."""
    def sections(name):
        return [line for line in (ROOT / name).read_text(encoding="utf-8").splitlines()
                if line.startswith("## ")]

    english, russian = sections("README.md"), sections("README.ru.md")
    assert len(english) == len(russian), \
        f"разделов: en {len(english)}, ru {len(russian)}"
