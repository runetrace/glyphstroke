"""След за курсором во время рисования жеста.

Отдельный процесс: демон шлёт ему в stdin строки ``begin``, ``end``, ``quit``,
а позицию курсора окно узнаёт само — так не нужно пересчитывать «попугаи»
мыши в пиксели экрана.

Работает в X11: прозрачное окно поверх всех, прозрачное и для щелчков.
В Wayland глобальную позицию курсора приложению не отдают, а окно поверх
всего требует протокола wlr-layer-shell, которого в GNOME нет, — там след
просто не рисуется, на сами жесты это не влияет.
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

from .i18n import _

FRAME_MS = 16
MIN_STEP_PX = 2.0
#: высота строки меню и отступ от курсора — в пикселях экрана. Подсветку
#: задаёт демон, поэтому картинка не может разойтись с его выбором
MENU_ROW_H = 30
MENU_GAP = 14


def parse_color(text: str) -> tuple[float, float, float]:
    text = text.lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="glyphstroke.overlay")
    parser.add_argument("--color", default="#4da3ff")
    parser.add_argument("--width", type=int, default=4)
    parser.add_argument("--opacity", type=float, default=0.9)
    parser.add_argument("--fade-ms", type=int, default=220)
    args = parser.parse_args(argv)

    # В сеансе Wayland глобальной позиции курсора нет. При наличии DISPLAY
    # окно молча подключилось бы к Xwayland и рисовало ломаную из случайных
    # координат, поэтому выходим до инициализации GTK.
    if os.environ.get("WAYLAND_DISPLAY") or \
            os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland":
        print(_("след не рисуется: сеанс Wayland"), file=sys.stderr)
        return 1

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, GLib, Gtk
    except Exception as exc:
        print(_("след не рисуется: нет GTK 3 ({0})").format(exc), file=sys.stderr)
        return 1

    if Gdk.Display.get_default() is None:
        print(_("след не рисуется: нет доступа к дисплею"), file=sys.stderr)
        return 1
    if type(Gdk.Display.get_default()).__name__.startswith("Wayland"):
        print(_("след не рисуется: в Wayland нет глобальной позиции курсора"),
              file=sys.stderr)
        return 1

    rgb = parse_color(args.color)
    overlay = Overlay(Gtk, Gdk, GLib, rgb, args.width, args.fade_ms,
                      opacity=args.opacity)
    threading.Thread(target=overlay.read_commands, daemon=True).start()
    Gtk.main()
    return 0


class Overlay:
    def __init__(self, Gtk, Gdk, GLib, rgb, width, fade_ms, opacity=0.9):
        self.Gtk, self.Gdk, self.GLib = Gtk, Gdk, GLib
        self.rgb = rgb
        self.width = width
        #: непрозрачность линии; на затухание она умножается
        self.opacity = max(0.05, min(1.0, opacity))
        self.fade_ms = fade_ms
        self.points: list[tuple[float, float]] = []
        self.alpha = 1.0
        self.timer = None
        self.name_text = ""
        self.hint_items: list[tuple[str, str]] = []
        self.menu_title = ""
        self.menu_items: list[str] = []
        self.menu_index = -1
        self.menu_anchor = (0.0, 0.0)

        screen = Gdk.Screen.get_default()
        self.window = Gtk.Window(type=Gtk.WindowType.POPUP)
        self.window.set_app_paintable(True)
        visual = screen.get_rgba_visual()
        if visual:
            self.window.set_visual(visual)
        self.window.set_keep_above(True)
        self.window.set_accept_focus(False)
        self.window.set_decorated(False)
        self.window.move(0, 0)
        self.window.resize(screen.get_width(), screen.get_height())
        self.window.connect("draw", self.on_draw)
        self.window.connect("realize", self.on_realize)
        self.window.connect("destroy", Gtk.main_quit)

    def on_realize(self, widget) -> None:
        import cairo
        # окно не должно ловить щелчки: пустая входная область
        widget.get_window().input_shape_combine_region(cairo.Region(), 0, 0)

    # --- команды от демона ---
    def read_commands(self) -> None:
        for line in sys.stdin:
            command = line.strip()
            if command == "begin":
                self.GLib.idle_add(self.begin)
            elif command == "end":
                self.GLib.idle_add(self.end)
            elif command.startswith("notify\t"):
                self.GLib.idle_add(self.show_name, command.split("\t", 1)[1])
            elif command.startswith("hint\t"):
                items = [tuple((part.split("|") + [""])[:2])
                         for part in command.split("\t")[1:] if part]
                self.GLib.idle_add(self.show_hint, items)
            elif command == "hint-hide":
                self.GLib.idle_add(self.show_hint, [])
            elif command.startswith("menu\t"):
                parts = command.split("\t")[1:]
                self.GLib.idle_add(self.show_menu, parts[0], parts[1:])
            elif command.startswith("menu-select\t"):
                try:
                    index = int(command.split("\t", 1)[1])
                except ValueError:
                    index = -1
                self.GLib.idle_add(self.select_menu, index)
            elif command == "menu-hide":
                self.GLib.idle_add(self.show_menu, "", [])
            elif command == "quit":
                self.GLib.idle_add(self.Gtk.main_quit)
        self.GLib.idle_add(self.Gtk.main_quit)

    def begin(self) -> bool:
        """Кнопка нажата: с этого мгновения копим точки росчерка."""
        self.points = []
        self.alpha = 1.0
        if self.timer is None:
            self.timer = self.GLib.timeout_add(FRAME_MS, self.on_frame)
        return False

    def end(self) -> bool:
        if self.timer is not None:
            self.GLib.source_remove(self.timer)
            self.timer = None
        if not self.window.get_visible():
            self.points = []       # был обычный щелчок, рисовать нечего
            return False
        steps = max(1, self.fade_ms // FRAME_MS)
        self.GLib.timeout_add(FRAME_MS, self.on_fade, 1.0 / steps)
        return False

    # --- отрисовка ---
    def pointer_position(self) -> tuple[float, float]:
        seat = self.Gdk.Display.get_default().get_default_seat()
        _screen, x, y = seat.get_pointer().get_position()[0:3]
        return float(x), float(y)

    def on_frame(self) -> bool:
        x, y = self.pointer_position()
        if not self.points or max(abs(x - self.points[-1][0]),
                                  abs(y - self.points[-1][1])) >= MIN_STEP_PX:
            self.points.append((x, y))
            # окно поднимаем только когда курсор поехал: на обычном щелчке
            # оно не должно мелькать
            if len(self.points) >= 2 and not self.window.get_visible():
                self.window.show()
            if self.window.get_visible():
                self.window.queue_draw()
        return True

    def on_fade(self, step: float) -> bool:
        self.alpha -= step
        if self.alpha <= 0:
            self.points = []
            self._hide_if_idle()
            return False
        self.window.queue_draw()
        return True

    # --- подсказки ---
    def show_name(self, name: str) -> bool:
        """Показать имя сработавшего жеста на полторы секунды."""
        self.name_text = name
        self.window.show()
        self.window.queue_draw()
        self.GLib.timeout_add(1500, self._clear_name, name)
        return False

    def _clear_name(self, name: str) -> bool:
        if self.name_text == name:      # за это время мог прийти другой жест
            self.name_text = ""
            self.window.queue_draw()
            self._hide_if_idle()
        return False

    def show_hint(self, items) -> bool:
        self.hint_items = list(items)
        if self.hint_items:
            self.window.show()
        self.window.queue_draw()
        self._hide_if_idle()
        return False

    # --- меню под жестом ---
    def show_menu(self, title: str, items) -> bool:
        """Открыть список у курсора. Пустой список закрывает меню."""
        self.menu_title = title
        self.menu_items = list(items)
        self.menu_index = -1
        if self.menu_items:
            # курсор во время меню стоит на месте: демон никуда его не пускает,
            # поэтому место запоминаем один раз, при открытии
            self.menu_anchor = self.pointer_position()
            self.window.show()
        self.window.queue_draw()
        self._hide_if_idle()
        return False

    def select_menu(self, index: int) -> bool:
        self.menu_index = index
        self.window.queue_draw()
        return False

    def _hide_if_idle(self) -> None:
        if not self.points and not self.hint_items and not self.name_text \
                and not self.menu_items:
            self.window.hide()

    def _draw_hint(self, cr, width, height) -> None:
        """Шпаргалка по центру: название жеста и как его сделать."""
        cr.select_font_face("Sans")
        cr.set_font_size(15)
        rows = list(self.hint_items)
        title = _("Жесты Glyphstroke")
        line_height = 24
        left = max([cr.text_extents(name).width for name, _how in rows] + [0])
        right = max([cr.text_extents(how).width for _name, how in rows] + [0])
        box_width = max(left + right + 90, cr.text_extents(title).width + 60)
        box_height = line_height * (len(rows) + 1) + 40
        x = (width - box_width) / 2
        y = (height - box_height) / 2

        self._rounded_box(cr, x, y, box_width, box_height, 14)
        cr.set_source_rgba(0.08, 0.08, 0.10, 0.88)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.set_line_width(1)
        cr.stroke()

        cr.set_source_rgba(0.95, 0.95, 0.95, 1)
        cr.move_to(x + 30, y + 34)
        cr.show_text(title)
        for index, (name, how) in enumerate(rows):
            line_y = y + 34 + line_height * (index + 1)
            cr.set_source_rgba(0.95, 0.95, 0.95, 1)
            cr.move_to(x + 30, line_y)
            cr.show_text(name)
            cr.set_source_rgba(0.5, 0.7, 1.0, 1)
            cr.move_to(x + box_width - 30 - cr.text_extents(how).width, line_y)
            cr.show_text(how)

    def _draw_menu(self, cr, width, height) -> None:
        """Список у курсора: заголовок сверху, подсвеченный пункт — полосой."""
        cr.select_font_face("Sans")
        cr.set_font_size(15)
        rows = self.menu_items
        title_h = MENU_ROW_H + 6 if self.menu_title else 0
        text_width = max([cr.text_extents(text).width for text in rows]
                         + [cr.text_extents(self.menu_title).width])
        box_width = text_width + 64
        box_height = title_h + MENU_ROW_H * len(rows) + 20
        anchor_x, anchor_y = self.menu_anchor
        x = min(max(8.0, anchor_x - box_width / 2), width - box_width - 8)
        y = anchor_y + MENU_GAP
        if y + box_height > height - 8:      # снизу не помещается — рисуем выше
            y = max(8.0, anchor_y - MENU_GAP - box_height)

        self._rounded_box(cr, x, y, box_width, box_height, 14)
        cr.set_source_rgba(0.08, 0.08, 0.10, 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(1, 1, 1, 0.14)
        cr.set_line_width(1)
        cr.stroke()

        if self.menu_title:
            cr.set_source_rgba(0.62, 0.72, 0.95, 1)
            cr.move_to(x + 24, y + 28)
            cr.show_text(self.menu_title)

        for index, text in enumerate(rows):
            row_y = y + 10 + title_h + MENU_ROW_H * index
            if index == self.menu_index:
                self._rounded_box(cr, x + 10, row_y, box_width - 20, MENU_ROW_H, 8)
                cr.set_source_rgba(*self.rgb, 0.85)
                cr.fill()
                cr.set_source_rgba(1, 1, 1, 1)
            else:
                cr.set_source_rgba(0.9, 0.9, 0.9, 1)
            cr.move_to(x + 24, row_y + MENU_ROW_H - 9)
            cr.show_text(text)

    def _draw_name(self, cr, width, height) -> None:
        """Имя сработавшего жеста — внизу по центру, как системная плашка."""
        cr.select_font_face("Sans")
        cr.set_font_size(18)
        extents = cr.text_extents(self.name_text)
        box_width = extents.width + 60
        box_height = 52
        x = (width - box_width) / 2
        y = height - box_height - 80
        self._rounded_box(cr, x, y, box_width, box_height, 12)
        cr.set_source_rgba(0.08, 0.08, 0.10, 0.88)
        cr.fill()
        cr.set_source_rgba(0.95, 0.95, 0.95, 1)
        cr.move_to(x + 30, y + 33)
        cr.show_text(self.name_text)

    @staticmethod
    def _rounded_box(cr, x, y, width, height, radius) -> None:
        cr.new_sub_path()
        cr.arc(x + width - radius, y + radius, radius, -1.5708, 0)
        cr.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
        cr.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
        cr.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
        cr.close_path()

    def on_draw(self, widget, cr) -> bool:
        cr.set_operator(1)  # OPERATOR_SOURCE — стираем прошлый кадр
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(2)  # OPERATOR_OVER
        if self.hint_items:
            self._draw_hint(cr, widget.get_allocated_width(),
                            widget.get_allocated_height())
        if self.menu_items:
            self._draw_menu(cr, widget.get_allocated_width(),
                            widget.get_allocated_height())
        if self.name_text:
            self._draw_name(cr, widget.get_allocated_width(),
                            widget.get_allocated_height())
        if len(self.points) < 2:
            return False
        cr.set_line_width(self.width)
        cr.set_line_cap(1)   # ROUND
        cr.set_line_join(1)  # ROUND
        cr.set_source_rgba(*self.rgb, self.alpha * self.opacity)
        cr.move_to(*self.points[0])
        for point in self.points[1:]:
            cr.line_to(*point)
        cr.stroke()
        return False


if __name__ == "__main__":
    raise SystemExit(main())
