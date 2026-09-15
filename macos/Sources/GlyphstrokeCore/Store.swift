import Foundation
import Yams

/// Чтение и запись файлов программы.
///
/// Формат намеренно тот же, что у версии для Linux: `settings.yaml` рядом с
/// каталогом `gestures/`, в каждом файле — один жест. Это не прихоть: жесты
/// человек настраивает долго, и переносить их между машинами он должен
/// копированием каталога, а не экспортом через три диалога.
///
/// Отличается только место. На маке настройки приложений живут в
/// `~/Library/Application Support/<имя>`, и класть их в `~/.config` было бы
/// чужеродно — каталог не виден в Finder и не попадает в резервные копии
/// приложения.
public final class Store {
    public let root: URL

    /// Ключи settings.yaml, которых на маке нет (устройства ввода, способ
    /// захвата, клавиша тачпада). Они читаются и сохраняются как есть, чтобы
    /// один и тот же файл можно было носить между Linux и маком, ничего не
    /// теряя по дороге.
    private var settingsExtras: [String: Any] = [:]

    public init(root: URL? = nil) {
        if let root {
            self.root = root
        } else {
            let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
                ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
            self.root = base.appendingPathComponent("Glyphstroke", isDirectory: true)
        }
    }

    public var settingsURL: URL { root.appendingPathComponent("settings.yaml") }

    /// Текущий набор жестов: пусто — основной (каталог `gestures/`), иначе имя
    /// набора из `profiles/`. Раскладка общая с версиями для Linux и Windows,
    /// чтобы каталог настроек переносился между системами целиком.
    public var activeProfile: String = ""

    public var profilesDirectory: URL { root.appendingPathComponent("profiles", isDirectory: true) }

    public var gesturesDirectory: URL {
        let name = Store.cleanProfileName(activeProfile)
        return name.isEmpty
            ? root.appendingPathComponent("gestures", isDirectory: true)
            : profilesDirectory.appendingPathComponent(name, isDirectory: true)
    }

    public func prepareDirectories() throws {
        try FileManager.default.createDirectory(at: gesturesDirectory, withIntermediateDirectories: true)
    }

    // MARK: - Наборы жестов

    /// Имя набора без символов, недопустимых в имени папки.
    public static func cleanProfileName(_ name: String?) -> String {
        let forbidden = CharacterSet(charactersIn: "/\\:")
        let kept = (name ?? "").unicodeScalars.filter { !forbidden.contains($0) }
        return String(String.UnicodeScalarView(kept)).trimmingCharacters(in: .whitespaces)
    }

    /// Имена заведённых наборов (без основного), по алфавиту.
    public func availableProfiles() -> [String] {
        let urls = (try? FileManager.default.contentsOfDirectory(
            at: profilesDirectory, includingPropertiesForKeys: [.isDirectoryKey])) ?? []
        return urls
            .filter { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true }
            .map { $0.lastPathComponent }
            .filter { !$0.isEmpty }
            .sorted { $0.localizedCaseInsensitiveCompare($1) == .orderedAscending }
    }

    /// Завести набор. `copyFrom` — откуда скопировать жесты: пустая строка это
    /// основной набор, `nil` — не копировать ничего.
    @discardableResult
    public func createProfile(_ name: String, copyFrom: String? = nil) -> String {
        let clean = Store.cleanProfileName(name)
        guard !clean.isEmpty else { return "" }
        let target = profilesDirectory.appendingPathComponent(clean, isDirectory: true)
        try? FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)

