"""Чтение и запись настроек.

Раскладка каталога ``~/.config/glyphstroke``::

    settings.yaml        общие параметры демона
    gestures/*.yaml      по файлу на жест: как распознать и что выполнить
    profiles/ИМЯ/*.yaml  дополнительные наборы жестов, если их заводили

Каждый жест — отдельный файл, поэтому редактор может переписать один жест,
не трогая остальные, а в git такие правки читаются построчно.
"""

from __future__ import annotations

import math
import os
import re
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

from .recognizer import GestureDef, Point

from .i18n import _

APP_NAME = "glyphstroke"
#: прежнее имя программы: настройки из него переносим при первом запуске
LEGACY_APP_NAME = "strokeit"
_migrated = False


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(os.environ.get("GLYPHSTROKE_CONFIG_DIR", Path(base) / APP_NAME))


def legacy_config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / LEGACY_APP_NAME


def migrate_legacy_config() -> Path | None:
    """Перенести настройки и жесты из каталога прежнего имени.

    Копируем, а не переносим: старая установка остаётся рабочей, пока человек
    не убедится, что новая делает то же самое. Возвращает каталог-источник,
    если перенос состоялся.
    """
    global _migrated
    if _migrated or os.environ.get("GLYPHSTROKE_CONFIG_DIR"):
        return None
    _migrated = True
    new, old = config_dir(), legacy_config_dir()
    if new.exists() or not old.exists():
        return None
    try:
        shutil.copytree(old, new)
    except OSError as exc:
        import logging
        logging.getLogger(APP_NAME).error(_("не удалось перенести настройки: %s"), exc)
        return None
    import logging
    logging.getLogger(APP_NAME).info(
        _("настройки перенесены из %s — прежний каталог остался нетронутым"), old)
    return old


#: название основного набора. Он лежит в ``gestures/`` и был единственным до
#: появления профилей, поэтому в настройках обозначается пустой строкой
BASE_PROFILE = "основной"


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def clean_profile_name(name: str) -> str:
    """Имя набора — оно же имя каталога, поэтому разделители убираем."""
    name = re.sub(r"[/\\]+", "-", (name or "").strip()).strip(". ")
    return name[:64]


def available_profiles() -> list[str]:
    """Дополнительные наборы. Основного в списке нет — он есть всегда."""
    if not profiles_dir().exists():
        return []
    return sorted((path.name for path in profiles_dir().iterdir() if path.is_dir()),
                  key=str.lower)


def active_profile() -> str:
    """Имя текущего набора; пусто — основной.

    Если каталог набора исчез, молча возвращаемся к основному: остаться вовсе
    без жестов хуже, чем откатиться к тому, что точно есть.
    """
    name = clean_profile_name(Settings.load().active_profile)
    if not name:
        return ""
    if not (profiles_dir() / name).is_dir():
        import logging
        logging.getLogger(APP_NAME).warning(
            _("набор «%s» не найден — беру основной"), name)
        return ""
    return name


def gestures_dir(profile: str | None = None) -> Path:
    """Каталог жестов набора; без имени — того, что сейчас выбран."""
    profile = active_profile() if profile is None else clean_profile_name(profile)
    return profiles_dir() / profile if profile else config_dir() / "gestures"


def create_profile(name: str, copy_from: str | None = None) -> str:
    """Завести набор. ``copy_from`` — имя набора-источника, ``""`` — основной."""
    name = clean_profile_name(name)
    if not name:
        raise ValueError(_("у набора должно быть название"))
    target = profiles_dir() / name
    if target.exists():
        raise ValueError(_("набор «{0}» уже есть").format(name))
    target.mkdir(parents=True)
    if copy_from is not None:
        for path in sorted(gestures_dir(copy_from).glob("*.yaml")):
            shutil.copy(path, target / path.name)
    return name


def remove_profile(name: str) -> None:
    """Убрать набор вместе с жестами. Основной удалить нельзя."""
    name = clean_profile_name(name)
    if not name:
        raise ValueError(_("основной набор удалить нельзя"))
    target = profiles_dir() / name
    if not target.is_dir():
        raise ValueError(_("нет набора «{0}»").format(name))
    shutil.rmtree(target)
    if clean_profile_name(Settings.load().active_profile) == name:
        use_profile("")


