"""Расширение оболочки GNOME: где лежит, какой версии и как его поставить.

Отдельный модуль, потому что этим занимаются двое: команда ``glyphstroke
shell-extension`` и сам демон, который при запуске обновляет копию в домашнем
каталоге. Класть общий код в cli.py нельзя — cli импортирует daemon, и обратный
импорт замкнул бы круг.

Почему расширение вообще нужно и почему его нельзя поставить из пакета:

* в Wayland обычному приложению не дают ни глобальной позиции курсора, ни слоя
  поверх окон, ни имени окна под курсором — след, меню жеста и мишень умеет
  рисовать и опрашивать только код внутри оболочки;
* GNOME загружает расширение из ``~/.local/share/gnome-shell/extensions``, то
  есть из домашнего каталога конкретного пользователя. postinst пакета работает
  от root и вне пользовательского сеанса: чужой дом он знает в лучшем случае по
  SUDO_USER (при автоматическом обновлении — никак), а включение расширения идёт
  через сессионную шину, которой у root нет;
* поэтому копию ставит то, что и так работает в сеансе пользователя, — демон.

Загрузить расширение на ходу в Wayland всё равно нельзя: оболочка подхватывает
их только при старте сеанса. Поэтому единственное, что остаётся человеку, —
перезайти в систему, и об этом нужно сказать прямо.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
EXTENSION_UUID = "glyphstroke@glyphstroke.local"


def extension_dir() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "gnome-shell/extensions" / EXTENSION_UUID


def system_extension_dir() -> Path:
    """Куда расширение кладёт .deb — общая для всех пользователей папка.

    Оболочка сканирует её при старте сеанса, поэтому лежащее здесь расширение
    можно включить на ходу, без перезахода — в отличие от свежескопированного
    в домашний каталог.
    """
    return Path("/usr/share/gnome-shell/extensions") / EXTENSION_UUID


def packaged_dir() -> Path:
    return DATA_DIR / "gnome-extension" / EXTENSION_UUID


def extension_version(directory: Path) -> int | None:
    """Поле ``version`` из metadata.json расширения; ``None`` — нет или не читается."""
    try:
        data = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
        return int(data.get("version"))
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def extension_versions() -> tuple[int | None, int | None]:
    """Версия копии в домашнем каталоге и версия, пришедшая с программой."""
    return (extension_version(extension_dir()), extension_version(packaged_dir()))


def is_gnome() -> bool:
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "") + os.environ.get("XDG_SESSION_DESKTOP", "")
    if "gnome" in desktop.lower():
        return True
    # В сеансе, запущенном без переменных (например, служба до graphical-session),
    # ориентируемся на наличие самой оболочки.
    return shutil.which("gnome-shell") is not None


def enable_via_gsettings() -> bool:
    """Дописать расширение в org.gnome.shell enabled-extensions."""
    if not shutil.which("gsettings"):
        return False
    key = ["org.gnome.shell", "enabled-extensions"]
    current = subprocess.run(["gsettings", "get", *key], capture_output=True, text=True)
    if current.returncode != 0:
        return False
    items = _parse_gsettings_list(current.stdout.strip())
    if EXTENSION_UUID in items:
        return True
    items.append(EXTENSION_UUID)
    value = "[" + ", ".join(f"'{item}'" for item in items) + "]"
    return subprocess.run(["gsettings", "set", *key, value], capture_output=True).returncode == 0


def _parse_gsettings_list(raw: str) -> list[str]:
    import re

    return re.findall(r"'([^']+)'", raw)


def enable() -> bool:
    """Включить расширение: сперва штатной командой, потом прямой правкой настроек."""
    if shutil.which("gnome-extensions"):
        result = subprocess.run(["gnome-extensions", "enable", EXTENSION_UUID],
                                capture_output=True, text=True)
        if result.returncode == 0:
            return True
    # Свежескопированное расширение оболочка ещё не видела, и штатная команда
    # отвечает «нет такого». Тогда пишем список включённых прямо в настройки —
    # при следующем запуске оболочка его подхватит.
    return enable_via_gsettings()


def install() -> tuple[bool, bool]:
    """Скопировать расширение в домашний каталог и включить.

    :return: (скопировано, включено)
    """
    source = packaged_dir()
    target = extension_dir()
    if not source.is_dir():
        return (False, False)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(source, target)
    return (True, enable())


def state() -> str:
    """``не установлено`` | ``выключено`` | ``включено`` | ``неизвестно``."""
    from .i18n import _

    if not extension_dir().exists():
        return _("не установлено")
    if not shutil.which("gnome-extensions"):
        return _("неизвестно")
    result = subprocess.run(["gnome-extensions", "info", EXTENSION_UUID],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return _("выключено")
    for line in result.stdout.splitlines():
        if "State:" in line or _("Состояние:") in line:
            return _("включено") if "ACTIVE" in line.upper() or "ENABLED" in line.upper() \
                else _("выключено")
    return _("неизвестно")


def ensure_current() -> str:
    """Держать копию в домашнем каталоге не старее той, что пришла с программой.

    Вызывается демоном при запуске: он работает в сеансе пользователя, где есть
    и домашний каталог, и сессионная шина, — в отличие от postinst пакета.

    :return: что сделано — ``ok`` (копия свежая), ``installed`` (поставили
             впервые), ``updated`` (обновили старую), ``skipped`` (не GNOME или
             нечего ставить), ``failed``.
    """
    if not is_gnome():
        return "skipped"

    packaged = extension_version(packaged_dir())
    if packaged is None:
        return "skipped"
    system = extension_version(system_extension_dir())
    user = extension_version(extension_dir())

    # Расширение уже несёт система (из .deb, в /usr/share) не старее нашего.
    # Своя копия в ~/.local тогда не нужна и вредна: свежескопированную оболочка
    # не подхватит без перезахода, а системную она увидела при старте сеанса.
    # Убираем устаревшую пользовательскую копию, чтобы не затеняла системную,
    # и — всегда — включаем: раньше здесь возвращалось «ok» без включения, и
    # уже установленное, но выключенное расширение так и оставалось выключенным.
    if system is not None and system >= packaged:
        if user is not None and user <= system:
            shutil.rmtree(extension_dir(), ignore_errors=True)
        enable()
        return "ok"

    # Системной копии нет (установка из исходников) — держим свою в ~/.local.
    if user is not None and user >= packaged:
        enable()
        return "ok"

    copied, _enabled = install()
    if not copied:
        return "failed"
    return "installed" if user is None else "updated"
