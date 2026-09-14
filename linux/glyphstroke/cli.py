"""Командная строка ``glyphstroke``."""

from __future__ import annotations

import argparse
import grp
import os
import pwd
import re
import selectors
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import capture, config, shellext, standard, update
from .config import (Gesture, Settings, export_bundle, find_conflicts,
                     import_bundle, load_gestures)
from .daemon import Daemon, setup_logging
from .recognizer import Recognizer, direction_code, resample
from . import version as about
from .version import __version__

from . import i18n
from .i18n import _

DATA_DIR = Path(__file__).resolve().parent / "data"
UDEV_RULE = "/etc/udev/rules.d/99-glyphstroke.rules"
EXTENSION_UUID = shellext.EXTENSION_UUID


# --- сбор росчерков с настоящей мыши ---------------------------------------
class StrokeCollector:
    """Захватывает мышь и отдаёт росчерки — для записи и проверки жестов."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.devices = capture.find_pointers(
            include=settings.device_include,
            exclude=settings.device_exclude,
            allow_touchpads=settings.allow_touchpads,
        )
        if not self.devices:
            raise RuntimeError(_("мышь не найдена — посмотрите «glyphstroke doctor»"))
        self.mirror = capture.Mirror(capture.build_mirror(self.devices))
        time.sleep(0.2)
        trigger = capture.ecodes.ecodes.get(
            settings.trigger_button.upper()
            if settings.trigger_button.upper().startswith("BTN_")
            else f"BTN_{settings.trigger_button.upper()}",
            capture.ecodes.BTN_RIGHT,
        )
        self.machines = {}
        for dev in self.devices:
            try:
                dev.grab()
            except OSError as exc:
                self.close()
                raise RuntimeError(
                    _("мышь {0} занята другим процессом ({1}). Похоже, работает демон — остановите его: systemctl --user stop glyphstroke").format(dev.name, exc)
                ) from exc
            self.machines[dev.fd] = capture.StrokeMachine(
                self.mirror, trigger, settings.min_stroke_px)

    def strokes(self, count: int):
        import selectors
        sel = selectors.DefaultSelector()
        for dev in self.devices:
            sel.register(dev, selectors.EVENT_READ, dev)
        collected = 0
        while collected < count:
            for key, _mask in sel.select(timeout=0.2):
                dev = key.data
                machine = self.machines[dev.fd]
                for event in dev.read():
                    for ev in machine.handle(event):
                        if ev.kind == "finish":
                            collected += 1
                            yield ev.points
                            if collected >= count:
                                return

    def close(self) -> None:
        for dev in self.devices:
            try:
                dev.ungrab()
            except Exception:
                pass
            dev.close()
        self.mirror.close()


# --- подкоманды -------------------------------------------------------------
def cmd_init(args) -> int:
    path = config.ensure_default_config(force=args.force)
    print(_("настройки: {0}").format(path))
    print(_("жестов в наборе: {0}").format(len(load_gestures())))
    return 0


def cmd_devices(args) -> int:
    settings = Settings.load()
    found = capture.find_pointers(settings.device_include, settings.device_exclude,
                                  settings.allow_touchpads)
    if not found:
        print(_("подходящих устройств не найдено"))
        return 1
    for dev in found:
        kind = _("тачпад") if capture.is_touchpad(dev) else _("мышь")
        print(f"{dev.path}\t{kind}\t{dev.name}")
        dev.close()
    return 0


def cmd_list(args) -> int:
    gestures = load_gestures()
    # пока наборов не заводили, про них и говорить незачем
    if config.active_profile() or config.available_profiles():
        print(_("набор: {0}\n").format(profile_label(config.active_profile())))
    if not gestures:
        print(_("жестов нет — выполните «glyphstroke init»"))
        return 1
    for g in gestures:
        mark = "✓" if g.enabled else " "
        if g.event:
            code = config.EVENT_SHORT.get(g.event, g.event)
        else:
            code = ", ".join(g.directions) or _("{0} образц.").format(len(g.templates))
        # У стандартного действия в файле лежит имя вроде «copy» — в списке
        # печатаем человеческое название, иначе строка нечитаема.
        actions = "; ".join(
            f"{a.type}: {standard.label(a.value)}" if a.type == "standard"
            else f"{a.type}: {a.value}"
            for a in g.actions)
        if g.menu:
            menu = _("меню: {0}").format(", ".join(i.name for i in g.menu))
            actions = f"{actions}; {menu}" if actions else menu
        actions = actions or "—"
        apps = _("  [только: {0}]").format(
            config.describe_patterns(g.apps, config.load_apps())) if g.apps else ""
        print(f"[{mark}] {g.name:<24} {code:<14} {actions}{apps}")
    print_conflicts(gestures)
    return 0


def profile_argument(text: str) -> str:
    """Как назвать основной набор в командной строке.

    Он же «-», он же «base»: подсказка в списке печатает его по-русски, но
    зависеть от языка интерфейса аргумент команды не должен.
    """
    value = (text or "").strip()
    aliases = {"-", "base", "default", config.BASE_PROFILE,
               _(config.BASE_PROFILE).lower()}
    return "" if value.lower() in aliases else value


def profile_label(name: str) -> str:
    return name or _(config.BASE_PROFILE)


def cmd_profile(args) -> int:
    """Наборы жестов: показать, переключить, завести, убрать."""
    action = getattr(args, "action", None) or "list"
    try:
        if action == "list":
            current = config.active_profile()
            for name in ["", *config.available_profiles()]:
                mark = "*" if name == current else " "
                print(f"{mark} {profile_label(name):<24} "
                      + _("жестов: {0}").format(config.profile_size(name)))
            print(_("\nпереключить: glyphstroke profile use ИМЯ; "
                  "завести: glyphstroke profile new ИМЯ [--copy]"))
            return 0
        if not getattr(args, "name", None):
            print(_("нужно имя набора"), file=sys.stderr)
            return 1
        if action == "use":
            name = config.use_profile(profile_argument(args.name))
            print(_("текущий набор: {0} (жестов: {1})").format(
                profile_label(name), config.profile_size(name)))
        elif action == "new":
            source = config.active_profile() if args.copy else None
            name = config.create_profile(args.name, copy_from=source)
            print(_("набор «{0}» заведён (жестов: {1})").format(
                name, config.profile_size(name)))
            if not args.use:
                print(_("переключиться: glyphstroke profile use {0}").format(name))
                return 0
            config.use_profile(name)
            print(_("текущий набор: {0}").format(name))
        elif action == "remove":
            name = profile_argument(args.name)
            config.remove_profile(name)
            print(_("набор «{0}» удалён").format(profile_label(name)))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    _reload_daemon()
    return 0


def print_conflicts(gestures: list[Gesture]) -> bool:
    """Сказать о жестах, описанных одинаково. Возвращает ``True``, если такие есть."""
    conflicts = find_conflicts(gestures)
    for code, names in conflicts.items():
        print(_("\n! код {0} занят сразу несколькими жестами: {1}").format(code, ', '.join('«' + n + '»' for n in names)))
        print(_("  нарисованное одинаково похоже на каждый, поэтому не сработает "
              "ни один —"))
        print(_("  оставьте код одному жесту, а остальным задайте свой код или "
              "образцы росчерка"))
    return bool(conflicts)


def cmd_record(args) -> int:
    settings = Settings.load()
    count = max(1, args.samples)
    print(_("Жест «{0}»: удерживайте {1} и нарисуйте его {2} раз(а).").format(args.name, settings.trigger_button, count))
    samples = []
    with ServicePause():
        collector = StrokeCollector(settings)
        try:
            for i, points in enumerate(collector.strokes(count), 1):
                samples.append(resample(points))
                print(_("  образец {0}/{1}: {2} точек, код направлений {3}").format(i, count, len(points), direction_code(points) or '—'))
        finally:
            collector.close()

    existing = {g.name: g for g in load_gestures()}
    gesture = existing.get(args.name) or Gesture(name=args.name)
    if args.replace:
        gesture.templates = samples
    else:
        gesture.templates = list(gesture.templates) + samples
    if args.code:
        codes = [direction_code(sample) for sample in samples]
        common = max(set(codes), key=codes.count)
        if common and common not in gesture.directions:
            gesture.directions.append(common)
        print(_("код направлений жеста: {0}").format(common or '—'))
    if args.keys:
        gesture.actions = [config.Action("keys", args.keys)]
    elif args.command:
        gesture.actions = [config.Action("command", args.command)]
    elif not gesture.actions:
        gesture.actions = [config.Action("none", "")]
    path = gesture.save()
    print(_("сохранено: {0}").format(path))
    _reload_daemon()
    return 0


def cmd_test(args) -> int:
    from .ipc import socket_path

    if socket_path().exists():
        # демон держит мышь эксклюзивно, второй раз её не захватить —
        # смотрим его же глазами
        print(_("демон запущен, показываю распознавание через его канал"))
        return cmd_watch(args)

    settings = Settings.load()
    gestures = [g for g in load_gestures() if g.enabled]
    recognizer = Recognizer([g.to_def() for g in gestures],
                            settings.min_score, settings.min_margin)
    print(_("Рисуйте жесты (Ctrl+C — выход). Действия не выполняются."))
    pause = ServicePause()
    pause.__enter__()
    collector = StrokeCollector(settings)
    try:
        for points in collector.strokes(10 ** 9):
            match = recognizer.recognize(points)
            best = ", ".join(f"{n} {s:.2f}" for n, s in recognizer.score_all(points)[:3])
            print(_("код {0:<12} → {1:<24} [{2}]").format(match.code or '—', match.name or 'не распознано', best or 'нет совпадений'))
    except KeyboardInterrupt:
        print()
    finally:
        collector.close()
        pause.__exit__(None, None, None)
    return 0


def cmd_daemon(args) -> int:
    from .daemon import main as daemon_main
    argv = []
    if args.dry_run:
        argv.append("--dry-run")
    if args.monitor:
        argv.append("--monitor")
    return daemon_main(argv)


def cmd_gui(args) -> int:
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        print(_("GUI недоступен: {0}\nУстановите: sudo apt install python3-gi gir1.2-gtk-3.0").format(exc), file=sys.stderr)
        return 1
    # аргументы командной строки уже разобраны здесь; редактору отдаём пустой
    # список, иначе он увидит слово «gui» и посчитает его лишним аргументом
    return gui_main([])


def group_state(group: str = "input") -> str:
    """Состояние членства в группе.

    Различает три случая, которые легко перепутать: ``effective`` — группа
    действует прямо сейчас, ``pending`` — записана в /etc/group, но сеанс
    начался раньше и её не видит (нужен перезаход), ``absent`` — не назначена.
    """
    if os.getuid() == 0:
        return "effective"
    try:
        entry = grp.getgrnam(group)
    except KeyError:
        return "absent"
    if entry.gr_gid in os.getgroups():
        return "effective"
    user = pwd.getpwuid(os.getuid()).pw_name
    return "pending" if user in entry.gr_mem else "absent"


def device_node_info(path: str) -> str:
    """``root:input 0660`` — чтобы видеть, применилось ли правило udev."""
    try:
        st = os.stat(path)
    except OSError:
        return _("нет устройства")
    try:
        owner = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner = str(st.st_uid)
    try:
        group = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group = str(st.st_gid)
    return f"{owner}:{group} {oct(st.st_mode & 0o777)[2:]}"


# --- привязка к одной мыши --------------------------------------------------
def name_pattern(name: str) -> str:
    """Имя устройства → выражение, совпадающее ровно с ним."""
    return f"^{re.escape(name)}$"


def bound_device(settings: Settings) -> str:
    return ", ".join(
        p.strip("^$").replace("\\", "") for p in settings.device_include
    ) or _("все найденные мыши")


def stable_id(dev) -> str:
    """Чем привязываться, от самого надёжного к самому простому.

    by-id строится по производителю и серийному номеру и переживает смену
    разъёма; by-path привязан к разъёму, но хотя бы различает одинаковые
    устройства; имя годится, когда мышь одна.
    """
    aliases = capture.device_aliases(dev)
    for prefix in ("/dev/input/by-id/", "/dev/input/by-path/"):
        for alias in aliases:
            if alias.startswith(prefix):
                return alias
    return dev.name or dev.path


def detect_pointer(timeout: float = 20.0):
    """Дождаться нажатия кнопки и вернуть устройство, на котором нажали.

    Демон держит мышь эксклюзивно, поэтому во время определения его нужно
    остановить — иначе события до нас не дойдут.
    """
    devices = capture.find_pointers()
    if not devices:
        raise RuntimeError(_("мышей не найдено — посмотрите «glyphstroke doctor»"))
    selector = selectors.DefaultSelector()
    for dev in devices:
        selector.register(dev, selectors.EVENT_READ, dev)
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            for key, _mask in selector.select(timeout=0.2):
                dev = key.data
                for event in dev.read():
                    if event.type == capture.ecodes.EV_KEY and event.value == 1:
                        return stable_id(dev), dev.name
        return None
    finally:
        for dev in devices:
            dev.close()


class ServicePause:
    """Остановить службу, пока мышь нужна нам самим, и вернуть как было.

    Демон держит мышь эксклюзивно, поэтому записать жест или посмотреть
    росчерк своими глазами, пока он работает, нельзя.
    """

    def __init__(self, announce: bool = True):
        self.announce = announce
        self.was_active = False

    def __enter__(self) -> "ServicePause":
        self.was_active = service_is_active()
        if self.was_active:
            if self.announce:
                print(_("останавливаю службу, чтобы забрать мышь…"))
            subprocess.run(["systemctl", "--user", "stop", "glyphstroke"], check=False)
            time.sleep(0.3)
        return self

    def __exit__(self, *exc_info) -> None:
        if self.was_active:
            subprocess.run(["systemctl", "--user", "start", "glyphstroke"], check=False)
            if self.announce:
                print(_("служба запущена обратно"))


def service_is_active() -> bool:
    result = subprocess.run(["systemctl", "--user", "is-active", "glyphstroke"],
                            capture_output=True, text=True)
    return result.stdout.strip() == "active"


#: что systemctl отвечает про включённую службу — «alias» и «indirect»
#: тоже означают, что при входе в систему она поднимется
ENABLED_STATES = {"enabled", "enabled-runtime", "alias", "static", "indirect"}


def service_is_enabled() -> bool | None:
    """Включён ли автозапуск. ``None`` — управлять им отсюда нельзя.

    ``not-found`` — это выключено: файла службы просто ещё нет. А вот пустой
    ответ означает, что systemd пользователя недоступен (нет шины, контейнер,
    сеанс без systemd), и тогда кнопкой автозапуска ничего не сделать.
    """
    if not shutil.which("systemctl"):
        return None
    result = subprocess.run(["systemctl", "--user", "is-enabled", "glyphstroke"],
                            capture_output=True, text=True)
    state = result.stdout.strip()
    if not state:
        return None
    return state in ENABLED_STATES


def cmd_bind(args) -> int:
    settings = Settings.load()
    if args.clear:
        settings.device_include = []
        settings.save()
        print(_("привязка снята: демон снова берёт все найденные мыши"))
        _restart_daemon()
        return 0
    if args.device:
        settings.device_include = [name_pattern(args.device)]
        settings.save()
        print(_("привязано к устройству: {0}").format(args.device))
        _restart_daemon()
        return 0

    found = capture.find_pointers()
    candidates = [(stable_id(dev), dev.name) for dev in found]
    for dev in found:
        dev.close()
    if not candidates:
        print(_("мышей не найдено — посмотрите «glyphstroke doctor»"), file=sys.stderr)
        return 1
    if len(candidates) == 1 and not args.ask:
        target, name = candidates[0]
    else:
        was_active = service_is_active()
        if was_active:
            print(_("останавливаю службу на время определения…"))
            subprocess.run(["systemctl", "--user", "stop", "glyphstroke"], check=False)
            time.sleep(0.3)
        print(_("Нажмите любую кнопку на той мыши, которую нужно слушать…"))
        try:
            detected = detect_pointer()
        finally:
            if was_active:
                subprocess.run(["systemctl", "--user", "start", "glyphstroke"], check=False)
        if not detected:
            print(_("кнопку так и не нажали, ничего не поменял"), file=sys.stderr)
            return 1
        target, name = detected

    settings.device_include = [name_pattern(target)]
    settings.save()
    print(_("привязано: {0}").format(name))
    if target != name:
        print(_("по постоянной ссылке {0}").format(target))
    print(_("остальные устройства ввода демон трогать не будет"))
    _restart_daemon()
    return 0


# --- расширение GNOME Shell -------------------------------------------------
# Работа с расширением оболочки живёт в glyphstroke/shellext.py: этим же кодом
# пользуется демон, который обновляет копию в домашнем каталоге при запуске.
extension_dir = shellext.extension_dir
extension_version = shellext.extension_version
extension_versions = shellext.extension_versions
extension_state = shellext.state
enable_via_gsettings = shellext.enable_via_gsettings


def cmd_shell_extension(args) -> int:
    target = extension_dir()

    if args.action == "remove":
        if shutil.which("gnome-extensions"):
            subprocess.run(["gnome-extensions", "disable", EXTENSION_UUID], check=False,
                           capture_output=True)
        shutil.rmtree(target, ignore_errors=True)
        print(_("расширение удалено: {0}").format(target))
        return 0

    if args.action == "status":
        print(_("состояние: {0}").format(extension_state()))
        print(_("каталог:   {0}").format(target))
        from .ipc import socket_path
        sock = socket_path()
        print(_("канал следа: {0} ({1})").format(sock, 'демон слушает' if sock.exists() else 'демон не запущен'))
        return 0

    copied, enabled = shellext.install()
    if not copied:
        print(_("расширение не найдено в пакете программы"), file=sys.stderr)
        return 1
    print(_("расширение установлено: {0}").format(target))

    print(_("расширение включено") if enabled
          else _("включить не удалось — сделайте это в приложении «Расширения»"))
    print()
    print(_("Оболочка загружает новые расширения при запуске, поэтому в Wayland"))
    print(_("нужно выйти из системы и войти снова — после этого след появится."))
    return 0


# --- наблюдение за распознаванием ------------------------------------------
def daemon_info(timeout: float = 1.0) -> tuple[str, str, str] | None:
    """Версия, pid и состояние перехвата работающего демона."""
    import socket as socket_module

    from .ipc import socket_path

    path = socket_path()
    if not path.exists():
        return None
    client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        greeting = client.recv(256).decode("utf-8", "replace").strip()
    except OSError:
        return None
    finally:
        client.close()
    parts = greeting.split("\t")
    if len(parts) >= 3 and parts[0] == "hello":
        return parts[1], parts[2], (parts[3] if len(parts) > 3 else "active")
    return None



def format_stroke_line(line: str) -> str | None:
    """Строка канала → строка для человека."""
    parts = line.split("\t")
    if parts and parts[0] == "action":
        name, summary, app, transport = (parts + ["-"] * 5)[1:5]
        window = _(", окно: {0}").format(app) if app != "-" else ""
        how = "" if transport == "-" else _(", клавиши через {0}").format(
            {"shell": _("оболочку"), "uinput": "uinput"}.get(transport, transport))
        return _("  выполнено: {0}{1}{2}").format(summary, window, how)
    if parts and parts[0] == "menu":
        return _("  меню «{0}»: {1}").format(parts[1], ", ".join(parts[2:]))
    if parts and parts[0] == "menu-choice":
        name, item = (parts + ["-"] * 3)[1:3]
        if item == "-":
            return _("  меню «{0}» закрыто без выбора").format(name)
        return _("  меню «{0}»: выбран «{1}»").format(name, item)
    if not parts or parts[0] != "stroke":
        return None
    code, name, score, runner, runner_score = (parts + ["-"] * 6)[1:6]
    if name != "-":
        return _("код {0:<12} → «{1}» ({2})").format(code, name, score)
    near = _(", ближайший «{0}» ({1})").format(runner, runner_score) if runner != "-" else ""
    return _("код {0:<12} → не распознано{1}").format(code, near)


def format_hello(line: str) -> str:
    parts = line.split("\t")
    version = parts[1] if len(parts) > 1 else "?"
    pid = parts[2] if len(parts) > 2 else "?"
    text = _("демон версии {0} (pid {1})").format(version, pid)
    state = parts[3] if len(parts) > 3 else "active"
    if state == "paused":
        text += _(" — перехват приостановлен")
    if version != __version__:
        text += (_("\n  ВНИМАНИЕ: установлена версия {0}, а работает {1} — перезапустите службу: systemctl --user restart glyphstroke").format(__version__, version))
    return text


def save_stroke(directory: Path, points_line: str, report_line: str) -> Path:
    """Сложить росчерк в файл — его можно разобрать позже или отправить."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = directory / f"stroke-{stamp}-{int(time.time() * 1000) % 1000:03d}.yaml"
    fields = report_line.split("\t") if report_line else []
    body = [
        _("# росчерк, снятый glyphstroke {0}").format(__version__),
        f"code: {fields[1] if len(fields) > 1 else '-'}",
        f"recognized: {fields[2] if len(fields) > 2 else '-'}",
        f"score: {fields[3] if len(fields) > 3 else '-'}",
        f"points: \"{points_line.split(chr(9), 1)[1]}\"",
        "",
    ]
    path.write_text("\n".join(body), encoding="utf-8")
    return path