def use_profile(name: str) -> str:
    """Переключиться на набор. Возвращает имя, ставшее текущим."""
    name = clean_profile_name(name)
    if name and not (profiles_dir() / name).is_dir():
        raise ValueError(_("нет набора «{0}»").format(name))
    settings = Settings.load()
    settings.active_profile = name
    settings.save()
    return name


def profile_size(name: str) -> int:
    """Сколько жестов в наборе — без их разбора."""
    directory = gestures_dir(name)
    return len(list(directory.glob("*.yaml"))) if directory.exists() else 0


def settings_path() -> Path:
    return config_dir() / "settings.yaml"


# --- настройки --------------------------------------------------------------
@dataclass
class OverlaySettings:
    enabled: bool = True
    color: str = "#4da3ff"
    width: int = 4
    #: непрозрачность линии, 0…1
    opacity: float = 0.9
    fade_ms: int = 220


@dataclass
class Settings:
    #: язык интерфейса: ``auto`` — по системному, иначе код вроде ``en``/``ru``
    language: str = "auto"
    #: тема оформления окон: ``system`` — как в системе, иначе ``light``/``dark``
    theme: str = "system"
    #: текущий набор жестов; пусто — основной, тот самый ``gestures/``
    active_profile: str = ""
    #: кнопка-модификатор: BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA
    trigger_button: str = "BTN_RIGHT"
    #: grab — перехватывать кнопку (контекстное меню не выскакивает),
    #: monitor — только следить, ничего не удерживая
    capture_mode: str = "grab"
    #: короче этого пути (в единицах устройства) считаем, что был обычный клик
    min_stroke_px: float = 40.0
    min_score: float = 0.80
    min_margin: float = 0.05
    #: что делать с нераспознанным росчерком: отдать клик приложению или съесть
    unrecognized: str = "passthrough"
    #: чем нажимать клавиши: ``auto`` — через расширение оболочки, если оно на
    #: связи (не зависит от раскладки), иначе напрямую через uinput;
    #: ``uinput`` и ``shell`` заставляют выбрать способ вручную
    keys_via: str = "auto"
    #: приложения, в которых перехват не нужен вовсе: правая кнопка работает
    #: как обычно. Выражения сверяются с «класс окна | заголовок»
    excluded_apps: list[str] = field(default_factory=list)
    #: отпускать мышь, пока активное окно развёрнуто во весь экран: в игре
    #: она должна принадлежать игре. Перехват вернётся сам, когда выйдете
    pause_in_fullscreen: bool = False
    #: показывать название сработавшего жеста на экране
    show_gesture_name: bool = True
    #: через сколько миллисекунд удержания без движения показать шпаргалку
    #: со списком жестов; 0 — не показывать
    hint_delay_ms: int = 700
    #: сколько нужно провести мышью вниз, чтобы перейти к следующему пункту
    #: меню под жестом (в единицах устройства)
    menu_step_px: float = 36.0
    #: через сколько миллисекунд без движения открытое меню закрывается само.
    #: Пока меню открыто, мышь принадлежит ему — без этого срока её можно
    #: было бы потерять насовсем
    menu_timeout_ms: int = 5000
    #: делать активным то окно, над которым начали рисовать. Работает через
    #: расширение оболочки; на двух экранах без этого действие уходит в окно,
    #: которое было в фокусе, а не в то, над которым нарисован жест
    focus_under_cursor: bool = True
    #: если кнопку держат дольше и почти не двигают — отпустить нажатие
    #: приложению (нужно для right-drag в играх и CAD). 0 — выключено
    press_passthrough_ms: int = 0
    #: регулярные выражения по имени устройства; пусто — автоподбор мышей
    device_include: list[str] = field(default_factory=list)
    device_exclude: list[str] = field(default_factory=list)
    allow_touchpads: bool = False
    #: клавиша для рисования на тачпаде: пока она зажата, палец рисует
    #: росчерк. Ни тачпад, ни клавиатура не захватываются. Пусто — выключено
    touchpad_key: str = "KEY_LEFTMETA"
    #: спрашивать сервер выпусков, не вышла ли версия новее. Сама программа
    #: не обновляется: она только показывает, что обновление есть. Это запрос
    #: к чужому серверу, поэтому его можно выключить
    check_updates: bool = True
    #: где лежат выпуски, в виде «владелец/хранилище»; пусто — как в коде
    update_repo: str = ""
    overlay: OverlaySettings = field(default_factory=OverlaySettings)
    log_level: str = "info"

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or settings_path()
        data = {}
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        overlay = OverlaySettings(**(data.pop("overlay", None) or {}))
        known = {f for f in cls.__dataclass_fields__ if f != "overlay"}
        unknown = set(data) - known
        for key in unknown:
            data.pop(key)
        return cls(overlay=overlay, **data)

    def save(self, path: Path | None = None) -> None:
        path = path or settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(path, yaml.safe_dump(asdict(self), allow_unicode=True,
                                           sort_keys=False))


