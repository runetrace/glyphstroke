"""Перевод интерфейса: каталог, выбор языка, полнота."""

from __future__ import annotations

import ast
import pathlib

import pytest
import yaml

from glyphstroke import i18n

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "glyphstroke"


def wrapped_keys() -> set[str]:
    """Всё, что обёрнуто в _() в исходниках, плюс переводимые словари."""
    keys: set[str] = set()
    for path in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "_" and node.args \
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value:
                keys.add(node.args[0].value)
    from glyphstroke.config import BASE_PROFILE, EVENTS
    from glyphstroke.daemon import EVENT_HINTS
    from glyphstroke.gui import ACTION_HINTS, ACTION_TYPES, TRIGGERS
    keys |= set(EVENTS.values()) | set(EVENT_HINTS.values()) | {BASE_PROFILE}
    keys |= {label for _key, label in ACTION_TYPES}
    keys |= {value for value in ACTION_HINTS.values() if value}
    keys |= {label for _key, label in TRIGGERS}
    from glyphstroke.standard import STANDARD_ACTIONS
    keys |= {label for label, _kind, _value in STANDARD_ACTIONS.values()}
    from glyphstroke.version import SUMMARY
    keys.add(SUMMARY)
    for path in sorted((PACKAGE / "data" / "gestures").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        keys.add(data["name"])
        if data.get("description"):
            keys.add(data["description"].strip())
    return keys


#: одинаковы на любом языке, переводить нечего
UNTRANSLATABLE = {
    "150", "ctrl+w, alt+Left, ctrl+c ctrl+v", "up 3, down, left 2",
    "minimize, maximize, unmaximize, close, fullscreen, activate",
}


def test_english_catalogue_is_complete():
    """Иначе английский интерфейс местами заговорит по-русски."""
    i18n.setup("en")
    missing = sorted(k for k in wrapped_keys()
                     if k not in UNTRANSLATABLE and i18n._(k) == k)
    assert missing == [], f"без перевода осталось: {missing[:5]}"


def test_catalogue_has_no_stale_entries():
    """Перевод строки, которой больше нет в коде, — забытый мусор."""
    i18n.setup("en")
    stale = sorted(set(i18n._catalog) - wrapped_keys())
    assert stale == [], f"лишние записи: {stale[:5]}"


def test_default_language_is_english(monkeypatch):
    monkeypatch.delenv("LANG", raising=False)
    monkeypatch.delenv("LC_ALL", raising=False)
    monkeypatch.delenv("LC_MESSAGES", raising=False)
    monkeypatch.delenv("LANGUAGE", raising=False)
    assert i18n.setup("auto") == "en"


def test_system_language_is_taken_from_environment(monkeypatch):
    # LC_ALL старше LANG, поэтому в тесте задаём обе переменные
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8")
    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    assert i18n.system_language() == "ru"
    monkeypatch.setenv("LC_ALL", "de_DE.UTF-8")
    monkeypatch.setenv("LANG", "de_DE.UTF-8")
    assert i18n.system_language() == "de"


def test_lc_all_wins_over_lang(monkeypatch):
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    assert i18n.system_language() == "ru"


def test_unknown_language_falls_back_to_english():
    assert i18n.setup("эльфийский") == "en"


def test_russian_needs_no_catalogue():
    """Ключи и есть русский текст."""
    i18n.setup("ru")
    assert i18n._("Сохранить") == "Сохранить"


def test_english_translation_is_used():
    i18n.setup("en")
    assert i18n._("Сохранить") == "Save"


def test_multiline_entries_survive_the_round_trip():
    i18n.setup("en")
    translated = i18n._("Опишите, что произошло:\n\n\n--- сведения о программе ---\n")
    assert translated.startswith("Describe what happened:")
    assert translated.count("\n") == 4


def test_po_parser_understands_escapes(tmp_path):
    (tmp_path / "xx.po").write_text(
        'msgid "с \\"кавычками\\" и\\nпереводом"\n'
        'msgstr "with \\"quotes\\" and\\na line break"\n', encoding="utf-8")
    catalog = i18n.parse_po(tmp_path / "xx.po")
    assert catalog['с "кавычками" и\nпереводом'] == 'with "quotes" and\na line break'


def test_po_parser_skips_the_header(tmp_path):
    (tmp_path / "xx.po").write_text('msgid ""\nmsgstr "Language: xx\\n"\n', encoding="utf-8")
    assert i18n.parse_po(tmp_path / "xx.po") == {}


def test_available_languages_lists_catalogues():
    assert set(i18n.available_languages()) >= {"en", "ru"}


# --- справка и стартовый набор ---
def test_help_follows_the_language():
    from glyphstroke import help as help_text
    i18n.setup("en")
    assert "How it works" in [title for title, _b in help_text.sections()]
    i18n.setup("ru")
    assert "Как это работает" in [title for title, _b in help_text.sections()]


def test_both_help_files_have_the_same_sections():
    """Перевод справки не должен отставать от исходника по составу."""
    from glyphstroke import help as help_text
    i18n.setup("en")
    english = len(help_text.sections())
    i18n.setup("ru")
    russian = len(help_text.sections())
    assert english == russian, f"разделов: en {english}, ru {russian}"


@pytest.mark.parametrize("language,expected", [("en", "Back"), ("ru", "Назад")])
def test_starter_gestures_are_translated(tmp_path, monkeypatch, language, expected):
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    i18n.setup(language)
    from glyphstroke import config
    config.ensure_default_config()
    assert expected in {g.name for g in config.load_gestures()}


def test_desktop_entry_has_a_russian_name():
    text = (PACKAGE / "data" / "glyphstroke.desktop").read_text(encoding="utf-8")
    assert "Name=Glyphstroke — mouse gestures" in text
    assert "Name[ru]=" in text


def test_extension_carries_its_own_translations():
    text = (PACKAGE / "data" / "gnome-extension" / "glyphstroke@glyphstroke.local"
            / "extension.js").read_text(encoding="utf-8")
    assert "const MESSAGES" in text and "'Перехват жестов'" in text
