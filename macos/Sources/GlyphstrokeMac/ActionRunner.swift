import Foundation
import AppKit
import CoreGraphics
import ApplicationServices
import GlyphstrokeCore

/// Пометка «событие отправили мы сами».
///
/// Всё, что программа посылает в систему — щелчок вместо неопознанного
/// росчерка, нажатия клавиш, прокрутка, — возвращается в наш же перехватчик.
/// Без пометки программа принимала бы собственные события за действия человека.
public enum SelfSentEvents {
    public static let mark: Int64 = 0x474C5946  // "GLYF"

    /// Пометить и отправить событие системе.
    public static func post(_ event: CGEvent) {
        event.setIntegerValueField(.eventSourceUserData, value: mark)
        event.post(tap: .cghidEventTap)
    }
}

/// Выполнение действий жеста.
///
/// Набор типов общий с версией для Linux, меняется только исполнение:
/// клавиши и щелчки уходят через CGEvent, окна слушаются Универсального
/// доступа, программы запускает NSWorkspace.
///
/// Одно отличие в лучшую сторону: текст печатается символами, а не кодами
/// клавиш. На Linux из-за этого действие `text` при русской раскладке
/// печатало не то, что просили; здесь такой болезни нет.
public final class ActionRunner {
    /// Длинные действия не должны задерживать перехватчик: пока он не вернул
    /// ответ, система держит очередь событий и может выключить его по таймауту.
    private let queue = DispatchQueue(label: "glyphstroke.actions", qos: .userInitiated)

    public var onLog: ((String) -> Void)?

    public init() {}

    /// Выполнить список действий по порядку, не задерживая вызывающего.
    public func run(_ actions: [Action], targetPid: pid_t = 0) {
        guard !actions.isEmpty else { return }
        queue.async { [weak self] in
            // Действия применяются к окну ПОД росчерком, а не к активному: если
            // цель известна, выводим её приложение вперёд, чтобы клавиши и текст
            // попали именно в него.
            if targetPid != 0 {
                DispatchQueue.main.sync {
                    NSRunningApplication(processIdentifier: targetPid)?.activate(options: [])
                }
            }
            for action in actions {
                self?.runOne(action, targetPid: targetPid)
            }
        }
    }

    private func runOne(_ action: Action, targetPid: pid_t) {
        switch action.type {
        case "keys": sendKeys(action.value)
        case "text": sendText(action.value)
        case "command": runCommand(action.value)
        case "app": openApp(action.value)
        case "button": clickButton(action.value)
        case "scroll": scroll(action.value)
        case "window": windowCommand(action.value, targetPid: targetPid)
        case "standard": runStandard(action.value, targetPid: targetPid)
        case "delay": Thread.sleep(forTimeInterval: max(0, Double(action.value) ?? 0) / 1000.0)
        case "none", "": break
        default: log("неизвестный тип действия: \(action.type)")
        }
    }

    /// Стандартное действие системы: разворачиваем имя и выполняем.
    ///
    /// Разворот здесь, а не при чтении файла, намеренно: в файле жеста
    /// остаётся имя, и тот же файл на Linux выполнит его собственное сочетание.
    private func runStandard(_ value: String, targetPid: pid_t) {
        guard let entry = StandardActions.entry(value) else {
            log("не знаю такого стандартного действия: \(value)")
            return
        }
        switch entry.kind {
        case .keys: sendKeys(entry.value)
        case .window: windowCommand(entry.value, targetPid: targetPid)
        }
    }

    // MARK: - Клавиши и текст

    private func sendKeys(_ value: String) {
        guard let combo = KeyMap.parse(value) else {
            log("не понял сочетание клавиш: \(value)")
            return
        }
        let source = CGEventSource(stateID: .combinedSessionState)
        guard let down = CGEvent(keyboardEventSource: source, virtualKey: combo.key, keyDown: true),
              let up = CGEvent(keyboardEventSource: source, virtualKey: combo.key, keyDown: false) else {
            return
        }
        down.flags = combo.flags
        up.flags = combo.flags
        SelfSentEvents.post(down)
        SelfSentEvents.post(up)
    }