# --- жесты ------------------------------------------------------------------
@dataclass
class Action:
    #: command | keys | text | button | scroll | delay | none
    type: str
    value: str = ""

    def to_dict(self) -> dict:
        return {"type": self.type, "value": self.value}


def parse_actions(raw) -> list["Action"]:
    return [Action(type=a.get("type", "none"), value=str(a.get("value", "")))
            for a in (raw or []) if isinstance(a, dict)]


@dataclass
class MenuItem:
    """Пункт меню под жестом: название и свои действия.

    Меню — необязательная добавка к жесту. Пока пунктов нет, жест ведёт себя
    ровно как раньше: выполняет свои действия и ничего не показывает.
    """

    name: str
    actions: list[Action] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "MenuItem":
        return cls(name=str(data.get("name", "")).strip(),
                   actions=parse_actions(data.get("actions")))

    def to_dict(self) -> dict:
        return {"name": self.name, "actions": [a.to_dict() for a in self.actions]}


#: особые жесты — они опознаются событием, а не формой росчерка
EVENTS = {
    "rocker-left": "Rocker: клик левой при зажатой правой",
    "rocker-right": "Rocker: клик правой при зажатой левой",
    "wheel-up": "Колесо вверх при зажатой кнопке",
    "wheel-down": "Колесо вниз при зажатой кнопке",
    "wheel-left": "Колесо влево при зажатой кнопке",
    "wheel-right": "Колесо вправо при зажатой кнопке",
}


#: короткая пометка для списков — длинное описание туда не влезает
EVENT_SHORT = {
    "rocker-left": "Rocker ◀",
    "rocker-right": "Rocker ▶",
    "rocker-middle": "Rocker ●",
    "wheel-up": "Wheel ▲",
    "wheel-down": "Wheel ▼",
    "wheel-left": "Wheel ◀",
    "wheel-right": "Wheel ▶",
}