def send_command(command: str, wait_state: bool = True,
                 timeout: float = 2.0) -> str | None:
    """Послать демону команду и, если нужно, дождаться нового состояния."""
    import socket as socket_module

    from .ipc import socket_path

    path = socket_path()
    if not path.exists():
        return None
    client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        client.recv(256)                      # приветствие
        client.sendall((command + "\n").encode("utf-8"))
        if not wait_state:
            return ""
        buffer = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            buffer += client.recv(256).decode("utf-8", "replace")
            for line in buffer.splitlines():
                if line.startswith("state\t"):
                    return line.split("\t")[1]
        return None
    except OSError:
        return None
    finally:
        client.close()


def pick_window(timeout: float = 2.0) -> tuple[str, str] | str:
    """Какое окно под курсором — спросить у оболочки через демона.

    Возвращает (класс окна, название приложения) или причину неудачи:
    ``nodaemon`` — демон не запущен, ``noshell`` — расширения оболочки нет на
    связи, ``nowindow`` — под курсором нет окна приложения, ``timeout`` —
    ответа не дождались.
    """
    import socket as socket_module

    from .ipc import socket_path

    path = socket_path()
    if not path.exists():
        return "nodaemon"
    client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(str(path))
        client.sendall(b"iam editor\npick\n")
        buffer = b""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            chunk = client.recv(4096)
            if not chunk:
                return "nodaemon"
            buffer += chunk
            while b"\n" in buffer:
                raw, _sep, buffer = buffer.partition(b"\n")
                parts = raw.decode("utf-8", "replace").split("\t")
                if parts[0] != "picked":
                    continue          # приветствие и чужие новости канала
                wm_class = parts[1] if len(parts) > 1 else "-"
                detail = parts[2] if len(parts) > 2 else ""
                if wm_class in ("", "-"):
                    return detail or "nowindow"
                return wm_class, detail or wm_class
        return "timeout"
    except TimeoutError:
        return "timeout"
    except OSError:
        return "nodaemon"
    finally:
        client.close()


