"""Проверка обновлений: сравнение версий, запрос к серверу, память о нём."""

from __future__ import annotations

import io
import json
import time
import urllib.error

import pytest

from glyphstroke import update
from glyphstroke.config import Settings
from glyphstroke.version import __version__


@pytest.fixture(autouse=True)
def own_config(tmp_path, monkeypatch):
    """Каждому тесту свой каталог настроек: состояние проверки лежит там."""
    monkeypatch.setenv("GLYPHSTROKE_CONFIG_DIR", str(tmp_path))
    return tmp_path


class FakeResponse(io.BytesIO):
    """Ответ сервера, какой отдаёт urlopen: файл с методами контекста."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def answer(monkeypatch, payload: dict, seen: list | None = None):
    def fake_urlopen(request, timeout=None):
        if seen is not None:
            seen.append(request.full_url)
        return FakeResponse(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(update.urllib.request, "urlopen", fake_urlopen)


def refuse(monkeypatch, error=None):
    def fake_urlopen(request, timeout=None):
        raise error or urllib.error.URLError("сети нет")

    monkeypatch.setattr(update.urllib.request, "urlopen", fake_urlopen)


# --- сравнение версий ---
def test_version_parsing():
    assert update.parse_version("0.7.0") == (0, 7, 0)
    assert update.parse_version("v1.2.3") == (1, 2, 3)
    assert update.parse_version("") == (0,)


def test_prerelease_is_not_newer_than_release():
    """«0.8.0-rc1» не должен выглядеть новее готовой 0.8.0."""
    assert not update.newer_than("0.8.0-rc1", "0.8.0")
    assert update.newer_than("0.8.0", "0.7.9")
    assert not update.newer_than("0.7.0", "0.7.0")


def test_shorter_version_compares_by_numbers():
    assert update.newer_than("1.0", "0.9.9")
    assert not update.newer_than("0.9", "0.9.1")


# --- адрес хранилища ---
def test_repo_comes_from_settings():
    settings = Settings()
    assert update.repo_name(settings) == update.DEFAULT_REPO
    settings.update_repo = "кто-то/что-то"
    assert update.repo_name(settings) == "кто-то/что-то"
    assert update.release_page(settings).endswith("кто-то/что-то/releases/latest")


# --- запрос ---
def test_latest_release_is_read(monkeypatch):
    seen: list[str] = []
    answer(monkeypatch, {"tag_name": "v0.9.0", "html_url": "https://пример/0.9.0",
                         "body": "что нового"}, seen)
    release = update.fetch_latest(Settings())
    assert release.version == "0.9.0"
    assert release.url == "https://пример/0.9.0"
    assert release.notes == "что нового"
    assert seen and seen[0].startswith("https://api.github.com/repos/")


def test_network_failure_is_not_an_error(monkeypatch):
    """Нет сети — нет ответа. Ронять из-за этого нечего."""
    refuse(monkeypatch)
    assert update.fetch_latest(Settings()) is None


def test_answer_without_a_tag_is_ignored(monkeypatch):
    answer(monkeypatch, {"message": "Not Found"})
    assert update.fetch_latest(Settings()) is None


# --- память между запусками ---
def test_check_remembers_the_answer(monkeypatch):
    answer(monkeypatch, {"tag_name": "9.9.9", "html_url": "https://пример/9.9.9"})
    release = update.check(Settings(), force=True)
    assert release is not None and release.version == "9.9.9"

    # второй раз к серверу не ходим: ответ уже есть, а сутки не прошли
    refuse(monkeypatch)
    assert update.check(Settings()).version == "9.9.9"
    assert update.pending().version == "9.9.9"


def test_same_version_is_not_reported(monkeypatch):
    answer(monkeypatch, {"tag_name": __version__})
    assert update.check(Settings(), force=True) is None
    assert update.pending() is None, "своя же версия — не новость"


def test_check_is_skipped_when_turned_off(monkeypatch):
    called: list[str] = []
    answer(monkeypatch, {"tag_name": "9.9.9"}, called)
    settings = Settings()
    settings.check_updates = False
    assert update.check(settings) is None
    assert called == [], "выключенная проверка не должна ходить в сеть"


def test_force_ignores_the_switch_and_the_interval(monkeypatch):
    called: list[str] = []
    answer(monkeypatch, {"tag_name": "9.9.9"}, called)
    settings = Settings()
    settings.check_updates = False
    assert update.check(settings, force=True).version == "9.9.9"
    assert len(called) == 1


def test_interval_is_respected(monkeypatch):
    state = {"checked_at": time.time()}
    assert not update.due(state)
    state["checked_at"] = time.time() - update.CHECK_INTERVAL_S - 1
    assert update.due(state)
    # время перевели вперёд и вернули назад: лучше спросить, чем ждать сутки
    assert update.due({"checked_at": time.time() + 10_000})


def test_pending_survives_a_broken_state_file(own_config):
    (own_config / "update.json").write_text("{ не json", encoding="utf-8")
    assert update.pending() is None
