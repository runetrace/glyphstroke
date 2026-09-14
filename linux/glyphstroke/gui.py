"""Редактор жестов — аналог Glyphstroke Command Editor.

Слева список жестов, справа три вкладки: сам росчерк, привязанные действия
и общие настройки. Рисовать образцы можно прямо в окне левой кнопкой мыши —
демону это не мешает, он следит за правой.
"""

from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

from . import capture, cli, config, context  # noqa: E402
from . import version as about  # noqa: E402
from .actions import ActionRunner  # noqa: E402
from .config import (EVENTS, Action, Gesture, MenuItem, Settings, export_bundle,
                     find_conflicts, import_bundle, load_gestures)  # noqa: E402
from .recognizer import Recognizer, direction_code, normalize, resample  # noqa: E402
from . import standard, update  # noqa: E402

from . import i18n
from .i18n import _

ACTION_TYPES = [
    ("standard", "Стандартное действие"),
    ("keys", "Клавиши"),
    ("command", "Команда"),
    ("app", "Запуск приложения"),
    ("text", "Ввести текст"),
    ("button", "Кнопка мыши"),
    ("scroll", "Прокрутка"),
    ("window", "Окно"),
    ("delay", "Пауза, мс"),
    ("none", "Ничего"),
]
ACTION_HINTS = {
    "standard": "выберите действие из списка",
    "keys": "ctrl+w, alt+Left, ctrl+c ctrl+v",
    "command": "gnome-terminal, xdg-open ~/Загрузки",
    "app": "путь к .desktop или к программе — удобнее выбрать кнопкой «Обзор»",
    "text": "любая строка латиницей",
    "button": "middle, left, right, back — можно «middle 2»",
    "scroll": "up 3, down, left 2",
    "window": "minimize, maximize, unmaximize, close, fullscreen, activate",
    "delay": "150",
    "none": "",
}
#: как называется язык на нём самом
LANGUAGE_NAMES = {"en": "English", "ru": "Русский"}


def _gsetting(key: str) -> str:
    """Значение ключа ``org.gnome.desktop.interface`` или пустая строка."""
    try:
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", key],
            capture_output=True, text=True)
        if out.returncode == 0:
            return out.stdout.strip().strip("'\"")
    except Exception:            # noqa: BLE001 - нет gsettings не повод падать
        pass
    return ""


def _system_prefers_dark() -> bool:
    """Хочет ли система тёмную тему — по ключу GNOME color-scheme."""
    return "prefer-dark" in _gsetting("color-scheme")


def apply_gtk_theme(theme: str) -> None:
    """Светлая/тёмная тема окон. ``system`` — как в системе.

    Одного ``gtk-application-prefer-dark-theme`` мало: у многих тем (Yaru на
    Ubuntu) светлая и тёмная — это разные *имена* (``Yaru`` и ``Yaru-dark``), и
    флаг их не переключает. Поэтому меняем и имя темы: тогда окно перекрашивается
    сразу. Трогаем только окна редактора и настроек — след, меню и значок в
    панели рисует расширение своими цветами.
    """
    gtk_settings = Gtk.Settings.get_default()
    if gtk_settings is None:
        return

    # За основу берём системную тему без суффикса варианта.
    base = _gsetting("gtk-theme") or gtk_settings.get_property("gtk-theme-name") or "Adwaita"
    stem = base[:-5] if base.endswith("-dark") else base

    if theme == "dark":
        dark, name = True, f"{stem}-dark"
    elif theme == "light":
        dark, name = False, stem
    else:  # system — как система: и имя, и флаг из системных настроек
        dark, name = _system_prefers_dark(), (base or stem)

    gtk_settings.set_property("gtk-application-prefer-dark-theme", dark)
    gtk_settings.set_property("gtk-theme-name", name)

TRIGGERS = [("BTN_RIGHT", "Правая кнопка"), ("BTN_MIDDLE", "Средняя кнопка"),
            ("BTN_SIDE", "Боковая кнопка"), ("BTN_EXTRA", "Дополнительная кнопка")]


class StrokeCanvas(Gtk.DrawingArea):
    """Холст: рисование левой кнопкой, показ образцов и кода направлений."""

    def __init__(self, on_stroke=None, height=260):
        super().__init__()
        self.on_stroke = on_stroke
        self.points: list[tuple[float, float]] = []
        self.samples: list[list[tuple[float, float]]] = []
        self.drawing = False
        self.set_size_request(320, height)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK)
        self.connect("draw", self._draw)
        self.connect("button-press-event", self._press)
        self.connect("motion-notify-event", self._motion)
        self.connect("button-release-event", self._release)

    def show_samples(self, samples) -> None:
        self.samples = [list(s) for s in samples]
        self.points = []
        self.queue_draw()

    def _press(self, _w, event):
        if event.button != 1:
            return False
        self.drawing = True
        self.points = [(event.x, event.y)]
        self.queue_draw()
        return True

    def _motion(self, _w, event):
        if self.drawing:
            self.points.append((event.x, event.y))
            self.queue_draw()
        return True

    def _release(self, _w, event):
        if event.button != 1 or not self.drawing:
            return False
        self.drawing = False
        if len(self.points) > 3 and self.on_stroke:
            self.on_stroke(list(self.points))
        return True

    @staticmethod
    def _fit(points, width, height, pad=24):
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        w = max(max(xs) - min(xs), 1e-6)
        h = max(max(ys) - min(ys), 1e-6)
        k = min((width - 2 * pad) / w, (height - 2 * pad) / h)
        ox = (width - w * k) / 2 - min(xs) * k
        oy = (height - h * k) / 2 - min(ys) * k
        return [(x * k + ox, y * k + oy) for x, y in points]

    def _draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cr.set_source_rgb(0.13, 0.14, 0.17)
        cr.paint()
        cr.set_source_rgb(0.22, 0.23, 0.27)
        cr.set_line_width(1)
        for i in range(1, 3):  # сетка третей, чтобы видеть пропорции росчерка
            cr.move_to(width * i / 3, 0); cr.line_to(width * i / 3, height)
            cr.move_to(0, height * i / 3); cr.line_to(width, height * i / 3)
        cr.stroke()

        for index, sample in enumerate(self.samples):
            if len(sample) < 2:
                continue
            shade = 0.35 + 0.45 * (index + 1) / max(len(self.samples), 1)
            cr.set_source_rgba(0.30, 0.64, 1.0, shade)
            self._polyline(cr, self._fit(sample, width, height), 3)
        if len(self.points) >= 2:
            cr.set_source_rgb(1.0, 0.78, 0.25)
            self._polyline(cr, self.points, 3)
        if not self.samples and not self.points:
            cr.set_source_rgb(0.45, 0.47, 0.52)
            cr.select_font_face("Sans")
            cr.set_font_size(13)
            text = _("нарисуйте здесь левой кнопкой")
            extents = cr.text_extents(text)
            cr.move_to((width - extents.width) / 2, height / 2)
            cr.show_text(text)
        return False

    @staticmethod
    def _polyline(cr, points, line_width):
        cr.set_line_width(line_width)
        cr.set_line_cap(1)
        cr.set_line_join(1)
        cr.move_to(*points[0])
        for point in points[1:]:
            cr.line_to(*point)
        cr.stroke()
        # точка начала росчерка — чтобы направление читалось с первого взгляда
        cr.arc(points[0][0], points[0][1], line_width + 1.5, 0, 2 * math.pi)
        cr.fill()


class TrailPreview(Gtk.DrawingArea):
    """Образец следа: видно, как линия ляжет на экран, до её рисования."""

    def __init__(self):
        super().__init__()
        self.rgb = (0.30, 0.64, 1.0)
        self.line_width = 4
        self.opacity = 0.9
        self.set_size_request(170, 34)
        self.connect("draw", self._draw)

    def set_style(self, rgb, line_width, opacity) -> None:
        self.rgb, self.line_width, self.opacity = rgb, line_width, opacity
        self.queue_draw()

    def _draw(self, widget, cr):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()
        cr.set_source_rgb(0.13, 0.14, 0.17)      # тёмный фон, как у холста
        cr.paint()
        cr.set_line_width(self.line_width)
        cr.set_line_cap(1)
        cr.set_line_join(1)
        cr.set_source_rgba(*self.rgb, self.opacity)
        step = width / 6
        cr.move_to(step * 0.6, height * 0.72)
        cr.line_to(step * 2.0, height * 0.28)
        cr.line_to(step * 3.4, height * 0.72)
        cr.line_to(step * 5.4, height * 0.28)
        cr.stroke()
        return False