def cmd_pause(args) -> int:
    command = {"pause": "pause", "resume": "resume", "toggle": "toggle"}[args.command]
    state = send_command(command)
    if state is None:
        print(_("демон не запущен — приостанавливать нечего"), file=sys.stderr)
        return 1
    print(_("перехват приостановлен — правая кнопка работает как обычно")
          if state == "paused" else _("перехват включён"))
    return 0


def cmd_watch(args) -> int:
    """Показывать, что распознаёт работающий демон.

    Читаем тот же канал, что и рисовальщик следа, поэтому мышь ни у кого не
    отбираем и службу останавливать не нужно.
    """
    import socket as socket_module

    from .ipc import socket_path

    path = socket_path()
    if not path.exists():
        print(_("демон не запущен — канал не открыт.\n"
              "Запустите службу («glyphstroke service enable») или сам демон "
              "(«glyphstroke daemon»)"), file=sys.stderr)
        return 1
    client = socket_module.socket(socket_module.AF_UNIX, socket_module.SOCK_STREAM)
    try:
        client.connect(str(path))
    except OSError as exc:
        print(_("не удалось подключиться к демону: {0}").format(exc), file=sys.stderr)
        return 1

    save_dir = Path(args.save).expanduser() if getattr(args, "save", None) else None
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        print(_("росчерки сохраняю в {0}").format(save_dir))
    print(_("Рисуйте жесты — покажу, что распознаётся. Ctrl+C — выход."))
    buffer = b""
    last_report = ""
    try:
        while True:
            chunk = client.recv(65536)
            if not chunk:
                print(_("демон закрыл канал"))
                return 1
            buffer += chunk
            while b"\n" in buffer:
                raw, _sep, buffer = buffer.partition(b"\n")
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("hello\t"):
                    print(format_hello(line), flush=True)
                    continue
                if line.startswith("state\t"):
                    print(_("перехват ") + (_("приостановлен")
                          if line.split("\t")[1] == "paused" else _("включён")),
                          flush=True)
                    continue
                if line.startswith("stroke\t"):
                    last_report = line
                if line.startswith("points\t") and save_dir:
                    print(_("  сохранён: {0}").format(save_stroke(save_dir, line, last_report).name),
                          flush=True)
                    continue
                text = format_stroke_line(line)
                if text:
                    print(text, flush=True)
    except KeyboardInterrupt:
        print()
        return 0
    finally:
        client.close()


