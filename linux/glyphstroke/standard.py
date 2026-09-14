"""Стандартные действия системы: «копировать», «свернуть окно» и прочие.

Зачем отдельный тип действия, когда есть «клавиши». Во-первых, человеку не
нужно помнить, что «вставить» — это ``ctrl+v``, а «вперёд» в браузере —
``alt+Right``; он выбирает из списка. Во-вторых и главное, запись остаётся
верной при переносе: файл жеста со «стандартным» действием работает и на
Linux, и на маке, потому что там то же действие — ``cmd+v`` и ``cmd+]``.
Жест с явными клавишами так не переносится, и это единственное, что мешало
возить набор жестов между машинами как есть.

Здесь перечислены только те действия, которые действительно одинаковы во всех
окружениях. Всё, что зависит от программы или от рабочего стола, сюда не
попадает: лучше десяток надёжных пунктов, чем сорок, половина из которых где-то
да не сработает.
"""

from __future__ import annotations

from .i18n import _

#: id → (название для списка, тип действия, значение)
#:
#: Тип не всегда «клавиши»: свернуть и развернуть окно клавишами нельзя —
#: сочетания у каждого рабочего стола свои, — поэтому они уходят в действие
#: «окно», которое умеет это делать напрямую.
STANDARD_ACTIONS: dict[str, tuple[str, str, str]] = {
    # правка
    "copy": ("Копировать", "keys", "ctrl+c"),
    "cut": ("Вырезать", "keys", "ctrl+x"),
    "paste": ("Вставить", "keys", "ctrl+v"),
    "delete": ("Удалить", "keys", "Delete"),
    "undo": ("Отменить", "keys", "ctrl+z"),
    "redo": ("Повторить", "keys", "ctrl+shift+z"),
    "select-all": ("Выделить всё", "keys", "ctrl+a"),
    # файлы
    "new": ("Создать", "keys", "ctrl+n"),
    "open": ("Открыть", "keys", "ctrl+o"),
    "save": ("Сохранить", "keys", "ctrl+s"),
    "print": ("Печать", "keys", "ctrl+p"),
    "find": ("Найти", "keys", "ctrl+f"),
    # вкладки и страницы
    "new-tab": ("Новая вкладка", "keys", "ctrl+t"),
    "close-tab": ("Закрыть вкладку", "keys", "ctrl+w"),
    "next-tab": ("Следующая вкладка", "keys", "ctrl+pagedown"),
    "prev-tab": ("Предыдущая вкладка", "keys", "ctrl+pageup"),
    "back": ("Назад", "keys", "alt+Left"),
    "forward": ("Вперёд", "keys", "alt+Right"),
    "refresh": ("Обновить", "keys", "F5"),
    # масштаб
    "zoom-in": ("Крупнее", "keys", "ctrl+plus"),
    "zoom-out": ("Мельче", "keys", "ctrl+minus"),
    "zoom-reset": ("Обычный размер", "keys", "ctrl+0"),
    # окна
    "minimize": ("Свернуть окно", "window", "minimize"),
    "maximize": ("Развернуть окно", "window", "maximize"),
    "unmaximize": ("Вернуть размер окна", "window", "unmaximize"),
    "fullscreen": ("Во весь экран", "window", "fullscreen"),
    "close-window": ("Закрыть окно", "window", "close"),
    "switch-window": ("Переключить окно", "keys", "alt+Tab"),
    # прочее
    "quit": ("Завершить программу", "keys", "ctrl+q"),
    "screenshot": ("Снимок экрана", "keys", "Print"),
}

#: в каком порядке показывать в списке — по смыслу, а не по алфавиту
ORDER = list(STANDARD_ACTIONS.keys())


def label(key: str) -> str:
    """Название действия на языке интерфейса."""
    entry = STANDARD_ACTIONS.get(key)
    return _(entry[0]) if entry else key


def resolve(key: str) -> tuple[str, str] | None:
    """``copy`` → ``("keys", "ctrl+c")``; неизвестное имя — ``None``."""
    entry = STANDARD_ACTIONS.get((key or "").strip().lower())
    return (entry[1], entry[2]) if entry else None


def describe(key: str) -> str:
    """Название вместе с сочетанием: «Вставить — ctrl+v».

    Сочетание показывается прямо в списке, потому что человек, выбирая пункт,
    обычно хочет знать, что именно нажмётся, — иначе выбор из тридцати строк
    превращается в гадание. У действий над окном показывать нечего: там не
    клавиши, а прямая команда окну.
    """
    entry = STANDARD_ACTIONS.get(key)
    if entry is None:
        return key
    name = _(entry[0])
    return f"{name} — {entry[2]}" if entry[1] == "keys" else name


def choices() -> list[tuple[str, str]]:
    """Пары «id, подпись» для выпадающего списка в редакторе."""
    return [(key, describe(key)) for key in ORDER]
