import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def source_language(monkeypatch):
    """Тесты сверяют русские строки: русский — исходный язык проекта.

    Язык задаётся и через окружение: демон в сквозных тестах запускается
    отдельным процессом и берёт его оттуда. Полноту английского каталога
    проверяет отдельный тест.
    """
    from glyphstroke import i18n

    monkeypatch.setenv("LANG", "ru_RU.UTF-8")
    monkeypatch.setenv("LC_ALL", "ru_RU.UTF-8")
    i18n.setup("ru")
    yield