@dataclass
class Gesture:
    name: str
    enabled: bool = True
    #: если задано — жест опознаётся по событию мыши, росчерк не рисуется
    event: str = ""
    directions: list[str] = field(default_factory=list)
    templates: list[list[Point]] = field(default_factory=list)
    apps: list[str] = field(default_factory=list)
    rotation_tolerance: float = 20.0  # градусы
    actions: list[Action] = field(default_factory=list)
    #: пункты меню; пусто — меню не показывается вовсе
    menu: list[MenuItem] = field(default_factory=list)
    description: str = ""
    path: Path | None = None

    # --- сериализация ---
    @classmethod
    def from_dict(cls, data: dict, path: Path | None = None) -> "Gesture":
        return cls(
            name=data.get("name") or (path.stem if path else "gesture"),
            enabled=bool(data.get("enabled", True)),
            event=str(data.get("event", "") or "").strip().lower(),
            directions=[d.strip().upper() for d in data.get("directions", []) if d.strip()],
            templates=[parse_stroke(s) for s in data.get("templates", [])],
            apps=list(data.get("apps", [])),
            rotation_tolerance=float(data.get("rotation_tolerance", 20.0)),
            actions=parse_actions(data.get("actions")),
            menu=[MenuItem.from_dict(m) for m in data.get("menu", [])
                  if isinstance(m, dict) and str(m.get("name", "")).strip()],
            description=data.get("description", ""),
            path=path,
        )

    def to_dict(self) -> dict:
        data = {
            "name": self.name,
            "enabled": self.enabled,
            "description": self.description,
            "event": self.event,
            "directions": self.directions,
            "apps": self.apps,
            "rotation_tolerance": self.rotation_tolerance,
            "actions": [a.to_dict() for a in self.actions],
        }
        # ключа menu у жеста без меню быть не должно: файлы прежних жестов
        # не должны меняться от одного лишь пересохранения
        if self.menu:
            data["menu"] = [item.to_dict() for item in self.menu]
        data["templates"] = [format_stroke(t) for t in self.templates]
        return data

    def to_def(self) -> GestureDef:
        return GestureDef(
            name=self.name,
            templates=self.templates,
            directions=self.directions,
            rotation_tolerance=math.radians(self.rotation_tolerance),
        )

    def matches_app(self, app_id: str | None) -> bool:
        if not self.apps:
            return True
        if not app_id:
            return False  # жест с фильтром не должен срабатывать вслепую
        return any(app_matches(p, app_id) for p in self.apps)

    def save(self, directory: Path | None = None) -> Path:
        directory = directory or gestures_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = self.path or directory / f"{slugify(self.name)}.yaml"
        _atomic_write(path, yaml.safe_dump(self.to_dict(), allow_unicode=True,
                                           sort_keys=False, width=10**6))
        self.path = path
        return path

    def delete(self) -> None:
        if self.path and self.path.exists():
            self.path.unlink()


def parse_stroke(text: str | list) -> list[Point]:
    """``"0,0 5,10 …"`` → список точек. Списки пар тоже принимаются."""
    if isinstance(text, list):
        return [(float(p[0]), float(p[1])) for p in text]
    points: list[Point] = []
    for chunk in str(text).split():
        x, _sep, y = chunk.partition(",")
        points.append((float(x), float(y)))
    return points


def format_stroke(points: list[Point]) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)


def slugify(name: str) -> str:
    slug = re.sub(r"[^\w.-]+", "-", name.strip(), flags=re.UNICODE).strip("-")
    return slug.lower() or "gesture"


def load_gestures(directory: Path | None = None) -> list[Gesture]:
    directory = directory or gestures_dir()
    result: list[Gesture] = []
    if not directory.exists():
        return result
    for path in sorted(directory.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            result.append(Gesture.from_dict(data, path))
        except Exception as exc:  # битый файл не должен ронять демон
            import logging
            logging.getLogger(APP_NAME).error(_("не читается %s: %s"), path, exc)
    return result


# --- перенос жестов между машинами ------------------------------------------
BUNDLE_FORMAT = 1


def export_bundle(path: Path, gestures: list[Gesture] | None = None,
                  settings: Settings | None = None) -> int:
    """Сложить жесты в один файл. Возвращает, сколько выгружено."""
    import datetime

    from .version import __version__

    gestures = load_gestures() if gestures is None else gestures
    bundle = {
        "glyphstroke": BUNDLE_FORMAT,
        "version": __version__,
        "exported": datetime.date.today().isoformat(),
        "gestures": [g.to_dict() for g in gestures],
    }
    # база приложений едет вместе с жестами: без неё на новом месте вместо
    # «Firefox» в списке стоял бы голый класс окна
    apps = load_apps()
    if apps:
        bundle["apps"] = [app.to_dict() for app in apps]
    if settings is not None:
        bundle["settings"] = asdict(settings)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, yaml.safe_dump(bundle, allow_unicode=True, sort_keys=False,
                                       width=10 ** 6))
    return len(gestures)


