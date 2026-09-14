import AppKit

/// Точка входа.
///
/// Делегат и модель привязаны к главному актору, поэтому создаются в его
/// контексте — оттого `main()` помечен `@MainActor`. Файл называется не
/// main.swift намеренно: при наличии main.swift исполняемый модуль считает
/// точкой входа его содержимое, и `@main` использовать нельзя.
@main
enum GlyphstrokeMain {
    @MainActor
    static func main() {
        // Программа живёт в строке меню, поэтому политику активации ставим до
        // первого окна — иначе значок на миг мелькнёт в Dock.
        let application = NSApplication.shared
        let delegate = AppDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        application.run()
    }
}
