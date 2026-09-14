import Foundation

/// Стандартные действия системы: «копировать», «свернуть окно» и прочие.
///
/// Зачем отдельный тип действия, когда есть «клавиши». Во-первых, человеку не
/// нужно помнить, что «вставить» — это ⌘V, а «назад» в браузере — ⌘[; он
/// выбирает из списка. Во-вторых и главное, запись остаётся верной при
/// переносе: файл жеста со «стандартным» действием работает и на маке, и на
/// Linux, потому что там то же действие — `ctrl+v` и `alt+Left`.
///
/// **Имена обязаны совпадать с таблицей в `glyphstroke/standard.py`** версии для
/// Linux. Разъедутся — перенесённый жест молча перестанет работать, а это ровно
/// та беда, ради которой тип и заводился. Проверка совпадения — в тестах.
public enum StandardActions {
    /// Что делать: нажать сочетание или выполнить действие над окном.
    public enum Kind: String {
        case keys
        case window
    }

    public struct Entry {
        public let id: String
        /// Название для списка в редакторе.
        public let title: String
        public let kind: Kind
        public let value: String
    }

    /// Порядок здесь смысловой, а не алфавитный: в списке правка идёт рядом с
    /// правкой, окна рядом с окнами.
    public static let all: [Entry] = [
        // правка
        Entry(id: "copy", title: "Копировать", kind: .keys, value: "cmd+c"),
        Entry(id: "cut", title: "Вырезать", kind: .keys, value: "cmd+x"),
        Entry(id: "paste", title: "Вставить", kind: .keys, value: "cmd+v"),
        // На маке «удалить» — это клавиша Delete, которая на самом деле забой;
        // forward delete там жмут через fn и в обычной работе не используют.
        Entry(id: "delete", title: "Удалить", kind: .keys, value: "backspace"),
        Entry(id: "undo", title: "Отменить", kind: .keys, value: "cmd+z"),
        Entry(id: "redo", title: "Повторить", kind: .keys, value: "cmd+shift+z"),
        Entry(id: "select-all", title: "Выделить всё", kind: .keys, value: "cmd+a"),
        // файлы
        Entry(id: "new", title: "Создать", kind: .keys, value: "cmd+n"),
        Entry(id: "open", title: "Открыть", kind: .keys, value: "cmd+o"),
        Entry(id: "save", title: "Сохранить", kind: .keys, value: "cmd+s"),
        Entry(id: "print", title: "Печать", kind: .keys, value: "cmd+p"),
        Entry(id: "find", title: "Найти", kind: .keys, value: "cmd+f"),
        // вкладки и страницы
        Entry(id: "new-tab", title: "Новая вкладка", kind: .keys, value: "cmd+t"),
        Entry(id: "close-tab", title: "Закрыть вкладку", kind: .keys, value: "cmd+w"),
        Entry(id: "next-tab", title: "Следующая вкладка", kind: .keys, value: "cmd+shift+bracketright"),
        Entry(id: "prev-tab", title: "Предыдущая вкладка", kind: .keys, value: "cmd+shift+bracketleft"),
        Entry(id: "back", title: "Назад", kind: .keys, value: "cmd+bracketleft"),
        Entry(id: "forward", title: "Вперёд", kind: .keys, value: "cmd+bracketright"),
        Entry(id: "refresh", title: "Обновить", kind: .keys, value: "cmd+r"),
        // масштаб
        Entry(id: "zoom-in", title: "Крупнее", kind: .keys, value: "cmd+equal"),
        Entry(id: "zoom-out", title: "Мельче", kind: .keys, value: "cmd+minus"),
        Entry(id: "zoom-reset", title: "Обычный размер", kind: .keys, value: "cmd+0"),
        // окна
        Entry(id: "minimize", title: "Свернуть окно", kind: .window, value: "minimize"),
        // «Развернуть» на маке — это полноэкранный режим: отдельной кнопки
        // «максимизировать», как в Windows и GNOME, здесь нет.
        Entry(id: "maximize", title: "Развернуть окно", kind: .window, value: "fullscreen"),
        Entry(id: "unmaximize", title: "Вернуть размер окна", kind: .window, value: "unfullscreen"),
        Entry(id: "fullscreen", title: "Во весь экран", kind: .window, value: "fullscreen"),
        Entry(id: "close-window", title: "Закрыть окно", kind: .window, value: "close"),
        Entry(id: "switch-window", title: "Переключить окно", kind: .keys, value: "cmd+tab"),
        // прочее
        Entry(id: "quit", title: "Завершить программу", kind: .keys, value: "cmd+q"),
        Entry(id: "screenshot", title: "Снимок экрана", kind: .keys, value: "cmd+shift+4"),
    ]

    private static let byID: [String: Entry] = Dictionary(
        uniqueKeysWithValues: all.map { ($0.id, $0) })

    public static func entry(_ id: String) -> Entry? {
        byID[id.trimmingCharacters(in: .whitespaces).lowercased()]
    }

    /// Название действия для списков и журнала.
    public static func title(_ id: String) -> String {
        entry(id)?.title ?? id
    }

    /// Название вместе с сочетанием: «Вставить — ⌘V».
    ///
    /// Сочетание показывается прямо в списке: выбирая пункт из трёх десятков,
    /// человек обычно хочет знать, что именно нажмётся. У действий над окном
    /// показывать нечего — там не клавиши, а прямая команда окну.
    public static func describe(_ id: String) -> String {
        guard let entry = entry(id) else { return id }
        guard entry.kind == .keys else { return entry.title }
        return "\(entry.title) — \(symbols(entry.value))"
    }

    /// `cmd+shift+bracketright` → `⌘⇧]`.
    ///
    /// На маке сочетания принято писать значками, и запись вида «cmd+shift+]»
    /// в родном интерфейсе смотрится чужеродно.
    public static func symbols(_ combination: String) -> String {
        let names: [String: String] = [
            "cmd": "⌘", "command": "⌘", "super": "⌘", "meta": "⌘", "win": "⌘",
            "ctrl": "⌃", "control": "⌃",
            "alt": "⌥", "option": "⌥", "opt": "⌥",
            "shift": "⇧", "fn": "fn",
            "bracketleft": "[", "bracketright": "]",
            "equal": "=", "minus": "−", "grave": "`", "comma": ",", "period": ".",
            "slash": "/", "backslash": "\\", "semicolon": ";", "apostrophe": "'",
            "backspace": "⌫", "delete": "⌫", "forwarddelete": "⌦",
            "tab": "⇥", "space": "␣", "return": "↩", "enter": "↩", "escape": "⎋", "esc": "⎋",
            "left": "←", "right": "→", "up": "↑", "down": "↓",
            "page_up": "⇞", "pageup": "⇞", "page_down": "⇟", "pagedown": "⇟",
            "home": "↖", "end": "↘",
        ]
        var modifiers = ""
        var key = ""
        for part in combination.split(separator: "+") {
            let name = part.trimmingCharacters(in: .whitespaces).lowercased()
            let symbol = names[name] ?? name.uppercased()
            if ["⌘", "⌃", "⌥", "⇧", "fn"].contains(symbol) {
                modifiers += symbol
            } else {
                key = symbol
            }
        }
        return modifiers + key
    }
}
