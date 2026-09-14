"""Значок программы: файлы на месте, размеры честные, установщик их знает."""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
ICONS = ROOT / "glyphstroke" / "data" / "icons"
EXTENSION = (ROOT / "glyphstroke" / "data" / "gnome-extension"
             / "glyphstroke@glyphstroke.local")
SIZES = (16, 24, 32, 48, 64, 128, 256)


def png_size(path: pathlib.Path) -> tuple[int, int]:
    """Ширина и высота из заголовка IHDR — без сторонних библиотек."""
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} — это не PNG"
    return (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big"))


@pytest.mark.parametrize("size", SIZES)
def test_every_size_is_really_that_size(size):
    path = ICONS / str(size) / "glyphstroke.png"
    assert path.exists(), f"нет растра {size}"
    assert png_size(path) == (size, size)


def test_corners_are_transparent():
    """Иначе значок поедет чёрным квадратом по светлой панели."""
    Image = pytest.importorskip("PIL.Image", reason="нужен Pillow")
    with Image.open(ICONS / "128" / "glyphstroke.png") as image:
        assert image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0


def test_scalable_and_symbolic_are_in_place():
    assert (ICONS / "glyphstroke.svg").exists()
    assert (ICONS / "glyphstroke-symbolic.svg").exists()


def test_the_extension_carries_the_same_symbolic_icon():
    """Тема оболочки не знает значок, пока программа не установлена."""
    theirs = (EXTENSION / "icons" / "glyphstroke-symbolic.svg")
    assert theirs.exists()
    assert theirs.read_text(encoding="utf-8") == \
        (ICONS / "glyphstroke-symbolic.svg").read_text(encoding="utf-8")


def test_the_symbolic_icon_is_made_of_fills():
    """Обводку оболочка не перекрасит — значок остался бы серым пятном."""
    text = (ICONS / "glyphstroke-symbolic.svg").read_text(encoding="utf-8")
    assert "stroke" not in text
    assert 'viewBox="0 0 16 16"' in text


def test_the_desktop_entry_points_at_our_icon():
    text = (ROOT / "glyphstroke" / "data" / "glyphstroke.desktop").read_text(encoding="utf-8")
    assert "Icon=glyphstroke" in text
    assert "input-mouse" not in text, "остался системный значок"


def test_the_panel_uses_our_icon():
    text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    assert "icons/glyphstroke-symbolic.svg" in text
    assert "input-mouse-symbolic" not in text


def sizes_in(path: pathlib.Path) -> set[int]:
    text = path.read_text(encoding="utf-8")
    line = re.search(r"for size in ([\d ]+); do", text)
    assert line, f"в {path.name} не нашёлся перебор размеров"
    return {int(value) for value in line.group(1).split()}


def test_the_installer_knows_every_size():
    """Размеры в скрипте и файлы в комплекте не должны разъезжаться."""
    assert sizes_in(ROOT / "install.sh") == set(SIZES)


def test_uninstall_removes_the_same_sizes():
    assert sizes_in(ROOT / "uninstall.sh") == set(SIZES)


def test_the_installer_refreshes_the_icon_cache():
    """Без этого значок не появится до перезахода в систему."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "gtk-update-icon-cache" in text
    assert "hicolor/scalable/apps/glyphstroke.svg" in text
    assert "hicolor/symbolic/apps/glyphstroke-symbolic.svg" in text


def test_the_package_carries_the_icons():
    """Иначе установка через pip оставит программу без значка."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "data/icons/*.svg" in text
    assert "data/icons/*/*.png" in text


def test_the_panel_shows_a_stopped_capture_in_red():
    """Красный значок — привычный знак «жесты выключены»: так у StrokeIt."""
    text = (EXTENSION / "extension.js").read_text(encoding="utf-8")
    assert "PAUSED_COLOUR" in text
    assert "media-playback-pause-symbolic" not in text, \
        "значок должен оставаться своим, меняться должен только цвет"