def cmd_export(args) -> int:
    path = Path(args.file).expanduser()
    settings = Settings.load() if args.with_settings else None
    count = export_bundle(path, settings=settings)
    print(_("выгружено жестов: {0} → {1}").format(count, path))
    if args.with_settings:
        print(_("вместе с настройками"))
    return 0


def cmd_import(args) -> int:
    path = Path(args.file).expanduser()
    if not path.exists():
        print(_("файла нет: {0}").format(path), file=sys.stderr)
        return 1
    try:
        result = import_bundle(path, replace=args.replace,
                              with_settings=args.with_settings)
    except (ValueError, yaml_error()) as exc:
        print(_("не удалось прочитать файл: {0}").format(exc), file=sys.stderr)
        return 1
    print(result.summary())
    for name in result.added:
        print(f"  + {name}")
    for name in result.replaced:
        print(f"  ~ {name}")
    print_conflicts(load_gestures())
    _reload_daemon()
    return 0


def yaml_error():
    import yaml
    return yaml.YAMLError


def about_lines() -> list[str]:
    """Сведения о программе и окружении — их удобно приложить к письму."""
    running = daemon_info()
    if running is None:
        daemon_state = _("не запущен")
    else:
        daemon_version, pid, state = running
        daemon_state = (_("версия {0}, pid {1}, {2}").format(daemon_version, pid, 'приостановлен' if state == 'paused' else 'работает'))
    session = os.environ.get("XDG_SESSION_TYPE", _("неизвестно"))
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", _("неизвестно"))
    return [
        f"Glyphstroke {about.__version__}",
        _(about.SUMMARY),
        "",
        _("Обновлено:   {0}").format(about.RELEASE_DATE),
        _("Разработчик: {0}").format(about.AUTHOR),
        _("Почта:       {0}  (сюда же об ошибках)").format(about.EMAIL),
        _("Лицензия:    {0}, © {1} {2}").format(about.LICENSE, about.YEARS, about.AUTHOR),
        "",
        _("Сеанс:       {0}, окружение {1}").format(session, desktop),
        _("Демон:       {0}").format(daemon_state),
        _("Настройки:   {0}").format(config.config_dir()),
        _("Расширение:  {0}").format(extension_state()),
    ]