class ActionRow(Gtk.Box):
    #: для каких действий имеет смысл выбирать файл
    BROWSABLE = ("app", "command")

    def __init__(self, action: Action, on_remove, on_change, parent=None):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.parent_window = parent
        self.combo = Gtk.ComboBoxText()
        for key, label in ACTION_TYPES:
            self.combo.append(key, _(label))
        self.combo.set_active_id(action.type if any(
            action.type == k for k, _label in ACTION_TYPES) else "none")
        self.entry = Gtk.Entry(text=action.value, hexpand=True, width_chars=12)
        self.entry.set_placeholder_text(_(ACTION_HINTS.get(action.type, "")))
        # У стандартного действия значение выбирается из списка: вспоминать,
        # что «вставить» — это ctrl+v, человек не обязан, а заодно такой жест
        # переносится на другую систему без правки.
        self.standard = Gtk.ComboBoxText(hexpand=True)
        for key, title in standard.choices():
            self.standard.append(key, title)
        self.standard.set_active_id(
            action.value if action.value in standard.STANDARD_ACTIONS else "copy")
        self.combo.connect("changed", self._type_changed, on_change)
        self.entry.connect("changed", lambda *_: on_change())
        self.standard.connect("changed", lambda *_: on_change())
        self.browse = Gtk.Button(label=_("Обзор…"))
        self.browse.set_tooltip_text(_("Выбрать приложение или файл"))
        self.browse.connect("clicked", lambda *_: self.choose_file())
        remove = Gtk.Button.new_from_icon_name("list-remove-symbolic",
                                               Gtk.IconSize.BUTTON)
        remove.set_tooltip_text(_("Убрать действие"))
        remove.connect("clicked", lambda *_: on_remove(self))
        self.pack_start(self.combo, False, False, 0)
        self.pack_start(self.entry, True, True, 0)
        self.pack_start(self.standard, True, True, 0)
        self.pack_start(self.browse, False, False, 0)
        self.pack_start(remove, False, False, 0)
        self.connect("realize", lambda *_: self.update_browse())

    def update_browse(self) -> None:
        is_standard = self.type == "standard"
        self.browse.set_visible(self.type in self.BROWSABLE)
        self.browse.set_no_show_all(self.type not in self.BROWSABLE)
        # Поле ввода и список занимают одно место: показываем ровно одно из них,
        # иначе в строке действия оказались бы два значения сразу.
        self.entry.set_visible(not is_standard)
        self.entry.set_no_show_all(is_standard)
        self.standard.set_visible(is_standard)
        self.standard.set_no_show_all(not is_standard)

    def choose_file(self) -> None:
        dialog = Gtk.FileChooserDialog(
            title=_("Выберите приложение"), transient_for=self.parent_window,
            action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(_("Отмена"), Gtk.ResponseType.CANCEL,
                           _("Выбрать"), Gtk.ResponseType.OK)
        desktop = Gtk.FileFilter()
        desktop.set_name(_("Приложения (*.desktop)"))
        desktop.add_pattern("*.desktop")
        everything = Gtk.FileFilter()
        everything.set_name(_("Все файлы"))
        everything.add_pattern("*")
        dialog.add_filter(desktop)
        dialog.add_filter(everything)
        start = self.entry.get_text().strip()
        if start and os.path.exists(os.path.dirname(start) or "/"):
            dialog.set_filename(start)
        elif os.path.isdir("/usr/share/applications"):
            dialog.set_current_folder("/usr/share/applications")
        if dialog.run() == Gtk.ResponseType.OK:
            self.entry.set_text(dialog.get_filename() or "")
        dialog.destroy()

    def _type_changed(self, _combo, on_change):
        self.entry.set_placeholder_text(_(ACTION_HINTS.get(self.type, "")))
        self.update_browse()
        on_change()

    @property
    def type(self) -> str:
        return self.combo.get_active_id() or "none"

    def to_action(self) -> Action:
        if self.type == "standard":
            return Action(self.type, self.standard.get_active_id() or "copy")
        return Action(self.type, self.entry.get_text())


class MenuItemRow(Gtk.Frame):
    """Пункт меню: название и свой набор действий."""

    def __init__(self, item: MenuItem, on_remove, parent=None):
        super().__init__(margin_bottom=4)
        self.parent_window = parent
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, margin=6)
        header = Gtk.Box(spacing=6)
        self.name_entry = Gtk.Entry(text=item.name, hexpand=True, width_chars=12)
        self.name_entry.set_placeholder_text(_("название пункта — его и видно в меню"))
        add = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add.set_tooltip_text(_("Добавить действие пункту"))
        add.connect("clicked", lambda *_: self.add_action(Action("keys", "")))
        remove = Gtk.Button.new_from_icon_name("user-trash-symbolic",
                                               Gtk.IconSize.BUTTON)
        remove.set_tooltip_text(_("Убрать пункт"))
        remove.connect("clicked", lambda *_: on_remove(self))
        header.pack_start(self.name_entry, True, True, 0)
        header.pack_start(add, False, False, 0)
        header.pack_start(remove, False, False, 0)
        box.pack_start(header, False, False, 0)
        self.actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4,
                                   margin_start=18)
        box.pack_start(self.actions_box, False, False, 0)
        self.add(box)
        for action in item.actions or [Action("keys", "")]:
            self.add_action(action)

    def add_action(self, action: Action) -> None:
        row = ActionRow(action, self.remove_action, lambda: None,
                        parent=self.parent_window)
        self.actions_box.pack_start(row, False, False, 0)
        self.actions_box.show_all()
        row.update_browse()

    def remove_action(self, row: ActionRow) -> None:
        self.actions_box.remove(row)

    def to_item(self) -> MenuItem:
        return MenuItem(
            name=self.name_entry.get_text().strip(),
            actions=[row.to_action() for row in self.actions_box.get_children()
                     if isinstance(row, ActionRow)])


def pick_failure_text(reason: str) -> str:
    """Почему мишень не поймала окно — словами для человека."""
    if reason == "nodaemon":
        return _("Служба glyphstroke не запущена — спросить, какое окно под мишенью, некого")
    if reason == "noshell":
        return _("Какое окно под мишенью, сообщает расширение оболочки, а его нет "
                 "на связи или оно устарело: glyphstroke shell-extension install, затем "
                 "перезайдите в систему")
    if reason == "nowindow":
        return _("Под мишенью не оказалось окна приложения")
    if reason == "timeout":
        return _("Оболочка не ответила — попробуйте ещё раз")
    if reason == "own":
        return _("Это окно самого Glyphstroke — отпустите мишень над окном того "
                 "приложения, которое нужно запомнить")
    return reason


def is_x11_session() -> bool:
    if os.environ.get("WAYLAND_DISPLAY") or \
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        return False
    return bool(os.environ.get("DISPLAY"))


def locate_window() -> tuple[str, str] | str:
    """Окно под курсором: (класс, название) или причина неудачи.

    Сначала спрашиваем оболочку: она видит окна так же, как их видит человек,
    и знает название приложения. Если её нет, в X11 спрашиваем сервер сами;
    в Wayland другого способа нет.
    """
    result = cli.pick_window()
    if isinstance(result, tuple) or result == "nowindow" or not is_x11_session():
        return result
    return context.window_at_pointer() or "nowindow"


def own_window_classes() -> set[str]:
    names = {GLib.get_prgname() or "", Gdk.get_program_class() or "", "glyphstroke", "glyphstroke"}
    return {name.lower() for name in names if name}


class WindowPicker(Gtk.EventBox):
    """Мишень, как в StrokeIt: зажать, перетащить на окно и отпустить.

    Кнопку зажали на нашем виджете, поэтому и отпускание над чужим окном
    приходит нам. Какое окно лежит под курсором, в Wayland знает только
    оболочка — спрашиваем её через демона, а в X11 без неё спрашиваем сервер.
    """

    ICON = "find-location-symbolic"

    def __init__(self, on_picked, on_message, locate=None):
        super().__init__()
        self.on_picked = on_picked
        self.on_message = on_message
        self.locate = locate or locate_window
        self.dragging = False
        self.image = Gtk.Image.new_from_icon_name(self.ICON, Gtk.IconSize.LARGE_TOOLBAR)
        self.image.set_margin_start(4)
        self.image.set_margin_end(4)
        frame = Gtk.Frame(shadow_type=Gtk.ShadowType.ETCHED_IN)
        frame.add(self.image)
        self.add(frame)
        self.set_tooltip_text(
            _("Зажмите мишень, перетащите на окно приложения и отпустите — "
              "приложение запомнится"))
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.connect("button-press-event", self._press)
        self.connect("button-release-event", self._release)

    def _press(self, _widget, event) -> bool:
        if event.button != 1:
            return False
        self.dragging = True
        # пока кнопку держат, прицел виден над любым окном, а сама мишень
        # бледнеет: её будто несут в руке
        window = self.get_window()
        if window is not None:
            window.set_cursor(Gdk.Cursor.new_from_name(window.get_display(), "crosshair"))
        self.image.set_opacity(0.25)
        return True

    def _release(self, _widget, event) -> bool:
        if event.button != 1 or not self.dragging:
            return False
        self.dragging = False
        window = self.get_window()
        if window is not None:
            window.set_cursor(None)
        self.image.set_opacity(1.0)
        if self.released_inside(event.x, event.y):
            self.on_message(_("Перетащите мишень на окно нужного приложения и "
                              "отпустите над ним"))
            return True
        self.on_message(_("Узнаю, что это за окно…"))
        threading.Thread(target=lambda: GLib.idle_add(self.finish, self.locate()),
                         daemon=True).start()
        return True

    def released_inside(self, x: float, y: float) -> bool:
        """Отпустили над своим же окном — ловить там нечего."""
        toplevel = self.get_toplevel()
        coords = self.translate_coordinates(toplevel, int(x), int(y))
        if not coords:
            return False
        if len(coords) == 3:      # в некоторых выпусках PyGObject первым идёт флаг
            ok, left, top = coords
            if not ok:
                return False
        else:
            left, top = coords
        allocation = toplevel.get_allocation()
        return 0 <= left < allocation.width and 0 <= top < allocation.height

    def finish(self, result) -> bool:
        if isinstance(result, tuple):
            wm_class, name = result
            if wm_class.lower() in own_window_classes():
                self.on_message(pick_failure_text("own"))
            else:
                self.on_picked(wm_class, name)
        else:
            self.on_message(pick_failure_text(result))
        return False


class AppChooser(Gtk.Box):
    """Приложения из базы: галочки в выпадающем списке и мишень рядом.

    Названия больше не вписываются руками — ошибиться в классе окна было
    проще простого. Выражения, записанные в файлах раньше, никуда не деваются:
    они в том же списке, с пометкой, и снимаются галочкой.
    """

    def __init__(self, empty_text: str, on_message, on_picked=None):
        super().__init__(spacing=6, hexpand=True)
        self.empty_text = empty_text
        self.on_message = on_message
        self.on_picked_app = on_picked
        self.patterns: list[str] = []
        self.popover: Gtk.Popover | None = None
        self.summary = Gtk.Label(xalign=0.0, hexpand=True, ellipsize=3)
        self.choose_button = Gtk.Button(label=_("Выбрать…"))
        self.choose_button.set_tooltip_text(_("Отметить приложения из списка"))
        self.choose_button.connect("clicked", lambda *_a: self.open_list())
        self.picker = WindowPicker(self.pick, on_message)
        self.pack_start(self.summary, True, True, 0)
        self.pack_start(self.choose_button, False, False, 0)
        self.pack_start(self.picker, False, False, 0)
        self.refresh()

    def set_patterns(self, patterns) -> None:
        self.patterns = list(patterns)
        self.refresh()

    def get_patterns(self) -> list[str]:
        return list(self.patterns)

    def has(self, pattern: str) -> bool:
        return any(config.same_pattern(pattern, known) for known in self.patterns)

    def set_active(self, pattern: str, active: bool) -> None:
        if active and not self.has(pattern):
            self.patterns.append(pattern)
        elif not active:
            self.patterns = [known for known in self.patterns
                             if not config.same_pattern(known, pattern)]
        self.refresh()

    def refresh(self) -> None:
        text = (config.describe_patterns(self.patterns, config.load_apps())
                if self.patterns else self.empty_text)
        self.summary.set_text(text)
        self.summary.set_tooltip_text(text)

    def choices(self) -> list[tuple[str, str]]:
        """(запись, подпись): сначала база, потом отмеченное, чего в ней нет."""
        items = [(app.pattern, app.title) for app in config.load_apps()]
        for pattern in self.patterns:
            if any(config.same_pattern(pattern, known) for known, _title in items):
                continue
            wm_class = config.pattern_class(pattern)
            items.append((pattern, wm_class if wm_class is not None
                          else _("выражение «{0}»").format(pattern)))
        return items

    def open_list(self) -> Gtk.Popover:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin=8)
        items = self.choices()
        if not items:
            box.pack_start(Gtk.Label(
                label=_("Список пуст — перетащите мишень на окно приложения"),
                wrap=True, max_width_chars=32), False, False, 0)
        for pattern, label in items:
            check = Gtk.CheckButton(label=label)
            wm_class = config.pattern_class(pattern)
            check.set_tooltip_text(
                _("класс окна: {0}").format(wm_class) if wm_class is not None
                else _("регулярное выражение по «класс окна | заголовок»"))
            check.set_active(self.has(pattern))
            check.connect("toggled", lambda button, known=pattern:
                          self.set_active(known, button.get_active()))
            box.pack_start(check, False, False, 0)
        popover = Gtk.Popover(relative_to=self.choose_button)
        popover.add(box)
        box.show_all()
        popover.popup()
        self.popover = popover
        return popover

    def pick(self, wm_class: str, name: str) -> None:
        """Мишень поймала окно: запомнить приложение и сразу его отметить."""
        try:
            app, created = config.add_app(wm_class, name)
        except ValueError as exc:
            self.on_message(str(exc))
            return
        self.set_active(app.pattern, True)
        if self.on_picked_app is not None:
            self.on_picked_app(app, created)


class EditorWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title=_("Glyphstroke — жесты мыши"))
        self.set_default_size(1040, 660)
        self.settings = Settings.load()
        apply_gtk_theme(getattr(self.settings, "theme", "system"))
        self.gestures: list[Gesture] = load_gestures()
        self.current: Gesture | None = None
        self._loading = False

        header = Gtk.HeaderBar(show_close_button=True, title=_("Glyphstroke — жесты мыши"))
        self.set_titlebar(header)
        add = Gtk.Button.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON)
        add.set_tooltip_text(_("Новый жест"))
        add.connect("clicked", self.on_add)
        remove = Gtk.Button.new_from_icon_name("user-trash-symbolic", Gtk.IconSize.BUTTON)
        remove.set_tooltip_text(_("Удалить жест"))
        remove.connect("clicked", self.on_remove)
        header.pack_start(add)
        header.pack_start(remove)
        help_button = Gtk.Button.new_from_icon_name("help-browser-symbolic",
                                                    Gtk.IconSize.BUTTON)
        help_button.set_tooltip_text(_("Справка: как всё устроено и что умеет"))
        help_button.connect("clicked", lambda *_: self.show_help())
        header.pack_end(help_button)
        about_button = Gtk.Button.new_from_icon_name("help-about-symbolic",
                                                     Gtk.IconSize.BUTTON)
        about_button.set_tooltip_text(_("О программе: версия, автор, связь"))
        about_button.connect("clicked", lambda *_: self.show_about())
        header.pack_end(about_button)
        settings_button = Gtk.Button.new_from_icon_name("emblem-system-symbolic",
                                                        Gtk.IconSize.BUTTON)
        settings_button.set_tooltip_text(_("Настройки программы"))
        settings_button.connect("clicked", lambda *_: self.show_settings())
        header.pack_end(settings_button)
        # раньше эта кнопка называлась просто «Сохранить» и стояла над вкладкой
        # с настройками всей программы — было непонятно, что именно она сохранит
        # кнопка живёт в строке вкладок, у правого края: она про жест, а
        # вкладки рядом — тоже про него
        self.save_button = Gtk.Button(label=_("Сохранить жест"), margin_end=6,
                                      margin_top=3, margin_bottom=3)
        self.save_button.get_style_context().add_class("suggested-action")
        self.save_button.connect("clicked", self.on_save)

        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(290)
        paned.add1(self._build_list())
        paned.add2(self._build_editor())
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(self._build_update_bar(), False, False, 0)
        box.pack_start(paned, True, True, 0)
        self.status = Gtk.Label(xalign=0.0, margin=6)
        box.pack_start(self.status, False, False, 0)
        self.add(box)

        self.settings_window = self._build_settings_window()
        self.refresh_list()
        self.connect("destroy", self.on_destroy)

    # --- обновления ---
    def _build_update_bar(self) -> Gtk.Widget:
        """Полоска «вышла новая версия».

        Спрашивает не сеть, а ответ прошлой проверки, которую делает демон:
        окно должно открываться мгновенно, а не ждать чужой сервер. Программа
        обновляется не сама — полоска только сообщает и ведёт на страницу.
        """
        self.update_bar = Gtk.InfoBar(message_type=Gtk.MessageType.INFO,
                                      show_close_button=True)
        self.update_label = Gtk.Label(xalign=0.0, wrap=True)
        self.update_bar.get_content_area().pack_start(self.update_label, True, True, 0)
        self.update_bar.add_button(_("Открыть страницу"), Gtk.ResponseType.OK)
        self.update_bar.connect("response", self.on_update_response)
        self.update_bar.set_no_show_all(True)
        self.update_bar.hide()
        self._update_release = None
        GLib.idle_add(self.refresh_update_bar)
        return self.update_bar

    def refresh_update_bar(self) -> bool:
        release = update.pending()
        self._update_release = release
        if release is None:
            self.update_bar.hide()
            return False
        self.update_label.set_text(
            _("Вышла версия {0} — у вас {1}").format(release.version, about.__version__))
        # У полоски выставлен no_show_all, иначе она появлялась бы при каждом
        # show_all окна. Поэтому и текст показываем сами: show_all внутрь
        # такого виджета не заходит.
        self.update_label.show()
        self.update_bar.show()
        return False

    def on_update_response(self, _bar, response) -> None:
        if response == Gtk.ResponseType.OK and self._update_release is not None:
            url = self._update_release.url or update.release_page(self.settings)
            Gtk.show_uri_on_window(self, url, Gdk.CURRENT_TIME)
        self.update_bar.hide()

    def check_updates_now(self) -> None:
        """Проверить по кнопке, не дожидаясь суточного перерыва.

        Запрос идёт в отдельном потоке: окно не должно замирать, пока чужой
        сервер думает.
        """
        self.set_status(_("Проверяю обновления…"))

        def work() -> None:
            try:
                release = update.check(self.settings, force=True)
            except Exception as exc:            # noqa: BLE001 - сеть не повод падать
                release = None
                GLib.idle_add(self.set_status,
                              _("Проверить не вышло: {0}").format(exc))
            GLib.idle_add(self._update_checked, release)

        threading.Thread(target=work, daemon=True).start()

    def _update_checked(self, release) -> bool:
        self.refresh_update_bar()
        if release is None:
            self.set_status(_("Установлена последняя версия {0}").format(about.__version__))
        else:
            self.set_status(_("Вышла версия {0}").format(release.version))
        return False

    # --- список жестов ---
    def _build_list(self) -> Gtk.Widget:
        self.profile_combo = Gtk.ComboBoxText(hexpand=True)
        self.profile_combo.set_tooltip_text(
            _("Набор жестов: у каждого свои жесты, переключается целиком"))
        self._profiles_updating = False
        self.profile_combo.connect("changed", self.on_profile_changed)
        add_profile = Gtk.Button.new_from_icon_name("list-add-symbolic",
                                                    Gtk.IconSize.BUTTON)
        add_profile.set_tooltip_text(_("Завести набор"))
        add_profile.connect("clicked", lambda *_: self.new_profile())
        self.remove_profile_button = Gtk.Button.new_from_icon_name(
            "user-trash-symbolic", Gtk.IconSize.BUTTON)
        self.remove_profile_button.set_tooltip_text(_("Удалить набор"))
        self.remove_profile_button.connect("clicked", lambda *_: self.delete_profile())
        profile_row = Gtk.Box(spacing=6, margin=6)
        profile_row.pack_start(self.profile_combo, True, True, 0)
        profile_row.pack_start(add_profile, False, False, 0)
        profile_row.pack_start(self.remove_profile_button, False, False, 0)

        self.store = Gtk.ListStore(bool, str, str, str)
        self.tree = Gtk.TreeView(model=self.store, headers_visible=True)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self.on_toggle_enabled)
        self.tree.append_column(Gtk.TreeViewColumn(_("Вкл"), toggle, active=0))
        self.tree.append_column(
            Gtk.TreeViewColumn(_("Жест"), Gtk.CellRendererText(), text=1))
        self.tree.append_column(
            Gtk.TreeViewColumn(_("Росчерк"), Gtk.CellRendererText(), text=2))
        self.tree.append_column(
            Gtk.TreeViewColumn(_("Где"), Gtk.CellRendererText(), text=3))
        self.tree.get_selection().connect("changed", self.on_select)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.add(self.tree)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(profile_row, False, False, 0)
        box.pack_start(scroller, True, True, 0)
        self.refresh_profiles()
        return box

    def refresh_list(self, select_name: str | None = None) -> None:
        self.store.clear()
        conflicts = find_conflicts(self.gestures)
        known_apps = config.load_apps()
        self.gestures.sort(key=lambda g: (bool(g.apps), g.name.lower()))
        for gesture in self.gestures:
            code = ", ".join(gesture.directions) or (
                _("{0} образц.").format(len(gesture.templates)) if gesture.templates else "—")
            # одинаковые коды гасят друг друга — это должно бросаться в глаза
            if gesture.event:
                code = config.EVENT_SHORT.get(gesture.event, gesture.event)
            keys = [gesture.event] if gesture.event else gesture.directions
            if any(k in conflicts for k in keys) and gesture.enabled:
                code = f"⚠ {code}"
            where = (config.describe_patterns(gesture.apps, known_apps)
                     if gesture.apps else _("везде"))
            self.store.append([gesture.enabled, gesture.name, code, where])
        if self.gestures:
            index = 0
            if select_name:
                index = next((i for i, g in enumerate(self.gestures)
                              if g.name == select_name), 0)
            self.tree.get_selection().select_path(Gtk.TreePath(index))
        else:
            # иначе после переключения на пустой набор остался бы выбранным
            # жест прежнего, и «Сохранить жест» записал бы его сюда
            self.current = None

    # --- наборы жестов ---
    def refresh_profiles(self) -> None:
        current = config.active_profile()
        self._profiles_updating = True
        self.profile_combo.remove_all()
        self.profile_combo.append("", _(config.BASE_PROFILE).capitalize())
        for name in config.available_profiles():
            self.profile_combo.append(name, name)
        self.profile_combo.set_active_id(current)
        self.remove_profile_button.set_sensitive(bool(current))
        self._profiles_updating = False

    def reload_gestures(self) -> None:
        self.gestures = load_gestures()
        self.refresh_list()

    def on_profile_changed(self, combo) -> None:
        if self._profiles_updating:
            return
        name = combo.get_active_id() or ""
        try:
            config.use_profile(name)
        except ValueError as exc:
            self.set_status(str(exc))
            self.refresh_profiles()
            return
        self.reload_gestures()
        self.notify_daemon(_("Набор «{0}»: жестов {1}").format(
            name or _(config.BASE_PROFILE), len(self.gestures)))

    def create_profile(self, name: str, copy_current: bool) -> bool:
        """Завести набор и перейти в него. ``False`` — не вышло."""
        try:
            created = config.create_profile(
                name, copy_from=config.active_profile() if copy_current else None)
            config.use_profile(created)
        except ValueError as exc:
            self.set_status(str(exc))
            return False
        self.refresh_profiles()
        self.reload_gestures()
        self.notify_daemon(_("Набор «{0}» заведён").format(created))
        return True

    def new_profile(self) -> None:
        dialog = Gtk.Dialog(title=_("Новый набор жестов"), transient_for=self,
                            modal=True)
        dialog.add_buttons(_("Отмена"), Gtk.ResponseType.CANCEL,
                           _("Завести"), Gtk.ResponseType.OK)
        dialog.set_default_response(Gtk.ResponseType.OK)
        area = dialog.get_content_area()
        area.set_spacing(8)
        area.set_border_width(12)
        entry = Gtk.Entry(activates_default=True, width_chars=24)
        entry.set_placeholder_text(_("название набора"))
        copy = Gtk.CheckButton(label=_("Скопировать жесты текущего набора"))
        copy.set_active(True)
        area.add(entry)
        area.add(copy)
        dialog.show_all()
        if dialog.run() == Gtk.ResponseType.OK:
            self.create_profile(entry.get_text(), copy.get_active())
        dialog.destroy()

    def delete_profile(self, confirmed: bool = False) -> bool:
        """Убрать текущий набор вместе с его жестами."""
        name = config.active_profile()
        if not name:
            self.set_status(_("основной набор удалить нельзя"))
            return False
        if not confirmed and not self.ask(
                _("Удалить набор «{0}» вместе с жестами ({1})?").format(
                    name, len(self.gestures))):
            return False
        try:
            config.remove_profile(name)
        except ValueError as exc:
            self.set_status(str(exc))
            return False
        self.refresh_profiles()
        self.reload_gestures()
        self.notify_daemon(_("Набор «{0}» удалён").format(name))
        return True

    def ask(self, question: str, parent: Gtk.Window | None = None) -> bool:
        dialog = Gtk.MessageDialog(transient_for=parent or self, modal=True,
                                   message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL,
                                   text=question)
        answer = dialog.run()
        dialog.destroy()
        return answer == Gtk.ResponseType.OK

    # --- известные приложения ---
    def _build_apps_list(self) -> Gtk.Widget:
        """Пойманные приложения: где они заняты и откуда их удалять."""
        caption = Gtk.Label(xalign=0.0, wrap=True)
        caption.set_markup(
            _("<small>Приложения, пойманные мишенью. Из них выбирают, где работает "
              "жест и где перехват не нужен.</small>"))
        self.apps_store = Gtk.ListStore(str, str, str)
        self.apps_tree = Gtk.TreeView(model=self.apps_store)
        for index, title in enumerate((_("Приложение"), _("Класс окна"), _("Где"))):
            column = Gtk.TreeViewColumn(title, Gtk.CellRendererText(ellipsize=3),
                                        text=index)
            column.set_resizable(True)
            column.set_expand(True)
            self.apps_tree.append_column(column)
        scroller = Gtk.ScrolledWindow(hexpand=True)
        scroller.set_size_request(-1, 130)
        scroller.set_shadow_type(Gtk.ShadowType.IN)
        scroller.add(self.apps_tree)
        self.apps_picker = WindowPicker(self.remember_app, self.set_status)
        hint = Gtk.Label(label=_("перетащите мишень на окно, чтобы добавить"),
                         xalign=0.0, hexpand=True, wrap=True)
        remove = Gtk.Button(label=_("Удалить"))
        remove.set_tooltip_text(_("Убрать приложение из списка вместе с привязками к нему"))
        remove.connect("clicked", lambda *_a: self.remove_selected_app())
        row = Gtk.Box(spacing=8)
        row.pack_start(self.apps_picker, False, False, 0)
        row.pack_start(hint, True, True, 0)
        row.pack_end(remove, False, False, 0)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        box.pack_start(caption, False, False, 0)
        box.pack_start(scroller, True, True, 0)
        box.pack_start(row, False, False, 0)
        self.refresh_apps()
        return box

    def refresh_apps(self) -> None:
        """Перечитать базу: список в настройках и подписи у выбора приложений."""
        store = getattr(self, "apps_store", None)
        if store is not None:
            usage = config.apps_usage()
            store.clear()
            for app in config.load_apps():
                used = usage.get(app.wm_class.lower())
                where = []
                if used is not None and used.gestures:
                    where.append(_("жестов: {0}").format(len(used.gestures)))
                if used is not None and used.excluded:
                    where.append(_("без перехвата"))
                store.append([app.title, app.wm_class, ", ".join(where) or "—"])
        for chooser in (getattr(self, "apps_chooser", None),
                        getattr(self, "excluded_chooser", None)):
            if chooser is not None:
                chooser.refresh()

    def on_app_picked(self, app: config.KnownApp, created: bool, hint: str) -> None:
        """Мишень у жеста или у исключений поймала окно и отметила приложение."""
        self.refresh_apps()
        message = (_("Приложение «{0}» запомнено и отмечено") if created
                   else _("Приложение «{0}» уже было в списке — отмечено"))
        self.set_status(f"{message.format(app.title)} — {hint}")

    def remember_app(self, wm_class: str, name: str) -> None:
        """Мишень в настройках: приложение только заносится в список."""
        try:
            app, created = config.add_app(wm_class, name)
        except ValueError as exc:
            self.set_status(str(exc))
            return
        self.refresh_apps()
        message = (_("Приложение «{0}» запомнено") if created
                   else _("Приложение «{0}» уже было в списке"))
        self.set_status(message.format(app.title))

    def selected_app(self) -> str | None:
        model, tree_iter = self.apps_tree.get_selection().get_selected()
        return model[tree_iter][1] if tree_iter is not None else None

    def remove_selected_app(self, confirmed: bool = False) -> bool:
        """Убрать приложение из списка вместе со всеми привязками к нему."""
        wm_class = self.selected_app()
        if wm_class is None:
            self.set_status(_("Выберите приложение в списке"))
            return False
        app = config.find_app(wm_class)
        title = app.title if app else wm_class
        used = config.apps_usage().get(wm_class.lower())
        question = _("Убрать «{0}» из списка приложений?").format(title)
        if used is not None and (used.gestures or used.excluded):
            places = list(used.gestures) + ([_("список исключений")] if used.excluded else [])
            question += "\n\n" + _(
                "Оно выбрано здесь: {0}. Привязки снимутся, а жесты, у которых не "
                "останется других приложений, выключатся.").format(", ".join(places))
        if not confirmed and not self.ask(question, parent=self.settings_window):
            return False
        result = config.remove_app(wm_class)
        pattern = config.class_pattern(wm_class)
        # несохранённый выбор тоже не должен вернуть приложение обратно
        self.apps_chooser.set_active(pattern, False)
        self.excluded_chooser.set_active(pattern, False)
        self.settings.excluded_apps = [known for known in self.settings.excluded_apps
                                       if not config.same_pattern(known, pattern)]
        if result.unbound:
            # жесты переписаны на диске. Прежние объекты в памяти помнят их
            # включёнными, и «Сохранить жест» включил бы выключенный обратно
            current = self.current.name if self.current else None
            self.gestures = load_gestures()
            self.refresh_list(select_name=current)
            fresh = next((g for g in self.gestures if g.name == current), None)
            if fresh is not None:
                self.load_gesture(fresh)
        self.refresh_apps()
        parts = [_("«{0}» убрано из списка приложений").format(title)]
        if result.unbound:
            parts.append(_("привязка снята у жестов: {0}").format(", ".join(result.unbound)))
        if result.disabled:
            parts.append(_("выключены: {0}").format(", ".join(result.disabled)))
        if result.excluded:
            parts.append(_("из исключений тоже убрано"))
        self.notify_daemon("; ".join(parts))
        return True

    def on_toggle_enabled(self, _renderer, path) -> None:
        gesture = self.gestures[int(path)]
        gesture.enabled = not gesture.enabled
        gesture.save()
        self.store[int(path)][0] = gesture.enabled
        self.notify_daemon(f"«{gesture.name}»: {_('включён') if gesture.enabled else _('выключен')}")

    def on_select(self, selection) -> None:
        model, tree_iter = selection.get_selected()
        if tree_iter is None:
            return
        self.load_gesture(self.gestures[int(model.get_path(tree_iter)[0])])

    # --- правая часть ---
    def _build_editor(self) -> Gtk.Widget:
        notebook = self.notebook = Gtk.Notebook()
        notebook.append_page(self._build_stroke_tab(), Gtk.Label(label=_("Росчерк")))
        notebook.append_page(self._build_actions_tab(), Gtk.Label(label=_("Действия")))
        notebook.append_page(self._build_menu_tab(), Gtk.Label(label=_("Меню")))
        # настройки всей программы среди вкладок жеста сбивали с толку: две
        # вкладки про выбранный жест, а третья — про программу целиком
        notebook.set_action_widget(self.save_button, Gtk.PackType.END)
        # show_all по окну до виджетов строки вкладок не доходит — они внутренние
        self.save_button.show_all()
        return notebook

    def _build_stroke_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        grid = Gtk.Grid(row_spacing=8, column_spacing=10)
        self.kind_combo = Gtk.ComboBoxText()
        self.kind_combo.append("", _("Росчерк — рисуется мышью"))
        for key, label in EVENTS.items():
            self.kind_combo.append(key, _(label))
        self.kind_combo.set_active_id("")
        self.kind_combo.connect("changed", lambda *_: self.on_kind_changed())
        self.name_entry = Gtk.Entry(hexpand=True, width_chars=12)
        self.description_entry = Gtk.Entry(hexpand=True, width_chars=12)
        self.directions_entry = Gtk.Entry(hexpand=True, width_chars=12)
        self.directions_entry.set_placeholder_text(
            _("не обязательно — если нарисованы образцы, оставьте пустым"))
        # раньше приложения вписывались строкой, и опечатка в классе окна
        # молча превращала жест в неработающий
        self.apps_chooser = AppChooser(
            _("везде"), self.set_status,
            on_picked=lambda app, created: self.on_app_picked(
                app, created, _("осталось «Сохранить жест»")))
        for row, (label, widget) in enumerate((
                (_("Тип жеста"), self.kind_combo),
                (_("Название"), self.name_entry),
                (_("Пояснение"), self.description_entry),
                (_("Код направлений"), self.directions_entry),
                (_("Только в приложениях"), self.apps_chooser))):
            grid.attach(Gtk.Label(label=label, xalign=1), 0, row, 1, 1)
            grid.attach(widget, 1, row, 1, 1)
        box.pack_start(grid, False, False, 0)

        self.canvas = StrokeCanvas(on_stroke=self.on_canvas_stroke)
        box.pack_start(self.canvas, True, True, 0)
        self.canvas_hint = Gtk.Label(xalign=0.0)
        box.pack_start(self.canvas_hint, False, False, 0)
        primer = Gtk.Label(xalign=0.0, wrap=True)
        primer.set_markup(
            _("<small>Нарисованное на холсте сразу становится образцом жеста — "
            "осталось нажать «Сохранить жест». Образцы сравниваются по форме, "
            "поэтому длина и точность росчерка неважны, а двух-трёх достаточно. "
            "Код направлений нужен, только когда рисовать не хочется.</small>"))
        box.pack_start(primer, False, False, 0)

        buttons = Gtk.Box(spacing=6)
        clear = Gtk.Button(label=_("Очистить образцы"))
        clear.connect("clicked", lambda *_: self.clear_samples())
        from_code = Gtk.Button(label=_("Код из росчерка"))
        from_code.set_tooltip_text(_("Записать нарисованное как код направлений"))
        from_code.connect("clicked", lambda *_: self.code_from_stroke())
        check = Gtk.Button(label=_("Проверить распознавание"))
        check.connect("clicked", lambda *_: self.check_stroke())
        for widget in (clear, from_code, check):
            buttons.pack_start(widget, True, True, 0)
        box.pack_start(buttons, False, False, 0)
        return box

    def _build_actions_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        self.actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.add(self.actions_box)
        box.pack_start(scroller, True, True, 0)
        row = Gtk.Box(spacing=6)
        add = Gtk.Button(label=_("Добавить действие"))
        add.connect("clicked", lambda *_: self.add_action_row(Action("keys", "")))
        run = Gtk.Button(label=_("Выполнить сейчас"))
        run.set_tooltip_text(_("Проверить действия, не рисуя жест"))
        run.connect("clicked", lambda *_: self.run_actions())
        row.pack_start(add, False, False, 0)
        row.pack_start(run, False, False, 0)
        box.pack_start(row, False, False, 0)
        hint = Gtk.Label(xalign=0.0, wrap=True)
        hint.set_markup(
            _("<small>Действия выполняются по очереди. Клавиши уходят в ядро "
            "через uinput, поэтому работают и в X11, и в Wayland.</small>"))
        box.pack_start(hint, False, False, 0)
        return box

    def _build_menu_tab(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        self.menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.add(self.menu_box)
        box.pack_start(scroller, True, True, 0)
        row = Gtk.Box(spacing=6)
        add = Gtk.Button(label=_("Добавить пункт"))
        add.connect("clicked", lambda *_: self.add_menu_row(MenuItem(name="")))
        row.pack_start(add, False, False, 0)
        box.pack_start(row, False, False, 0)
        hint = Gtk.Label(xalign=0.0, wrap=True)
        hint.set_markup(
            _("<small>Пунктов нет — меню и не появится: жест выполняет свои "
            "действия, как раньше. Если пункты есть, жест открывает список у "
            "курсора: ведите мышь вниз и отпустите левую кнопку на нужном "
            "пункте, правая — отмена. Рисует список расширение оболочки, "
            "в X11 — окно следа.</small>"))
        box.pack_start(hint, False, False, 0)
        return box

    def _build_settings_window(self) -> Gtk.Window:
        """Отдельное окно: настройки программы живут не среди вкладок жеста."""
        window = Gtk.Window(title=_("Glyphstroke — настройки"), transient_for=self,
                            modal=True, destroy_with_parent=True)
        window.set_default_size(660, 640)
        window.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        # закрытие прячет окно: виджеты настроек живут вместе с редактором
        window.connect("delete-event", lambda w, _e: w.hide() or True)
        window.add(self._build_settings_page())
        return window

    def show_settings(self) -> None:
        # состояние службы могло измениться, пока окно было закрыто
        self.refresh_capture_state()
        self.refresh_autostart()
        # мишень у жеста могла занести новое приложение, пока окно было закрыто
        self.refresh_apps()
        self.settings_window.show_all()
        self.settings_window.present()

    def hide_settings(self) -> None:
        self.settings_window.hide()

    def on_destroy(self, *_args) -> None:
        self.settings_window.destroy()
        Gtk.main_quit()

    def _settings_group(self, title: str, rows) -> Gtk.Frame:
        """Рамка с заголовком из строк вида «подпись, виджет».

        Подпись ``None`` отдаёт виджету обе колонки — так ложатся ряды кнопок
        и пояснения под ними.
        """
        grid = Gtk.Grid(row_spacing=8, column_spacing=10, margin=10)
        for index, (label, widget) in enumerate(rows):
            if label is None:
                grid.attach(widget, 0, index, 2, 1)
                continue
            grid.attach(Gtk.Label(label=label, xalign=1), 0, index, 1, 1)
            grid.attach(widget, 1, index, 1, 1)
        heading = Gtk.Label(margin_start=6, margin_end=6)
        heading.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>")
        frame = Gtk.Frame(margin_bottom=10)
        frame.set_label_widget(heading)
        frame.add(grid)
        return frame

    def _build_settings_page(self) -> Gtk.Widget:
        """Настройки группами: мышь, распознавание, приложения, след, служба.

        Плоским списком из шестнадцати строк искать в них было нечего: соседями
        оказывались цвет линии и порог длины росчерка.
        """
        # --- мышь ---
        self.device_label = Gtk.Label(xalign=0.0, hexpand=True, ellipsize=3)
        self.device_label.set_text(cli.bound_device(self.settings))
        self.detect_button = Gtk.Button(label=_("Определить"))
        self.detect_button.set_tooltip_text(
            _("Слушать только одну мышь: если она в системе одна, привяжется сразу, "
            "иначе попросит нажать на ней кнопку"))
        self.detect_button.connect("clicked", lambda *_: self.detect_mouse())
        any_button = Gtk.Button(label=_("Слушать все"))
        any_button.connect("clicked", lambda *_: self.unbind_mouse())
        device_row = Gtk.Box(spacing=6)
        device_row.pack_start(self.device_label, True, True, 0)
        device_row.pack_start(self.detect_button, False, False, 0)
        device_row.pack_start(any_button, False, False, 0)

        self.trigger_combo = Gtk.ComboBoxText()
        for key, label in TRIGGERS:
            self.trigger_combo.append(key, _(label))
        self.trigger_combo.set_active_id(self.settings.trigger_button)

        self.monitor_switch = Gtk.Switch(halign=Gtk.Align.START)
        self.monitor_switch.set_active(self.settings.capture_mode == "monitor")
        self.monitor_switch.set_tooltip_text(
            _("Только следить за жестами: кнопка при этом работает как обычно"))

        # --- тачпад ---
        self.touchpad_key_combo = Gtk.ComboBoxText()
        self.touchpad_key_combo.set_tooltip_text(
            _("Пока клавиша зажата, палец по тачпаду рисует росчерк"))
        self.touchpad_key_combo.append("", _("Выключено"))
        for name in capture.TOUCHPAD_KEYS:
            self.touchpad_key_combo.append(name, capture.key_label(name))
        self.select_touchpad_key(self.settings.touchpad_key)
        assign_key = Gtk.Button(label=_("Назначить…"))
        assign_key.set_tooltip_text(_("Нажать клавишу, которую будете зажимать"))
        assign_key.connect("clicked", lambda *_a: self.capture_touchpad_key())
        touchpad_row = Gtk.Box(spacing=6)
        touchpad_row.pack_start(self.touchpad_key_combo, True, True, 0)
        touchpad_row.pack_start(assign_key, False, False, 0)
        touchpad_hint = Gtk.Label(xalign=0.0, wrap=True)
        touchpad_hint.set_markup(
            _("<small>Зажмите клавишу и ведите пальцем по тачпаду — это росчерк. "
              "Жест срабатывает, когда отпускаете палец или клавишу.</small>"))

        # --- распознавание ---
        self.min_stroke = Gtk.SpinButton.new_with_range(10, 400, 5)
        self.min_stroke.set_value(self.settings.min_stroke_px)
        self.min_stroke.set_tooltip_text(
            _("Короче этого пути движение считается обычным щелчком"))

        self.min_score = Gtk.SpinButton.new_with_range(0.5, 0.99, 0.01)
        self.min_score.set_digits(2)
        self.min_score.set_value(self.settings.min_score)
        self.min_score.set_tooltip_text(
            _("Насколько похожим на образец должен быть росчерк"))

        self.unrecognized_combo = Gtk.ComboBoxText()
        self.unrecognized_combo.append("passthrough", _("Отдать клик приложению"))
        self.unrecognized_combo.append("ignore", _("Ничего не делать"))
        self.unrecognized_combo.set_active_id(self.settings.unrecognized)

        # --- приложения ---
        self.excluded_chooser = AppChooser(
            _("ни в каких"), self.set_status,
            on_picked=lambda app, created: self.on_app_picked(
                app, created, _("осталось «Применить настройки»")))
        self.excluded_chooser.set_patterns(self.settings.excluded_apps)
        apps_list = self._build_apps_list()

        self.fullscreen_switch = Gtk.Switch(halign=Gtk.Align.START)
        self.fullscreen_switch.set_active(self.settings.pause_in_fullscreen)
        self.fullscreen_switch.set_tooltip_text(
            _("Пока окно развёрнуто во весь экран, мышь отпускается: в игре "
            "она должна принадлежать игре. Перехват вернётся сам"))

        # --- след и подсказки ---
        self.overlay_switch = Gtk.Switch(halign=Gtk.Align.START)
        self.overlay_switch.set_active(self.settings.overlay.enabled)

        self.trail_preview = TrailPreview()
        self.color_button = Gtk.ColorButton()
        colour = Gdk.RGBA()
        colour.parse(self.settings.overlay.color)
        self.color_button.set_rgba(colour)
        self.color_button.set_tooltip_text(_("Цвет линии следа"))
        self.color_button.connect("color-set", lambda *_a: self.refresh_trail_preview())

        self.trail_width = Gtk.SpinButton.new_with_range(1, 24, 1)
        self.trail_width.set_value(self.settings.overlay.width)
        self.trail_width.set_tooltip_text(_("Толщина линии, точек"))
        self.trail_width.connect("value-changed", lambda *_a: self.refresh_trail_preview())

        trail_row = Gtk.Box(spacing=8)
        trail_row.pack_start(self.color_button, False, False, 0)
        trail_row.pack_start(self.trail_width, False, False, 0)
        trail_row.pack_start(self.trail_preview, True, True, 0)

        self.trail_opacity = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        self.trail_opacity.set_value(self.settings.overlay.opacity * 100)
        self.trail_opacity.set_digits(0)
        self.trail_opacity.set_value_pos(Gtk.PositionType.RIGHT)
        self.trail_opacity.set_tooltip_text(
            _("Насколько линия непрозрачна: 100 — сплошная"))
        self.trail_opacity.connect("value-changed", lambda *_a: self.refresh_trail_preview())
        self.refresh_trail_preview()

        self.name_switch = Gtk.Switch(halign=Gtk.Align.START)
        self.name_switch.set_active(self.settings.show_gesture_name)

        self.hint_spin = Gtk.SpinButton.new_with_range(0, 5000, 100)
        self.hint_spin.set_value(self.settings.hint_delay_ms)
        self.hint_spin.set_tooltip_text(
            _("Через сколько миллисекунд удержания показать список жестов; "
            "0 — не показывать"))

        # --- служба и автозапуск ---
        self.capture_switch = Gtk.Switch(halign=Gtk.Align.START, valign=Gtk.Align.CENTER)
        self.capture_switch.set_tooltip_text(
            _("Временно отпустить мышь: правая кнопка станет обычной, "
            "жесты не перехватываются"))
        self._capture_updating = False
        self.capture_switch.connect("state-set", self.on_capture_switch)
        capture_row = Gtk.Box(spacing=10)
        capture_row.pack_start(self.capture_switch, False, False, 0)
        self.capture_state = Gtk.Label(xalign=0.0)
        capture_row.pack_start(self.capture_state, False, False, 0)
        self.refresh_capture_state()

        service_row = Gtk.Box(spacing=6)
        service = Gtk.Button(label=_("Перезапустить службу"))
        service.set_tooltip_text(_("Пригодится после правки настроек руками"))
        service.connect("clicked", lambda *_: self.restart_service())
        # кнопка показывает состояние, а не одно только действие: включённый
        # автозапуск виден по нажатой и подкрашенной кнопке
        self.autostart_button = Gtk.ToggleButton(label=_("Автозапуск"))
        self._autostart_updating = False
        self.autostart_button.connect("toggled", self.on_autostart_toggled)
        service_row.pack_start(service, False, False, 0)
        service_row.pack_start(self.autostart_button, False, False, 0)
        self.refresh_autostart()

        # --- программа ---
        self.language_combo = Gtk.ComboBoxText()
        self.language_combo.append("auto", _("как в системе"))
        for code in i18n.available_languages():
            self.language_combo.append(code, LANGUAGE_NAMES.get(code, code))
        self.language_combo.set_active_id(self.settings.language or "auto")
        self.language_combo.set_tooltip_text(
            _("Язык интерфейса. Новый язык подхватится при следующем запуске"))

        self.theme_combo = Gtk.ComboBoxText()
        self.theme_combo.append("system", _("как в системе"))
        self.theme_combo.append("light", _("светлая"))
        self.theme_combo.append("dark", _("тёмная"))
        self.theme_combo.set_active_id(getattr(self.settings, "theme", "system") or "system")
        self.theme_combo.set_tooltip_text(_("Тема оформления окон программы"))
        self.theme_combo.connect("changed", self.on_theme_changed)

        self.updates_switch = Gtk.Switch(halign=Gtk.Align.START, valign=Gtk.Align.CENTER)
        self.updates_switch.set_active(getattr(self.settings, "check_updates", True))
        self.updates_switch.set_tooltip_text(
            _("Раз в сутки спрашивать страницу выпусков, не вышла ли версия новее. "
            "Сама программа не обновляется: она только показывает, что обновление есть"))
        updates_row = Gtk.Box(spacing=6)
        updates_row.pack_start(self.updates_switch, False, False, 0)
        check_now = Gtk.Button(label=_("Проверить сейчас"))
        check_now.connect("clicked", lambda *_: self.check_updates_now())
        updates_row.pack_start(check_now, False, False, 0)

        transfer = Gtk.Box(spacing=6)
        save_button = Gtk.Button(label=_("Выгрузить в файл…"))
        save_button.set_tooltip_text(_("Сохранить все жесты и их действия в один файл"))
        save_button.connect("clicked", lambda *_: self.export_gestures())
        load_button = Gtk.Button(label=_("Загрузить из файла…"))
        load_button.set_tooltip_text(
            _("Добавить жесты из файла; совпадающие по названию будут заменены"))
        load_button.connect("clicked", lambda *_: self.import_gestures())
        transfer.pack_start(save_button, False, False, 0)
        transfer.pack_start(load_button, False, False, 0)

        paths = Gtk.Label(xalign=0.0, wrap=True)
        paths.set_markup(
            _("<small>Файлы настроек: <tt>{0}</tt>\nПроверка окружения и прав: <tt>glyphstroke doctor</tt></small>").format(config.config_dir()))

        groups = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, margin=12)
        for title, rows in (
            (_("Мышь"), ((_("Слушать"), device_row),
                         (_("Кнопка-модификатор"), self.trigger_combo),
                         (_("Не перехватывать кнопку"), self.monitor_switch))),
            (_("Тачпад"), ((_("Рисовать, пока зажата"), touchpad_row),
                           (None, touchpad_hint))),
            (_("Распознавание"), ((_("Порог длины росчерка"), self.min_stroke),
                                  (_("Строгость распознавания"), self.min_score),
                                  (_("Если жест не распознан"), self.unrecognized_combo))),
            (_("Приложения"), ((None, apps_list),
                               (_("Не мешать в приложениях"), self.excluded_chooser),
                               (_("Отключаться в полноэкранных"),
                                self.fullscreen_switch))),
            (_("След и подсказки"), ((_("Рисовать след"), self.overlay_switch),
                                     (_("Цвет и толщина"), trail_row),
                                     (_("Непрозрачность, %"), self.trail_opacity),
                                     (_("Показывать имя жеста"), self.name_switch),
                                     (_("Шпаргалка после, мс"), self.hint_spin))),
            (_("Служба и автозапуск"), ((_("Перехват жестов"), capture_row),
                                        (None, service_row))),
            (_("Программа"), ((_("Язык"), self.language_combo),
                              (_("Тема"), self.theme_combo),
                              (_("Проверять обновления"), updates_row),
                              (_("Перенос жестов"), transfer),
                              (None, paths))),
        ):
            groups.pack_start(self._settings_group(title, rows), False, False, 0)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.add(groups)

        # «Применить» держим под прокруткой: до него не придётся долистывать
        footer = Gtk.Box(spacing=6, margin=12)
        apply_button = Gtk.Button(label=_("Применить настройки"))
        apply_button.get_style_context().add_class("suggested-action")
        apply_button.connect("clicked", lambda *_: self.save_settings())
        close_button = Gtk.Button(label=_("Закрыть"))
        close_button.connect("clicked", lambda *_: self.hide_settings())
        footer.pack_start(apply_button, False, False, 0)
        footer.pack_end(close_button, False, False, 0)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.pack_start(scroller, True, True, 0)
        box.pack_start(footer, False, False, 0)
        return box

    # --- загрузка и сохранение жеста ---
    def on_kind_changed(self) -> None:
        """У особого жеста нет росчерка — прячем всё, что к нему относится."""
        is_stroke = not (self.kind_combo.get_active_id() or "")
        for widget in (self.canvas, self.directions_entry, self.canvas_hint):
            widget.set_sensitive(is_stroke)
        if not is_stroke and not self._loading:
            self.set_status(_("Особый жест рисовать не нужно — "
                            "он срабатывает от щелчка или колеса"))

    def load_gesture(self, gesture: Gesture) -> None:
        self._loading = True
        self.current = gesture
        self.kind_combo.set_active_id(gesture.event or "")
        self.on_kind_changed()
        self.name_entry.set_text(gesture.name)
        self.description_entry.set_text(gesture.description or "")
        self.directions_entry.set_text(", ".join(gesture.directions))
        self.apps_chooser.set_patterns(gesture.apps)
        self.canvas.show_samples(gesture.templates)
        self.canvas_hint.set_text(
            _("образцов: {0}").format(len(gesture.templates))
            + (_("; код: {0}").format(', '.join(gesture.directions)) if gesture.directions else ""))
        for child in self.actions_box.get_children():
            self.actions_box.remove(child)
        for action in gesture.actions or [Action("keys", "")]:
            self.add_action_row(action)
        for child in self.menu_box.get_children():
            self.menu_box.remove(child)
        # пустого пункта по умолчанию тут быть не должно: пустое меню — это
        # обычный жест, и заводить его никто не просил
        for item in gesture.menu:
            self.add_menu_row(item)
        self._loading = False

    def add_action_row(self, action: Action) -> None:
        row = ActionRow(action, self.remove_action_row, lambda: None, parent=self)
        self.actions_box.pack_start(row, False, False, 0)
        self.actions_box.show_all()
        row.update_browse()

    def remove_action_row(self, row: ActionRow) -> None:
        self.actions_box.remove(row)

    def collect_actions(self) -> list[Action]:
        return [row.to_action() for row in self.actions_box.get_children()
                if isinstance(row, ActionRow)]

    def add_menu_row(self, item: MenuItem) -> None:
        row = MenuItemRow(item, self.remove_menu_row, parent=self)
        self.menu_box.pack_start(row, False, False, 0)
        self.menu_box.show_all()

    def remove_menu_row(self, row: MenuItemRow) -> None:
        self.menu_box.remove(row)

    def collect_menu(self) -> list[MenuItem]:
        """Пункты без названия отбрасываем: в меню их всё равно не видно."""
        items = [row.to_item() for row in self.menu_box.get_children()
                 if isinstance(row, MenuItemRow)]
        return [item for item in items if item.name]

    def on_save(self, *_args) -> None:
        if self.current is None:
            return
        name = self.name_entry.get_text().strip()
        if not name:
            self.set_status(_("У жеста должно быть название"))
            return
        gesture = self.current
        gesture.name = name
        gesture.description = self.description_entry.get_text().strip()
        gesture.directions = [d.strip().upper() for d in
                              self.directions_entry.get_text().split(",") if d.strip()]
        gesture.apps = self.apps_chooser.get_patterns()
        gesture.actions = self.collect_actions()
        gesture.menu = self.collect_menu()
        gesture.event = self.kind_combo.get_active_id() or ""
        if gesture.event:
            gesture.save()
            self.refresh_list(select_name=gesture.name)
            self.notify_daemon(_("Сохранено: «{0}» ({1})").format(gesture.name, EVENTS.get(gesture.event, gesture.event)))
            return
        if not gesture.directions and not gesture.templates:
            self.set_status(_("Нарисуйте росчерк на холсте — он сразу станет "
                            "образцом (либо впишите код направлений)"))
            return
        gesture.save()
        self.refresh_list(select_name=gesture.name)
        clash = [code for code in gesture.directions
                 if code in find_conflicts(self.gestures)]
        if clash:
            others = [g.name for g in self.gestures
                      if g.enabled and g.name != gesture.name
                      and any(c in g.directions for c in clash)]
            self.notify_daemon(
                _("Сохранено, но код {0} уже занят: {1}. Пока так — не сработает ни один жест").format(', '.join(clash), ', '.join(others)))
            return
        self.notify_daemon(_("Сохранено: «{0}»").format(gesture.name))

    def on_add(self, *_args) -> None:
        gesture = Gesture(name=_("Новый жест"), actions=[Action("keys", "")])
        self.gestures.append(gesture)
        self.refresh_list(select_name=gesture.name)
        self.set_status(_("Нарисуйте росчерк или задайте код направлений, "
                        "затем «Сохранить жест»"))

    def on_remove(self, *_args) -> None:
        if self.current is None:
            return
        dialog = Gtk.MessageDialog(
            transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text=_("Удалить жест «{0}»?").format(self.current.name))
        response = dialog.run()
        dialog.destroy()
        if response != Gtk.ResponseType.OK:
            return
        self.current.delete()
        self.gestures.remove(self.current)
        self.current = None
        self.refresh_list()
        self.notify_daemon(_("Жест удалён"))

    # --- холст ---
    def on_canvas_stroke(self, points) -> None:
        """Нарисованное сразу становится образцом.

        Раньше рисунок ждал отдельной кнопки: человек рисовал, нажимал
        «Сохранить», холст очищался — и росчерк пропадал, потому что образцом
        он так и не стал.
        """
        self._last_stroke = points
        code = direction_code(points)
        if self.current is None:
            self.canvas_hint.set_text(
                _("нарисовано: код {0}, точек {1}").format(code or '—', len(points)))
            self.set_status(_("Сначала выберите жест слева или заведите новый"))
            return
        self.current.templates = list(self.current.templates) + [resample(points)]
        self.canvas.show_samples(self.current.templates)
        self.canvas_hint.set_text(_("образцов: {0}; код нарисованного: {1}").format(
            len(self.current.templates), code or '—'))
        self.set_status(_("Образец добавлен — осталось «Сохранить жест»"))

    def clear_samples(self) -> None:
        if self.current is None:
            return
        self.current.templates = []
        self.canvas.show_samples([])
        self.set_status(_("Образцы очищены"))

    def code_from_stroke(self) -> None:
        points = getattr(self, "_last_stroke", None)
        if not points:
            self.set_status(_("Сначала нарисуйте росчерк на холсте"))
            return
        code = direction_code(points)
        self.directions_entry.set_text(code)
        self.set_status(_("Код направлений: {0}").format(code or 'не определился'))

    def check_stroke(self) -> None:
        points = getattr(self, "_last_stroke", None)
        if not points:
            self.set_status(_("Сначала нарисуйте росчерк на холсте"))
            return
        enabled = [g for g in load_gestures() if g.enabled]
        recognizer = Recognizer([g.to_def() for g in enabled],
                                self.settings.min_score, self.settings.min_margin)
        match = recognizer.recognize(points)
        best = ", ".join(f"{n} {s:.2f}" for n, s in recognizer.score_all(points)[:3])
        self.set_status(_("Код {0} → {1}   [{2}]").format(match.code or '—', match.name or 'не распознано', best or 'совпадений нет'))

    def run_actions(self) -> None:
        runner = ActionRunner()
        try:
            runner.run(self.collect_actions())
            self.set_status(_("Действия выполнены"))
        except Exception as exc:
            self.set_status(_("Ошибка: {0}").format(exc))
        finally:
            GLib.timeout_add(1500, lambda: (runner.close(), False)[1])

    # --- справка ---
    def show_help(self) -> None:
        from . import help as help_text

        window = Gtk.Window(title=_("Glyphstroke — справка"), transient_for=self)
        window.set_default_size(860, 640)
        paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        paned.set_position(240)

        store = Gtk.ListStore(str, str)
        for title, body in help_text.sections():
            store.append([title, body])
        tree = Gtk.TreeView(model=store, headers_visible=False)
        tree.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(), text=0))
        left = Gtk.ScrolledWindow()
        left.add(tree)
        paned.add1(left)

        label = Gtk.Label(xalign=0.0, yalign=0.0, wrap=True, selectable=True,
                          margin=18)
        label.set_max_width_chars(70)
        right = Gtk.ScrolledWindow()
        right.add(label)
        paned.add2(right)

        def show_section(selection):
            model, tree_iter = selection.get_selected()
            if tree_iter is None:
                return
            title, body = model[tree_iter][0], model[tree_iter][1]
            label.set_markup(help_text.to_markup(f"## {title}\n\n{body}"))
            right.get_vadjustment().set_value(0)

        tree.get_selection().connect("changed", show_section)
        tree.get_selection().select_path(Gtk.TreePath(0))

        window.add(paned)
        window.show_all()

    # --- о программе ---
    REPORT_RESPONSE = 1

    def show_about(self) -> None:
        dialog = Gtk.AboutDialog(transient_for=self, modal=True)
        dialog.set_program_name("Glyphstroke")
        dialog.set_version(_("{0} от {1}").format(about.__version__, about.RELEASE_DATE))
        dialog.set_comments(
            _("{0}\n\nВопросы и сообщения об ошибках: {1}").format(
                _(about.SUMMARY), about.EMAIL))
        dialog.set_copyright(f"© {about.YEARS} {about.AUTHOR}")
        dialog.set_authors([f"{about.AUTHOR} <{about.EMAIL}>"])
        # Лицензия PolyForm Noncommercial: пользоваться бесплатно можно,
        # продавать нельзя. Полный текст — в файле LICENSE репозитория.
        dialog.set_license_type(Gtk.License.CUSTOM)
        dialog.set_license("PolyForm Noncommercial 1.0.0 — "
                           "бесплатно для некоммерческого использования. "
                           "Полный текст: файл LICENSE.")
        # Значок программы, а не системная мышка: у программы он свой, и в окне
        # «О программе» человек ожидает увидеть именно его. Из темы значок
        # доступен только после установки, поэтому при запуске из исходников
        # берём файл напрямую — иначе окно осталось бы вовсе без картинки.
        logo = Path(__file__).resolve().parent / "data" / "icons" / "128" / "glyphstroke.png"
        if Gtk.IconTheme.get_default().has_icon("glyphstroke"):
            dialog.set_logo_icon_name("glyphstroke")
        elif logo.exists():
            try:
                dialog.set_logo(GdkPixbuf.Pixbuf.new_from_file(str(logo)))
            except Exception:
                pass      # без картинки окно всё равно откроется
        # письмо об ошибке уходит с уже собранным описанием окружения
        dialog.add_button(_("Написать об ошибке"), self.REPORT_RESPONSE)
        if dialog.run() == self.REPORT_RESPONSE:
            self.report_problem()
        dialog.destroy()

    def report_problem(self) -> None:
        """Открыть письмо, подставив версию и окружение."""
        from urllib.parse import quote

        body = (_("Опишите, что произошло:\n\n\n"
                "--- сведения о программе ---\n") + "\n".join(cli.about_lines()))
        url = (f"mailto:{about.EMAIL}"
               f"?subject={quote(_("Glyphstroke {0} — ошибка").format(about.__version__))}"
               f"&body={quote(body)}")
        try:
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            self.set_status(_("Письмо открыто в почтовой программе ({0})").format(about.EMAIL))
        except OSError:
            self.set_status(_("Напишите на {0}, приложив вывод «glyphstroke about»").format(about.EMAIL))

    # --- след ---
    def trail_style(self) -> tuple[tuple[float, float, float], int, float]:
        colour = self.color_button.get_rgba()
        return ((colour.red, colour.green, colour.blue),
                int(self.trail_width.get_value()),
                self.trail_opacity.get_value() / 100.0)

    def refresh_trail_preview(self) -> None:
        self.trail_preview.set_style(*self.trail_style())

    # --- пауза перехвата ---
    def refresh_capture_state(self) -> None:
        running = cli.daemon_info()
        self._capture_updating = True
        if running is None:
            self.capture_switch.set_active(False)
            self.capture_switch.set_sensitive(False)
            self.capture_state.set_markup(_("<small>демон не запущен</small>"))
        else:
            _version, _pid, state = running
            self.capture_switch.set_sensitive(True)
            self.capture_switch.set_active(state != "paused")
            self.capture_state.set_markup(
                _("<small>приостановлен</small>") if state == "paused"
                else _("<small>работает</small>"))
        self._capture_updating = False

    def on_capture_switch(self, _switch, active) -> bool:
        if self._capture_updating:
            return False
        state = cli.send_command("resume" if active else "pause")
        if state is None:
            self.set_status(_("Демон не отвечает — проверьте «glyphstroke doctor»"))
        else:
            self.set_status(_("Перехват включён") if state == "active"
                            else _("Перехват приостановлен: правая кнопка работает "
                                 "как обычно"))
        self.refresh_capture_state()
        return False

    # --- перенос жестов ---
    def export_gestures(self) -> None:
        dialog = Gtk.FileChooserDialog(
            title=_("Куда выгрузить жесты"), transient_for=self,
            action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(_("Отмена"), Gtk.ResponseType.CANCEL,
                           _("Сохранить"), Gtk.ResponseType.OK)
        dialog.set_current_name(_("жесты-glyphstroke.yaml"))
        dialog.set_do_overwrite_confirmation(True)
        if dialog.run() == Gtk.ResponseType.OK:
            path = Path(dialog.get_filename())
            try:
                count = export_bundle(path, gestures=load_gestures())
                self.set_status(_("Выгружено жестов: {0} → {1}").format(count, path))
            except OSError as exc:
                self.set_status(_("Не удалось сохранить: {0}").format(exc))
        dialog.destroy()

    def import_gestures(self) -> None:
        dialog = Gtk.FileChooserDialog(
            title=_("Откуда загрузить жесты"), transient_for=self,
            action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(_("Отмена"), Gtk.ResponseType.CANCEL,
                           _("Загрузить"), Gtk.ResponseType.OK)
        yaml_filter = Gtk.FileFilter()
        yaml_filter.set_name(_("Файлы жестов (*.yaml)"))
        yaml_filter.add_pattern("*.yaml")
        dialog.add_filter(yaml_filter)
        path = None
        if dialog.run() == Gtk.ResponseType.OK:
            path = Path(dialog.get_filename())
        dialog.destroy()
        if path is None:
            return
        try:
            result = import_bundle(path)
        except Exception as exc:
            self.set_status(_("Не удалось прочитать файл: {0}").format(exc))
            return
        self.reload_gestures()
        conflicts = find_conflicts(self.gestures)
        note = (_("; внимание, коды {0} заняты дважды").format(', '.join(conflicts))
                if conflicts else "")
        self.notify_daemon(_("Загрузка: {0}{1}").format(result.summary(), note))

    # --- привязка к устройству ---
    def detect_mouse(self) -> None:
        found = capture.find_pointers()
        candidates = [(cli.stable_id(dev), dev.name) for dev in found]
        for dev in found:
            dev.close()
        if not candidates:
            self.set_status(_("Мышей не найдено — проверьте «glyphstroke doctor»"))
            return
        if len(candidates) == 1:
            self.apply_binding(*candidates[0])
            return
        # мышей несколько: демон держит их эксклюзивно, поэтому на время
        # определения службу нужно остановить
        self.detect_button.set_sensitive(False)
        self.set_status(_("Нажмите любую кнопку на нужной мыши…"))
        threading.Thread(target=self._detect_worker, daemon=True).start()

    def _detect_worker(self) -> None:
        was_active = cli.service_is_active()
        if was_active:
            subprocess.run(["systemctl", "--user", "stop", "glyphstroke"], check=False)
        try:
            detected = cli.detect_pointer()
        except Exception as exc:
            detected = None
            GLib.idle_add(self.set_status, _("Не вышло определить мышь: {0}").format(exc))
        finally:
            if was_active:
                subprocess.run(["systemctl", "--user", "start", "glyphstroke"], check=False)
        GLib.idle_add(self._detect_done, detected)

    def _detect_done(self, detected) -> bool:
        self.detect_button.set_sensitive(True)
        if detected:
            self.apply_binding(*detected)
        else:
            self.set_status(_("Кнопку так и не нажали — привязка не изменилась"))
        return False

    def apply_binding(self, target: str, name: str) -> None:
        self.settings.device_include = [cli.name_pattern(target)]
        self.settings.save()
        self.device_label.set_text(cli.bound_device(self.settings))
        self.set_status(_("Слушаем только «{0}»").format(name))
        self.restart_service(quiet=True)

    def unbind_mouse(self) -> None:
        self.settings.device_include = []
        self.settings.save()
        self.device_label.set_text(cli.bound_device(self.settings))
        self.set_status(_("Привязка снята: слушаем все найденные мыши"))
        self.restart_service(quiet=True)

    # --- клавиша для тачпада ---
    def select_touchpad_key(self, name: str) -> None:
        """Показать клавишу в списке; назначенной нажатием там может не быть."""
        name = (name or "").strip().upper()
        if name and capture.key_code(name) is None:
            name = ""
        if not self.touchpad_key_combo.set_active_id(name):
            self.touchpad_key_combo.append(name, capture.key_label(name))
            self.touchpad_key_combo.set_active_id(name)

    def touchpad_key_from_keycode(self, hardware_keycode: int) -> bool:
        """X-код клавиши → имя ядра: коды X сдвинуты на 8 от кодов evdev."""
        name = capture.key_name(hardware_keycode - 8)
        if name is None:
            self.set_status(_("Эту клавишу назначить не выйдет"))
            return False
        self.select_touchpad_key(name)
        self.set_status(_("Клавиша для тачпада: {0} — осталось «Применить настройки»").format(
            capture.key_label(name)))
        return True

    def capture_touchpad_key(self) -> None:
        dialog = Gtk.Dialog(title=_("Клавиша для тачпада"),
                            transient_for=self.settings_window, modal=True)
        dialog.add_buttons(_("Отмена"), Gtk.ResponseType.CANCEL)
        label = Gtk.Label(
            label=_("Нажмите клавишу, которую будете зажимать, рисуя на тачпаде. "
                    "Esc — отмена."),
            wrap=True, max_width_chars=40, margin=18)
        dialog.get_content_area().add(label)

        def on_key(_widget, event) -> bool:
            if event.keyval == Gdk.KEY_Escape:
                dialog.response(Gtk.ResponseType.CANCEL)
            elif self.touchpad_key_from_keycode(event.hardware_keycode):
                dialog.response(Gtk.ResponseType.OK)
            return True

        dialog.connect("key-press-event", on_key)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    # --- настройки и служба ---
    def save_settings(self) -> None:
        self.settings.trigger_button = self.trigger_combo.get_active_id()
        self.settings.touchpad_key = self.touchpad_key_combo.get_active_id() or ""
        self.settings.min_stroke_px = self.min_stroke.get_value()
        self.settings.min_score = round(self.min_score.get_value(), 2)
        self.settings.unrecognized = self.unrecognized_combo.get_active_id()
        self.settings.overlay.enabled = self.overlay_switch.get_active()
        rgb, line_width, opacity = self.trail_style()
        self.settings.overlay.color = "#{:02x}{:02x}{:02x}".format(
            *(round(channel * 255) for channel in rgb))
        self.settings.overlay.width = line_width
        self.settings.overlay.opacity = round(opacity, 2)
        self.settings.excluded_apps = self.excluded_chooser.get_patterns()
        self.settings.show_gesture_name = self.name_switch.get_active()
        self.settings.pause_in_fullscreen = self.fullscreen_switch.get_active()
        language = self.language_combo.get_active_id() or "auto"
        if language != self.settings.language:
            self.settings.language = language
            self.set_status(_("Язык сменится при следующем запуске редактора"))
        self.settings.theme = self.theme_combo.get_active_id() or "system"
        self.settings.hint_delay_ms = int(self.hint_spin.get_value())
        self.settings.capture_mode = "monitor" if self.monitor_switch.get_active() else "grab"
        self.settings.check_updates = self.updates_switch.get_active()
        self.settings.save()  # привязка к устройству лежит в тех же настройках
        self.notify_daemon(_("Настройки сохранены"))
        self.restart_service(quiet=True)

    def on_theme_changed(self, combo) -> None:
        """Тему применяем сразу — без ожидания сохранения и перезапуска."""
        apply_gtk_theme(combo.get_active_id() or "system")

    def restart_service(self, quiet: bool = False) -> None:
        subprocess.run(["systemctl", "--user", "restart", "glyphstroke"],
                       check=False, capture_output=True)
        if not quiet:
            self.set_status(_("Служба перезапущена"))

    # --- автозапуск ---
    def refresh_autostart(self) -> None:
        """Привести кнопку к тому, что на самом деле говорит systemd."""
        state = cli.service_is_enabled()
        self._autostart_updating = True
        self.autostart_button.set_sensitive(state is not None)
        self.autostart_button.set_active(bool(state))
        # нажатое состояние в некоторых темах едва заметно, поэтому включённый
        # автозапуск ещё и подкрашиваем
        style = self.autostart_button.get_style_context()
        (style.add_class if state else style.remove_class)("suggested-action")
        self.autostart_button.set_tooltip_text(
            _("systemd пользователя недоступен — автозапуском отсюда не управлять")
            if state is None else
            _("Служба запускается при входе в систему. Отжать — вернуть как было")
            if state else _("Запускать службу при входе в систему"))
        self._autostart_updating = False

    def on_autostart_toggled(self, button) -> None:
        if self._autostart_updating:
            return
        self.set_autostart(button.get_active())
        # спрашиваем systemd заново: если включить не вышло, кнопка должна
        # вернуться к правде, а не остаться нажатой
        self.refresh_autostart()

    def set_autostart(self, enabled: bool) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "glyphstroke.cli", "service",
             "enable" if enabled else "disable"],
            capture_output=True, text=True)
        self.set_status(result.stdout.strip() or result.stderr.strip()
                        or (_("Автозапуск включён") if enabled
                            else _("Автозапуск выключен")))

    def notify_daemon(self, message: str) -> None:
        subprocess.run(["pkill", "-HUP", "-f", "glyphstroke.daemon"],
                       check=False, capture_output=True)
        subprocess.run(["systemctl", "--user", "reload", "glyphstroke"],
                       check=False, capture_output=True)
        self.set_status(message)

    def set_status(self, text: str) -> None:
        self.status.set_markup(f"<small>{GLib.markup_escape_text(text)}</small>")