    private func sendText(_ value: String) {
        guard !value.isEmpty else { return }
        let source = CGEventSource(stateID: .combinedSessionState)
        // Символы отправляются строкой, без обращения к раскладке: так печатается
        // и кириллица, и то, чего на клавиатуре вовсе нет.
        for character in value {
            let units = Array(String(character).utf16)
            guard let down = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: true),
                  let up = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: false) else {
                continue
            }
            down.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units)
            up.keyboardSetUnicodeString(stringLength: units.count, unicodeString: units)
            SelfSentEvents.post(down)
            SelfSentEvents.post(up)
        }
    }

    // MARK: - Программы

    private func runCommand(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/sh")
        process.arguments = ["-c", trimmed]
        do {
            try process.run()
        } catch {
            log("не удалось выполнить «\(trimmed)»: \(error.localizedDescription)")
        }
    }

    /// Запустить программу: по имени («Safari»), по пути или по идентификатору
    /// пакета («com.apple.Safari»).
    private func openApp(_ value: String) {
        let name = value.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }

        if name.hasPrefix("/") {
            NSWorkspace.shared.open(URL(fileURLWithPath: name))
            return
        }
        if name.contains("."), let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: name) {
            NSWorkspace.shared.open(url)
            return
        }
        // Имя без пути отдаём системе: она сама найдёт программу среди
        // установленных, как это делает Spotlight.
        runCommand("open -a \(shellQuoted(name))")
    }

    private func shellQuoted(_ text: String) -> String {
        "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'"
    }

    // MARK: - Мышь

    private func clickButton(_ value: String) {
        let name = value.trimmingCharacters(in: .whitespaces).lowercased()
        let button: CGMouseButton
        let down: CGEventType
        let up: CGEventType
        switch name {
        case "middle", "btn_middle": button = .center; down = .otherMouseDown; up = .otherMouseUp
        case "right", "btn_right": button = .right; down = .rightMouseDown; up = .rightMouseUp
        default: button = .left; down = .leftMouseDown; up = .leftMouseUp
        }

        let position = CGEvent(source: nil)?.location ?? .zero
        let source = CGEventSource(stateID: .combinedSessionState)
        for type in [down, up] {
            guard let event = CGEvent(mouseEventSource: source, mouseType: type,
                                      mouseCursorPosition: position, mouseButton: button) else { continue }
            SelfSentEvents.post(event)
        }
    }

    /// `up`, `down`, `up 3`, `left 2` — прокрутка на несколько щелчков.
    private func scroll(_ value: String) {
        let parts = value.split(separator: " ")
        let direction = (parts.first.map(String.init) ?? "down").lowercased()
        let amount = Int32(parts.count > 1 ? Int(parts[1]) ?? 1 : 1)
        let source = CGEventSource(stateID: .combinedSessionState)

        var vertical: Int32 = 0
        var horizontal: Int32 = 0
        switch direction {
        case "up": vertical = amount
        case "down": vertical = -amount
        case "left": horizontal = amount
        case "right": horizontal = -amount
        default: vertical = -amount
        }

        guard let event = CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 2,
                                  wheel1: vertical, wheel2: horizontal, wheel3: 0) else { return }
        SelfSentEvents.post(event)
    }

    // MARK: - Окна

    /// minimize | close | activate | fullscreen — через Универсальный доступ.
    private func windowCommand(_ value: String, targetPid: pid_t) {
        let command = value.trimmingCharacters(in: .whitespaces).lowercased()
        guard Permissions.hasAccessibility else {
            log("действие «окно: \(command)» требует Универсального доступа")
            return
        }
        // Цель — приложение окна под росчерком; если не определили, откатываемся
        // на активное.
        guard let app = (targetPid != 0 ? NSRunningApplication(processIdentifier: targetPid) : nil)
            ?? NSWorkspace.shared.frontmostApplication else { return }

        if command == "activate" {
            app.activate(options: [])
            return
        }

        let element = AXUIElementCreateApplication(app.processIdentifier)
        var windowRef: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXFocusedWindowAttribute as CFString, &windowRef) == .success,
              let rawWindow = windowRef else {
            log("не вижу активного окна у \(app.localizedName ?? "программы")")
            return
        }
        let window = rawWindow as! AXUIElement

        switch command {
        case "minimize", "":
            AXUIElementSetAttributeValue(window, kAXMinimizedAttribute as CFString, kCFBooleanTrue)
        case "close":
            var buttonRef: CFTypeRef?
            if AXUIElementCopyAttributeValue(window, kAXCloseButtonAttribute as CFString, &buttonRef) == .success,
               let rawButton = buttonRef {
                AXUIElementPerformAction(rawButton as! AXUIElement, kAXPressAction as CFString)
            }
        case "fullscreen", "maximize":
            // Атрибут есть не у всех окон: у части программ полноэкранного
            // режима просто нет, и это не ошибка.
            AXUIElementSetAttributeValue(window, "AXFullScreen" as CFString, kCFBooleanTrue)
        case "unfullscreen", "unmaximize":
            AXUIElementSetAttributeValue(window, "AXFullScreen" as CFString, kCFBooleanFalse)
        default:
            log("не знаю такого действия над окном: \(command)")
        }
    }

    private func log(_ message: String) {
        onLog?(message)
    }
}