def cmd_help(args) -> int:
    from . import help as help_text

    print(help_text.to_plain(args.topic))
    if not args.topic:
        print(_("\nОтдельный раздел: glyphstroke help <часть названия>, например "
              "«glyphstroke help действия»"))
    return 0


def cmd_about(args) -> int:
    print("\n".join(about_lines()))
    return 0


def cmd_doctor(args) -> int:
    ok = True
    def check(label: str, good: bool, hint: str = "") -> None:
        nonlocal ok
        print(f"[{'✓' if good else '✗'}] {label}")
        if not good:
            ok = False
            if hint:
                print(f"    → {hint}")

    print(_("сессия: {0}, DISPLAY={1}, WAYLAND_DISPLAY={2}").format(os.environ.get('XDG_SESSION_TYPE', 'неизвестно'), os.environ.get('DISPLAY') or '—', os.environ.get('WAYLAND_DISPLAY') or '—'))
    try:
        import evdev  # noqa: F401
        check(_("модуль python3-evdev"), True)
    except ImportError:
        check(_("модуль python3-evdev"), False, "sudo apt install python3-evdev")

    user = pwd.getpwuid(os.getuid()).pw_name
    state = group_state("input")
    relogin = (_("группа назначена, но этот сеанс начался раньше и её не видит. "
               "Выйдите из системы и войдите снова; для текущего терминала "
               "хватит «newgrp input»"))
    check(_("группа input действует у {0}").format(user), state == "effective",
          relogin if state == "pending"
          else _("sudo usermod -aG input {0}, затем выйти из системы и войти снова").format(user))
    # подсказку про перезаход печатаем один раз: остальные пункты — её следствие
    consequence = _("следствие пункта выше") if state == "pending" else ""
    readable = any(os.access(p, os.R_OK) for p in Path("/dev/input").glob("event*"))
    check(_("чтение /dev/input/event*"), readable,
          consequence or _("доступ даёт группа input"))
    uinput_hint = consequence or (
        "sudo modprobe uinput" if not os.path.exists("/dev/uinput")
        else _("правило udev ставит ./install.sh — проверьте, что владелец "
             "устройства root:input, а права 660"))
    check(_("доступ к /dev/uinput ({0})").format(device_node_info('/dev/uinput')),
          os.access("/dev/uinput", os.W_OK), uinput_hint)

    settings = Settings.load()
    touch_code = capture.key_code(settings.touchpad_key)
    touchpads = capture.find_touchpads(settings.device_exclude) if touch_code else []
    keyboards = capture.find_keyboards(touch_code) if touchpads else []
    for dev in touchpads + keyboards:
        dev.close()
    if touch_code is None:
        print(_("[i] рисование на тачпаде выключено: клавиша не назначена"))
    else:
        print(_("[i] рисование на тачпаде: зажмите {0} и ведите пальцем; "
              "тачпадов {1}, клавиатур с этой клавишей {2}").format(
                  capture.key_label(settings.touchpad_key), len(touchpads),
                  len(keyboards)))
    try:
        found = capture.find_pointers(settings.device_include, settings.device_exclude,
                                      settings.allow_touchpads)
        # на ноутбуке без мыши демону хватает тачпада с клавишей
        check(_("найдено мышей: {0}").format(len(found)),
              bool(found) or bool(touchpads and keyboards),
              consequence if not readable
              else _("если мышь не видна, задайте device_include в settings.yaml"))
        for dev in found:
            print(f"    {dev.path}  {dev.name}")
            dev.close()
    except Exception as exc:
        check(_("поиск мышей"), False, str(exc))

    running = daemon_info()
    if running is None:
        print(_("[i] демон не запущен (служба: systemctl --user status glyphstroke)"))
    else:
        version, pid, state = running
        note = _("перехват приостановлен") if state == "paused" else _("перехват включён")
        if version == __version__:
            print(_("[✓] демон работает: версия {0}, pid {1}, {2}").format(version, pid, note))
        else:
            ok = False
            print(_("[✗] демон работает ({0}), но версии {1}, а установлена {2}").format(note, version, __version__))
            print("    → systemctl --user restart glyphstroke")
    print(_("[i] слушаем: {0} (привязать одну — «glyphstroke bind»)").format(bound_device(settings)))
    check(_("каталог настроек {0}").format(config.config_dir()), config.config_dir().exists(),
          "glyphstroke init")
    gestures = load_gestures()
    if config.active_profile() or config.available_profiles():
        print(_("[i] набор жестов: {0} (переключить — «glyphstroke profile use ИМЯ»)").format(
            profile_label(config.active_profile())))
    check(_("жестов загружено: {0}").format(len(gestures)), bool(gestures), "glyphstroke init")
    conflicting = find_conflicts(gestures)
    check(_("коды жестов не пересекаются"), not conflicting,
          "; ".join(f"{code}: {', '.join(names)}"
                    for code, names in conflicting.items())
          + _(" — сработать не сможет ни один, см. «glyphstroke list»"))
    installed, packaged = extension_versions()
    if installed is not None and packaged is not None:
        check(_("расширение оболочки совпадает с программой (версия {0})").format(installed),
              installed >= packaged,
              _("в домашнем каталоге расширение версии {0}, в программе {1}: "
                "перезапустите демон (systemctl --user restart glyphstroke) — он "
                "обновит расширение сам, либо сделайте это руками "
                "(glyphstroke shell-extension install); затем перезайдите в систему"
                ).format(installed, packaged))
    elif packaged is not None and shellext.is_gnome():
        # Обычно расширение кладёт сам демон при запуске, поэтому пустой
        # каталог означает, что демон ещё ни разу не отработал в сеансе.
        check(_("расширение оболочки установлено"), False,
              _("каталога нет: запустите демон («glyphstroke service enable») или "
                "поставьте вручную — glyphstroke shell-extension install"))
    pending = update.pending()
    if pending is not None:
        print(_("[i] вышла версия {0} (установлена {1}): {2}").format(
            pending.version, __version__, pending.url or update.release_page(settings)))
    elif not getattr(settings, "check_updates", True):
        print(_("[i] проверка обновлений выключена (check_updates: false)"))

    if settings.pause_in_fullscreen:
        print(_("[i] «отключаться в полноэкранных» включено: в X11, sway и "
              "Hyprland окно видно напрямую, в GNOME про него сообщает "
              "расширение оболочки ({0})").format(extension_state()))
    with_menu = [g.name for g in gestures if g.enabled and g.menu]
    if with_menu:
        print(_("[i] меню под жестом у: {0}. Рисует его расширение оболочки "
              "({1}), в X11 — окно следа; без них жест просто выполнит свои "
              "действия").format(", ".join(with_menu), extension_state()))
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk  # noqa: F401
        check(_("GTK 3 для редактора и следа"), True)
    except Exception:
        check(_("GTK 3 для редактора и следа"), False,
              "sudo apt install python3-gi gir1.2-gtk-3.0")
    if os.environ.get("XDG_SESSION_TYPE") == "wayland" and \
            "gnome" in (os.environ.get("XDG_CURRENT_DESKTOP", "").lower()):
        print(_("[i] GNOME на Wayland: след рисует расширение оболочки ({0}, ставится командой «glyphstroke shell-extension install»)").format(extension_state()))
        print(_("[i] фильтр жестов по приложению в GNOME на Wayland недоступен, "
              "сами жесты работают"))
    if not ok:
        print(_("\nЕсть незакрытые пункты, поэтому команда вернёт код 1: "
              "цепочка «glyphstroke doctor && …» дальше не пойдёт."))
    return 0 if ok else 1