@dataclass
class ImportResult:
    added: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    removed: int = 0
    settings_applied: bool = False
    apps_added: int = 0

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(_("добавлено {0}").format(len(self.added)))
        if self.replaced:
            parts.append(_("заменено {0}").format(len(self.replaced)))
        if self.removed:
            parts.append(_("удалено прежних {0}").format(self.removed))
        if self.apps_added:
            parts.append(_("приложений в списке прибавилось: {0}").format(self.apps_added))
        if self.settings_applied:
            parts.append(_("настройки применены"))
        return ", ".join(parts) or _("файл не содержал жестов")


def import_bundle(path: Path, replace: bool = False,
                  with_settings: bool = False) -> ImportResult:
    """Загрузить жесты из файла.

    Совпадающие по названию заменяются, остальные добавляются. ``replace``
    сначала убирает все прежние жесты — это точная копия чужой настройки.
    """
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or "gestures" not in data:
        raise ValueError(_("это не файл с жестами glyphstroke"))
    if int(data.get("glyphstroke", BUNDLE_FORMAT)) > BUNDLE_FORMAT:
        raise ValueError(_("файл сделан более новой версией программы"))

    result = ImportResult()
    existing = {g.name: g for g in load_gestures()}
    if replace:
        for gesture in existing.values():
            gesture.delete()
        result.removed = len(existing)
        existing = {}

    for raw in data["gestures"]:
        gesture = Gesture.from_dict(raw)
        previous = existing.get(gesture.name)
        if previous is not None:
            gesture.path = previous.path      # пишем поверх того же файла
            result.replaced.append(gesture.name)
        else:
            result.added.append(gesture.name)
        gesture.save()

    for raw in data.get("apps") or []:
        if isinstance(raw, dict) and str(raw.get("class", "") or "").strip():
            _app, created = add_app(str(raw["class"]), str(raw.get("name", "") or ""))
            result.apps_added += int(created)

    if with_settings and isinstance(data.get("settings"), dict):
        incoming = dict(data["settings"])
        overlay = OverlaySettings(**(incoming.pop("overlay", None) or {}))
        known = {f for f in Settings.__dataclass_fields__ if f != "overlay"}
        Settings(overlay=overlay,
                 **{k: v for k, v in incoming.items() if k in known}).save()
        result.settings_applied = True
    return result


# --- известные приложения ---------------------------------------------------
#: пометка приложения, пойманного мишенью: оно сверяется с классом окна
#: целиком. Строка без пометки — прежнее регулярное выражение по «класс окна
#: | заголовок». Выражение ловит и заголовки, поэтому «code» срабатывало в
#: браузере на вкладке, в названии которой встретилось это слово
CLASS_PREFIX = "class:"


def apps_path() -> Path:
    """База приложений общая для всех наборов: окна у них одни и те же."""
    return config_dir() / "apps.yaml"


@dataclass
class KnownApp:
    """Приложение из базы: класс окна и название для человека."""

    wm_class: str
    name: str = ""

    @property
    def pattern(self) -> str:
        return class_pattern(self.wm_class)

    @property
    def title(self) -> str:
        return self.name or self.wm_class

    def to_dict(self) -> dict:
        return {"class": self.wm_class, "name": self.name}


def class_pattern(wm_class: str) -> str:
    return CLASS_PREFIX + wm_class.strip()


def pattern_class(pattern: str) -> str | None:
    """Класс окна из записи с пометкой ``class:``; ``None`` — это выражение."""
    if pattern.startswith(CLASS_PREFIX):
        return pattern[len(CLASS_PREFIX):].strip()
    return None


def window_class(app_id: str) -> str:
    """``"firefox | Заголовок"`` → ``"firefox"``."""
    return app_id.split(" | ", 1)[0].strip()


def app_matches(pattern: str, app_id: str | None) -> bool:
    """Подходит ли окно под запись из ``apps`` жеста или ``excluded_apps``."""
    if not app_id:
        return False
    wanted = pattern_class(pattern)
    if wanted is not None:
        return wanted.lower() == window_class(app_id).lower()
    try:
        return re.search(pattern, app_id, re.IGNORECASE) is not None
    except re.error:
        return False  # опечатка в выражении не должна ронять разбор росчерка


