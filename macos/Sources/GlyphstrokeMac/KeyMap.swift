import Foundation
import CoreGraphics

/// Разбор записи вроде `cmd+shift+t` в код клавиши и набор модификаторов.
///
/// Имена клавиш приняты и в маковском виде (`cmd`, `option`), и в том, что
/// лежит в файлах жестов от Linux (`ctrl`, `Page_Up`, `Return`): файлы у нас
/// общие, и запись, перенесённая с другой машины, должна хотя бы разбираться.
///
/// А вот сами сочетания перенести нельзя, и делать это молча тем более: на
/// Linux «назад» в браузере — `alt+Left`, на маке — `cmd+[`. Подмена `ctrl` на
/// `cmd` за спиной пользователя ломала бы ровно те жесты, где `ctrl` на маке и
/// нужен (в терминале). Поэтому стартовый набор для мака лежит отдельным
/// файлом, а перенесённые жесты человек правит сам.
public enum KeyMap {
    /// Клавиши по именам. Основа — ANSI-раскладка: коды у macOS позиционные,
    /// от языка ввода не зависят.
    public static let keys: [String: CGKeyCode] = [
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9,
        "b": 11, "q": 12, "w": 13, "e": 14, "r": 15, "y": 16, "t": 17,
        "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
        "equal": 24, "=": 24, "9": 25, "7": 26, "minus": 27, "-": 27, "8": 28, "0": 29,
        "bracketright": 30, "]": 30, "o": 31, "u": 32, "bracketleft": 33, "[": 33,
        "i": 34, "p": 35, "l": 37, "j": 38, "apostrophe": 39, "'": 39, "k": 40,
        "semicolon": 41, ";": 41, "backslash": 42, "\\": 42, "comma": 43, ",": 43,
        "slash": 44, "/": 44, "n": 45, "m": 46, "period": 47, ".": 47, "grave": 50, "`": 50,

        "return": 36, "enter": 36, "tab": 48, "space": 49,
        "backspace": 51, "delete": 51,            // как на Linux: Delete — это забой
        "forwarddelete": 117, "del": 117,
        "escape": 53, "esc": 53,

        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98,
        "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
        "f13": 105, "f14": 107, "f15": 113, "f16": 106, "f17": 64, "f18": 79, "f19": 80,

        "home": 115, "end": 119, "page_up": 116, "pageup": 116, "prior": 116,
        "page_down": 121, "pagedown": 121, "next": 121,
        "left": 123, "right": 124, "down": 125, "up": 126,
        "help": 114, "insert": 114,
    ]

    /// Модификаторы: и маковские имена, и те, что встречаются в файлах Linux.
    public static let modifiers: [String: CGEventFlags] = [
        "cmd": .maskCommand, "command": .maskCommand, "super": .maskCommand,
        "meta": .maskCommand, "win": .maskCommand,
        "ctrl": .maskControl, "control": .maskControl,
        "alt": .maskAlternate, "option": .maskAlternate, "opt": .maskAlternate,
        "shift": .maskShift,
        "fn": .maskSecondaryFn,
    ]

    public struct Combination {
        public var key: CGKeyCode
        public var flags: CGEventFlags
    }

    /// `cmd+shift+t` → код клавиши и модификаторы; `nil` — не разобрали.
    public static func parse(_ text: String) -> Combination? {
        let parts = text.split(separator: "+").map {
            $0.trimmingCharacters(in: .whitespaces)
        }.filter { !$0.isEmpty }
        guard !parts.isEmpty else { return nil }

        var flags: CGEventFlags = []
        var key: CGKeyCode?
        for part in parts {
            let name = part.lowercased()
            if let modifier = modifiers[name] {
                flags.insert(modifier)
                continue
            }
            // Клавиша в записи одна: «ctrl+a+b» — это опечатка, и лучше
            // отказаться целиком, чем нажать наугад половину.
            if key != nil { return nil }
            key = keys[name]
            if key == nil { return nil }
        }
        guard let key else { return nil }
        return Combination(key: key, flags: flags)
    }
}
