"""Перевод строк интерфейса.

Ключом служит строка из кода — она русская, потому что на русском написан и
весь остальной текст проекта. Языки подключаются каталогами ``locale/<язык>.po``
в обычном формате gettext; читаем мы их сами, поэтому ни msgfmt при сборке, ни
двоичных каталогов в репозитории не нужно.

По умолчанию программа говорит по-английски: для этого рядом лежит ``en.po``.
Русский язык каталога не требует — там ключи и есть перевод. Язык берётся из
настроек (``language``), при значении ``auto`` — из переменных окружения.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent / "locale"
#: язык, на котором написаны ключи в коде
SOURCE_LANGUAGE = "ru"
#: язык, на который переходим, если ничего не указано
DEFAULT_LANGUAGE = "en"

_catalog: dict[str, str] = {}
_language = DEFAULT_LANGUAGE


def available_languages() -> list[str]:
    """Исходный язык плюс все, для которых есть файл перевода."""
    found = sorted(path.stem for path in LOCALE_DIR.glob("*.po"))
    return sorted({SOURCE_LANGUAGE, *found})


def system_language() -> str:
    """Язык из окружения: ``ru_RU.UTF-8`` → ``ru``."""
    for name in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        value = os.environ.get(name)
        if value:
            code = re.split(r"[._:@]", value)[0].strip().lower()
            if code and code not in ("c", "posix"):
                return code
    return DEFAULT_LANGUAGE


def setup(language: str = "auto") -> str:
    """Выбрать язык и загрузить каталог. Возвращает выбранный код."""
    global _catalog, _language
    code = system_language() if language in ("", "auto", None) else str(language).lower()
    if code not in available_languages():
        # незнакомый язык — говорим по-английски, если перевод есть
        code = DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in available_languages() \
            else SOURCE_LANGUAGE
    _language = code
    _catalog = {} if code == SOURCE_LANGUAGE else parse_po(LOCALE_DIR / f"{code}.po")
    return code


def current_language() -> str:
    return _language


def gettext(message: str) -> str:
    return _catalog.get(message, message)


#: короткое имя, как принято в gettext
_ = gettext


def parse_po(path: Path) -> dict[str, str]:
    """Разобрать файл перевода в словарь.

    Понимает то, что действительно встречается: ``msgid``/``msgstr``, строки,
    склеенные по несколько подряд, экранированные кавычки и переводы строк.
    Комментарии, ``msgctxt`` и формы множественного числа пропускаются — в
    интерфейсе такого пока нет.
    """
    catalog: dict[str, str] = {}
    if not path.exists():
        return catalog
    key: str | None = None
    target: list[str] = []
    current: str | None = None

    def store() -> None:
        if key and current == "msgstr":
            value = "".join(target)
            if value:
                catalog[key] = value

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            store()
            key = _unquote(line[len("msgid "):])
            current, target = "msgid", []
            continue
        if line.startswith("msgstr "):
            if current == "msgid" and target:
                key = (key or "") + "".join(target)
            current, target = "msgstr", [_unquote(line[len("msgstr "):])]
            continue
        if line.startswith(chr(34)):
            target.append(_unquote(line))
    store()
    catalog.pop("", None)          # заголовок каталога переводом не является
    return catalog


def _unquote(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == chr(34) and text[-1] == chr(34):
        text = text[1:-1]
    return (text.replace("\\n", "\n").replace("\\t", "\t")
            .replace(chr(92) + chr(34), chr(34)).replace(chr(92) * 2, chr(92)))