def same_pattern(first: str, second: str) -> bool:
    return first.strip().lower() == second.strip().lower()


def load_apps() -> list[KnownApp]:
    path = apps_path()
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # битый файл не должен ронять редактор
        import logging
        logging.getLogger(APP_NAME).error(_("не читается %s: %s"), path, exc)
        return []
    apps: list[KnownApp] = []
    seen: set[str] = set()
    for raw in (data.get("apps") or []) if isinstance(data, dict) else []:
        if not isinstance(raw, dict):
            continue
        wm_class = str(raw.get("class", "") or "").strip()
        if not wm_class or wm_class.lower() in seen:
            continue
        seen.add(wm_class.lower())
        apps.append(KnownApp(wm_class, str(raw.get("name", "") or "").strip()))
    return sorted(apps, key=lambda app: app.title.lower())


def save_apps(apps: list[KnownApp]) -> None:
    path = apps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(apps, key=lambda app: app.title.lower())
    _atomic_write(path, yaml.safe_dump({"apps": [app.to_dict() for app in ordered]},
                                       allow_unicode=True, sort_keys=False))


def find_app(wm_class: str, apps: list[KnownApp] | None = None) -> KnownApp | None:
    apps = load_apps() if apps is None else apps
    wanted = wm_class.strip().lower()
    return next((app for app in apps if app.wm_class.lower() == wanted), None)


def add_app(wm_class: str, name: str = "") -> tuple[KnownApp, bool]:
    """Занести приложение в базу. Второе значение ``True`` — оно новое."""
    wm_class, name = wm_class.strip(), name.strip()
    if not wm_class:
        raise ValueError(_("у окна нет класса — такое приложение не запомнить"))
    apps = load_apps()
    existing = find_app(wm_class, apps)
    if existing is not None:
        if name and not existing.name:
            existing.name = name
            save_apps(apps)
        return existing, False
    app = KnownApp(wm_class, name)
    save_apps(apps + [app])
    return app, True


def pattern_title(pattern: str, apps: list[KnownApp]) -> str:
    """Как показать запись человеку: название из базы, класс или выражение."""
    wm_class = pattern_class(pattern)
    if wm_class is None:
        return pattern
    app = find_app(wm_class, apps)
    return app.title if app else wm_class


def describe_patterns(patterns: list[str], apps: list[KnownApp]) -> str:
    return ", ".join(pattern_title(pattern, apps) for pattern in patterns)


def all_gesture_dirs() -> list[tuple[str, Path]]:
    """Каталоги жестов всех наборов: основной и дополнительные."""
    return [("", gestures_dir(""))] + [(name, gestures_dir(name))
                                       for name in available_profiles()]


@dataclass
class AppUsage:
    """Где записано приложение: жесты всех наборов и список исключений."""

    gestures: list[str] = field(default_factory=list)
    excluded: bool = False


def apps_usage() -> dict[str, AppUsage]:
    """Класс окна в нижнем регистре → где он используется. Один проход."""
    usage: dict[str, AppUsage] = {}
    for profile, directory in all_gesture_dirs():
        for gesture in load_gestures(directory):
            label = f"{profile}: {gesture.name}" if profile else gesture.name
            for pattern in gesture.apps:
                wm_class = pattern_class(pattern)
                if wm_class is not None:
                    usage.setdefault(wm_class.lower(), AppUsage()).gestures.append(label)
    for pattern in Settings.load().excluded_apps:
        wm_class = pattern_class(pattern)
        if wm_class is not None:
            usage.setdefault(wm_class.lower(), AppUsage()).excluded = True
    return usage


@dataclass
class AppRemoval:
    unbound: list[str] = field(default_factory=list)
    disabled: list[str] = field(default_factory=list)
    excluded: bool = False


