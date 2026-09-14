import Foundation
import AppKit
import CoreGraphics
import ApplicationServices

/// Разрешения, без которых программа не работает.
///
/// На маке перехват мыши закрыт двумя воротами, и это ближайший аналог группы
/// `input` из версии для Linux:
///
/// * **Мониторинг ввода** — право видеть события мыши и клавиатуры вообще;
/// * **Универсальный доступ** — право эти события подменять и отправлять свои,
///   а также спрашивать систему об окнах чужих приложений.
///
/// Обе выдаёт человек руками в «Системных настройках», программно их не
/// получить — можно только открыть нужную страницу настроек и объяснить, что
/// там нажать. Ещё одна особенность: после выдачи права приложение обязано
/// перезапуститься, иначе система продолжит отдавать ему старый ответ.
public enum Permissions {
    /// Универсальный доступ: подмена и отправка событий, работа с окнами.
    public static var hasAccessibility: Bool {
        AXIsProcessTrusted()
    }

    /// Мониторинг ввода: право получать события мыши.
    public static var hasInputMonitoring: Bool {
        CGPreflightListenEventAccess()
    }

    public static var allGranted: Bool {
        hasAccessibility && hasInputMonitoring
    }

    /// Показать системный запрос Универсального доступа.
    ///
    /// Диалог появляется один раз на установку: дальше система молчит, и
    /// человека надо вести в настройки самому.
    @discardableResult
    public static func requestAccessibility() -> Bool {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    /// Показать системный запрос Мониторинга ввода.
    @discardableResult
    public static func requestInputMonitoring() -> Bool {
        CGRequestListenEventAccess()
    }

    public static func openAccessibilitySettings() {
        open("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
    }

    public static func openInputMonitoringSettings() {
        open("x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")
    }

    private static func open(_ urlString: String) {
        guard let url = URL(string: urlString) else { return }
        NSWorkspace.shared.open(url)
    }

    /// Чего не хватает — человеческим языком, для окна первого запуска и меню.
    public static func missingDescription() -> String? {
        switch (hasInputMonitoring, hasAccessibility) {
        case (true, true):
            return nil
        case (false, true):
            return "Нет разрешения «Мониторинг ввода»: программа не видит движений мыши."
        case (true, false):
            return "Нет разрешения «Универсальный доступ»: жест распознаётся, но выполнить его нечем."
        case (false, false):
            return "Нужны два разрешения: «Мониторинг ввода» и «Универсальный доступ»."
        }
    }
}
