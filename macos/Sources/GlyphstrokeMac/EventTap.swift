import Foundation
import CoreGraphics
import GlyphstrokeCore

/// Кому перехватчик рассказывает о росчерке.
public protocol MouseTapDelegate: AnyObject {
    /// Кнопку-модификатор нажали.
    func tapDidBeginStroke(at point: Point)
    /// Курсор поехал с зажатой кнопкой.
    func tapDidExtendStroke(to point: Point)
    /// Кнопку отпустили. Вернуть `true`, если щелчок забираем себе
    /// (жест выполнен), и `false`, если его надо отдать приложению.
    func tapDidEndStroke(at point: Point) -> Bool
}

/// Перехват мыши через CGEventTap — маковский аналог захвата evdev.
///
/// Устройство простое, но в нём есть две неочевидные вещи.
///
/// **Нажатие мы забираем сразу.** Пока кнопка держится, ещё неизвестно, жест
/// это или обычный щелчок, а отдать нажатие приложению «задним числом»
/// нельзя. Поэтому нажатие глотается всегда, и если росчерка не вышло, мы сами
/// отправляем системе пару нажатие-отпускание в той же точке. Для приложения
/// это выглядит обычным щелчком, только чуть позже; ровно так же поступает
/// версия для Linux, только там для этого заводится виртуальная мышь.
///
/// **Свои события надо узнавать.** Отправленный нами щелчок приходит обратно в
/// этот же перехватчик, и без пометки мы съели бы его снова — и так по кругу.
/// Пометка живёт в поле `eventSourceUserData`, его никто, кроме нас, не
/// заполняет.
public final class MouseTap {
    public weak var delegate: MouseTapDelegate?

    /// Пауза: события проходят насквозь, как будто программы нет.
    public var paused = false

    /// Кнопка-модификатор. Имена те же, что в файлах Linux.
    public var triggerButton = "BTN_RIGHT"

    private var tap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var pressLocation: CGPoint = .zero
    private var pressing = false

    public init() {}

    public var isRunning: Bool { tap != nil }

    /// Включить перехват. Бросает, если система не дала прав.
    public func start() throws {
        guard tap == nil else { return }

        let mask: CGEventMask =
            (1 << CGEventType.leftMouseDown.rawValue) |
            (1 << CGEventType.leftMouseUp.rawValue) |
            (1 << CGEventType.rightMouseDown.rawValue) |
            (1 << CGEventType.rightMouseUp.rawValue) |
            (1 << CGEventType.rightMouseDragged.rawValue) |
            (1 << CGEventType.otherMouseDown.rawValue) |
            (1 << CGEventType.otherMouseUp.rawValue) |
            (1 << CGEventType.otherMouseDragged.rawValue) |
            (1 << CGEventType.mouseMoved.rawValue)

        let callback: CGEventTapCallBack = { _, type, event, refcon in
            guard let refcon else { return Unmanaged.passUnretained(event) }
            let tap = Unmanaged<MouseTap>.fromOpaque(refcon).takeUnretainedValue()
            return tap.handle(type: type, event: event)
        }

        guard let port = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: mask,
            callback: callback,
            userInfo: Unmanaged.passUnretained(self).toOpaque()
        ) else {
            throw TapError.notPermitted
        }

        let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, port, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes)
        CGEvent.tapEnable(tap: port, enable: true)

        tap = port
        runLoopSource = source
    }

    public func stop() {
        if let tap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }
        if let runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetMain(), runLoopSource, .commonModes)
        }
        tap = nil
        runLoopSource = nil
        pressing = false
    }

    public enum TapError: Error {
        /// Система не дала создать перехватчик: нет разрешений.
        case notPermitted
    }

    // MARK: - Разбор событий

    private func handle(type: CGEventType, event: CGEvent) -> Unmanaged<CGEvent>? {
        // Система выключает перехватчик, если он задумался дольше положенного.
        // Это не ошибка, а рабочая ситуация: включаем обратно и живём дальше.
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let tap {
                CGEvent.tapEnable(tap: tap, enable: true)
            }
            return nil
        }

        if paused || event.getIntegerValueField(.eventSourceUserData) == SelfSentEvents.mark {
            return Unmanaged.passUnretained(event)
        }

        let location = event.location
        switch type {
        case downType:
            pressing = true
            pressLocation = location
            delegate?.tapDidBeginStroke(at: Point(location.x, location.y))
            return nil                       // нажатие забираем: решим на отпускании

        case draggedType, .mouseMoved:
            guard pressing else { return Unmanaged.passUnretained(event) }
            delegate?.tapDidExtendStroke(to: Point(location.x, location.y))
            return type == .mouseMoved ? Unmanaged.passUnretained(event) : nil

        case upType:
            guard pressing else { return Unmanaged.passUnretained(event) }
            pressing = false
            let swallowed = delegate?.tapDidEndStroke(at: Point(location.x, location.y)) ?? false
            if !swallowed {
                // Жеста не вышло — возвращаем приложению обычный щелчок в той
                // точке, где кнопку нажали, а не там, где отпустили: иначе
                // меню открылось бы в стороне от места нажатия.
                replayClick(at: pressLocation)
            }
            return nil

        default:
            return Unmanaged.passUnretained(event)
        }
    }

    /// Отправить системе щелчок кнопкой-модификатором.
    private func replayClick(at point: CGPoint) {
        let source = CGEventSource(stateID: .combinedSessionState)
        for type in [downType, upType] {
            guard let event = CGEvent(mouseEventSource: source, mouseType: type,
                                      mouseCursorPosition: point, mouseButton: button) else { continue }
            SelfSentEvents.post(event)
        }
    }

    // MARK: - Кнопка-модификатор

    private var button: CGMouseButton {
        switch triggerButton.uppercased() {
        case "BTN_MIDDLE": return .center
        case "BTN_LEFT": return .left
        default: return .right
        }
    }

    private var downType: CGEventType {
        switch triggerButton.uppercased() {
        case "BTN_MIDDLE": return .otherMouseDown
        case "BTN_LEFT": return .leftMouseDown
        default: return .rightMouseDown
        }
    }

    private var upType: CGEventType {
        switch triggerButton.uppercased() {
        case "BTN_MIDDLE": return .otherMouseUp
        case "BTN_LEFT": return .leftMouseUp
        default: return .rightMouseUp
        }
    }

    private var draggedType: CGEventType {
        switch triggerButton.uppercased() {
        case "BTN_MIDDLE": return .otherMouseDragged
        case "BTN_LEFT": return .leftMouseDragged
        default: return .rightMouseDragged
        }
    }
}