def cmd_install(args) -> int:
    if os.geteuid() != 0:
        print(_("нужны права root: sudo glyphstroke install"), file=sys.stderr)
        return 1
    target_user = args.user or os.environ.get("SUDO_USER") or ""
    Path(UDEV_RULE).write_text(
        (DATA_DIR / "99-glyphstroke.rules").read_text(encoding="utf-8"), encoding="utf-8")
    print(_("правило udev: {0}").format(UDEV_RULE))
    subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
    subprocess.run(["udevadm", "trigger", "--subsystem-match=misc",
                    "--attr-match=name=uinput"], check=False)
    if target_user:
        subprocess.run(["usermod", "-aG", "input", target_user], check=False)
        print(_("пользователь {0} добавлен в группу input (нужен перезаход в систему)").format(target_user))
    subprocess.run(["modprobe", "uinput"], check=False)
    Path("/etc/modules-load.d/glyphstroke.conf").write_text("uinput\n", encoding="utf-8")
    print(_("модуль uinput включён в автозагрузку"))
    print(_("Дальше от своего пользователя: glyphstroke init && glyphstroke service enable"))
    return 0


def cmd_update(args) -> int:
    """Проверить сейчас, не дожидаясь суточного перерыва.

    Программа обновляться сама не умеет: она перехватывает мышь, и подменять
    демона у человека за спиной нельзя. Поэтому здесь только ответ «есть» или
    «нет» и ссылка.
    """
    settings = Settings.load()
    print(_("установлено: {0}").format(__version__))
    release = update.check(settings, force=True)
    if release is None:
        known = update.pending()
        if known is None:
            print(_("новых версий нет (или сервер не ответил)"))
            return 0
        release = known
    print(_("вышла версия {0}").format(release.version))
    if release.notes:
        # Описание выпуска бывает длинным: показываем начало, остальное — на
        # странице, ссылка ниже.
        head = "\n".join(release.notes.splitlines()[:10])
        print()
        print(head)
        print()
    print(_("страница загрузки: {0}").format(release.url or update.release_page(settings)))
    return 0


