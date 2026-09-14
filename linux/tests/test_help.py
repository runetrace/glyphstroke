"""Справка: разделы, разметка и текст для терминала."""

from glyphstroke import help as help_text


def test_sections_are_found():
    titles = [title for title, _ in help_text.sections()]
    assert "Действия" in titles
    assert "Пауза" in titles
    assert len(titles) >= 8


def test_every_section_has_content():
    for title, body in help_text.sections():
        assert body.strip(), f"раздел «{title}» пуст"


def test_markup_joins_paragraph_lines():
    """Перенос делает GTK по ширине окна, а не разметка."""
    markup = help_text.to_markup("Первая строка\nвторая строка\n\nНовый абзац")
    assert "Первая строка вторая строка" in markup
    assert "\n\nНовый абзац" in markup


def test_markup_escapes_dangerous_characters():
    assert "&lt;b&gt;" in help_text.to_markup("<b>не разметка</b>")


def test_markup_marks_code_and_lists():
    markup = help_text.to_markup("- пункт с `кодом`")
    assert "•" in markup and "<tt>кодом</tt>" in markup


def test_plain_text_has_no_markers():
    plain = help_text.to_plain()
    assert "##" not in plain and "`" not in plain


def test_plain_text_of_one_section():
    plain = help_text.to_plain("действия")
    assert plain.startswith("Действия")
    assert "keys" in plain


def test_unknown_topic_lists_available():
    assert "Есть:" in help_text.to_plain("такого раздела нет")