def apply_window_icon() -> None:
    """Значок окна: из темы, а при запуске из исходников — прямо из файла."""
    if Gtk.IconTheme.get_default().has_icon("glyphstroke"):
        Gtk.Window.set_default_icon_name("glyphstroke")
        return
    icon = Path(__file__).resolve().parent / "data" / "icons" / "128" / "glyphstroke.png"
    if icon.exists():
        try:
            Gtk.Window.set_default_icon_from_file(str(icon))
        except Exception:
            pass          # без значка окно всё равно откроется


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="glyphstroke gui")
    # служебные ключи для автотеста интерфейса
    parser.add_argument("--screenshot", help=argparse.SUPPRESS)
    parser.add_argument("--quit-after-ms", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    i18n.setup(Settings.load().language)
    apply_window_icon()
    config.ensure_default_config()
    window = EditorWindow()
    window.show_all()
    if args.screenshot:
        GLib.timeout_add(700, _grab_screenshot, window, args.screenshot)
    if args.quit_after_ms:
        GLib.timeout_add(args.quit_after_ms, Gtk.main_quit)
    Gtk.main()
    return 0


def _grab_screenshot(window, path: str) -> bool:
    gdk_window = window.get_window()
    pixbuf = Gdk.pixbuf_get_from_window(
        gdk_window, 0, 0, gdk_window.get_width(), gdk_window.get_height())
    pixbuf.savev(path, "png", [], [])
    return False


if __name__ == "__main__":
    raise SystemExit(main())
