import Foundation
import AppKit
import GlyphstrokeCore

/// Связка всего: перехват мыши, след, распознавание, выполнение.
///
/// Здесь же принимается главное решение каждого росчерка — забрать щелчок себе
/// или отдать приложению. Правило то же, что в версии для Linux: щелчок
/// забирается, только если жест действительно выполнен. Коротким движением
/// человек хотел открыть контекстное меню, а неопознанный росчерк — это
/// промах, и молча съедать его нельзя: пользователь решит, что мышь сломалась.
public final class GestureEngine: MouseTapDelegate {
    private let store: Store
    private let tap = MouseTap()
    private let trail: TrailWindow
    private let actions = ActionRunner()

    private var settings: Settings
    private var gestures: [Gesture] = []
    private var recognizer = Recognizer(gestures: [])

    private var stroke: [Point] = []
    /// Приложение, которое было впереди в момент нажатия. Спрашиваем один раз:
    /// пока рисуется росчерк, оно поменяться не может, а опрос не бесплатный.
    private var strokeApp: String?

    /// Куда писать происходящее — в журнал приложения и в окно проверки.
    public var onLog: ((String) -> Void)?
    /// Что распознали: имя жеста (или `nil`) и код направлений.
    public var onRecognized: ((Match) -> Void)?

    public private(set) var paused = false {
        didSet {
            tap.paused = paused
            if paused { trail.cancel() }
        }
    }

    public init(store: Store = Store()) {
        self.store = store
        self.settings = store.loadSettings()
        self.trail = TrailWindow(settings: settings.overlay)
        tap.delegate = self
        actions.onLog = { [weak self] message in self?.log(message) }
        reload()
    }

    /// Перечитать настройки и жесты с диска.
    public func reload() {
        settings = store.loadSettings()
        gestures = store.loadGestures()
        trail.settings = settings.overlay
        tap.triggerButton = settings.triggerButton
        rebuildRecognizer(for: nil)
        log("жестов загружено: \(gestures.filter(\.enabled).count)")
    }

    public func start() throws {
        try tap.start()
        log("перехват включён, кнопка-модификатор: \(settings.triggerButton)")
    }

    public func stop() {
        tap.stop()
        trail.cancel()
    }

    public func setPaused(_ value: Bool) {
        paused = value
        WindowContext.forget()
        log(value ? "перехват на паузе" : "перехват продолжен")
    }

    public var isRunning: Bool { tap.isRunning }
    public var gestureCount: Int { gestures.filter(\.enabled).count }

    // MARK: - Перехватчик

    public func tapDidBeginStroke(at point: Point) {
        strokeApp = WindowContext.current()

        // Исключённые программы: в них мышь не трогаем вовсе. Проверка именно
        // здесь, а не при выполнении, — иначе в чужом окне пропадал бы щелчок.
        if isExcluded(app: strokeApp) {
            stroke = []
            return
        }
        if settings.pauseInFullscreen && WindowContext.isFrontmostFullscreen() {
            stroke = []
            return
        }

        stroke = [point]
        rebuildRecognizer(for: strokeApp)
        trail.begin(at: point)
    }

    public func tapDidExtendStroke(to point: Point) {
        guard !stroke.isEmpty else { return }
        stroke.append(point)
        trail.extend(to: point)
    }

    public func tapDidEndStroke(at point: Point) -> Bool {
        defer {
            trail.end()
            stroke = []
        }
        guard !stroke.isEmpty else { return false }
        stroke.append(point)

        let length = Geometry.pathLength(stroke)
        if length < settings.minStrokePx {
            // Это не росчерк, а обычный щелчок: пусть уходит приложению.
            return false
        }

        let match = recognizer.recognize(stroke)
        onRecognized?(match)

        guard let name = match.name,
              let gesture = gestures.first(where: { $0.enabled && $0.name == name }) else {
            log("не опознано: \(match.code)"
                + (match.runnerUp.map { ", ближе всех «\($0)» (\(percent(match.runnerUpScore)))" } ?? ""))
            // Неопознанный росчерк по умолчанию отдаём приложению целиком.
            return settings.unrecognized == "swallow"
        }

        log("жест «\(gesture.name)» (\(match.code), \(percent(match.score)))")
        actions.run(gesture.actions)
        return true
    }

    // MARK: - Внутреннее

    /// Собрать распознаватель из жестов, подходящих текущей программе.
    ///
    /// Отбор до распознавания, а не после, — не ради скорости: жест «вниз» в
    /// браузере и жест «вниз» в терминале могут быть разными, и лишний
    /// кандидат портил бы отрыв от второго места, из-за чего не сработал бы ни
    /// один из двух.
    private func rebuildRecognizer(for app: String?) {
        let usable = gestures.filter { $0.enabled && $0.event.isEmpty && $0.matches(app: app) }
        recognizer = Recognizer(gestures: usable.map(\.definition),
                                minScore: settings.minScore,
                                minMargin: settings.minMargin)
    }

    private func isExcluded(app: String?) -> Bool {
        guard let app, !settings.excludedApps.isEmpty else { return false }
        return settings.excludedApps.contains { Gesture.appMatches(pattern: $0, app: app) }
    }

    private func percent(_ score: Double) -> String {
        String(format: "%.0f%%", score * 100)
    }

    private func log(_ message: String) {
        onLog?(message)
    }
}