def cmd_service(args) -> int:
    unit_dir = Path.home() / ".config/systemd/user"
    unit = unit_dir / "glyphstroke.service"
    if args.action == "enable":
        unit_dir.mkdir(parents=True, exist_ok=True)
        exec_path = shutil.which("glyphstroked") or f"{sys.executable} -m glyphstroke.daemon"
        unit.write_text(
            (DATA_DIR / "glyphstroke.service").read_text(encoding="utf-8")
            .replace("@EXEC@", exec_path), encoding="utf-8")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        result = subprocess.run(["systemctl", "--user", "enable", "--now", "glyphstroke"],
                                capture_output=True, text=True)
        if result.returncode != 0:
            # Молчать нельзя: раньше здесь всегда печаталось «включена», и
            # провал enable выглядел как успех — служба оставалась выключенной,
            # а понять это можно было только по systemctl напрямую.
            detail = (result.stderr or result.stdout).strip()
            print(_("не удалось включить службу: {0}").format(detail), file=sys.stderr)
            return 1
        print(_("служба включена: {0}").format(unit))
    elif args.action == "disable":
        subprocess.run(["systemctl", "--user", "disable", "--now", "glyphstroke"], check=False)
        print(_("служба выключена"))
    elif args.action == "status":
        subprocess.run(["systemctl", "--user", "--no-pager", "status", "glyphstroke"],
                       check=False)
    elif args.action == "restart":
        subprocess.run(["systemctl", "--user", "restart", "glyphstroke"], check=False)
    return 0


