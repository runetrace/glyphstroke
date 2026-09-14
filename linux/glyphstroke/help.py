"""Справка: один текст для окна редактора и для командной строки.

Текст лежит в ``data/help.md`` и написан подмножеством разметки: заголовки,
списки, `код`. Здесь оно превращается либо в разметку Pango для GTK, либо в
обычный текст для терминала.
"""

from __future__ import annotations

import re
from html import escape
from pathlib import Path

from .i18n import _

HELP_DIR = Path(__file__).resolve().parent / "data"


def help_path(language: str | None = None) -> Path:
    """Файл справки на нужном языке, иначе английский, иначе какой есть."""
    from .i18n import DEFAULT_LANGUAGE, current_language

    for code in (language or current_language(), DEFAULT_LANGUAGE, "ru"):
        path = HELP_DIR / f"help.{code}.md"
        if path.exists():
            return path
    return next(HELP_DIR.glob("help.*.md"))


def raw_text(language: str | None = None) -> str:
    return help_path(language).read_text(encoding="utf-8")


def sections() -> list[tuple[str, str]]:
    """Разделы справки: заголовок и его текст."""
    result: list[tuple[str, str]] = []
    title, body = "", []
    for line in raw_text().splitlines():
        if line.startswith("## "):
            if title:
                result.append((title, "\n".join(body).strip()))
            title, body = line[3:].strip(), []
        elif line.startswith("# "):
            continue
        else:
            body.append(line)
    if title:
        result.append((title, "\n".join(body).strip()))
    return result


def _inline(text: str) -> str:
    text = escape(text)
    text = re.sub(r"`([^`]+)`", r"<tt>\1</tt>", text)
    return re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)


def to_markup(text: str | None = None) -> str:
    """Разметка Pango для Gtk.Label.

    Строки одного абзаца склеиваются: перенос делает сам GTK по ширине окна,
    а переносы из исходника рвали бы текст в неожиданных местах.
    """
    out: list[str] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            out.append(_inline(" ".join(paragraph)))
            paragraph.clear()

    for line in (text if text is not None else raw_text()).splitlines():
        stripped = line.strip()
        if not stripped:
            flush()
            out.append("")
        elif line.startswith("## "):
            flush()
            out.append(f"<big><b>{escape(line[3:].strip())}</b></big>")
        elif line.startswith("# "):
            flush()
            out.append(f"<span size='x-large'><b>{escape(line[2:].strip())}</b></span>")
        elif line.startswith("- "):
            flush()
            out.append(f"  • {_inline(stripped[2:])}")
        elif re.match(r"^\d+\. ", stripped):
            flush()
            out.append(f"  {_inline(stripped)}")
        elif line.startswith("  ") and out and out[-1].startswith("  •"):
            out[-1] += " " + _inline(stripped)      # продолжение пункта списка
        else:
            paragraph.append(stripped)
    flush()
    return "\n".join(out).strip("\n")


def to_plain(topic: str | None = None) -> str:
    """Текст для терминала; ``topic`` оставляет только подходящие разделы."""
    if topic:
        wanted = [(title, body) for title, body in sections()
                  if topic.lower() in title.lower()]
        if not wanted:
            available = ", ".join(f"«{t}»" for t, _body in sections())
            return _("Нет такого раздела. Есть: {0}").format(available)
        return re.sub(r"`([^`]+)`", r"\1",
                      "\n\n".join(f"{title}\n{'─' * len(title)}\n{body}"
                                   for title, body in wanted))
    text = raw_text()
    text = re.sub(r"^#+ ", "", text, flags=re.MULTILINE)
    return re.sub(r"`([^`]+)`", r"\1", text)
