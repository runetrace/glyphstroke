import AppKit
import SwiftUI

/// Окна программы.
///
/// Программа живёт в строке меню, поэтому окна создаются руками, а не через
/// `WindowGroup`: иначе SwiftUI откроет пустое окно при запуске и вернёт
/// значок в Dock. Каждое окно держится в поле — иначе оно закроется само,
/// как только уйдёт последняя ссылка.
@MainActor
final class Windows {
    private var editor: NSWindow?
    private var settings: NSWindow?
    private var onboarding: NSWindow?

    private let model: AppModel

    init(model: AppModel) {
        self.model = model
    }

    func showEditor() {
        model.reload()
        present(&editor, title: tr("Glyphstroke — жесты"),
                size: NSSize(width: 860, height: 620),
                view: EditorView(model: model))
    }

    func showSettings() {
        present(&settings, title: tr("Glyphstroke — настройки"),
                size: NSSize(width: 560, height: 640),
                view: SettingsView(model: model))
    }

    func showOnboarding() {
        var window: NSWindow?
        present(&window, title: "Glyphstroke", size: NSSize(width: 520, height: 420),
                view: OnboardingView(onDone: { [weak self] in self?.onboarding?.close() }))
        onboarding = window
    }

    private func present<V: View>(_ slot: inout NSWindow?, title: String,
                                  size: NSSize, view: V) {
        if let existing = slot {
            existing.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }

        let window = NSWindow(contentRect: NSRect(origin: .zero, size: size),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable],
                              backing: .buffered, defer: false)
        window.title = title
        window.contentView = NSHostingView(rootView: ThemedHost(model: model) { view })
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        slot = window
    }
}

/// Общая обёртка окон: фирменный оранжевый акцент и тема по настройке.
///
/// Наблюдает за моделью, поэтому смена темы в настройках применяется сразу,
/// во всех открытых окнах — без перезапуска.
private struct ThemedHost<Content: View>: View {
    @ObservedObject var model: AppModel
    @ViewBuilder let content: () -> Content

    var body: some View {
        content()
            .tint(RcTheme.accent)
            .preferredColorScheme(RcTheme.colorScheme(for: model.settings.theme))
    }
}
