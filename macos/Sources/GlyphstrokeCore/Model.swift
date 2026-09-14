import Foundation

/// Действие жеста: что выполнить, когда росчерк опознан.
///
/// Набор типов общий с версией для Linux — файлы жестов переносятся между
/// машинами как есть. Что именно умеет каждая платформа, решает исполнитель:
/// на маке, например, `window` работает через Универсальный доступ, а не через
/// расширение оболочки.
public struct Action: Equatable {
    /// command | app | keys | text | button | scroll | window | delay | none
    public var type: String
    public var value: String

    public init(type: String, value: String = "") {
        self.type = type
        self.value = value
    }
}

/// Пункт меню под жестом: название и свои действия.
public struct MenuItem: Equatable {
    public var name: String
    public var actions: [Action]

    public init(name: String, actions: [Action] = []) {
        self.name = name
        self.actions = actions
    }
}

/// Особые жесты: опознаются событием мыши, а не формой росчерка.
public enum GestureEvent: String, CaseIterable {
    case rockerLeft = "rocker-left"
    case rockerRight = "rocker-right"
    case rockerMiddle = "rocker-middle"
    case wheelUp = "wheel-up"
    case wheelDown = "wheel-down"
    case wheelLeft = "wheel-left"
    case wheelRight = "wheel-right"
}

/// Жест целиком: фигура, условия и что делать.
public struct Gesture: Equatable {
    public var name: String
    public var enabled: Bool
    /// Если задано — жест опознаётся событием мыши, росчерк не рисуется.
    public var event: String
    public var directions: [String]
    public var templates: [[Point]]
    /// Фильтр по приложению; пусто — жест работает везде.
    public var apps: [String]
    /// Допуск поворота в градусах (в файле хранится именно в градусах).
    public var rotationTolerance: Double
    public var actions: [Action]
    /// Пункты меню; пусто — меню не показывается вовсе.
    public var menu: [MenuItem]
    public var describedAs: String
    /// Файл, из которого жест прочитан.
    public var fileURL: URL?

    public init(name: String, enabled: Bool = true, event: String = "",
                directions: [String] = [], templates: [[Point]] = [], apps: [String] = [],
                rotationTolerance: Double = 20.0, actions: [Action] = [],
                menu: [MenuItem] = [], describedAs: String = "", fileURL: URL? = nil) {
        self.name = name
        self.enabled = enabled
        self.event = event
        self.directions = directions
        self.templates = templates
        self.apps = apps
        self.rotationTolerance = rotationTolerance
        self.actions = actions
        self.menu = menu
        self.describedAs = describedAs
        self.fileURL = fileURL
    }

    public var definition: GestureDefinition {
        GestureDefinition(name: name, templates: templates, directions: directions,
                          rotationTolerance: rotationTolerance * .pi / 180.0)
    }

    /// Подходит ли жест приложению, которое сейчас впереди.
    ///
    /// Жест с фильтром не должен срабатывать вслепую: не знаем приложение —
    /// считаем, что не подходит.
    public func matches(app: String?) -> Bool {
        if apps.isEmpty { return true }
        guard let app, !app.isEmpty else { return false }
        return apps.contains { Gesture.appMatches(pattern: $0, app: app) }
    }

    /// Сверка приложения с образцом — так же, как на Linux.
    ///
    /// Образец бывает двух видов. С пометкой `class:` — это точное имя
    /// приложения: на Linux класс окна, на маке идентификатор пакета
    /// («class:com.apple.Safari»). Без пометки — регулярное выражение, которое
    /// ищется в строке «приложение | заголовок окна». Опечатка в выражении не
    /// должна ронять разбор росчерка, поэтому негодное выражение просто не
    /// совпадает.
    public static func appMatches(pattern: String, app: String) -> Bool {
        let trimmed = pattern.trimmingCharacters(in: .whitespaces)
        if trimmed.isEmpty { return false }

        if trimmed.lowercased().hasPrefix(classPrefix) {
            let wanted = String(trimmed.dropFirst(classPrefix.count))
                .trimmingCharacters(in: .whitespaces)
            return wanted.caseInsensitiveCompare(windowClass(of: app)) == .orderedSame
        }

        guard let re = try? NSRegularExpression(pattern: trimmed, options: [.caseInsensitive]) else {
            return false
        }
        let range = NSRange(app.startIndex..<app.endIndex, in: app)
        return re.firstMatch(in: app, options: [], range: range) != nil
    }

    /// Пометка «это точное имя приложения, а не выражение».
    public static let classPrefix = "class:"

    /// `"com.apple.Safari | Заголовок"` → `"com.apple.Safari"`.
    public static func windowClass(of app: String) -> String {
        if let separator = app.range(of: " | ") {
            return String(app[app.startIndex..<separator.lowerBound])
                .trimmingCharacters(in: .whitespaces)
        }
        return app.trimmingCharacters(in: .whitespaces)
    }
}

/// Вид следа за курсором.
public struct OverlaySettings: Equatable {
    public var enabled = true
    public var color = "#4da3ff"
    public var width = 4
    public var opacity = 0.9
    public var fadeMs = 220

    public init() {}
}

/// Настройки программы.
///
/// Имена полей те же, что в settings.yaml на Linux: файл общий. Поля, которых
/// на маке нет (устройства ввода, способ захвата, клавиша тачпада), читаются и
/// сохраняются без изменений — иначе перенос настроек туда-обратно затирал бы
/// их молча.
public struct Settings: Equatable {
    public var language = "auto"
    /// Тема окон: system — как в системе, иначе light/dark.
    public var theme = "system"
    public var activeProfile = ""
    /// Кнопка-модификатор: `BTN_RIGHT`, `BTN_MIDDLE`, `BTN_SIDE`, `BTN_EXTRA`.
    public var triggerButton = "BTN_RIGHT"
    /// Короче какого росчерка это не жест, а обычный щелчок.
    public var minStrokePx = 40.0
    public var minScore = 0.80
    public var minMargin = 0.05
    /// Что делать с неопознанным росчерком: passthrough | swallow.
    public var unrecognized = "passthrough"
    public var excludedApps: [String] = []
    public var pauseInFullscreen = false
    public var showGestureName = true
    public var hintDelayMs = 700
    public var menuStepPx = 36.0
    public var menuTimeoutMs = 5000
    /// Спрашивать страницу выпусков, не вышла ли версия новее. Сама программа
    /// не обновляется: она только показывает, что обновление есть. Это запрос
    /// к чужому серверу, поэтому его можно выключить.
    public var checkUpdates = true
    /// Где лежат выпуски, «владелец/хранилище»; пусто — как в коде.
    public var updateRepo = ""
    public var overlay = OverlaySettings()
    public var logLevel = "info"

    public init() {}
}
