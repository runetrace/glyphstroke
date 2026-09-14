import Foundation
import AppKit
import ApplicationServices
import GlyphstrokeCore

/// Кто сейчас впереди: по этому жест решает, работать ему или нет.
///
/// Строка собирается в том же виде, что на Linux, — «приложение | заголовок
/// окна», — потому что фильтры в файлах жестов сверяются именно с ней.
/// Отличие в первой половине: на Linux это класс окна (`firefox`), на маке —
/// идентификатор пакета (`org.mozilla.firefox`).
///
/// Заголовок окна macOS отдаёт только с разрешением Универсального доступа, и
/// это ещё одна причина его просить: без заголовка фильтр вида «Safari.*банк»
/// работать не сможет, хотя фильтр по самому приложению — сможет.
public enum WindowContext {
    /// Сколько доверять последнему ответу. Опрос идёт на каждом росчерке, а
    /// система отвечает не мгновенно.
    static let cacheTTL: TimeInterval = 0.25

    private static var cachedValue: String?
    private static var cachedAt: Date = .distantPast

    public static func current() -> String? {
        if let cachedValue, Date().timeIntervalSince(cachedAt) < cacheTTL {
            return cachedValue
        }
        let value = read()
        cachedValue = value
        cachedAt = Date()
        return value
    }

    /// Сбросить кеш — например, после паузы.
    public static func forget() {
        cachedValue = nil
        cachedAt = .distantPast
    }

    private static func read() -> String? {
        guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
        let identifier = app.bundleIdentifier ?? app.localizedName ?? ""
        guard !identifier.isEmpty else { return nil }
        guard let title = focusedWindowTitle(pid: app.processIdentifier), !title.isEmpty else {
            return identifier
        }
        return "\(identifier) | \(title)"
    }

    static func focusedWindowTitle(pid: pid_t) -> String? {
        guard Permissions.hasAccessibility else { return nil }
        let element = AXUIElementCreateApplication(pid)

        var windowRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXFocusedWindowAttribute as CFString, &windowRef) == .success,
              let rawWindow = windowRef else {
            return nil
        }
        let window = rawWindow as! AXUIElement

        var titleRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(window, kAXTitleAttribute as CFString, &titleRef) == .success else {
            return nil
        }
        return titleRef as? String
    }

    // MARK: - Окно под курсором

    /// Какому приложению принадлежит окно под курсором.
    ///
    /// Нужно кнопке-мишени в редакторе: человеку не приходится знать
    /// идентификатор пакета заранее — он показывает нужное окно пальцем.
    /// Список окон система отдаёт без Универсального доступа, поэтому мишень
    /// работает даже до выдачи разрешений.
    public static func appUnderCursor(excluding pid: pid_t = 0) -> String? {
        // Положение курсора берём у CoreGraphics: оно сразу в тех координатах,
        // в которых система перечисляет окна, — начало в левом верхнем углу.
        // Cocoa считает от левого нижнего, и пересчёт на многомониторной
        // раскладке ошибается ровно на высоту не того экрана.
        guard let point = CGEvent(source: nil)?.location else { return nil }
        return app(at: point, excluding: pid)
    }

    public static func app(at point: CGPoint, excluding pid: pid_t) -> String? {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let list = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return nil
        }
        // Список идёт сверху вниз по слоям, поэтому первое подходящее окно —
        // это и есть то, что человек видит под курсором.
        for info in list {
            guard let layer = info[kCGWindowLayer as String] as? Int, layer == 0,
                  let owner = info[kCGWindowOwnerPID as String] as? pid_t, owner != pid,
                  let raw = info[kCGWindowBounds as String] as? NSDictionary,
                  let bounds = CGRect(dictionaryRepresentation: raw),
                  bounds.contains(point) else {
                continue
            }
            if let app = NSRunningApplication(processIdentifier: owner),
               let identifier = app.bundleIdentifier ?? app.localizedName,
               !identifier.isEmpty {
                return identifier
            }
            return info[kCGWindowOwnerName as String] as? String
        }
        return nil
    }

    /// Развёрнуто ли активное окно во весь экран — для настройки
    /// «отключаться в полноэкранных».
    public static func isFrontmostFullscreen() -> Bool {
        guard Permissions.hasAccessibility,
              let app = NSWorkspace.shared.frontmostApplication else { return false }
        let element = AXUIElementCreateApplication(app.processIdentifier)

        var windowRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXFocusedWindowAttribute as CFString, &windowRef) == .success,
              let rawWindow = windowRef else {
            return false
        }
        let window = rawWindow as! AXUIElement

        var fullscreenRef: CFTypeRef?
        if AXUIElementCopyAttributeValue(window, "AXFullScreen" as CFString, &fullscreenRef) == .success,
           let value = fullscreenRef as? Bool {
            return value
        }
        return false
    }
}