def remove_app(wm_class: str) -> AppRemoval:
    """Убрать приложение из базы вместе со всеми привязками к нему.

    Жест, у которого не осталось других приложений, выключается: иначе жест
    «только в Firefox» молча заработал бы везде.
    """
    pattern = class_pattern(wm_class)
    save_apps([app for app in load_apps()
               if app.wm_class.lower() != wm_class.strip().lower()])
    result = AppRemoval()
    for profile, directory in all_gesture_dirs():
        for gesture in load_gestures(directory):
            kept = [p for p in gesture.apps if not same_pattern(p, pattern)]
            if len(kept) == len(gesture.apps):
                continue
            label = f"{profile}: {gesture.name}" if profile else gesture.name
            gesture.apps = kept
            result.unbound.append(label)
            if not kept and gesture.enabled:
                gesture.enabled = False
                result.disabled.append(label)
            gesture.save()
    settings = Settings.load()
    kept = [p for p in settings.excluded_apps if not same_pattern(p, pattern)]
    if len(kept) != len(settings.excluded_apps):
        settings.excluded_apps = kept
        settings.save()
        result.excluded = True
    return result


def bound_events(gestures: list[Gesture]) -> dict[str, Gesture]:
    """Особые жесты по событию: последний включённый выигрывает."""
    return {g.event: g for g in gestures if g.enabled and g.event in EVENTS}


def find_conflicts(gestures: list[Gesture]) -> dict[str, list[str]]:
    """Коды направлений, занятые сразу несколькими включёнными жестами.

    Такие жесты гасят друг друга: нарисованное одинаково похоже на оба, и
    защита от неоднозначности не даёт сработать ни одному. Молча это выглядит
    как «жест не работает», поэтому о совпадении нужно сказать вслух.
    """
    by_code: dict[str, list[Gesture]] = {}
    for gesture in gestures:
        if not gesture.enabled:
            continue
        keys = [gesture.event] if gesture.event else \
            [code.strip().upper() for code in gesture.directions]
        for key in keys:
            by_code.setdefault(key, []).append(gesture)

    conflicts: dict[str, list[str]] = {}
    for code, group in by_code.items():
        clashing: list[str] = []
        for i, first in enumerate(group):
            for second in group[i + 1:]:
                if not _scopes_clash(first, second):
                    continue
                for name in (first.name, second.name):
                    if name not in clashing:
                        clashing.append(name)
        if clashing:
            conflicts[code] = clashing
    return conflicts


def _scopes_clash(first: Gesture, second: Gesture) -> bool:
    """Мешают ли друг другу два жеста с одинаковым росчерком.

    Жест приложения и общий жест уживаются: в своём приложении выигрывает
    первый, в остальных — второй. Ссорятся только те, чьи области совпадают.
    """
    if not first.apps and not second.apps:
        return True
    if bool(first.apps) != bool(second.apps):
        return False
    return bool({a.lower() for a in first.apps} & {a.lower() for a in second.apps})


def ensure_default_config(force: bool = False) -> Path:
    """Создать каталог настроек и разложить стартовый набор жестов."""
    migrate_legacy_config()
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    if force or not settings_path().exists():
        Settings().save()
    gdir = gestures_dir()
    gdir.mkdir(parents=True, exist_ok=True)
    if force or not any(gdir.glob("*.yaml")):
        src = Path(__file__).resolve().parent / "data" / "gestures"
        for path in sorted(src.glob("*.yaml")):
            shutil.copy(path, gdir / path.name)
        translate_gesture_names(gdir)
    return directory


def translate_gesture_names(directory: Path) -> int:
    """Перевести названия и пояснения стартовых жестов на язык интерфейса.

    Файлы жестов — это данные пользователя, и переводить их на лету нельзя:
    он их правит и переименовывает. Поэтому перевод делается один раз, при
    создании набора.
    """
    changed = 0
    for path in sorted(directory.glob("*.yaml")):
        gesture = Gesture.from_dict(
            yaml.safe_load(path.read_text(encoding="utf-8")) or {}, path)
        name, description = _(gesture.name), _(gesture.description.strip())
        if (name, description) == (gesture.name, gesture.description.strip()):
            continue
        gesture.name, gesture.description = name, description
        gesture.save()
        changed += 1
    return changed


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