def _restart_daemon() -> None:
    """Смена устройства требует переоткрытия — одним SIGHUP не обойтись."""
    if service_is_active():
        subprocess.run(["systemctl", "--user", "restart", "glyphstroke"], check=False)
        print(_("служба перезапущена"))


def _reload_daemon() -> None:
    """Сказать работающему демону перечитать жесты."""
    subprocess.run(["systemctl", "--user", "reload-or-restart", "glyphstroke"],
                   check=False, capture_output=True)
    subprocess.run(["pkill", "-HUP", "-f", "glyphstroke.daemon"],
                   check=False, capture_output=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="glyphstroke",
        description=_("жесты мыши для Linux — аналог Glyphstroke"))
    parser.add_argument("--version", action="version",
                        version=f"glyphstroke {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help=_("создать настройки и стартовый набор жестов"))
    p.add_argument("--force", action="store_true", help=_("перезаписать существующие"))
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("daemon", help=_("запустить перехват жестов"))
    p.add_argument("--dry-run", action="store_true", help=_("не выполнять действия"))
    p.add_argument("--monitor", action="store_true", help=_("не перехватывать кнопку"))
    p.set_defaults(func=cmd_daemon)

    p = sub.add_parser("gui", help=_("редактор жестов"))
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("record", help=_("записать жест с мыши"))
    p.add_argument("name", help=_("название жеста"))
    p.add_argument("-n", "--samples", type=int, default=3, help=_("сколько раз рисовать"))
    p.add_argument("--keys", help=_("действие: комбинация клавиш, например ctrl+w"))
    p.add_argument("--command", help=_("действие: команда оболочки"))
    p.add_argument("--replace", action="store_true", help=_("заменить прежние образцы"))
    p.add_argument("--code", action="store_true",
                   help=_("добавить ещё и код направлений нарисованного"))
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("test", help=_("показывать распознанное, ничего не выполняя"))
    p.set_defaults(func=cmd_test)

    for name, help_text in (
            ("pause", _("приостановить перехват (правая кнопка станет обычной)")),
            ("resume", _("вернуть перехват")),
            ("toggle", _("переключить перехват"))):
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=cmd_pause)

    p = sub.add_parser("watch", help=_("что распознаёт работающий демон"))
    p.add_argument("--save", metavar=_("КАТАЛОГ"),
                   help=_("сохранять росчерки в файлы — их можно разобрать позже"))
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("list", help=_("список жестов"))
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("profile", help=_("наборы жестов и переключение между ними"))
    p.add_argument("action", nargs="?", default="list",
                   choices=["list", "use", "new", "remove"])
    p.add_argument("name", nargs="?")
    p.add_argument("--copy", action="store_true",
                   help=_("завести набор копией текущего"))
    p.add_argument("--use", action="store_true",
                   help=_("сразу переключиться на заведённый набор"))
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("devices", help=_("какие мыши будут перехвачены"))
    p.set_defaults(func=cmd_devices)

    p = sub.add_parser("bind", help=_("слушать только одну мышь"))
    p.add_argument("--ask", action="store_true",
                   help=_("выбрать нажатием кнопки, даже если мышь одна"))
    p.add_argument("--device", help=_("привязать по точному имени устройства"))
    p.add_argument("--clear", action="store_true", help=_("снять привязку"))
    p.set_defaults(func=cmd_bind)

    p = sub.add_parser("shell-extension",
                       help=_("след за курсором в GNOME на Wayland"))
    p.add_argument("action", choices=["install", "remove", "status"])
    p.set_defaults(func=cmd_shell_extension)

    p = sub.add_parser("export", help=_("выгрузить жесты в файл"))
    p.add_argument("file", help=_("куда сохранить (например ~/жесты.yaml)"))
    p.add_argument("--with-settings", action="store_true",
                   help=_("выгрузить вместе с настройками"))
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("import", help=_("загрузить жесты из файла"))
    p.add_argument("file", help=_("откуда читать"))
    p.add_argument("--replace", action="store_true",
                   help=_("сначала убрать все прежние жесты"))
    p.add_argument("--with-settings", action="store_true",
                   help=_("применить и настройки из файла"))
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("help", help=_("справка о возможностях"))
    p.add_argument("topic", nargs="?", help=_("часть названия раздела"))
    p.set_defaults(func=cmd_help)

    p = sub.add_parser("about", help=_("о программе: версия, автор, связь"))
    p.set_defaults(func=cmd_about)

    p = sub.add_parser("doctor", help=_("проверить окружение и права"))
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("install", help=_("правило udev и группа input (нужен root)"))
    p.add_argument("--user", help=_("кого добавить в группу input"))
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("update", help=_("проверить, не вышла ли версия новее"))
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("service", help=_("автозапуск через systemd --user"))
    p.add_argument("action", choices=["enable", "disable", "status", "restart"])
    p.set_defaults(func=cmd_service)
    return parser


def main(argv: list[str] | None = None) -> int:
    i18n.setup(Settings.load().language)
    args = build_parser().parse_args(argv)
    config.migrate_legacy_config()
    setup_logging(Settings.load().log_level)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(_("ошибка: {0}").format(exc), file=sys.stderr)
        return 1
    except PermissionError as exc:
        print(_("нет прав: {0}\nзапустите «glyphstroke doctor»").format(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