        if let copyFrom {
            let sourceName = Store.cleanProfileName(copyFrom)
            let source = sourceName.isEmpty
                ? root.appendingPathComponent("gestures", isDirectory: true)
                : profilesDirectory.appendingPathComponent(sourceName, isDirectory: true)
            let urls = (try? FileManager.default.contentsOfDirectory(
                at: source, includingPropertiesForKeys: nil)) ?? []
            for file in urls where ["yaml", "yml"].contains(file.pathExtension.lowercased()) {
                let copy = target.appendingPathComponent(file.lastPathComponent)
                try? FileManager.default.removeItem(at: copy)
                try? FileManager.default.copyItem(at: file, to: copy)
            }
        }
        return clean
    }

    public func removeProfile(_ name: String) {
        let clean = Store.cleanProfileName(name)
        guard !clean.isEmpty else { return }
        try? FileManager.default.removeItem(
            at: profilesDirectory.appendingPathComponent(clean, isDirectory: true))
    }

    // MARK: - Настройки

    public func loadSettings() -> Settings {
        var settings = Settings()
        guard let text = try? String(contentsOf: settingsURL, encoding: .utf8),
              let raw = (try? Yams.load(yaml: text)) as? [String: Any] else {
            return settings
        }

        settings.language = string(raw["language"]) ?? settings.language
        settings.theme = string(raw["theme"]) ?? settings.theme
        settings.activeProfile = string(raw["active_profile"]) ?? settings.activeProfile
        settings.triggerButton = string(raw["trigger_button"]) ?? settings.triggerButton
        settings.minStrokePx = double(raw["min_stroke_px"]) ?? settings.minStrokePx
        settings.minScore = double(raw["min_score"]) ?? settings.minScore
        settings.minMargin = double(raw["min_margin"]) ?? settings.minMargin
        settings.unrecognized = string(raw["unrecognized"]) ?? settings.unrecognized
        settings.excludedApps = stringList(raw["excluded_apps"])
        settings.pauseInFullscreen = bool(raw["pause_in_fullscreen"]) ?? settings.pauseInFullscreen
        settings.showGestureName = bool(raw["show_gesture_name"]) ?? settings.showGestureName
        settings.hintDelayMs = int(raw["hint_delay_ms"]) ?? settings.hintDelayMs
        settings.menuStepPx = double(raw["menu_step_px"]) ?? settings.menuStepPx
        settings.menuTimeoutMs = int(raw["menu_timeout_ms"]) ?? settings.menuTimeoutMs
        settings.logLevel = string(raw["log_level"]) ?? settings.logLevel
        settings.checkUpdates = bool(raw["check_updates"]) ?? settings.checkUpdates
        settings.updateRepo = string(raw["update_repo"]) ?? settings.updateRepo

        if let overlay = raw["overlay"] as? [String: Any] {
            settings.overlay.enabled = bool(overlay["enabled"]) ?? settings.overlay.enabled
            settings.overlay.color = string(overlay["color"]) ?? settings.overlay.color
            settings.overlay.width = int(overlay["width"]) ?? settings.overlay.width
            settings.overlay.opacity = double(overlay["opacity"]) ?? settings.overlay.opacity
            settings.overlay.fadeMs = int(overlay["fade_ms"]) ?? settings.overlay.fadeMs
        }

        settingsExtras = raw.filter { !Store.knownSettingsKeys.contains($0.key) }
        // Каталог жестов зависит от набора, поэтому выбор из файла применяем
        // сразу: иначе редактор и перехват читали бы разные папки.
        activeProfile = settings.activeProfile
        return settings
    }

    public func saveSettings(_ settings: Settings) throws {
        activeProfile = settings.activeProfile
        try prepareDirectories()
        var raw: [String: Any] = settingsExtras
        raw["language"] = settings.language
        raw["theme"] = settings.theme
        raw["active_profile"] = settings.activeProfile
        raw["trigger_button"] = settings.triggerButton
        raw["min_stroke_px"] = settings.minStrokePx
        raw["min_score"] = settings.minScore
        raw["min_margin"] = settings.minMargin
        raw["unrecognized"] = settings.unrecognized
        raw["excluded_apps"] = settings.excludedApps
        raw["pause_in_fullscreen"] = settings.pauseInFullscreen
        raw["show_gesture_name"] = settings.showGestureName
        raw["hint_delay_ms"] = settings.hintDelayMs
        raw["menu_step_px"] = settings.menuStepPx
        raw["menu_timeout_ms"] = settings.menuTimeoutMs
        raw["log_level"] = settings.logLevel
        raw["check_updates"] = settings.checkUpdates
        raw["update_repo"] = settings.updateRepo
        raw["overlay"] = [
            "enabled": settings.overlay.enabled,
            "color": settings.overlay.color,
            "width": settings.overlay.width,
            "opacity": settings.overlay.opacity,
            "fade_ms": settings.overlay.fadeMs,
        ]

        try write(text: try Yams.dump(object: raw, allowUnicode: true), to: settingsURL)
    }

    static let knownSettingsKeys: Set<String> = [
        "language", "theme", "active_profile", "trigger_button", "min_stroke_px", "min_score",
        "min_margin", "unrecognized", "excluded_apps", "pause_in_fullscreen",
        "show_gesture_name", "hint_delay_ms", "menu_step_px", "menu_timeout_ms",
        "log_level", "overlay", "check_updates", "update_repo",
    ]

    // MARK: - Жесты

    public func loadGestures() -> [Gesture] {
        let urls = (try? FileManager.default.contentsOfDirectory(at: gesturesDirectory,
                                                                 includingPropertiesForKeys: nil)) ?? []
        return urls
            .filter { ["yaml", "yml"].contains($0.pathExtension.lowercased()) }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
            .compactMap { Store.gesture(fromFile: $0) }
    }

    /// Прочитать жест из файла. Битый файл не должен ронять весь набор:
    /// одна испорченная запись — это одна пропавшая фигура, а не мёртвая
    /// программа.
    public static func gesture(fromFile url: URL) -> Gesture? {
        guard let text = try? String(contentsOf: url, encoding: .utf8),
              let raw = (try? Yams.load(yaml: text)) as? [String: Any] else {
            return nil
        }
        return gesture(fromDictionary: raw, url: url)
    }

    public static func gesture(fromDictionary raw: [String: Any], url: URL? = nil) -> Gesture {
        let fallbackName = url?.deletingPathExtension().lastPathComponent ?? "gesture"
        return Gesture(
            name: string(raw["name"]) ?? fallbackName,
            enabled: bool(raw["enabled"]) ?? true,
            event: (string(raw["event"]) ?? "").trimmingCharacters(in: .whitespaces).lowercased(),
            directions: stringList(raw["directions"])
                .map { $0.trimmingCharacters(in: .whitespaces).uppercased() }
                .filter { !$0.isEmpty },
            templates: (raw["templates"] as? [Any] ?? []).map { parseStroke($0) },
            apps: stringList(raw["apps"]),
            rotationTolerance: double(raw["rotation_tolerance"]) ?? 20.0,
            actions: parseActions(raw["actions"]),
            menu: (raw["menu"] as? [Any] ?? []).compactMap { item in
                guard let dict = item as? [String: Any],
                      let name = string(dict["name"])?.trimmingCharacters(in: .whitespaces),
                      !name.isEmpty else { return nil }
                return MenuItem(name: name, actions: parseActions(dict["actions"]))
            },
            describedAs: string(raw["description"]) ?? "",
            fileURL: url
        )
    }

    @discardableResult
    public func save(_ gesture: Gesture) throws -> URL {
        try prepareDirectories()
        // Для нового жеста берём СВОБОДНОЕ имя файла. Иначе два разных жеста с
        // одинаковым слагом имени (переименовали первый «Новый жест», слаг
        // освободился, добавили второй) писались бы в один файл — второй молча
        // затирал первый. Проверяем существование на диске, а не только имя.
        // Имя не менялось — файл оставляем; переименовали жест — приводим имя
        // файла к новому названию, старый удалим после успешной записи.
        var oldToDelete: URL? = nil
        let url: URL
        if let existing = gesture.fileURL {
            if fileNameMatchesName(existing, gesture.name) {
                url = existing
            } else {
                oldToDelete = existing
                url = uniqueGestureURL(for: gesture.name)
            }
        } else {
            url = uniqueGestureURL(for: gesture.name)
        }

        var raw: [String: Any] = [
            "name": gesture.name,
            "enabled": gesture.enabled,
            "description": gesture.describedAs,
            "event": gesture.event,
            "directions": gesture.directions,
            "apps": gesture.apps,
            "rotation_tolerance": gesture.rotationTolerance,
            "actions": gesture.actions.map { ["type": $0.type, "value": $0.value] },
        ]
        // Ключа menu у жеста без меню быть не должно: файл прежнего жеста не
        // должен меняться от одного лишь пересохранения.
        if !gesture.menu.isEmpty {
            raw["menu"] = gesture.menu.map { item in
                ["name": item.name, "actions": item.actions.map { ["type": $0.type, "value": $0.value] }]
            }
        }
        raw["templates"] = gesture.templates.map { Store.formatStroke($0) }

        try write(text: try Yams.dump(object: raw, allowUnicode: true), to: url)
        if let old = oldToDelete, old != url {
            try? FileManager.default.removeItem(at: old)
        }
        return url
    }

    /// Положить стартовый набор жестов, если каталог пуст.
    ///
    /// Пустой список на первом запуске выглядит поломкой: человек нарисовал
    /// росчерк, ничего не произошло, и понять, программа сломана или просто
    /// нечему срабатывать, нельзя.
    @discardableResult
    public func installStarterGestures(from directory: URL) throws -> Int {
        try prepareDirectories()
        guard loadGestures().isEmpty else { return 0 }

        let urls = (try? FileManager.default.contentsOfDirectory(at: directory,
                                                                 includingPropertiesForKeys: nil)) ?? []
        var copied = 0
        for source in urls where ["yaml", "yml"].contains(source.pathExtension.lowercased()) {
            let target = gesturesDirectory.appendingPathComponent(source.lastPathComponent)
            if !FileManager.default.fileExists(atPath: target.path) {
                try FileManager.default.copyItem(at: source, to: target)
                copied += 1
            }
        }
        return copied
    }

    // MARK: - Мелочи

    /// Запись через временный файл: обрыв на середине не должен оставлять
    /// половину настроек.
    private func write(text: String, to url: URL) throws {
        let temporary = url.appendingPathExtension("tmp")
        try text.write(to: temporary, atomically: false, encoding: .utf8)
        if FileManager.default.fileExists(atPath: url.path) {
            _ = try FileManager.default.replaceItemAt(url, withItemAt: temporary)
        } else {
            // replaceItemAt требует, чтобы файл уже был: первый раз просто
            // переносим временный на его место.
            try FileManager.default.moveItem(at: temporary, to: url)
        }
    }

    public static func parseStroke(_ raw: Any) -> [Point] {
        if let pairs = raw as? [[Any]] {
            return pairs.compactMap { pair in
                guard pair.count >= 2, let x = double(pair[0]), let y = double(pair[1]) else { return nil }
                return Point(x, y)
            }
        }
        guard let text = raw as? String else { return [] }
        return text.split(whereSeparator: { $0 == " " || $0 == "\n" }).compactMap { chunk in
            let parts = chunk.split(separator: ",", maxSplits: 1)
            guard parts.count == 2, let x = Double(parts[0]), let y = Double(parts[1]) else { return nil }
            return Point(x, y)
        }
    }

    public static func formatStroke(_ points: [Point]) -> String {
        points.map { String(format: "%.1f,%.1f", $0.x, $0.y) }.joined(separator: " ")
    }

    /// Имя файла из названия жеста: буквы и цифры любых языков, остальное — дефис.
    /// Соответствует ли имя файла текущему названию жеста: точный слаг или слаг
    /// с числовым суффиксом «-2» (его добавляет uniqueGestureURL при совпадении).
    private func fileNameMatchesName(_ url: URL, _ name: String) -> Bool {
        let stem = url.deletingPathExtension().lastPathComponent
        let want = Store.slug(name)
        if stem == want { return true }
        guard stem.hasPrefix(want + "-") else { return false }
        let suffix = stem.dropFirst(want.count + 1)
        return !suffix.isEmpty && suffix.allSatisfy { $0.isNumber }
    }

    /// Путь под новый жест, не совпадающий с уже существующим файлом.
    private func uniqueGestureURL(for name: String) -> URL {
        let slug = Store.slug(name)
        var candidate = gesturesDirectory.appendingPathComponent(slug + ".yaml")
        var counter = 2
        while FileManager.default.fileExists(atPath: candidate.path) {
            candidate = gesturesDirectory.appendingPathComponent("\(slug)-\(counter).yaml")
            counter += 1
        }
        return candidate
    }

    public static func slug(_ name: String) -> String {
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: ".-_"))
        let scalars = name.trimmingCharacters(in: .whitespaces).unicodeScalars.map {
            allowed.contains($0) ? Character($0) : "-"
        }
        let collapsed = String(scalars)
            .split(separator: "-", omittingEmptySubsequences: true)
            .joined(separator: "-")
            .lowercased()
        return collapsed.isEmpty ? "gesture" : collapsed
    }

    static func parseActions(_ raw: Any?) -> [Action] {
        (raw as? [Any] ?? []).compactMap { item in
            guard let dict = item as? [String: Any] else { return nil }
            return Action(type: string(dict["type"]) ?? "none", value: string(dict["value"]) ?? "")
        }
    }

    // Значения из YAML приходят как Int, Double, Bool или String — приводим
    // руками, без обобщённого разбора: так видно, что именно ожидается.
    static func string(_ value: Any?) -> String? {
        switch value {
        case let text as String: return text
        case let number as Int: return String(number)
        case let number as Double: return String(number)
        case let flag as Bool: return flag ? "true" : "false"
        default: return nil
        }
    }

    static func double(_ value: Any?) -> Double? {
        switch value {
        case let number as Double: return number
        case let number as Int: return Double(number)
        case let text as String: return Double(text)
        default: return nil
        }
    }

    static func int(_ value: Any?) -> Int? {
        switch value {
        case let number as Int: return number
        case let number as Double: return Int(number)
        case let text as String: return Int(text)
        default: return nil
        }
    }

    static func bool(_ value: Any?) -> Bool? {
        switch value {
        case let flag as Bool: return flag
        case let text as String: return ["y", "yes", "true", "on", "1"].contains(text.lowercased())
        case let number as Int: return number != 0
        default: return nil
        }
    }

    static func stringList(_ value: Any?) -> [String] {
        (value as? [Any] ?? []).compactMap { string($0) }
    }

    // Те же помощники нужны и снаружи статических методов разбора жеста.
    private func string(_ value: Any?) -> String? { Store.string(value) }
    private func double(_ value: Any?) -> Double? { Store.double(value) }
    private func int(_ value: Any?) -> Int? { Store.int(value) }
    private func bool(_ value: Any?) -> Bool? { Store.bool(value) }
    private func stringList(_ value: Any?) -> [String] { Store.stringList(value) }
}
