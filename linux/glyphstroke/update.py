"""Проверка обновлений: вышла ли версия новее установленной.

Программа обновляться сама не умеет и не должна: она перехватывает мышь, и
тихая подмена демона посреди работы — совсем не то, чего человек ждёт. Здесь
только проверка. Нашлась версия новее — говорим об этом в редакторе и в
``glyphstroke doctor``, а ставить человек идёт сам.

Откуда берутся выпуски. Своего сервера у проекта нет, поэтому источник —
страница выпусков на GitHub и её открытый интерфейс: один запрос, ответ в
JSON, ни ключей, ни учётных записей. Адрес хранилища — настройка
``update_repo``, так что при переезде менять программу не придётся.

Что с приватностью. Проверка — это обращение к чужому серверу, а значит, наш
адрес и время запуска становятся ему известны. Молча так делать нельзя,
поэтому: проверка выключается настройкой ``check_updates``, ходит не чаще
раза в сутки, ничего о системе не сообщает и ответ кладёт в файл рядом с
настройками — чтобы редактор спрашивал его, а не сеть.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import config
from .i18n import _
from .version import __version__

log = logging.getLogger("glyphstroke.update")

#: где лежат выпуски по умолчанию
DEFAULT_REPO = "runetrace/glyphstroke"

#: как часто спрашивать: чаще раза в сутки смысла нет, а сервер чужой
CHECK_INTERVAL_S = 24 * 3600

#: сколько ждём ответа — проверка не должна задерживать запуск демона
TIMEOUT_S = 10.0


@dataclass
class Release:
    """Выпуск, о котором рассказал сервер."""

    version: str
    url: str
    notes: str = ""

    def is_newer(self) -> bool:
        return newer_than(self.version, __version__)


def state_path() -> Path:
    return config.config_dir() / "update.json"


def repo_name(settings=None) -> str:
    name = getattr(settings, "update_repo", "") if settings is not None else ""
    return (name or DEFAULT_REPO).strip().strip("/")


def release_page(settings=None) -> str:
    return f"https://github.com/{repo_name(settings)}/releases/latest"


# --- сравнение версий -------------------------------------------------------
def parse_version(text: str) -> tuple[int, ...]:
    """``v0.7.1`` → ``(0, 7, 1)``.

    Буквенные хвосты вроде ``0.8.0-rc1`` отбрасываются: черновой выпуск не
    должен выглядеть новее готового.
    """
    numbers = re.findall(r"\d+", (text or "").split("-", 1)[0])
    return tuple(int(number) for number in numbers[:4]) or (0,)


def newer_than(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


# --- обращение к серверу ----------------------------------------------------
def fetch_latest(settings=None, timeout: float = TIMEOUT_S) -> Release | None:
    """Спросить сервер о последнем выпуске. Ошибка сети — это не ошибка."""
    url = f"https://api.github.com/repos/{repo_name(settings)}/releases/latest"
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        # Без своего имени сервер отвечает отказом. Версию сообщаем ту же,
        # что и так видна в выпусках, — ничего нового этим не раскрываем.
        "User-Agent": f"glyphstroke/{__version__}",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log.debug(_("проверка обновлений не удалась: %s"), exc)
        return None

    tag = str(data.get("tag_name") or data.get("name") or "").strip()
    if not tag:
        return None
    return Release(
        version=tag.lstrip("vV"),
        url=str(data.get("html_url") or release_page(settings)),
        notes=str(data.get("body") or "").strip(),
    )


# --- память между запусками -------------------------------------------------
def load_state() -> dict:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    try:
        path = state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    except OSError as exc:          # нет прав на каталог — это не повод падать
        log.debug(_("не удалось сохранить состояние проверки: %s"), exc)


def due(state: dict | None = None, now: float | None = None) -> bool:
    """Пора ли спрашивать снова."""
    state = load_state() if state is None else state
    now = time.time() if now is None else now
    checked = float(state.get("checked_at") or 0)
    # Время на машине могли перевести назад — тогда лучше спросить, чем ждать
    # сутки от будущего момента.
    return not (0 < now - checked < CHECK_INTERVAL_S)


def check(settings=None, force: bool = False) -> Release | None:
    """Проверить и запомнить ответ. Возвращает выпуск, если он новее.

    Без ``force`` уважает и настройку, и суточный перерыв: это точка входа
    для демона, который зовёт её при запуске и раз в сутки.
    """
    if settings is not None and not getattr(settings, "check_updates", True) and not force:
        return None
    state = load_state()
    if not force and not due(state):
        return pending(state)

    release = fetch_latest(settings)
    state["checked_at"] = time.time()
    if release is not None:
        state["version"] = release.version
        state["url"] = release.url
        state["notes"] = release.notes
    save_state(state)
    return release if release is not None and release.is_newer() else None


def pending(state: dict | None = None) -> Release | None:
    """Что известно из прошлой проверки, без обращения к сети.

    Этим пользуется редактор: показывать полоску «вышла новая версия» он
    должен мгновенно, а не ждать ответа чужого сервера при открытии окна.
    """
    state = load_state() if state is None else state
    version = str(state.get("version") or "")
    if not version:
        return None
    release = Release(version=version, url=str(state.get("url") or ""),
                      notes=str(state.get("notes") or ""))
    return release if release.is_newer() else None
