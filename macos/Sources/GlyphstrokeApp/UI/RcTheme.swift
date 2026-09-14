import SwiftUI

/// Единые акценты — как в базовой версии для Linux: оранжевый тон у тумблеров,
/// слайдеров и выделения строки, зелёный у главных кнопок. Светлую и тёмную
/// тему даёт сама система (родные Form и List её уже слушают), здесь только
/// цвета акцентов, чтобы вид совпал с линуксовым.
enum RcTheme {
    static let accent = Color(red: 0xE6 / 255, green: 0x61 / 255, blue: 0x00 / 255)
    static let green = Color(red: 0x26 / 255, green: 0xA2 / 255, blue: 0x69 / 255)

    /// Схема по настройке темы: nil — как в системе, иначе светлая/тёмная.
    static func colorScheme(for theme: String) -> ColorScheme? {
        switch theme {
        case "light": return .light
        case "dark": return .dark
        default: return nil
        }
    }
}
